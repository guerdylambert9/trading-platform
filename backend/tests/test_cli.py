from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from trader.cli import app

runner = CliRunner()


@pytest.fixture
def env(monkeypatch, tmp_path):
    values = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'trader.db'}",
        "FAKE_BROKER_STATE": str(tmp_path / "fake_broker.json"),
        "REPORTS_DIR": str(tmp_path / "reports"),
        "UNIVERSE": "SPY,QQQ,TLT,GLD",
        "BROKER": "fake",
        "DATA_SOURCE": "synthetic",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    from trader.config import get_settings

    get_settings.cache_clear()
    return tmp_path


def test_backtest_writes_a_report(env):
    result = runner.invoke(app, ["backtest", "--end", "2020-12-31"])
    assert result.exit_code == 0, result.output
    reports = list((env / "reports").glob("backtest-trend-*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text())["window"]["end"] == "2020-12-31"


def test_gate1_logs_the_holdout_and_sets_the_exit_code(env):
    result = runner.invoke(app, ["gate1", "--yes"])
    assert result.exit_code in (0, 1), result.output
    assert "GATE 1" in result.output
    assert (env / "reports" / "holdout_log.jsonl").exists()


def test_demo_then_status_and_proposals(env):
    assert runner.invoke(app, ["demo", "--days", "30"]).exit_code == 0
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0 and "DEMO" in status.output
    assert runner.invoke(app, ["proposals", "--status", ""]).exit_code == 0


def test_forward_gates_fail_on_the_demo_broker(env):
    assert runner.invoke(app, ["demo", "--days", "70"]).exit_code == 0
    gate2 = runner.invoke(app, ["gate2"])
    assert gate2.exit_code == 1 and "GATE 2 FAILED" in gate2.output
    gate4 = runner.invoke(app, ["gate4", "--weeks", "12"])
    assert gate4.exit_code == 1 and "GATE 4 FAILED" in gate4.output
    assert len(list((env / "reports").glob("gate*.json"))) == 2


def test_env_file_option_selects_another_account(env, monkeypatch):
    from trader.config import ENV_FILE_VAR

    assert "account=A" in runner.invoke(app, ["status"]).output
    other = env / ".env.b"
    other.write_text("ACCOUNT_LABEL=B\nSTRATEGY=momentum\n")
    monkeypatch.setenv(ENV_FILE_VAR, "")  # the option sets this; monkeypatch removes it afterwards
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{env / 'trader-b.db'}")
    result = runner.invoke(app, ["--env-file", str(other), "status"])
    assert result.exit_code == 0, result.output
    assert "account=B" in result.output and "momentum" in result.output


def test_smoke_test_refuses_the_fake_broker(env):
    result = runner.invoke(app, ["smoke-test"])
    assert result.exit_code == 1
    assert "PAPER" in result.output


def test_live_mode_needs_explicit_confirmation(monkeypatch, env):
    from trader.config import Settings

    with pytest.raises(ValueError, match="LIVE_TRADING_CONFIRMED"):
        Settings(_env_file=None, trading_mode="live", broker="alpaca")
    with pytest.raises(ValueError, match="BROKER=alpaca"):
        Settings(_env_file=None, trading_mode="live", live_trading_confirmed=True, broker="fake")

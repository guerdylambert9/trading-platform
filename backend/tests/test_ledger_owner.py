from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tests.helpers import make_settings
from trader.broker.fake import FakeBroker
from trader.cli import app
from trader.config import DEMO_DATABASE_URL, Settings
from trader.ledger import LedgerOwnerError, ledger_owner
from trader.notify.telegram import LogNotifier
from trader.services.context import build_context


def context(url, **overrides):
    return build_context(
        make_settings(database_url=url, **overrides), broker=FakeBroker(cash=100_000), notifier=LogNotifier()
    )


def test_a_database_belongs_to_one_mode_and_account(tmp_path):
    url = f"sqlite:///{tmp_path / 'ledger.db'}"
    context(url)
    context(url)  # the same account again is fine
    assert ledger_owner(url) == {"mode": "DEMO", "account": "A"}
    with pytest.raises(LedgerOwnerError, match="DEMO account A"):
        context(url, broker="alpaca")
    with pytest.raises(LedgerOwnerError):
        context(url, account_label="B")


def test_ledger_owner_of_a_new_file_is_none(tmp_path):
    assert ledger_owner(f"sqlite:///{tmp_path / 'empty.db'}") is None


def test_the_demo_gets_its_own_database_unless_one_is_set():
    assert Settings(_env_file=None).database_url == DEMO_DATABASE_URL
    assert Settings(_env_file=None, broker="alpaca").database_url == "sqlite:///./trader.db"
    assert Settings(_env_file=None, database_url="sqlite:///./mine.db").database_url == "sqlite:///./mine.db"


def test_the_demo_never_resets_a_real_ledger(tmp_path, monkeypatch):
    path = tmp_path / "paper.db"
    url = f"sqlite:///{path}"
    context(url, broker="alpaca", alpaca_api_key="k", alpaca_secret_key="s")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("BROKER", "fake")
    monkeypatch.setenv("FAKE_BROKER_STATE", str(tmp_path / "fake.json"))
    result = CliRunner().invoke(app, ["demo", "--days", "5"])
    assert result.exit_code == 1
    assert "PAPER" in result.output
    assert ledger_owner(url) == {"mode": "PAPER", "account": "A"}


def test_a_missing_database_driver_says_how_to_install_it(monkeypatch):
    import builtins

    from trader.db import DatabaseDriverError, make_engine

    real_import = builtins.__import__

    def no_psycopg(name, *args, **kwargs):
        if name == "psycopg":
            raise ModuleNotFoundError("No module named 'psycopg'", name="psycopg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_psycopg)
    with pytest.raises(DatabaseDriverError, match="postgres"):
        make_engine("postgresql+psycopg://trader@localhost:5432/trader")

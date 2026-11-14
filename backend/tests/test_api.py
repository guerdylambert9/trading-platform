from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.helpers import TODAY, make_ctx
from trader.api.app import create_app
from trader.services.replay import replay


@pytest.fixture
def ctx():
    return make_ctx()


@pytest.fixture
def client(ctx):
    return TestClient(create_app(ctx, start_background=False))


def test_health_needs_no_token(ctx):
    ctx.settings.api_token = "secret"
    client = TestClient(create_app(ctx, start_background=False))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_status_describes_mode_account_and_kill_switch(client):
    body = client.get("/api/status").json()
    assert body["mode"] == "DEMO"
    assert body["account"]["equity"] == pytest.approx(100_000)
    assert body["kill_switch"]["engaged"] is False
    assert body["strategy"]["name"] == "trend"


def test_nightly_job_then_approve_and_reject(client):
    run = client.post("/api/jobs/nightly").json()
    assert run["result"]["pending"] >= 2
    pending = client.get("/api/proposals", params={"status": "pending"}).json()
    first, second = pending[0], pending[1]
    assert client.post(f"/api/proposals/{first['id']}/approve").json()["status"] == "approved"
    assert client.post(f"/api/proposals/{second['id']}/reject").json()["status"] == "rejected"
    assert client.post(f"/api/proposals/{first['id']}/approve").status_code == 409
    assert client.post("/api/proposals/9999/approve").status_code == 404
    assert client.post("/api/jobs/nope").status_code == 404


def test_kill_switch_needs_confirmation_to_release(client):
    assert client.post("/api/kill-switch", json={"engage": True, "reason": "test"}).json()["engaged"] is True
    assert client.post("/api/kill-switch", json={"engage": False}).status_code == 400
    released = client.post("/api/kill-switch", json={"engage": False, "confirm": "RELEASE"}).json()
    assert released["engaged"] is False


def test_dashboard_data_after_a_replay(ctx, client):
    replay(ctx, TODAY - timedelta(days=40), TODAY)
    positions = client.get("/api/positions").json()
    assert positions and all(p["protected"] for p in positions)
    equity = client.get("/api/equity").json()
    assert len(equity) > 20 and equity[0]["benchmark"] == pytest.approx(equity[0]["equity"])
    assert client.get("/api/orders").json()
    assert len(client.get("/api/signals").json()) == 6
    risk = client.get("/api/risk").json()
    assert risk["limits"]["max_position_pct"] == 10 and risk["usage"]["open_positions"] == len(positions)
    recon = client.get("/api/reconciliations").json()
    assert recon and recon[0]["ok"] is True
    assert client.get("/api/ai-decisions").json() == []

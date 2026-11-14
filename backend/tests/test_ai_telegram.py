from __future__ import annotations

import json

import httpx
import pytest

from tests.helpers import make_ctx
from trader import ledger
from trader.ai import NullResearcher, get_researcher, parse_rating
from trader.notify.telegram import TelegramNotifier, TelegramPoller
from trader.services.approvals import handle_telegram_callback
from trader.services.pipeline import run_nightly


@pytest.mark.parametrize(
    ("text", "rating"),
    [
        ("BUY", "buy"),
        ("Rating: **Overweight**", "overweight"),
        ("FINAL TRANSACTION PROPOSAL: **SELL**", "sell"),
        ("We hold the view that... rating - Underweight", "underweight"),
        ("Could buy or sell", "no_opinion"),
        ("", "no_opinion"),
    ],
)
def test_parse_rating(text, rating):
    assert parse_rating(text) == rating


def test_researcher_factory():
    ctx = make_ctx()
    assert isinstance(get_researcher(ctx.settings), NullResearcher)
    ctx.settings.ai_researcher = "oracle"
    with pytest.raises(ValueError):
        get_researcher(ctx.settings)


def telegram(handler) -> TelegramNotifier:
    return TelegramNotifier("TOKEN", "42", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_telegram_sends_approve_and_reject_buttons():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "result": {}})

    telegram(handler).send("hello", buttons=[[("Approve", "approve:1"), ("Reject", "reject:1")]])
    path, payload = sent[0]
    assert path.endswith("/sendMessage") and payload["chat_id"] == "42"
    assert payload["reply_markup"]["inline_keyboard"][0][0] == {
        "text": "Approve",
        "callback_data": "approve:1",
    }


def callback(data: str, chat_id: int = 42) -> dict:
    return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}}}


def test_telegram_callbacks_only_work_from_your_chat():
    ctx = make_ctx(telegram_chat_id="42")
    run_nightly(ctx)
    with ctx.session() as session:
        first = ledger.list_proposals(session, ctx.label, status="pending")[-1]
    assert "Ignored" in handle_telegram_callback(ctx, callback(f"approve:{first.id}", chat_id=7))
    assert handle_telegram_callback(ctx, callback("launch:1")) == "Unknown action."
    assert handle_telegram_callback(ctx, callback(f"approve:{first.id}")).startswith("Approved")
    assert "only pending" in handle_telegram_callback(ctx, callback(f"reject:{first.id}"))


def test_poller_handles_button_presses():
    ctx = make_ctx(telegram_chat_id="42")
    run_nightly(ctx)
    with ctx.session() as session:
        target = ledger.list_proposals(session, ctx.label, status="pending")[0]
    answered = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getUpdates":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {"update_id": 5, "callback_query": callback(f"reject:{target.id}")},
                    ],
                },
            )
        answered.append(json.loads(request.content)["text"])
        return httpx.Response(200, json={"ok": True, "result": True})

    poller = TelegramPoller(ctx, telegram(handler))
    assert poller.poll_once(timeout=0) == 1
    assert poller.offset == 6
    assert answered and answered[0].startswith("Rejected")

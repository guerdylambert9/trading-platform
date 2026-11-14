"""Notifications: Telegram when configured, otherwise the log.

Proposals arrive with Approve and Reject buttons. Only button presses from your own chat
(TELEGRAM_CHAT_ID) are honored.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Protocol

import httpx

if TYPE_CHECKING:
    from trader.config import Settings
    from trader.services.context import AppContext

log = logging.getLogger(__name__)

Buttons = list[list[tuple[str, str]]]


class Notifier(Protocol):
    enabled: bool

    def send(self, text: str, buttons: Buttons | None = None) -> None: ...


class LogNotifier:
    """Writes notifications to the log and keeps them in memory (handy in tests)."""

    enabled = False

    def __init__(self) -> None:
        self.sent: list[tuple[str, Buttons | None]] = []

    def send(self, text: str, buttons: Buttons | None = None) -> None:
        self.sent.append((text, buttons))
        log.info("notify: %s", text)


class TelegramNotifier:
    enabled = True

    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None) -> None:
        self.token = token
        self.chat_id = str(chat_id)
        self.client = client or httpx.Client(timeout=40)

    def _call(self, method: str, **payload: Any) -> Any:
        response = self.client.post(f"https://api.telegram.org/bot{self.token}/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
        return data.get("result")

    def send(self, text: str, buttons: Buttons | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": text[:4000]}
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": label, "callback_data": data} for label, data in row] for row in buttons
                ]
            }
        self._call("sendMessage", **payload)

    def get_updates(self, offset: int, timeout: int = 25) -> list[dict[str, Any]]:
        return (
            self._call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["callback_query"]) or []
        )

    def answer_callback(self, callback_id: str, text: str) -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_id, text=text[:190])


class TelegramPoller:
    """Long-polls Telegram for Approve/Reject presses in a background thread."""

    def __init__(self, ctx: AppContext, notifier: TelegramNotifier) -> None:
        self.ctx = ctx
        self.notifier = notifier
        self.offset = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="telegram-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self, timeout: int = 25) -> int:
        from trader.services.approvals import handle_telegram_callback

        handled = 0
        for update in self.notifier.get_updates(self.offset, timeout=timeout):
            self.offset = max(self.offset, int(update["update_id"]) + 1)
            callback = update.get("callback_query")
            if not callback:
                continue
            reply = handle_telegram_callback(self.ctx, callback)
            try:
                self.notifier.answer_callback(callback["id"], reply)
            except Exception:
                log.exception("Could not answer the Telegram button press")
            handled += 1
        return handled

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("Telegram polling failed; retrying in 10 seconds")
                self._stop.wait(10)


def get_notifier(settings: Settings) -> Notifier:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return LogNotifier()

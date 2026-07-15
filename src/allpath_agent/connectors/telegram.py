from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import ConnectorStatus, InboundMessage, OutboundMessage


TelegramTransport = Callable[[str, dict[str, Any], float], dict[str, Any]]


class TelegramConnector:
    id = "telegram"

    def __init__(
        self,
        bot_token: str,
        transport: TelegramTransport | None = None,
        *,
        timeout_seconds: float = 30.0,
    ):
        if not bot_token:
            raise ValueError("Telegram bot token cannot be empty")
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._transport = transport or telegram_json_transport
        self._timeout_seconds = timeout_seconds
        self._offset = 0

    def status(self) -> ConnectorStatus:
        try:
            payload = self._call("getMe", {})
            username = payload.get("result", {}).get("username", "unknown")
            return ConnectorStatus(self.id, True, f"@{username}")
        except Exception as error:
            return ConnectorStatus(self.id, False, f"{type(error).__name__}: {str(error)[:160]}")

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def poll(self) -> tuple[InboundMessage, ...]:
        payload = self._call(
            "getUpdates",
            {"offset": self._offset, "timeout": 0, "allowed_updates": ["message"]},
        )
        events: list[InboundMessage] = []
        for update in payload.get("result", []):
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self._offset = max(self._offset, update_id + 1)
            message = update.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("text"), str):
                continue
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            if "id" not in chat or "message_id" not in message:
                continue
            timestamp = message.get("date")
            received_at = (
                datetime.fromtimestamp(timestamp, UTC).isoformat()
                if isinstance(timestamp, int)
                else datetime.now(UTC).isoformat()
            )
            events.append(
                InboundMessage(
                    connector_id=self.id,
                    conversation_id=str(chat["id"]),
                    sender_id=str(sender.get("id", "unknown")),
                    message_id=str(message["message_id"]),
                    text=message["text"].strip(),
                    received_at=received_at,
                    metadata={"update_id": update_id},
                )
            )
        return tuple(event for event in events if event.text)

    def send(self, message: OutboundMessage) -> None:
        payload: dict[str, Any] = {
            "chat_id": message.conversation_id,
            "text": message.text,
        }
        if message.reply_to_message_id:
            payload["reply_parameters"] = {"message_id": int(message.reply_to_message_id)}
        self._call("sendMessage", payload)

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._transport(
            f"{self._base_url}/{method}",
            payload,
            self._timeout_seconds,
        )
        if not response.get("ok"):
            raise RuntimeError(str(response.get("description") or "Telegram API request failed"))
        return response


def telegram_json_transport(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise RuntimeError(f"Telegram HTTP error: {error.code}") from error
    except URLError as error:
        raise RuntimeError("Telegram connection failed") from error
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("Telegram returned invalid JSON") from error
    if not isinstance(parsed, dict):
        raise RuntimeError("Telegram returned an invalid response")
    return parsed

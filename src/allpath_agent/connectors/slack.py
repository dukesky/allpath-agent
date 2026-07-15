from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any, Callable

from .contracts import ConnectorStatus, InboundMessage, OutboundMessage


class SlackConnector:
    id = "slack"

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        client_factory: Callable[[str, str], Any] | None = None,
        verifier: Callable[[str, str], str] | None = None,
        response_factory: Callable[[str], Any] | None = None,
    ):
        if not bot_token.startswith("xoxb-"):
            raise ValueError("Slack Bot Token must start with xoxb-")
        if not app_token.startswith("xapp-"):
            raise ValueError("Slack App-Level Token must start with xapp-")
        self._bot_token = bot_token
        self._app_token = app_token
        self._client_factory = client_factory or _default_client_factory
        self._verifier = verifier or verify_slack_tokens
        self._response_factory = response_factory or _socket_response
        self._client: Any = None
        self._events: deque[InboundMessage] = deque()

    def status(self) -> ConnectorStatus:
        try:
            detail = self._verifier(self._bot_token, self._app_token)
            return ConnectorStatus(self.id, True, detail)
        except Exception as error:
            return ConnectorStatus(self.id, False, f"{type(error).__name__}: {str(error)[:160]}")

    def start(self) -> None:
        if self._client is not None:
            return
        self._client = self._client_factory(self._bot_token, self._app_token)
        self._client.socket_mode_request_listeners.append(self._receive)
        self._client.connect()

    def stop(self) -> None:
        if self._client is not None:
            self._client.disconnect()
            self._client = None

    def poll(self) -> tuple[InboundMessage, ...]:
        events = tuple(self._events)
        self._events.clear()
        return events

    def send(self, message: OutboundMessage) -> None:
        if self._client is None:
            raise RuntimeError("Slack connector is not started")
        arguments: dict[str, Any] = {
            "channel": message.conversation_id,
            "text": message.text,
        }
        thread_ts = message.metadata.get("thread_ts")
        if thread_ts:
            arguments["thread_ts"] = thread_ts
        self._client.web_client.chat_postMessage(**arguments)

    def _receive(self, client: Any, request: Any) -> None:
        if request.type != "events_api":
            return
        client.send_socket_mode_response(self._response_factory(request.envelope_id))
        event = request.payload.get("event") or {}
        if event.get("type") != "message" or event.get("bot_id") or event.get("subtype"):
            return
        text = event.get("text")
        channel = event.get("channel")
        timestamp = event.get("ts")
        if not isinstance(text, str) or not channel or not timestamp:
            return
        channel_type = event.get("channel_type")
        is_direct_message = channel_type == "im" or str(channel).startswith("D")
        thread_ts = event.get("thread_ts")
        if not thread_ts and not is_direct_message:
            thread_ts = timestamp
        metadata = {"thread_ts": thread_ts} if thread_ts else {}
        self._events.append(
            InboundMessage(
                connector_id=self.id,
                conversation_id=str(channel),
                sender_id=str(event.get("user", "unknown")),
                message_id=str(timestamp),
                text=text.strip(),
                received_at=datetime.now(UTC).isoformat(),
                metadata=metadata,
            )
        )


def verify_slack_tokens(
    bot_token: str,
    app_token: str,
    client_factory: Callable[..., Any] | None = None,
) -> str:
    if client_factory is None:
        from slack_sdk.web import WebClient

        client_factory = WebClient
    bot = client_factory(token=bot_token).auth_test()
    client_factory().apps_connections_open(app_token=app_token)
    team = bot.get("team") or "Slack workspace"
    user = bot.get("user") or bot.get("user_id") or "bot"
    return f"{team} / {user}"


def _default_client_factory(bot_token: str, app_token: str) -> Any:
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.web import WebClient

    return SocketModeClient(app_token=app_token, web_client=WebClient(token=bot_token))


def _socket_response(envelope_id: str) -> Any:
    from slack_sdk.socket_mode.response import SocketModeResponse

    return SocketModeResponse(envelope_id=envelope_id)

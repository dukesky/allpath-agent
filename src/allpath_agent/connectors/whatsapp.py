from __future__ import annotations

import hashlib
import hmac
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .contracts import ConnectorStatus, InboundMessage, OutboundMessage


GRAPH_VERSION = "v23.0"
WEBHOOK_PATH = "/webhooks/whatsapp"
WhatsAppTransport = Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]]


class WhatsAppConnector:
    id = "whatsapp"

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        app_secret: str,
        verify_token: str,
        *,
        host: str = "127.0.0.1",
        port: int = 8787,
        transport: WhatsAppTransport | None = None,
        server_factory: Callable[..., Any] = ThreadingHTTPServer,
    ):
        if not all(value.strip() for value in (access_token, phone_number_id, app_secret, verify_token)):
            raise ValueError("WhatsApp credentials cannot be empty")
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._app_secret = app_secret
        self._verify_token = verify_token
        self._host = host
        self._port = port
        self._transport = transport or whatsapp_json_transport
        self._server_factory = server_factory
        self._events: deque[InboundMessage] = deque()
        self._server: Any = None
        self._thread: threading.Thread | None = None

    @property
    def callback_path(self) -> str:
        return WEBHOOK_PATH

    def status(self) -> ConnectorStatus:
        try:
            payload = self._transport(
                f"https://graph.facebook.com/{GRAPH_VERSION}/{self._phone_number_id}"
                "?fields=display_phone_number,verified_name",
                self._access_token,
                None,
                15,
            )
            name = payload.get("verified_name") or "WhatsApp Business"
            number = payload.get("display_phone_number") or self._phone_number_id
            return ConnectorStatus(self.id, True, f"{name} / {number}")
        except Exception as error:
            return ConnectorStatus(self.id, False, f"{type(error).__name__}: {str(error)[:160]}")

    def start(self) -> None:
        if self._server is not None:
            return
        connector = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                connector._handle_verification(self)

            def do_POST(self) -> None:
                connector._handle_webhook(self)

            def log_message(self, format: str, *args: Any) -> None:
                return None

        self._server = self._server_factory((self._host, self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def poll(self) -> tuple[InboundMessage, ...]:
        events = tuple(self._events)
        self._events.clear()
        return events

    def send(self, message: OutboundMessage) -> None:
        self._transport(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{self._phone_number_id}/messages",
            self._access_token,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": message.conversation_id,
                "type": "text",
                "text": {"preview_url": False, "body": message.text},
            },
            30,
        )

    def ingest(self, body: bytes, signature: str) -> int:
        expected = "sha256=" + hmac.new(self._app_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("invalid WhatsApp webhook signature")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid WhatsApp webhook payload") from error
        added = 0
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                for message in value.get("messages", []):
                    text = (message.get("text") or {}).get("body")
                    sender = message.get("from")
                    message_id = message.get("id")
                    if message.get("type") != "text" or not isinstance(text, str) or not sender or not message_id:
                        continue
                    timestamp = message.get("timestamp")
                    received_at = (
                        datetime.fromtimestamp(int(timestamp), UTC).isoformat()
                        if timestamp and str(timestamp).isdigit()
                        else datetime.now(UTC).isoformat()
                    )
                    self._events.append(
                        InboundMessage(
                            connector_id=self.id,
                            conversation_id=str(sender),
                            sender_id=str(sender),
                            message_id=str(message_id),
                            text=text.strip(),
                            received_at=received_at,
                        )
                    )
                    added += 1
        return added

    def _handle_verification(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urllib.parse.urlparse(handler.path)
        query = urllib.parse.parse_qs(parsed.query)
        if (
            parsed.path == WEBHOOK_PATH
            and query.get("hub.mode") == ["subscribe"]
            and query.get("hub.verify_token") == [self._verify_token]
        ):
            _respond(handler, 200, query.get("hub.challenge", [""])[0].encode())
            return
        _respond(handler, 403, b"forbidden")

    def _handle_webhook(self, handler: BaseHTTPRequestHandler) -> None:
        if urllib.parse.urlparse(handler.path).path != WEBHOOK_PATH:
            _respond(handler, 404, b"not found")
            return
        body = handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
        try:
            self.ingest(body, handler.headers.get("X-Hub-Signature-256", ""))
        except ValueError:
            _respond(handler, 401, b"invalid signature")
            return
        _respond(handler, 200, b"ok")


def verify_whatsapp_credentials(
    access_token: str,
    phone_number_id: str,
    transport: WhatsAppTransport | None = None,
) -> str:
    connector = WhatsAppConnector(
        access_token,
        phone_number_id,
        "verification-only",
        "verification-only",
        transport=transport,
    )
    status = connector.status()
    if not status.connected:
        raise ValueError(status.detail)
    return status.detail


def whatsapp_json_transport(
    url: str,
    access_token: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="GET" if payload is None else "POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"WhatsApp HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("WhatsApp connection failed") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("WhatsApp returned invalid JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError("WhatsApp returned an invalid response")
    if result.get("error"):
        raise RuntimeError(str(result["error"])[:300])
    return result


def _respond(handler: BaseHTTPRequestHandler, status: int, body: bytes) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

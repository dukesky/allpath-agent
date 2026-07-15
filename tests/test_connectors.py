from __future__ import annotations

import tempfile
import unittest
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

from allpath_agent.connectors import (
    ConnectorRegistry,
    ConnectorRuntime,
    ConnectorStatus,
    InboundMessage,
    OutboundMessage,
    TelegramConnector,
)
from allpath_agent.storage import (
    ConnectorSessionRepository,
    Database,
    SessionRepository,
)


class FakeApplication:
    def __init__(self):
        self.started: list[str] = []
        self.messages: list[tuple[str, str]] = []

    def start_session(self, session_id: str) -> None:
        self.started.append(session_id)

    def send(self, session_id: str, text: str):
        self.messages.append((session_id, text))
        return SimpleNamespace(agent=SimpleNamespace(content=f"reply: {text}"))


class FakeConnector:
    id = "fake"

    def __init__(self, events=()):
        self.events = tuple(events)
        self.sent: list[OutboundMessage] = []

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(self.id, True, "ready")

    def start(self):
        return None

    def stop(self):
        return None

    def poll(self):
        events, self.events = self.events, ()
        return events

    def send(self, message: OutboundMessage) -> None:
        self.sent.append(message)


class ConnectorRuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_dispatch_reuses_one_agent_session_per_platform_conversation(self) -> None:
        first = InboundMessage("fake", "chat-1", "user-1", "10", "hello", "now")
        second = InboundMessage("fake", "chat-1", "user-1", "11", "again", "now")
        connector = FakeConnector((first, second))
        application = FakeApplication()
        sessions = SessionRepository(self.database)
        bindings = ConnectorSessionRepository(self.database)
        runtime = ConnectorRuntime(
            application,
            ConnectorRegistry((connector,)),
            sessions,
            bindings,
        )

        self.assertEqual(runtime.poll_once("fake"), 2)
        session_id = bindings.session_for("fake", "chat-1")

        self.assertIsNotNone(session_id)
        self.assertEqual({item[0] for item in application.messages}, {session_id})
        self.assertEqual([message.text for message in connector.sent], ["reply: hello", "reply: again"])
        self.assertEqual(connector.sent[0].reply_to_message_id, "10")
        self.assertEqual(len(sessions.list_recent()), 1)

    def test_registry_rejects_duplicate_connector_ids(self) -> None:
        registry = ConnectorRegistry((FakeConnector(),))
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(FakeConnector())


class TelegramConnectorTestCase(unittest.TestCase):
    def test_normalizes_updates_tracks_offset_and_sends_threaded_reply(self) -> None:
        calls = []

        def transport(url, payload, timeout):
            calls.append((url, payload, timeout))
            if url.endswith("/getUpdates"):
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 42,
                            "message": {
                                "message_id": 7,
                                "date": 1_700_000_000,
                                "chat": {"id": -1001},
                                "from": {"id": 99},
                                "text": " hello ",
                            },
                        },
                        {"update_id": 43, "message": {"photo": []}},
                    ],
                }
            return {"ok": True, "result": {}}

        connector = TelegramConnector("secret-token", transport)
        events = connector.poll()
        connector.send(OutboundMessage("-1001", "world", reply_to_message_id="7"))
        connector.poll()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].connector_id, "telegram")
        self.assertEqual(events[0].conversation_id, "-1001")
        self.assertEqual(events[0].sender_id, "99")
        self.assertEqual(events[0].text, "hello")
        self.assertEqual(calls[2][1]["offset"], 44)
        self.assertEqual(calls[1][1]["reply_parameters"], {"message_id": 7})
        self.assertNotIn("secret-token", repr(calls[0][1]))

    def test_status_reports_bot_identity_without_exposing_token(self) -> None:
        connector = TelegramConnector(
            "private-token",
            lambda url, payload, timeout: {
                "ok": True,
                "result": {"username": "allpath_test_bot"},
            },
        )

        status = connector.status()

        self.assertTrue(status.connected)
        self.assertEqual(status.detail, "@allpath_test_bot")
        self.assertNotIn("private-token", status.detail)


class SlackConnectorTestCase(unittest.TestCase):
    def test_token_verification_passes_app_token_as_required_keyword(self) -> None:
        from allpath_agent.connectors import verify_slack_tokens

        calls = []

        class Client:
            def __init__(self, token=None):
                self.token = token

            def auth_test(self):
                calls.append(("auth_test", self.token))
                return {"team": "Test Workspace", "user": "allpath"}

            def apps_connections_open(self, *, app_token):
                calls.append(("apps_connections_open", app_token))
                return {"ok": True, "url": "wss://example"}

        detail = verify_slack_tokens("xoxb-bot", "xapp-app", client_factory=Client)

        self.assertEqual(detail, "Test Workspace / allpath")
        self.assertEqual(
            calls,
            [("auth_test", "xoxb-bot"), ("apps_connections_open", "xapp-app")],
        )

    def test_direct_message_reply_stays_in_main_conversation(self) -> None:
        from allpath_agent.connectors import SlackConnector

        acknowledgements = []
        posts = []

        class Client:
            def __init__(self):
                self.socket_mode_request_listeners = []
                self.web_client = SimpleNamespace(chat_postMessage=lambda **kwargs: posts.append(kwargs))

            def connect(self):
                return None

            def disconnect(self):
                return None

            def send_socket_mode_response(self, response):
                acknowledgements.append(response)

        client = Client()
        connector = SlackConnector(
            "xoxb-bot",
            "xapp-app",
            client_factory=lambda bot, app: client,
            verifier=lambda bot, app: "Test Workspace / allpath",
            response_factory=lambda envelope: {"envelope_id": envelope},
        )
        connector.start()
        request = SimpleNamespace(
            type="events_api",
            envelope_id="env-1",
            payload={
                "event": {
                    "type": "message",
                    "channel": "D123",
                    "user": "U123",
                    "ts": "1700.25",
                    "text": " hello slack ",
                }
            },
        )
        client.socket_mode_request_listeners[0](client, request)
        event = connector.poll()[0]
        connector.send(OutboundMessage("D123", "reply", metadata=event.metadata))
        connector.stop()

        self.assertEqual(acknowledgements, [{"envelope_id": "env-1"}])
        self.assertEqual(event.text, "hello slack")
        self.assertEqual(event.conversation_id, "D123")
        self.assertEqual(posts, [{"channel": "D123", "text": "reply"}])

    def test_existing_thread_reply_stays_in_thread(self) -> None:
        from allpath_agent.connectors import SlackConnector

        posts = []
        client = SimpleNamespace(
            socket_mode_request_listeners=[],
            web_client=SimpleNamespace(chat_postMessage=lambda **kwargs: posts.append(kwargs)),
            connect=lambda: None,
            disconnect=lambda: None,
            send_socket_mode_response=lambda response: None,
        )
        connector = SlackConnector(
            "xoxb-bot", "xapp-app", client_factory=lambda bot, app: client,
            verifier=lambda bot, app: "ok", response_factory=lambda envelope: envelope,
        )
        connector.start()
        client.socket_mode_request_listeners[0](client, SimpleNamespace(
            type="events_api", envelope_id="env", payload={"event": {
                "type": "message", "channel": "D123", "channel_type": "im",
                "user": "U123", "ts": "1701", "thread_ts": "1700", "text": "thread",
            }}
        ))
        event = connector.poll()[0]
        connector.send(OutboundMessage("D123", "reply", metadata=event.metadata))

        self.assertEqual(posts, [{"channel": "D123", "text": "reply", "thread_ts": "1700"}])

    def test_channel_root_message_is_replied_to_in_thread(self) -> None:
        from allpath_agent.connectors import SlackConnector

        posts = []
        client = SimpleNamespace(
            socket_mode_request_listeners=[],
            web_client=SimpleNamespace(chat_postMessage=lambda **kwargs: posts.append(kwargs)),
            connect=lambda: None,
            disconnect=lambda: None,
            send_socket_mode_response=lambda response: None,
        )
        connector = SlackConnector(
            "xoxb-bot", "xapp-app", client_factory=lambda bot, app: client,
            verifier=lambda bot, app: "ok", response_factory=lambda envelope: envelope,
        )
        connector.start()
        client.socket_mode_request_listeners[0](client, SimpleNamespace(
            type="events_api", envelope_id="env", payload={"event": {
                "type": "message", "channel": "C123", "channel_type": "channel",
                "user": "U123", "ts": "1700", "text": "channel",
            }}
        ))
        event = connector.poll()[0]
        connector.send(OutboundMessage("C123", "reply", metadata=event.metadata))

        self.assertEqual(posts, [{"channel": "C123", "text": "reply", "thread_ts": "1700"}])


class WhatsAppConnectorTestCase(unittest.TestCase):
    def test_verifies_normalizes_signed_webhook_and_sends_text(self) -> None:
        from allpath_agent.connectors import WhatsAppConnector

        calls = []

        def transport(url, token, payload, timeout):
            calls.append((url, token, payload, timeout))
            if payload is None:
                return {"verified_name": "Allpath", "display_phone_number": "+15551234567"}
            return {"messages": [{"id": "outbound-1"}]}

        connector = WhatsAppConnector(
            "access-token", "phone-id", "app-secret", "verify-token", transport=transport
        )
        status = connector.status()
        body = json.dumps({"entry": [{"changes": [{"value": {"messages": [{
            "from": "15550001111", "id": "wamid.1", "timestamp": "1700000000",
            "type": "text", "text": {"body": " hello whatsapp "},
        }]}}]}]}).encode()
        signature = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()

        self.assertEqual(connector.ingest(body, signature), 1)
        event = connector.poll()[0]
        connector.send(OutboundMessage(event.conversation_id, "reply"))

        self.assertTrue(status.connected)
        self.assertEqual(status.detail, "Allpath / +15551234567")
        self.assertEqual(event.text, "hello whatsapp")
        self.assertEqual(event.conversation_id, "15550001111")
        self.assertEqual(calls[1][2]["text"]["body"], "reply")
        self.assertNotIn("access-token", repr(calls[1][2]))

    def test_rejects_invalid_webhook_signature(self) -> None:
        from allpath_agent.connectors import WhatsAppConnector

        connector = WhatsAppConnector("token", "phone", "secret", "verify", transport=lambda *args: {})
        with self.assertRaisesRegex(ValueError, "signature"):
            connector.ingest(b"{}", "sha256=invalid")


if __name__ == "__main__":
    unittest.main()

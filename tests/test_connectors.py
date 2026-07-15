from __future__ import annotations

import tempfile
import unittest
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
    def test_socket_event_is_acknowledged_normalized_and_replied_in_thread(self) -> None:
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
        self.assertEqual(posts, [{"channel": "D123", "text": "reply", "thread_ts": "1700.25"}])


if __name__ == "__main__":
    unittest.main()

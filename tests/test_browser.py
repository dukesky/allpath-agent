from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from allpath_agent.agent import AgentLoop, ChatResponse, ToolCall
from allpath_agent.models import FakeProvider, ModelProfile
from allpath_agent.storage import (
    Database,
    MemoryRepository,
    MessageRepository,
    SessionRepository,
    ToolApprovalRepository,
    ToolExecutionRepository,
)
from allpath_agent.tools import (
    BrowserAccessError,
    BrowserService,
    ToolApprovalDenied,
    ToolContext,
    ToolRisk,
    ToolRuntime,
    create_builtin_registry,
    validate_public_url,
)


class FakeBrowserBackend:
    def __init__(self):
        self.calls: list[tuple] = []

    def navigate(self, url: str):
        self.calls.append(("navigate", url))
        return {"url": url, "title": "Example", "elements": []}

    def snapshot(self):
        self.calls.append(("snapshot",))
        return {"url": "https://example.com", "title": "Example", "elements": []}

    def click(self, ref: str):
        self.calls.append(("click", ref))
        return {"clicked": ref}

    def type_text(self, ref: str, text: str):
        self.calls.append(("type", ref, text))
        return {"ref": ref, "typed_characters": len(text), "text_redacted": True}


class StaticApproval:
    def __init__(self, allowed: bool):
        self.allowed = allowed

    def request(self, approval):
        return self.allowed, "browser test"


def public_resolver(host: str, port: int):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


class BrowserSafetyTestCase(unittest.TestCase):
    def test_public_url_validation_blocks_local_private_credentials_and_schemes(self) -> None:
        self.assertEqual(
            validate_public_url("https://example.com/path", public_resolver),
            "https://example.com/path",
        )
        blocked = (
            "http://127.0.0.1",
            "http://10.0.0.1",
            "http://localhost",
            "http://service.internal",
            "file:///etc/passwd",
            "https://user:password@example.com",
        )
        for url in blocked:
            with self.subTest(url=url), self.assertRaises(BrowserAccessError):
                validate_public_url(url, public_resolver)

    def test_browser_tools_use_stable_refs_and_require_approval_for_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "state.db")
            database.initialize()
            session = SessionRepository(database).create(session_id="session-browser")
            approvals = ToolApprovalRepository(database)
            backend = FakeBrowserBackend()
            registry = create_builtin_registry(
                MemoryRepository(database),
                browser_service=BrowserService(backend),
            )
            context = ToolContext(session.id, "task-browser")

            names = {schema["function"]["name"] for schema in registry.schemas()}
            expected = {"browser_navigate", "browser_snapshot", "browser_click", "browser_type"}
            self.assertTrue(expected <= names)
            self.assertEqual(registry.get("browser_navigate").risk, ToolRisk.READ_ONLY)
            self.assertEqual(registry.get("browser_click").risk, ToolRisk.SIDE_EFFECT)

            denied = ToolRuntime(registry, approvals, StaticApproval(False))
            with self.assertRaises(ToolApprovalDenied):
                denied.execute("browser_click", {"ref": "e1"}, context)

            allowed = ToolRuntime(registry, approvals, StaticApproval(True))
            result = allowed.execute(
                "browser_type",
                {"ref": "e2", "text": "super-secret-password"},
                context,
            )
            self.assertEqual(result["typed_characters"], 21)
            self.assertIn(("type", "e2", "super-secret-password"), backend.calls)
            records = approvals.list_for_task(session.id, "task-browser")
            serialized = str(records)
            self.assertNotIn("super-secret-password", serialized)
            self.assertIn("redacted browser text", serialized)

    def test_rejects_stale_or_invalid_refs_before_backend(self) -> None:
        backend = FakeBrowserBackend()
        service = BrowserService(backend)
        with self.assertRaises(BrowserAccessError):
            service.click({"ref": "button.submit"})
        self.assertEqual(backend.calls, [])

    def test_browser_text_is_redacted_from_tool_execution_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "state.db")
            database.initialize()
            session = SessionRepository(database).create(session_id="session-audit")
            executions = ToolExecutionRepository(database)
            backend = FakeBrowserBackend()
            registry = create_builtin_registry(
                MemoryRepository(database),
                browser_service=BrowserService(backend),
            )
            runtime = ToolRuntime(
                registry,
                ToolApprovalRepository(database),
                StaticApproval(True),
            )
            provider = FakeProvider([
                ChatResponse(tool_calls=(
                    ToolCall("browser-call", "browser_type", {
                        "ref": "e3",
                        "text": "another-private-value",
                    }),
                )),
                ChatResponse(content="The field was filled."),
            ])
            loop = AgentLoop(
                provider,
                MessageRepository(database),
                executions,
                runtime,
            )

            loop.run(
                session.id,
                "task-audit",
                "Fill the field",
                "You are helpful.",
                ModelProfile("standard", "test-model", quality=6, cost=2),
            )
            serialized = str(executions.list_for_task(session.id, "task-audit"))

        self.assertNotIn("another-private-value", serialized)
        self.assertIn("redacted browser text", serialized)


if __name__ == "__main__":
    unittest.main()

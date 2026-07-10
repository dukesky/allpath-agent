from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.storage import (
    Database,
    MemoryRepository,
    SessionRepository,
    ToolApprovalRepository,
)
from allpath_agent.tools import (
    ApprovalRequest,
    ToolApprovalDenied,
    ToolContext,
    ToolRuntime,
    ToolValidationError,
    create_builtin_registry,
)


class StaticApprovalHandler:
    def __init__(self, allowed: bool):
        self.allowed = allowed
        self.requests: list[ApprovalRequest] = []

    def request(self, approval: ApprovalRequest) -> tuple[bool, str | None]:
        self.requests.append(approval)
        return self.allowed, "test decision"


class ToolRuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.session = SessionRepository(self.database).create(session_id="session-1")
        self.memories = MemoryRepository(self.database)
        self.approvals = ToolApprovalRepository(self.database)
        self.registry = create_builtin_registry(self.memories)
        self.context = ToolContext(self.session.id, "task-1")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_schemas_are_stable_and_sorted(self) -> None:
        names = [schema["function"]["name"] for schema in self.registry.schemas()]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names, ["calculate", "current_datetime", "memory_get", "memory_set"])

    def test_invalid_arguments_do_not_reach_handler(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        with self.assertRaises(ToolValidationError):
            runtime.execute("calculate", {"expression": "1 + 1", "unknown": True}, self.context)

    def test_unknown_tool_is_rejected(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        with self.assertRaisesRegex(KeyError, "unknown tool"):
            runtime.execute("missing_tool", {}, self.context)

    def test_read_only_calculator_executes_without_approval(self) -> None:
        handler = StaticApprovalHandler(False)
        runtime = ToolRuntime(self.registry, self.approvals, handler)
        result = runtime.execute("calculate", {"expression": "2 * (3 + 4)"}, self.context)

        self.assertEqual(result, {"result": 14})
        self.assertEqual(handler.requests, [])
        self.assertEqual(self.approvals.list_for_task(self.session.id, "task-1"), [])

    def test_current_datetime_uses_requested_timezone(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        result = runtime.execute("current_datetime", {"timezone": "UTC"}, self.context)
        self.assertEqual(result["timezone"], "UTC")
        self.assertIn("+00:00", result["iso"])

    def test_calculator_rejects_code_execution(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        with self.assertRaises(ValueError):
            runtime.execute(
                "calculate",
                {"expression": "__import__('os').system('echo unsafe')"},
                self.context,
            )

    def test_side_effect_is_denied_and_persisted_by_default(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        with self.assertRaises(ToolApprovalDenied):
            runtime.execute(
                "memory_set",
                {"key": "style", "content": "concise"},
                self.context,
            )

        self.assertIsNone(self.memories.get("style"))
        decisions = self.approvals.list_for_task(self.session.id, "task-1")
        self.assertEqual(decisions[0]["decision"], "denied")

    def test_approved_side_effect_writes_memory(self) -> None:
        handler = StaticApprovalHandler(True)
        runtime = ToolRuntime(self.registry, self.approvals, handler)
        result = runtime.execute(
            "memory_set",
            {"key": "style", "content": "concise"},
            self.context,
        )

        self.assertEqual(result["content"], "concise")
        self.assertEqual(self.memories.get("style").content, "concise")
        decisions = self.approvals.list_for_task(self.session.id, "task-1")
        self.assertEqual(decisions[0]["decision"], "allowed")


if __name__ == "__main__":
    unittest.main()

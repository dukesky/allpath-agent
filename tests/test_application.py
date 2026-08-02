from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.application import AgentApplication, detect_intents
from allpath_agent.storage import (
    Database,
    SessionRepository,
    ToolApprovalRepository,
    ToolExecutionRepository,
)


class DetectIntentsTestCase(unittest.TestCase):
    def test_plain_greeting_carries_only_chat_intent(self) -> None:
        self.assertEqual(detect_intents("hello"), {"chat"})

    def test_detects_english_intents(self) -> None:
        self.assertIn("time", detect_intents("what date is it today?"))
        self.assertIn("automation", detect_intents("create a cron job for me"))
        self.assertIn("workspace", detect_intents("search files for TODO"))

    def test_detects_chinese_intents(self) -> None:
        self.assertIn("memory", detect_intents("记住我喜欢简洁的回答"))
        self.assertIn("browser", detect_intents("帮我打开网站看看"))
        self.assertIn("terminal", detect_intents("帮我运行测试"))

    def test_one_message_can_carry_multiple_intents(self) -> None:
        intents = detect_intents("remember to calculate my time budget")
        self.assertLessEqual({"chat", "memory", "calculation", "time"}, intents)


class TaskEvidenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.sessions = SessionRepository(self.database)
        self.tool_executions = ToolExecutionRepository(self.database)
        self.approvals = ToolApprovalRepository(self.database)
        self.sessions.create(session_id="session-1")
        self.application = AgentApplication(
            loop=None,
            router=None,
            routing_decisions=None,
            tool_executions=self.tool_executions,
            approvals=self.approvals,
            curriculum=None,
            system_prompt="",
            live_provider=True,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _finish_tool(self, tool_name: str, status: str = "succeeded") -> None:
        execution_id = self.tool_executions.start("session-1", "task-1", tool_name, {})
        self.tool_executions.finish(execution_id, status, {"ok": True})

    def test_browser_screenshot_counts_as_browser_evidence(self) -> None:
        self._finish_tool("browser_screenshot")

        evidence = self.application._task_evidence("session-1", "task-1", "fast")

        self.assertIn("browser_tasks", evidence)

    def test_browser_download_counts_as_browser_evidence(self) -> None:
        self._finish_tool("browser_download")

        evidence = self.application._task_evidence("session-1", "task-1", "fast")

        self.assertIn("browser_tasks", evidence)

    def test_failed_tools_produce_no_capability_evidence(self) -> None:
        self._finish_tool("browser_screenshot", status="failed")

        evidence = self.application._task_evidence("session-1", "task-1", "fast")

        self.assertNotIn("browser_tasks", evidence)

    def test_advanced_profile_mcp_and_approvals_evidence(self) -> None:
        self._finish_tool("mcp__github__search")
        self.approvals.record("session-1", "task-1", "memory_set", {}, "allowed")

        evidence = self.application._task_evidence("session-1", "task-1", "advanced")

        self.assertEqual(
            {"basic_chat", "live_provider", "model_routing", "mcp_tools", "tool_approvals"},
            evidence,
        )


if __name__ == "__main__":
    unittest.main()

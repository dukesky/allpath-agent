from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from allpath_agent.agent import AgentLoop, ChatResponse, IterationLimitError, ToolCall
from allpath_agent.models import FakeProvider, ModelProfile
from allpath_agent.storage import (
    Database,
    MemoryRepository,
    MessageRepository,
    SessionRepository,
    ToolApprovalRepository,
    ToolExecutionRepository,
)
from allpath_agent.tools import ToolContext, ToolRuntime, create_builtin_registry


class MappingToolExecutor:
    def __init__(self, values: dict[str, Any]):
        self.values = values
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def schemas(self) -> tuple[dict[str, Any], ...]:
        return ()

    def execute(self, name: str, arguments: dict[str, Any], context: ToolContext) -> Any:
        self.calls.append((name, arguments))
        value = self.values[name]
        if isinstance(value, Exception):
            raise value
        return value


class AgentLoopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.session = SessionRepository(self.database).create(session_id="session-1")
        self.messages = MessageRepository(self.database)
        self.executions = ToolExecutionRepository(self.database)
        self.profile = ModelProfile("fast", "fast-model", quality=4, cost=1)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_completes_simple_conversation_and_persists_messages(self) -> None:
        provider = FakeProvider([ChatResponse(content="Hello back")])
        loop = AgentLoop(provider, self.messages, self.executions, MappingToolExecutor({}))

        result = loop.run(
            self.session.id,
            "task-1",
            "Hello",
            "You are helpful.",
            self.profile,
        )

        self.assertEqual(result.content, "Hello back")
        self.assertEqual(result.model_calls, 1)
        self.assertEqual([item.role for item in self.messages.list_for_session(self.session.id)], ["user", "assistant"])
        self.assertEqual([item.role for item in provider.requests[0].messages], ["system", "user"])

    def test_executes_tool_and_reconstructs_valid_history(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse(tool_calls=(ToolCall("call-1", "current_time", {"timezone": "UTC"}),)),
                ChatResponse(content="It is noon."),
            ]
        )
        executor = MappingToolExecutor({"current_time": {"time": "12:00"}})
        loop = AgentLoop(provider, self.messages, self.executions, executor)

        result = loop.run(
            self.session.id,
            "task-1",
            "What time is it?",
            "You are helpful.",
            self.profile,
            tool_schemas=({"type": "function", "function": {"name": "current_time"}},),
        )

        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(executor.calls, [("current_time", {"timezone": "UTC"})])
        self.assertEqual(
            [item.role for item in self.messages.list_for_session(self.session.id)],
            ["user", "assistant", "tool", "assistant"],
        )
        second_request = provider.requests[1]
        self.assertEqual([item.role for item in second_request.messages], ["system", "user", "assistant", "tool"])
        self.assertEqual(second_request.messages[2].tool_calls[0].id, "call-1")
        self.assertEqual(second_request.messages[3].tool_call_id, "call-1")

    def test_tool_failure_returns_structured_result_to_model(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse(tool_calls=(ToolCall("call-1", "broken", {}),)),
                ChatResponse(content="The tool failed safely."),
            ]
        )
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            MappingToolExecutor({"broken": RuntimeError("boom")}),
        )

        result = loop.run(
            self.session.id,
            "task-1",
            "Try it",
            "You are helpful.",
            self.profile,
        )

        tool_message = provider.requests[1].messages[-1]
        self.assertEqual(result.content, "The tool failed safely.")
        self.assertIn('"ok": false', tool_message.content)
        self.assertIn("boom", tool_message.content)

    def test_iteration_limit_stops_unbounded_tool_loop(self) -> None:
        provider = FakeProvider(
            [ChatResponse(tool_calls=(ToolCall("call-1", "current_time", {}),))]
        )
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            MappingToolExecutor({"current_time": "noon"}),
            max_model_calls=1,
        )

        with self.assertRaises(IterationLimitError):
            loop.run(
                self.session.id,
                "task-1",
                "Keep going",
                "You are helpful.",
                self.profile,
            )

    def test_registry_runtime_denies_side_effect_and_returns_result_to_model(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse(
                    tool_calls=(
                        ToolCall(
                            "call-1",
                            "memory_set",
                            {"key": "style", "content": "concise"},
                        ),
                    )
                ),
                ChatResponse(content="I did not save that without approval."),
            ]
        )
        memories = MemoryRepository(self.database)
        approvals = ToolApprovalRepository(self.database)
        runtime = ToolRuntime(create_builtin_registry(memories), approvals)
        loop = AgentLoop(provider, self.messages, self.executions, runtime)

        result = loop.run(
            self.session.id,
            "task-approval",
            "Remember that I prefer concise answers",
            "You are helpful.",
            self.profile,
        )

        self.assertEqual(result.content, "I did not save that without approval.")
        self.assertEqual(len(provider.requests[0].tools), 4)
        self.assertIsNone(memories.get("style"))
        self.assertEqual(
            approvals.list_for_task(self.session.id, "task-approval")[0]["decision"],
            "denied",
        )
        self.assertIn("ToolApprovalDenied", provider.requests[1].messages[-1].content)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from allpath_agent.agent import (
    AgentLoop,
    BudgetExceededError,
    ChatResponse,
    IterationLimitError,
    ToolCall,
)
from allpath_agent.models import (
    FakeProvider,
    ModelProfile,
    ProviderAuthenticationError,
    ProviderPool,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from allpath_agent.storage import (
    Database,
    MemoryRepository,
    MessageRepository,
    SessionRepository,
    ToolApprovalRepository,
    ToolExecutionRepository,
)
from allpath_agent.tools import ToolContext, ToolRuntime, create_builtin_registry
from allpath_agent.application import _runtime_system_prompt


class MappingToolExecutor:
    def __init__(self, values: dict[str, Any]):
        self.values = values
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def schemas(self) -> tuple[dict[str, Any], ...]:
        return ()

    def execute(self, name: str, arguments: dict[str, Any], context: ToolContext) -> Any:
        self.calls.append((name, arguments))
        value = self.values[name]
        if isinstance(value, BaseException):
            raise value
        return value


class SequenceProvider:
    def __init__(self, outcomes: list[ChatResponse | BaseException]):
        self.outcomes = list(outcomes)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class RecordingEventLogger:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def emit(self, event: str, **fields: Any) -> None:
        self.records.append({"event": event, **fields})


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

    def test_runtime_prompt_reports_exact_model_and_provider_boundaries(self) -> None:
        profile = ModelProfile(
            "standard",
            "gpt-5.5",
            quality=7,
            cost=4,
            supports_tools=False,
            provider="openai-codex",
        )

        prompt = _runtime_system_prompt("You are Allpath Agent.", profile)

        self.assertIn("role=standard, provider=openai-codex, model=gpt-5.5", prompt)
        self.assertIn("does not receive Allpath tool schemas", prompt)
        self.assertIn("read-only sandbox", prompt)

    def test_completes_simple_conversation_and_persists_messages(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse(
                    content="Hello back",
                    usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                )
            ]
        )
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
        self.assertEqual(result.input_tokens, 10)
        self.assertEqual(result.output_tokens, 4)
        self.assertEqual(result.total_tokens, 14)
        self.assertTrue(result.usage_reported)
        self.assertEqual(
            [item.role for item in self.messages.list_for_session(self.session.id)],
            ["user", "assistant"],
        )
        self.assertEqual([item.role for item in provider.requests[0].messages], ["system", "user"])

    def test_model_without_tool_support_does_not_receive_tool_schemas(self) -> None:
        provider = FakeProvider([ChatResponse(content="No tools needed")])
        executor = MappingToolExecutor({})
        loop = AgentLoop(provider, self.messages, self.executions, executor)
        profile = ModelProfile(
            "text-only",
            "text-model",
            quality=3,
            cost=1,
            supports_tools=False,
        )

        loop.run(
            self.session.id,
            "task-no-tools",
            "Hello",
            "You are helpful.",
            profile,
            tool_schemas=({"type": "function", "function": {"name": "unused"}},),
        )

        self.assertEqual(provider.requests[0].tools, ())

    def test_model_profile_routes_to_its_provider(self) -> None:
        fast_provider = FakeProvider([])
        advanced_provider = FakeProvider([ChatResponse(content="advanced response")])
        loop = AgentLoop(
            ProviderPool({"fast-api": fast_provider, "claude-api": advanced_provider}),
            self.messages,
            self.executions,
            MappingToolExecutor({}),
        )
        profile = ModelProfile(
            "advanced",
            "claude-model",
            quality=10,
            cost=8,
            provider="claude-api",
        )

        result = loop.run(
            self.session.id,
            "task-multi-provider",
            "Analyze this",
            "You are helpful.",
            profile,
        )

        self.assertEqual(result.content, "advanced response")
        self.assertEqual(fast_provider.requests, [])
        self.assertEqual(len(advanced_provider.requests), 1)

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

    def test_token_budget_blocks_tool_execution_and_follow_up_call(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse(
                    tool_calls=(ToolCall("call-1", "current_time", {}),),
                    usage={"input_tokens": 8, "output_tokens": 2},
                )
            ]
        )
        executor = MappingToolExecutor({"current_time": "noon"})
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            executor,
            max_task_tokens=10,
        )

        with self.assertRaises(BudgetExceededError):
            loop.run(
                self.session.id,
                "task-budget",
                "Keep going",
                "You are helpful.",
                self.profile,
            )

        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(executor.calls, [])

    def test_final_answer_is_returned_after_single_call_crosses_budget(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse(
                    content="Completed answer",
                    usage={"input_tokens": 8, "output_tokens": 7},
                )
            ]
        )
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            MappingToolExecutor({}),
            max_task_tokens=10,
        )

        result = loop.run(
            self.session.id,
            "task-final-over-budget",
            "Answer once",
            "You are helpful.",
            self.profile,
        )

        self.assertEqual(result.content, "Completed answer")
        self.assertEqual(result.total_tokens, 15)

    def test_retries_transient_provider_errors_with_bounded_backoff(self) -> None:
        provider = SequenceProvider(
            [
                ProviderRateLimitError("busy", retry_after_seconds=4.0),
                ProviderTimeoutError("slow"),
                ChatResponse(content="Recovered"),
            ]
        )
        delays: list[float] = []
        events = RecordingEventLogger()
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            MappingToolExecutor({}),
            provider_max_attempts=3,
            retry_base_delay_seconds=0.5,
            retry_max_delay_seconds=2.0,
            sleep_fn=delays.append,
            event_logger=events,
        )

        result = loop.run(
            self.session.id,
            "task-retry",
            "Try safely",
            "You are helpful.",
            self.profile,
        )

        self.assertEqual(result.content, "Recovered")
        self.assertEqual(result.model_calls, 3)
        self.assertEqual(delays, [2.0, 1.0])
        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(
            [record["event"] for record in events.records].count(
                "model_call_retry_scheduled"
            ),
            2,
        )

    def test_does_not_retry_authentication_failures(self) -> None:
        provider = SequenceProvider([ProviderAuthenticationError("invalid key")])
        delays: list[float] = []
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            MappingToolExecutor({}),
            sleep_fn=delays.append,
        )

        with self.assertRaises(ProviderAuthenticationError):
            loop.run(
                self.session.id,
                "task-auth",
                "Hello",
                "You are helpful.",
                self.profile,
            )

        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(delays, [])

    def test_does_not_retry_invalid_provider_responses(self) -> None:
        provider = SequenceProvider([ProviderResponseError("invalid response")])
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            MappingToolExecutor({}),
            sleep_fn=lambda delay: self.fail("invalid responses must not retry"),
        )

        with self.assertRaises(ProviderResponseError):
            loop.run(
                self.session.id,
                "task-invalid-response",
                "Hello",
                "You are helpful.",
                self.profile,
            )

        self.assertEqual(len(provider.requests), 1)

    def test_retry_attempts_respect_model_call_limit(self) -> None:
        provider = SequenceProvider(
            [ProviderTimeoutError("slow"), ProviderTimeoutError("still slow")]
        )
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            MappingToolExecutor({}),
            max_model_calls=2,
            provider_max_attempts=3,
            retry_base_delay_seconds=0,
            sleep_fn=lambda delay: None,
        )

        with self.assertRaises(ProviderTimeoutError):
            loop.run(
                self.session.id,
                "task-retry-limit",
                "Hello",
                "You are helpful.",
                self.profile,
            )

        self.assertEqual(len(provider.requests), 2)

    def test_tool_interrupt_closes_all_tool_results_and_execution(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse(
                    tool_calls=(
                        ToolCall("call-1", "first", {}),
                        ToolCall("call-2", "second", {}),
                    )
                )
            ]
        )
        events = RecordingEventLogger()
        loop = AgentLoop(
            provider,
            self.messages,
            self.executions,
            MappingToolExecutor({"first": KeyboardInterrupt()}),
            event_logger=events,
        )

        with self.assertRaises(KeyboardInterrupt):
            loop.run(
                self.session.id,
                "task-interrupt",
                "Run tools",
                "You are helpful.",
                self.profile,
            )

        history = self.messages.list_for_session(self.session.id)
        executions = self.executions.list_for_task(self.session.id, "task-interrupt")
        self.assertEqual(
            [record.role for record in history],
            ["user", "assistant", "tool", "tool", "assistant"],
        )
        self.assertEqual(
            [record.tool_call_id for record in history if record.role == "tool"],
            ["call-1", "call-2"],
        )
        self.assertEqual(executions[0]["status"], "interrupted")
        self.assertEqual(events.records[-1]["event"], "task_interrupted")

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

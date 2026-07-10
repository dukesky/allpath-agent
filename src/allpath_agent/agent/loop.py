from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from allpath_agent.models.messages import ChatMessage, ChatRequest, ToolCall
from allpath_agent.models.pool import ProviderPool
from allpath_agent.models.provider import ChatProvider, RetryableProviderError
from allpath_agent.models.router import ModelProfile
from allpath_agent.observability import EventLogger, NullEventLogger
from allpath_agent.storage import MessageRepository, ToolExecutionRepository
from allpath_agent.storage.records import MessageRecord
from allpath_agent.tools import ToolContext, ToolExecutor

from .budget import BudgetTracker, TaskBudget


class IterationLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentResult:
    content: str
    model_profile: str
    model_calls: int
    tool_calls: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    usage_reported: bool = False


class AgentLoop:
    def __init__(
        self,
        provider: ChatProvider | ProviderPool,
        messages: MessageRepository,
        tool_executions: ToolExecutionRepository,
        tool_executor: ToolExecutor,
        max_model_calls: int = 12,
        max_task_tokens: int = 100_000,
        max_task_cost_usd: float = 0.0,
        provider_max_attempts: int = 3,
        retry_base_delay_seconds: float = 0.5,
        retry_max_delay_seconds: float = 8.0,
        sleep_fn: Callable[[float], None] | None = None,
        event_logger: EventLogger | None = None,
    ):
        if max_model_calls < 1:
            raise ValueError("max_model_calls must be positive")
        if provider_max_attempts < 1:
            raise ValueError("provider_max_attempts must be positive")
        if retry_base_delay_seconds < 0 or retry_max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        self._providers = (
            provider if isinstance(provider, ProviderPool) else ProviderPool.single(provider)
        )
        self._messages = messages
        self._tool_executions = tool_executions
        self._tool_executor = tool_executor
        self._max_model_calls = max_model_calls
        self._budget = TaskBudget(max_task_tokens, max_task_cost_usd)
        self._provider_max_attempts = provider_max_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._retry_max_delay_seconds = retry_max_delay_seconds
        self._sleep = sleep_fn or time.sleep
        self._events = event_logger or NullEventLogger()

    def run(
        self,
        session_id: str,
        task_id: str,
        user_message: str,
        system_prompt: str,
        model_profile: ModelProfile,
        tool_schemas: tuple[dict[str, Any], ...] | None = None,
    ) -> AgentResult:
        self._messages.append(session_id, "user", user_message)
        model_calls = 0
        executed_tool_calls = 0
        budget = BudgetTracker(self._budget)
        self._events.emit(
            "task_started",
            session_id=session_id,
            task_id=task_id,
            provider=model_profile.provider,
            model=model_profile.model,
            profile=model_profile.name,
            max_model_calls=self._max_model_calls,
            max_task_tokens=self._budget.max_total_tokens,
            max_task_cost_usd=self._budget.max_cost_usd,
            provider_max_attempts=self._provider_max_attempts,
        )

        try:
            while model_calls < self._max_model_calls:
                budget.ensure_can_continue()
                available_tools = (
                    self._tool_executor.schemas() if tool_schemas is None else tool_schemas
                )
                request = ChatRequest(
                    model=model_profile.model,
                    messages=(ChatMessage("system", system_prompt), *self._history(session_id)),
                    tools=available_tools if model_profile.supports_tools else (),
                )
                response = None
                for attempt in range(1, self._provider_max_attempts + 1):
                    if model_calls >= self._max_model_calls:
                        raise IterationLimitError(
                            f"task exceeded the limit of {self._max_model_calls} model calls"
                        )
                    model_calls += 1
                    started = perf_counter()
                    try:
                        response = self._providers.complete(model_profile.provider, request)
                    except RetryableProviderError as error:
                        duration_ms = round((perf_counter() - started) * 1000, 3)
                        can_retry = (
                            attempt < self._provider_max_attempts
                            and model_calls < self._max_model_calls
                        )
                        if not can_retry:
                            self._events.emit(
                                "model_call_failed",
                                session_id=session_id,
                                task_id=task_id,
                                provider=model_profile.provider,
                                model=model_profile.model,
                                model_call=model_calls,
                                attempt=attempt,
                                duration_ms=duration_ms,
                                error_type=type(error).__name__,
                                retryable=True,
                            )
                            raise
                        delay = self._retry_delay(error, attempt)
                        self._events.emit(
                            "model_call_retry_scheduled",
                            session_id=session_id,
                            task_id=task_id,
                            provider=model_profile.provider,
                            model=model_profile.model,
                            model_call=model_calls,
                            attempt=attempt,
                            duration_ms=duration_ms,
                            error_type=type(error).__name__,
                            delay_seconds=delay,
                        )
                        self._sleep(delay)
                        continue
                    except Exception as error:
                        self._events.emit(
                            "model_call_failed",
                            session_id=session_id,
                            task_id=task_id,
                            provider=model_profile.provider,
                            model=model_profile.model,
                            model_call=model_calls,
                            attempt=attempt,
                            duration_ms=round((perf_counter() - started) * 1000, 3),
                            error_type=type(error).__name__,
                            retryable=False,
                        )
                        raise
                    break
                if response is None:
                    raise RuntimeError("provider attempts ended without a response")
                totals = budget.record(response.usage, model_profile)
                self._events.emit(
                    "model_call_completed",
                    session_id=session_id,
                    task_id=task_id,
                    provider=model_profile.provider,
                    model=model_profile.model,
                    model_call=model_calls,
                    attempt=attempt,
                    duration_ms=round((perf_counter() - started) * 1000, 3),
                    input_tokens=totals.input_tokens,
                    output_tokens=totals.output_tokens,
                    total_tokens=totals.total_tokens,
                    estimated_cost_usd=round(totals.estimated_cost_usd, 8),
                    usage_reported=totals.usage_reported,
                )

                if response.tool_calls:
                    budget.ensure_can_continue()
                    metadata = {
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                            }
                            for tool_call in response.tool_calls
                        ]
                    }
                    self._messages.append(
                        session_id,
                        "assistant",
                        response.content or "",
                        metadata=metadata,
                    )
                    for tool_call in response.tool_calls:
                        tool_payload = self._execute_tool(session_id, task_id, tool_call)
                        self._messages.append(
                            session_id,
                            "tool",
                            json.dumps(tool_payload, ensure_ascii=False, sort_keys=True),
                            tool_call_id=tool_call.id,
                        )
                        executed_tool_calls += 1
                    continue

                if not response.content:
                    raise ValueError("provider returned neither content nor tool calls")
                self._messages.append(session_id, "assistant", response.content)
                result = AgentResult(
                    content=response.content,
                    model_profile=model_profile.name,
                    model_calls=model_calls,
                    tool_calls=executed_tool_calls,
                    input_tokens=totals.input_tokens,
                    output_tokens=totals.output_tokens,
                    total_tokens=totals.total_tokens,
                    estimated_cost_usd=totals.estimated_cost_usd,
                    usage_reported=totals.usage_reported,
                )
                self._events.emit(
                    "task_completed",
                    session_id=session_id,
                    task_id=task_id,
                    model_calls=model_calls,
                    tool_calls=executed_tool_calls,
                    total_tokens=totals.total_tokens,
                    estimated_cost_usd=round(totals.estimated_cost_usd, 8),
                    usage_reported=totals.usage_reported,
                )
                return result

            raise IterationLimitError(
                f"task exceeded the limit of {self._max_model_calls} model calls"
            )
        except KeyboardInterrupt:
            self._close_interrupted_history(session_id)
            totals = budget.totals
            self._events.emit(
                "task_interrupted",
                session_id=session_id,
                task_id=task_id,
                model_calls=model_calls,
                tool_calls=executed_tool_calls,
                total_tokens=totals.total_tokens,
                estimated_cost_usd=round(totals.estimated_cost_usd, 8),
                usage_reported=totals.usage_reported,
            )
            raise
        except Exception as error:
            totals = budget.totals
            self._events.emit(
                "task_failed",
                session_id=session_id,
                task_id=task_id,
                error_type=type(error).__name__,
                model_calls=model_calls,
                tool_calls=executed_tool_calls,
                total_tokens=totals.total_tokens,
                estimated_cost_usd=round(totals.estimated_cost_usd, 8),
                usage_reported=totals.usage_reported,
            )
            raise

    def _execute_tool(
        self,
        session_id: str,
        task_id: str,
        tool_call: ToolCall,
    ) -> dict[str, Any]:
        started = perf_counter()
        execution_id = self._tool_executions.start(
            session_id,
            task_id,
            tool_call.name,
            tool_call.arguments,
        )
        try:
            result = self._tool_executor.execute(
                tool_call.name,
                tool_call.arguments,
                ToolContext(session_id, task_id),
            )
        except KeyboardInterrupt:
            payload = {
                "ok": False,
                "error": {
                    "type": "Interrupted",
                    "message": "tool execution interrupted",
                },
            }
            self._tool_executions.finish(execution_id, "interrupted", payload)
            self._events.emit(
                "tool_call_completed",
                session_id=session_id,
                task_id=task_id,
                tool=tool_call.name,
                status="interrupted",
                duration_ms=round((perf_counter() - started) * 1000, 3),
                error_type="KeyboardInterrupt",
            )
            raise
        except Exception as error:
            payload = {
                "ok": False,
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                },
            }
            self._tool_executions.finish(execution_id, "failed", payload)
            self._events.emit(
                "tool_call_completed",
                session_id=session_id,
                task_id=task_id,
                tool=tool_call.name,
                status="failed",
                duration_ms=round((perf_counter() - started) * 1000, 3),
                error_type=type(error).__name__,
            )
            return payload

        payload = {"ok": True, "result": result}
        self._tool_executions.finish(execution_id, "succeeded", payload)
        self._events.emit(
            "tool_call_completed",
            session_id=session_id,
            task_id=task_id,
            tool=tool_call.name,
            status="succeeded",
            duration_ms=round((perf_counter() - started) * 1000, 3),
        )
        return payload

    def _retry_delay(
        self,
        error: RetryableProviderError,
        attempt: int,
    ) -> float:
        requested = error.retry_after_seconds
        exponential = self._retry_base_delay_seconds * (2 ** (attempt - 1))
        delay = requested if requested is not None else exponential
        return min(delay, self._retry_max_delay_seconds)

    def _history(self, session_id: str) -> tuple[ChatMessage, ...]:
        records = self._messages.list_for_session(session_id)
        return tuple(_record_to_message(record) for record in records)

    def _close_interrupted_history(self, session_id: str) -> None:
        history = self._messages.list_for_session(session_id)
        if not history:
            return
        last = history[-1]
        if last.role == "assistant" and not last.metadata.get("tool_calls"):
            return

        pending_calls: list[dict[str, Any]] = []
        completed_call_ids: set[str] = set()
        for record in reversed(history):
            if record.role == "tool" and record.tool_call_id:
                completed_call_ids.add(record.tool_call_id)
                continue
            if record.role == "assistant" and record.metadata.get("tool_calls"):
                pending_calls = list(record.metadata["tool_calls"])
                break
            if record.role == "user":
                break

        for tool_call in pending_calls:
            if tool_call["id"] in completed_call_ids:
                continue
            self._messages.append(
                session_id,
                "tool",
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "type": "Interrupted",
                            "message": "task interrupted",
                        },
                    },
                    sort_keys=True,
                ),
                tool_call_id=tool_call["id"],
            )
        self._messages.append(
            session_id,
            "assistant",
            "Task interrupted before completion.",
        )


def _record_to_message(record: MessageRecord) -> ChatMessage:
    raw_tool_calls = record.metadata.get("tool_calls") or []
    tool_calls = tuple(
        ToolCall(item["id"], item["name"], item.get("arguments") or {})
        for item in raw_tool_calls
    )
    return ChatMessage(
        role=record.role,
        content=record.content,
        tool_calls=tool_calls,
        tool_call_id=record.tool_call_id,
    )

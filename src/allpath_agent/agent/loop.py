from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from allpath_agent.models.messages import ChatMessage, ChatRequest, ToolCall
from allpath_agent.models.provider import ChatProvider
from allpath_agent.models.router import ModelProfile
from allpath_agent.storage import MessageRepository, ToolExecutionRepository
from allpath_agent.storage.records import MessageRecord
from allpath_agent.tools import ToolContext, ToolExecutor


class IterationLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentResult:
    content: str
    model_profile: str
    model_calls: int
    tool_calls: int


class AgentLoop:
    def __init__(
        self,
        provider: ChatProvider,
        messages: MessageRepository,
        tool_executions: ToolExecutionRepository,
        tool_executor: ToolExecutor,
        max_model_calls: int = 12,
    ):
        if max_model_calls < 1:
            raise ValueError("max_model_calls must be positive")
        self._provider = provider
        self._messages = messages
        self._tool_executions = tool_executions
        self._tool_executor = tool_executor
        self._max_model_calls = max_model_calls

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

        while model_calls < self._max_model_calls:
            request = ChatRequest(
                model=model_profile.model,
                messages=(ChatMessage("system", system_prompt), *self._history(session_id)),
                tools=self._tool_executor.schemas() if tool_schemas is None else tool_schemas,
            )
            response = self._provider.complete(request)
            model_calls += 1

            if response.tool_calls:
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
            return AgentResult(
                content=response.content,
                model_profile=model_profile.name,
                model_calls=model_calls,
                tool_calls=executed_tool_calls,
            )

        raise IterationLimitError(
            f"task exceeded the limit of {self._max_model_calls} model calls"
        )

    def _execute_tool(self, session_id: str, task_id: str, tool_call: ToolCall) -> dict[str, Any]:
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
        except Exception as error:
            payload = {
                "ok": False,
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                },
            }
            self._tool_executions.finish(execution_id, "failed", payload)
            return payload

        payload = {"ok": True, "result": result}
        self._tool_executions.finish(execution_id, "succeeded", payload)
        return payload

    def _history(self, session_id: str) -> tuple[ChatMessage, ...]:
        return tuple(_record_to_message(record) for record in self._messages.list_for_session(session_id))


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

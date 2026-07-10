from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"invalid chat role: {self.role}")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("only assistant messages can contain tool calls")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages require a tool_call_id")
        if self.role != "tool" and self.tool_call_id:
            raise ValueError("only tool messages can contain a tool_call_id")
        if self.role in {"system", "user"} and not self.content:
            raise ValueError(f"{self.role} message content cannot be empty")
        if self.role == "assistant" and not self.content and not self.tool_calls:
            raise ValueError("assistant messages require content or tool calls")

    def to_openai(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [tool_call.to_openai() for tool_call in self.tool_calls]
        if self.tool_call_id:
            message["tool_call_id"] = self.tool_call_id
        return message


@dataclass(frozen=True)
class ChatRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("chat request model cannot be empty")
        if not self.messages:
            raise ValueError("chat request requires at least one message")


@dataclass(frozen=True)
class ChatResponse:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)

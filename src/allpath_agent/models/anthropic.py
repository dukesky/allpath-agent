from __future__ import annotations

from typing import Any

from .messages import ChatMessage, ChatRequest, ChatResponse, ToolCall
from .provider import ProviderError, Transport, json_http_transport


class AnthropicMessagesProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        max_output_tokens: int = 4096,
        timeout_seconds: float = 60,
        transport: Transport | None = None,
    ):
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._max_output_tokens = max_output_tokens
        self._timeout_seconds = timeout_seconds
        self._transport = transport or json_http_transport

    def complete(self, request: ChatRequest) -> ChatResponse:
        system, messages = _convert_messages(request.messages)
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": self._max_output_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [_convert_tool_schema(tool) for tool in request.tools]

        response = self._transport(
            f"{self._base_url}/v1/messages",
            {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload,
            self._timeout_seconds,
        )
        return _parse_anthropic_response(response)


def _convert_messages(messages: tuple[ChatMessage, ...]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        if message.role == "tool":
            _append_blocks(
                converted,
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content or "",
                    }
                ],
            )
            continue

        blocks: list[dict[str, Any]] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        if message.role == "assistant":
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.arguments,
                }
                for tool_call in message.tool_calls
            )
        if blocks:
            _append_blocks(converted, message.role, blocks)
    return "\n\n".join(system_parts), converted


def _append_blocks(
    messages: list[dict[str, Any]],
    role: str,
    blocks: list[dict[str, Any]],
) -> None:
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(blocks)
    else:
        messages.append({"role": role, "content": list(blocks)})


def _convert_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    try:
        function = tool["function"]
        return {
            "name": function["name"],
            "description": function.get("description", ""),
            "input_schema": function["parameters"],
        }
    except (KeyError, TypeError) as error:
        raise ProviderError("invalid OpenAI-style tool schema for Anthropic conversion") from error


def _parse_anthropic_response(payload: dict[str, Any]) -> ChatResponse:
    content = payload.get("content")
    if not isinstance(content, list):
        raise ProviderError("Anthropic response is missing content blocks")
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
        elif block.get("type") == "tool_use":
            try:
                arguments = block.get("input") or {}
                if not isinstance(arguments, dict):
                    raise TypeError("tool input must be an object")
                tool_calls.append(ToolCall(block["id"], block["name"], arguments))
            except (KeyError, TypeError) as error:
                raise ProviderError("Anthropic response contains an invalid tool_use block") from error

    raw_usage = payload.get("usage") or {}
    usage = {
        key: value
        for key, value in raw_usage.items()
        if isinstance(key, str) and isinstance(value, int)
    }
    return ChatResponse(
        content="\n".join(text_parts) or None,
        tool_calls=tuple(tool_calls),
        finish_reason=payload.get("stop_reason"),
        usage=usage,
    )

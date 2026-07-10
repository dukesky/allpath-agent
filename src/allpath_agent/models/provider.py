from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .messages import ChatMessage, ChatRequest, ChatResponse, ToolCall


class ProviderError(RuntimeError):
    pass


class ChatProvider(Protocol):
    def complete(self, request: ChatRequest) -> ChatResponse: ...


Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60,
        transport: Transport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _url_transport

    def complete(self, request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [_serialize_message(message) for message in request.messages],
        }
        if request.tools:
            payload["tools"] = list(request.tools)

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        response = self._transport(
            f"{self._base_url}/chat/completions",
            headers,
            payload,
            self._timeout_seconds,
        )
        return _parse_response(response)


class FakeProvider:
    def __init__(self, responses: list[ChatResponse]):
        self._responses = list(responses)
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if not self._responses:
            raise ProviderError("fake provider has no response remaining")
        return self._responses.pop(0)


def _serialize_message(message: ChatMessage) -> dict[str, Any]:
    payload = message.to_openai()
    if message.tool_calls:
        for tool_call in payload["tool_calls"]:
            tool_call["function"]["arguments"] = json.dumps(
                tool_call["function"]["arguments"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
    return payload


def _parse_response(payload: dict[str, Any]) -> ChatResponse:
    try:
        choice = payload["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise ProviderError("provider response is missing choices[0].message") from error

    tool_calls: list[ToolCall] = []
    for raw_call in message.get("tool_calls") or []:
        try:
            function = raw_call["function"]
            raw_arguments = function.get("arguments") or "{}"
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            if not isinstance(arguments, dict):
                raise TypeError("tool arguments must decode to an object")
            tool_calls.append(ToolCall(raw_call["id"], function["name"], arguments))
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ProviderError("provider returned an invalid tool call") from error

    raw_usage = payload.get("usage") or {}
    usage = {
        key: value
        for key, value in raw_usage.items()
        if isinstance(key, str) and isinstance(value, int)
    }
    return ChatResponse(
        content=message.get("content"),
        tool_calls=tuple(tool_calls),
        finish_reason=choice.get("finish_reason"),
        usage=usage,
    )


def _url_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise ProviderError(f"provider HTTP {error.code}: {body[:500]}") from error
    except URLError as error:
        raise ProviderError(f"provider connection failed: {error.reason}") from error

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise ProviderError("provider returned invalid JSON") from error
    if not isinstance(parsed, dict):
        raise ProviderError("provider response must be a JSON object")
    return parsed

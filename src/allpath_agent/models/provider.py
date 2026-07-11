from __future__ import annotations

import json
import re
import socket
from collections.abc import Callable
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .messages import ChatMessage, ChatRequest, ChatResponse, ToolCall


class ProviderError(RuntimeError):
    pass


class RetryableProviderError(ProviderError):
    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderTimeoutError(RetryableProviderError):
    pass


class ProviderRateLimitError(RetryableProviderError):
    pass


class ProviderConnectionError(RetryableProviderError):
    pass


class ProviderServerError(RetryableProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class ChatProvider(Protocol):
    def complete(self, request: ChatRequest) -> ChatResponse: ...


Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 60,
        transport: Transport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport or json_http_transport

    def complete(self, request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [_serialize_message(message) for message in request.messages],
        }
        if request.tools:
            payload["tools"] = list(request.tools)

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
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


class DemoProvider:
    def __init__(self) -> None:
        self._tool_call_number = 0

    def complete(self, request: ChatRequest) -> ChatResponse:
        last_message = request.messages[-1]
        if last_message.role == "tool":
            try:
                payload = json.loads(last_message.content or "{}")
            except json.JSONDecodeError:
                payload = {"ok": False, "error": {"message": "invalid tool result"}}
            if payload.get("ok"):
                result = payload.get("result")
                tool_name = _tool_name_for_result(request.messages, last_message.tool_call_id)
                if tool_name == "calculate" and isinstance(result, dict):
                    return ChatResponse(content=f"The result is {result.get('result')}.")
                if tool_name == "current_datetime" and isinstance(result, dict):
                    return ChatResponse(
                        content=(
                            f"The current time in {result.get('timezone')} is "
                            f"{result.get('time')}."
                        )
                    )
                if tool_name == "memory_set":
                    return ChatResponse(content="I saved that preference locally.")
                return ChatResponse(content=f"The local tool completed: {result}")
            error = payload.get("error") or {}
            return ChatResponse(content=f"Demo tool was not completed: {error.get('message', 'unknown error')}")

        content = last_message.content or ""
        lowered = content.lower()
        if any(phrase in lowered for phrase in ("what time", "current time", "几点", "时间")):
            return ChatResponse(
                tool_calls=(self._tool_call("current_datetime", {"timezone": "UTC"}),),
                finish_reason="tool_calls",
            )
        expression = _extract_arithmetic_expression(content)
        if expression:
            return ChatResponse(
                tool_calls=(self._tool_call("calculate", {"expression": expression}),),
                finish_reason="tool_calls",
            )
        if "remember" in lowered or "记住" in content:
            remembered = re.sub(r"^.*?(remember|记住)\s*", "", content, flags=re.IGNORECASE).strip()
            return ChatResponse(
                tool_calls=(
                    self._tool_call(
                        "memory_set",
                        {"key": "demo_note", "content": remembered or content},
                    ),
                ),
                finish_reason="tool_calls",
            )
        if any(
            phrase in lowered
            for phrase in (
                "connect a model",
                "connecting a model",
                "connect a provider",
                "连接模型",
                "模型配置",
            )
        ):
            return ChatResponse(
                content=(
                    "I can help you connect a real model. The current MVP supports "
                    "OpenAI, Anthropic, OpenRouter, Ollama, and Claude Code. Run "
                    "`allpath-agent init` once to create provider settings; this "
                    "local session will remain available."
                )
            )
        if lowered.strip() in {"hello", "hi", "hey", "你好", "嗨"}:
            return ChatResponse(
                content=(
                    "Hello! I'm running locally. You can try arithmetic, time, "
                    "memory, sessions, or ask how to connect a model."
                )
            )
        return ChatResponse(
            content=(
                "I'm running in local starter mode without a reasoning model, so I "
                "couldn't interpret that yet. I can currently handle arithmetic, "
                "current time, memory, sessions, and model connection guidance."
            )
        )

    def _tool_call(self, name: str, arguments: dict[str, Any]) -> ToolCall:
        self._tool_call_number += 1
        return ToolCall(f"demo-call-{self._tool_call_number}", name, arguments)


def _extract_arithmetic_expression(content: str) -> str | None:
    candidate = content.strip()
    candidate = re.sub(
        r"^(?:what\s+is|what's|calculate|compute|please\s+calculate|"
        r"帮我算(?:一下)?|计算|算一下)\s*",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"(?:等于多少|是多少|的结果是什么)\s*[?？]?$", "", candidate)
    candidate = candidate.strip().rstrip("?？")
    candidate = candidate.replace("×", "*").replace("÷", "/")
    candidate = candidate.replace("（", "(").replace("）", ")")
    word_operators = {
        r"\s+plus\s+": "+",
        r"\s+minus\s+": "-",
        r"\s+(?:times|multiplied\s+by)\s+": "*",
        r"\s+divided\s+by\s+": "/",
    }
    for pattern, operator_symbol in word_operators.items():
        candidate = re.sub(
            pattern,
            operator_symbol,
            candidate,
            flags=re.IGNORECASE,
        )
    candidate = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", "*", candidate)
    if not re.fullmatch(r"[0-9+\-*/%.()\s]+", candidate):
        return None
    if not re.search(r"[+\-*/%]", candidate) or not re.search(r"\d", candidate):
        return None
    return candidate.strip()


def _tool_name_for_result(
    messages: tuple[ChatMessage, ...],
    tool_call_id: str | None,
) -> str | None:
    for message in reversed(messages[:-1]):
        for tool_call in message.tool_calls:
            if tool_call.id == tool_call_id:
                return tool_call.name
    return None


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
        raise ProviderResponseError(
            "provider response is missing choices[0].message"
        ) from error

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
            raise ProviderResponseError("provider returned an invalid tool call") from error

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


def json_http_transport(
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
        message = f"provider HTTP {error.code}: {body[:500]}"
        if error.code in {401, 403}:
            raise ProviderAuthenticationError(message) from error
        if error.code == 408:
            raise ProviderTimeoutError(message) from error
        if error.code == 429:
            raise ProviderRateLimitError(
                message,
                retry_after_seconds=_retry_after_seconds(error),
            ) from error
        if error.code >= 500:
            raise ProviderServerError(message) from error
        raise ProviderResponseError(message) from error
    except (TimeoutError, socket.timeout) as error:
        raise ProviderTimeoutError("provider request timed out") from error
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise ProviderTimeoutError("provider request timed out") from error
        raise ProviderConnectionError(
            f"provider connection failed: {error.reason}"
        ) from error

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise ProviderResponseError("provider returned invalid JSON") from error
    if not isinstance(parsed, dict):
        raise ProviderResponseError("provider response must be a JSON object")
    return parsed


def _retry_after_seconds(error: HTTPError) -> float | None:
    value = error.headers.get("Retry-After") if error.headers else None
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None

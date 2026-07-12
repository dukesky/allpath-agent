from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .messages import ChatMessage, ChatRequest, ChatResponse
from .provider import ProviderError, Transport, json_http_transport


class GeminiGenerateContentProvider:
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
        self._transport = transport or json_http_transport

    def complete(self, request: ChatRequest) -> ChatResponse:
        if request.tools:
            raise ProviderError("Gemini tools are not enabled in the first API integration")
        system, contents = _convert_messages(request.messages)
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        model = quote(request.model.removeprefix("models/"), safe="-._")
        response = self._transport(
            f"{self._base_url}/models/{model}:generateContent?key={self._api_key}",
            {"content-type": "application/json"},
            payload,
            self._timeout_seconds,
        )
        return _parse_response(response)


def _convert_messages(messages: tuple[ChatMessage, ...]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        if message.role == "tool":
            raise ProviderError("Gemini tool history is not supported yet")
        role = "model" if message.role == "assistant" else "user"
        if message.content:
            contents.append({"role": role, "parts": [{"text": message.content}]})
    return "\n\n".join(system_parts), contents


def _parse_response(payload: dict[str, Any]) -> ChatResponse:
    try:
        candidate = payload["candidates"][0]
        parts = candidate["content"]["parts"]
    except (KeyError, IndexError, TypeError) as error:
        raise ProviderError("Gemini response is missing candidate content") from error
    text = "\n".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )
    if not text:
        raise ProviderError("Gemini response contains no text")
    raw_usage = payload.get("usageMetadata") or {}
    usage = {
        key: value
        for key, value in raw_usage.items()
        if isinstance(key, str) and isinstance(value, int)
    }
    return ChatResponse(
        content=text,
        finish_reason=candidate.get("finishReason"),
        usage=usage,
    )

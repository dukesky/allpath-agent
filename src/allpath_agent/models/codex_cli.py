from __future__ import annotations

import json

from .external_cli import CommandResult, CommandRunner, _flatten_messages, _run_command
from .messages import ChatRequest, ChatResponse
from .provider import ProviderError


class CodexCliProvider:
    def __init__(
        self,
        command: str = "codex",
        timeout_seconds: float = 300,
        runner: CommandRunner | None = None,
    ):
        self._command = command
        self._timeout_seconds = timeout_seconds
        self._runner = runner or _run_command

    def complete(self, request: ChatRequest) -> ChatResponse:
        if request.tools:
            raise ProviderError("Codex account provider does not yet support Allpath tool schemas")
        result = self._runner(
            [
                self._command,
                "exec",
                "--json",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--model",
                request.model,
                _flatten_messages(request.messages),
            ],
            self._timeout_seconds,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown CLI error"
            raise ProviderError(f"Codex command failed: {detail[:500]}")
        content = _last_agent_message(result)
        if not content:
            raise ProviderError("Codex JSONL response is missing an agent message")
        return ChatResponse(content=content, finish_reason="completed")


def _last_agent_message(result: CommandResult) -> str:
    messages: list[str] = []
    errors: list[str] = []
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "error" and isinstance(event.get("message"), str):
            errors.append(event["message"])
        failure = event.get("error")
        if event_type == "turn.failed" and isinstance(failure, dict):
            message = failure.get("message")
            if isinstance(message, str):
                errors.append(message)
        nested = event.get("msg")
        if isinstance(nested, dict):
            nested_type = nested.get("type")
            nested_message = nested.get("message")
            if nested_type in {"error", "stream_error"} and isinstance(nested_message, str):
                errors.append(nested_message)
            if nested_type == "agent_message" and isinstance(nested_message, str):
                messages.append(nested_message)
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            messages.append(text)
    if messages:
        return messages[-1]
    if errors:
        raise ProviderError(f"Codex request failed: {errors[-1][:500]}")
    return ""

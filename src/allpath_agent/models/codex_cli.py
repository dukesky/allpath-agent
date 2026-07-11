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
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            messages.append(text)
    return messages[-1] if messages else ""

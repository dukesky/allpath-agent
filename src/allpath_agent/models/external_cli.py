from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .messages import ChatMessage, ChatRequest, ChatResponse
from .provider import ProviderError, ProviderTimeoutError


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], float], CommandResult]


class ClaudeCodeProvider:
    def __init__(
        self,
        command: str = "claude",
        timeout_seconds: float = 300,
        runner: CommandRunner | None = None,
    ):
        self._command = command
        self._timeout_seconds = timeout_seconds
        self._runner = runner or _run_command

    def complete(self, request: ChatRequest) -> ChatResponse:
        if request.tools:
            raise ProviderError(
                "Claude Code account provider does not yet support Allpath tool schemas"
            )
        result = self._runner(
            [
                self._command,
                "-p",
                "--output-format",
                "json",
                "--permission-mode",
                "plan",
                "--model",
                request.model,
                _flatten_messages(request.messages),
            ],
            self._timeout_seconds,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown CLI error"
            raise ProviderError(f"Claude Code command failed: {detail[:500]}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ProviderError("Claude Code returned invalid JSON") from error
        content = payload.get("result") or payload.get("content")
        if not isinstance(content, str) or not content:
            raise ProviderError("Claude Code JSON response is missing result text")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return ChatResponse(
            content=content,
            finish_reason=payload.get("subtype") or payload.get("type"),
            usage={
                key: value
                for key, value in usage.items()
                if isinstance(key, str) and isinstance(value, int)
            },
        )


def _flatten_messages(messages: tuple[ChatMessage, ...]) -> str:
    parts: list[str] = []
    for message in messages:
        label = message.role.upper()
        if message.content:
            parts.append(f"{label}: {message.content}")
        for tool_call in message.tool_calls:
            parts.append(
                f"ASSISTANT TOOL CALL {tool_call.name}: "
                f"{json.dumps(tool_call.arguments, ensure_ascii=False, sort_keys=True)}"
            )
    return "\n\n".join(parts)


def _run_command(arguments: list[str], timeout_seconds: float) -> CommandResult:
    try:
        completed = subprocess.run(
            arguments,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as error:
        raise ProviderError(f"external provider command not found: {arguments[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise ProviderTimeoutError("external provider command timed out") from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)

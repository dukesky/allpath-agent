from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any

from .registry import ToolDefinition, ToolRegistry, ToolRisk
from .workspace import WorkspaceAccessError


ALLOWED_EXECUTABLES = frozenset(
    {
        "cat", "find", "git", "grep", "head", "jq", "ls", "node", "npm",
        "npx", "pwd", "python", "python3", "pytest", "rg", "sed", "sort",
        "tail", "uniq", "wc",
    }
)
BLOCKED_GIT_ACTIONS = frozenset({"clean", "reset", "restore", "checkout", "switch"})
MAX_TIMEOUT_SECONDS = 120
DEFAULT_TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 20_000


def register_terminal_tool(registry: ToolRegistry, roots: tuple[Path, ...]) -> None:
    terminal = BoundedTerminal(roots)
    registry.register(
        ToolDefinition(
            name="terminal",
            description=(
                "Run one approved foreground command inside the workspace without a shell. "
                "Use an argv array; pipes, redirects, background jobs, and arbitrary executables "
                "are unavailable."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    "cwd": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            handler=terminal.execute,
            risk=ToolRisk.SIDE_EFFECT,
        )
    )


class BoundedTerminal:
    def __init__(self, roots: tuple[Path, ...]):
        if not roots:
            raise ValueError("at least one terminal workspace root is required")
        self._roots = tuple(root.expanduser().resolve(strict=True) for root in roots)
        if any(not root.is_dir() for root in self._roots):
            raise ValueError("terminal workspace roots must be directories")

    def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = arguments["command"]
        if not command:
            raise ValueError("command must contain at least one argument")
        if len(command) > 100 or any(len(argument) > 10_000 for argument in command):
            raise ValueError("command arguments exceed terminal limits")
        executable = Path(command[0]).name
        if command[0] != executable or executable not in ALLOWED_EXECUTABLES:
            raise WorkspaceAccessError(f"terminal executable is not allowed: {command[0]}")
        if executable == "git" and len(command) > 1 and command[1] in BLOCKED_GIT_ACTIONS:
            raise WorkspaceAccessError(f"destructive git action is not allowed: {command[1]}")
        timeout_seconds = arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if timeout_seconds < 1 or timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS}")
        root, cwd = self._resolve_cwd(arguments.get("cwd", ""))
        started = perf_counter()
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=_safe_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _signal_group(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                _signal_group(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
        return {
            "workspace": str(root),
            "cwd": str(cwd.relative_to(root)) or ".",
            "command": command,
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "stdout": _bounded(stdout),
            "stderr": _bounded(stderr),
            "stdout_truncated": len(stdout) > MAX_OUTPUT_CHARS,
            "stderr_truncated": len(stderr) > MAX_OUTPUT_CHARS,
        }

    def _resolve_cwd(self, raw_cwd: str) -> tuple[Path, Path]:
        normalized = raw_cwd.replace("\\", "/")
        relative = PurePosixPath(normalized or ".")
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkspaceAccessError("terminal cwd must stay inside the workspace")
        parts = () if normalized == "" else relative.parts
        for root in self._roots:
            candidate = root.joinpath(*parts)
            if not candidate.exists():
                continue
            current = root
            for part in parts:
                current = current / part
                if current.is_symlink():
                    raise WorkspaceAccessError("terminal cwd cannot pass through symbolic links")
            resolved = candidate.resolve(strict=True)
            if resolved.is_relative_to(root) and resolved.is_dir():
                return root, resolved
        raise FileNotFoundError(f"terminal cwd does not exist: {raw_cwd or '.'}")


def _safe_environment() -> dict[str, str]:
    allowed = {"HOME", "LANG", "PATH", "SHELL", "TERM", "TMPDIR"}
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update({key: value for key, value in os.environ.items() if key.startswith("LC_")})
    environment["ALLPATH_TERMINAL"] = "1"
    return environment


def _signal_group(process_id: int, requested_signal: signal.Signals) -> None:
    try:
        os.killpg(process_id, requested_signal)
    except ProcessLookupError:
        pass


def _bounded(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return f"{value[:MAX_OUTPUT_CHARS]}\n… [output truncated]"

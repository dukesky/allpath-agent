from __future__ import annotations

import shutil
import sys
from collections.abc import Callable

from allpath_agent.hooks import HookEvent


Input = Callable[[str], str]
Output = Callable[[str], None]

_RESET = "\x1b[0m"
_ACCENT = "\x1b[38;5;39m"
_USER = "\x1b[38;5;81m"
_MUTED = "\x1b[2m"
_SUCCESS = "\x1b[38;5;114m"
_WARNING = "\x1b[38;5;214m"
_ERROR = "\x1b[38;5;203m"


class TerminalChatUI:
    """Small scrollback-friendly terminal UI for the classic Allpath CLI."""

    def __init__(
        self,
        input_fn: Input = input,
        output_fn: Output = print,
        *,
        color: bool | None = None,
        width: int | None = None,
    ):
        self._input = input_fn
        self._output = output_fn
        self._color = sys.stdout.isatty() if color is None else color
        terminal_width = width or shutil.get_terminal_size(fallback=(80, 24)).columns
        self._width = max(52, min(terminal_width, 92))

    def read_message(self, hint: str | None = None) -> str:
        self._output("")
        self._output(self._styled(self._top("YOU"), _USER))
        if hint:
            self._output(f"│  {self._styled(hint, _MUTED)}")
        self._output("│")
        try:
            return self._input(self._styled("│  ❯ ", _USER)).strip()
        finally:
            self._output(self._styled(self._bottom(), _USER))

    def assistant(self, content: str, profile: str = "standard") -> None:
        label = f"ALLPATH · {profile.upper()}"
        self._output("")
        self._output(self._styled(self._top(label), _ACCENT))
        lines = str(content).splitlines() or [""]
        for line in lines:
            self._output(f"│  {line}" if line else "│")
        self._output(self._styled(self._bottom(), _ACCENT))

    def usage(self, *, calls: int, tokens: int, estimated_cost_usd: float) -> None:
        text = (
            f"┊ model activity · {calls} call(s) · {tokens} tokens "
            f"· estimated ${estimated_cost_usd:.6f}"
        )
        self._output(self._styled(text, _MUTED))

    def suggestion(self, capability_id: str, message: str) -> None:
        self._output("")
        self._output(self._styled(self._top(f"NEXT · {capability_id}"), _SUCCESS))
        for line in str(message).splitlines() or [""]:
            self._output(f"│  {line}" if line else "│")
        self._output(self._styled(self._bottom(), _SUCCESS))

    def request_confirmation(
        self,
        title: str,
        description: str,
        details: str,
        prompt: str = "Allow this action? [y/N] ",
    ) -> str:
        self._output("")
        self._output(self._styled(self._top(f"APPROVAL · {title}"), _WARNING))
        self._output(f"│  {description}")
        self._output("│")
        for line in details.splitlines():
            self._output(f"│  {line}")
        try:
            return self._input(self._styled(f"│  ❯ {prompt}", _WARNING)).strip()
        finally:
            self._output(self._styled(self._bottom(), _WARNING))

    def handle_event(self, event: HookEvent) -> None:
        fields = event.fields
        if event.name == "task_started":
            profile = str(fields.get("profile", "standard"))
            provider = str(fields.get("provider", "model"))
            model = str(fields.get("model", "unknown"))
            self._output("")
            self._output(self._styled(f"● Working · {profile} · {provider}/{model}", _ACCENT))
        elif event.name == "model_call_completed":
            duration = _duration(fields.get("duration_ms"))
            self._output(self._styled(f"┊ model response · {duration}", _MUTED))
        elif event.name == "model_call_retry_scheduled":
            delay = fields.get("delay_seconds", 0)
            self._output(self._styled(f"┊ retrying model · in {delay}s", _WARNING))
        elif event.name == "tool_call_started":
            self._output(self._styled(f"┊ tool · {fields.get('tool', 'unknown')} · running", _MUTED))
        elif event.name == "tool_call_completed":
            status = str(fields.get("status", "unknown"))
            marker = "✓" if status == "succeeded" else "!"
            style = _SUCCESS if status == "succeeded" else _ERROR
            duration = _duration(fields.get("duration_ms"))
            self._output(
                self._styled(
                    f"┊ {marker} {fields.get('tool', 'unknown')} · {status} · {duration}",
                    style,
                )
            )

    def _top(self, label: str) -> str:
        prefix = f"╭─ {label} "
        return prefix + "─" * max(self._width - len(prefix), 1)

    def _bottom(self) -> str:
        return "╰" + "─" * max(self._width - 1, 1)

    def _styled(self, text: str, style: str) -> str:
        if not self._color:
            return text
        return f"{style}{text}{_RESET}"


def _duration(value: object) -> str:
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return "done"
    if milliseconds < 1000:
        return f"{milliseconds:.0f}ms"
    return f"{milliseconds / 1000:.1f}s"

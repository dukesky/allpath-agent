from __future__ import annotations

import json
from collections.abc import Callable

from allpath_agent.tools import ApprovalRequest
from allpath_agent.tools.redaction import redact_tool_arguments

from .render import TerminalChatUI


class TerminalApprovalHandler:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ):
        self._input = input_fn
        self._output = output_fn
        self._ui = TerminalChatUI(input_fn, output_fn)

    def request(self, approval: ApprovalRequest) -> tuple[bool, str | None]:
        details = json.dumps(
            _approval_preview(redact_tool_arguments(approval.tool_name, approval.arguments)),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        try:
            answer = self._ui.request_confirmation(
                approval.tool_name,
                approval.description,
                details,
            ).lower()
        except (EOFError, KeyboardInterrupt):
            self._output("")
            return False, "approval prompt was interrupted"
        if answer in {"y", "yes"}:
            return True, "approved in terminal"
        return False, "denied in terminal"


def _approval_preview(arguments: dict, limit: int = 4_000) -> dict:
    preview = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > limit:
            preview[key] = f"{value[:limit]}\n… [truncated; {len(value)} characters total]"
        else:
            preview[key] = value
    return preview

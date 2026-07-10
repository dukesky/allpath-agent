from __future__ import annotations

import json
from collections.abc import Callable

from allpath_agent.tools import ApprovalRequest


class TerminalApprovalHandler:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ):
        self._input = input_fn
        self._output = output_fn

    def request(self, approval: ApprovalRequest) -> tuple[bool, str | None]:
        self._output("")
        self._output(f"Approval required: {approval.tool_name}")
        self._output(approval.description)
        self._output(json.dumps(approval.arguments, ensure_ascii=False, indent=2, sort_keys=True))
        try:
            answer = self._input("Allow this action? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            self._output("")
            return False, "approval prompt was interrupted"
        if answer in {"y", "yes"}:
            return True, "approved in terminal"
        return False, "denied in terminal"

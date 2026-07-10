from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from allpath_agent.storage import ToolApprovalRepository

from .contracts import ToolContext
from .registry import ToolRegistry, ToolRisk


class ToolApprovalDenied(PermissionError):
    pass


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    description: str
    arguments: dict[str, Any]
    context: ToolContext


class ApprovalHandler(Protocol):
    def request(self, approval: ApprovalRequest) -> tuple[bool, str | None]: ...


class DenyByDefaultApprovalHandler:
    def request(self, approval: ApprovalRequest) -> tuple[bool, str | None]:
        return False, "no interactive approval handler is configured"


class ToolRuntime:
    def __init__(
        self,
        registry: ToolRegistry,
        approvals: ToolApprovalRepository,
        approval_handler: ApprovalHandler | None = None,
    ):
        self._registry = registry
        self._approvals = approvals
        self._approval_handler = approval_handler or DenyByDefaultApprovalHandler()

    def schemas(self) -> tuple[dict[str, Any], ...]:
        return self._registry.schemas()

    def execute(self, name: str, arguments: dict[str, Any], context: ToolContext) -> Any:
        definition = self._registry.validate(name, arguments)
        if definition.risk == ToolRisk.SIDE_EFFECT:
            allowed, reason = self._approval_handler.request(
                ApprovalRequest(name, definition.description, arguments, context)
            )
            decision = "allowed" if allowed else "denied"
            self._approvals.record(
                context.session_id,
                context.task_id,
                name,
                arguments,
                decision,
                reason,
            )
            if not allowed:
                raise ToolApprovalDenied(reason or f"approval denied for tool: {name}")
        return definition.handler(arguments)

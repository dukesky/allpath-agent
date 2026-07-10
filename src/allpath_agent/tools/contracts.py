from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolContext:
    session_id: str
    task_id: str


class ToolExecutor(Protocol):
    def schemas(self) -> tuple[dict[str, Any], ...]: ...

    def execute(self, name: str, arguments: dict[str, Any], context: ToolContext) -> Any: ...

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .validation import validate_arguments


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    SIDE_EFFECT = "side_effect"


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    risk: ToolRisk = ToolRisk.READ_ONLY

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    _VALID_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if not self._VALID_NAME.fullmatch(definition.name):
            raise ValueError(f"invalid tool name: {definition.name}")
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        if definition.parameters.get("type") != "object":
            raise ValueError("tool parameter schema must have object type")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"unknown tool: {name}") from error

    def schemas(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._tools[name].schema() for name in sorted(self._tools))

    def validate(self, name: str, arguments: dict[str, Any]) -> ToolDefinition:
        definition = self.get(name)
        validate_arguments(arguments, definition.parameters)
        return definition

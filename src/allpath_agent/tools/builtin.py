from __future__ import annotations

import ast
import math
import operator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from allpath_agent.storage import MemoryRepository

from .registry import ToolDefinition, ToolRegistry, ToolRisk


def create_builtin_registry(memories: MemoryRepository) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="current_datetime",
            description="Return the current date and time in an IANA timezone.",
            parameters={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone such as UTC or America/Los_Angeles.",
                        "minLength": 1,
                    }
                },
                "additionalProperties": False,
            },
            handler=_current_datetime,
        )
    )
    registry.register(
        ToolDefinition(
            name="memory_get",
            description="Read one durable user preference or fact by key.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "scope": {"type": "string", "minLength": 1},
                },
                "required": ["key"],
                "additionalProperties": False,
            },
            handler=lambda arguments: _memory_get(memories, arguments),
        )
    )
    registry.register(
        ToolDefinition(
            name="memory_set",
            description="Save or update one durable user preference or fact.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "content": {"type": "string", "minLength": 1},
                    "scope": {"type": "string", "minLength": 1},
                },
                "required": ["key", "content"],
                "additionalProperties": False,
            },
            handler=lambda arguments: _memory_set(memories, arguments),
            risk=ToolRisk.SIDE_EFFECT,
        )
    )
    registry.register(
        ToolDefinition(
            name="calculate",
            description="Evaluate a basic arithmetic expression without executing code.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "minLength": 1},
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            handler=_calculate,
        )
    )
    return registry


def _current_datetime(arguments: dict[str, Any]) -> dict[str, str]:
    timezone_name = arguments.get("timezone", "UTC")
    current = datetime.now(ZoneInfo(timezone_name))
    return {
        "timezone": timezone_name,
        "iso": current.isoformat(),
        "date": current.date().isoformat(),
        "time": current.time().isoformat(timespec="seconds"),
    }


def _memory_get(memories: MemoryRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    scope = arguments.get("scope", "user")
    record = memories.get(arguments["key"], scope)
    if record is None:
        return {"found": False, "key": arguments["key"], "scope": scope}
    return {
        "found": True,
        "key": record.key,
        "scope": record.scope,
        "content": record.content,
        "updated_at": record.updated_at,
    }


def _memory_set(memories: MemoryRepository, arguments: dict[str, Any]) -> dict[str, str]:
    record = memories.set(
        arguments["key"],
        arguments["content"],
        arguments.get("scope", "user"),
    )
    return {
        "key": record.key,
        "scope": record.scope,
        "content": record.content,
        "updated_at": record.updated_at,
    }


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _calculate(arguments: dict[str, Any]) -> dict[str, int | float]:
    expression = arguments["expression"]
    if len(expression) > 200:
        raise ValueError("expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ValueError("invalid arithmetic expression") from error
    result = _evaluate_node(tree.body)
    if not math.isfinite(float(result)) or abs(result) > 1e100:
        raise ValueError("calculation result is outside the allowed range")
    return {"result": result}


def _evaluate_node(node: ast.AST) -> int | float:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("exponent is outside the allowed range")
        return _BINARY_OPERATORS[type(node.op)](left, right)
    raise ValueError("expression contains unsupported syntax")

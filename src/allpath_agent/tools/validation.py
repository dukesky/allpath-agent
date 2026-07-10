from __future__ import annotations

from typing import Any


class ToolValidationError(ValueError):
    pass


def validate_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    _validate(arguments, schema, "arguments")


def _validate(value: Any, schema: dict[str, Any], path: str) -> None:
    expected_type = schema.get("type")
    if expected_type and not _matches_type(value, expected_type):
        raise ToolValidationError(f"{path} must be {expected_type}")

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(repr(item) for item in schema["enum"])
        raise ToolValidationError(f"{path} must be one of: {allowed}")

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise ToolValidationError(f"{path} must contain at least {minimum_length} characters")

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                raise ToolValidationError(f"{path}.{key} is required")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ToolValidationError(f"{path} contains unknown field: {unknown[0]}")
        for key, item in value.items():
            property_schema = properties.get(key)
            if property_schema:
                _validate(item, property_schema, f"{path}.{key}")

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]")


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    raise ToolValidationError(f"unsupported schema type: {expected_type}")

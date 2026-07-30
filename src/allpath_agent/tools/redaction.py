from __future__ import annotations

from typing import Any


def redact_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(arguments)
    if tool_name == "browser_type" and isinstance(redacted.get("text"), str):
        redacted["text"] = f"[redacted browser text; {len(redacted['text'])} characters]"
    return redacted

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from allpath_agent.storage import ConnectorConfigRepository

from .registry import ToolDefinition, ToolRegistry

SUPPORTED_CHANNELS = ("telegram", "slack", "whatsapp")
_PREFILL_FIELDS = ("name", "prompt", "schedule", "timezone")
_HANDOFF_NOTE = (
    "The host chat now starts the guided flow with the user. "
    "Tell the user the setup questions come next; do not describe the steps yourself."
)


@dataclass
class AssistantDirective:
    kind: str
    channel: str | None = None
    reconnect: bool = False
    prefill: dict[str, str] = field(default_factory=dict)


class DirectiveSink:
    def __init__(self):
        self._pending: AssistantDirective | None = None

    def set(self, directive: AssistantDirective) -> None:
        self._pending = directive

    def take(self) -> AssistantDirective | None:
        pending, self._pending = self._pending, None
        return pending


def register_assistant_tools(
    registry: ToolRegistry,
    configs: ConnectorConfigRepository,
    sink: DirectiveSink,
) -> None:
    def _entry(channel: str) -> dict[str, Any]:
        record = configs.get(channel)
        if record is None:
            return {"channel": channel, "status": "not_configured", "detail": "never connected"}
        return {"channel": channel, "status": record["status"], "detail": record["detail"]}

    def _channel_status(arguments: dict[str, Any]) -> dict[str, Any]:
        channel = arguments.get("channel")
        if channel:
            if channel not in SUPPORTED_CHANNELS:
                raise ValueError(f"unsupported channel: {channel}")
            return _entry(channel)
        return {"channels": [_entry(channel) for channel in SUPPORTED_CHANNELS]}

    def _channel_connect(arguments: dict[str, Any]) -> dict[str, Any]:
        channel = arguments["channel"]
        if channel not in SUPPORTED_CHANNELS:
            raise ValueError(f"unsupported channel: {channel}")
        reconnect = bool(arguments.get("reconnect", False))
        record = configs.get(channel)
        if record is not None and record["status"] == "active" and not reconnect:
            return {
                "already_connected": True,
                "channel": channel,
                "detail": record["detail"],
                "note": (
                    "This channel is already connected. Tell the user, and only call again "
                    "with reconnect=true if they explicitly want to reconfigure it."
                ),
            }
        sink.set(AssistantDirective("channel_setup", channel=channel, reconnect=reconnect))
        return {"directive": "channel_setup", "channel": channel, "note": _HANDOFF_NOTE}

    def _create_automation(arguments: dict[str, Any]) -> dict[str, Any]:
        prefill = {
            fieldname: str(arguments[fieldname]).strip()
            for fieldname in _PREFILL_FIELDS
            if arguments.get(fieldname)
        }
        sink.set(AssistantDirective("automation_setup", prefill=prefill))
        return {"directive": "automation_setup", "prefilled": sorted(prefill), "note": _HANDOFF_NOTE}

    def _connect_model(arguments: dict[str, Any]) -> dict[str, Any]:
        sink.set(AssistantDirective("model_setup"))
        return {"directive": "model_setup", "note": _HANDOFF_NOTE}

    registry.register(
        ToolDefinition(
            name="channel_status",
            description=(
                "Report whether the Telegram, Slack, and WhatsApp messaging channels are "
                "connected. Use this whenever the user asks ABOUT a channel or its state. "
                "Read-only; never starts setup."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": list(SUPPORTED_CHANNELS)},
                },
                "additionalProperties": False,
            },
            handler=_channel_status,
        )
    )
    registry.register(
        ToolDefinition(
            name="channel_connect",
            description=(
                "Start the guided setup for a messaging channel when the user asks to CONNECT "
                "one. The host runs the interactive tutorial after this call — do not describe "
                "the steps yourself. Set reconnect=true only when the user explicitly wants to "
                "reconfigure an already-connected channel."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": list(SUPPORTED_CHANNELS)},
                    "reconnect": {"type": "boolean"},
                },
                "required": ["channel"],
                "additionalProperties": False,
            },
            handler=_channel_connect,
        )
    )
    registry.register(
        ToolDefinition(
            name="create_automation",
            description=(
                "Start the guided creation of a scheduled automation (one-time or recurring, "
                "with optional delivery to a connected channel). Pass any values you can "
                "extract from the user's request: name, prompt (the task instruction), "
                "schedule (a five-field cron expression or an ISO date-time), and timezone "
                "(IANA name). The host collects anything missing and always asks the user to "
                "confirm before saving."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "prompt": {"type": "string"},
                    "schedule": {"type": "string"},
                    "timezone": {"type": "string"},
                },
                "additionalProperties": False,
            },
            handler=_create_automation,
        )
    )
    registry.register(
        ToolDefinition(
            name="connect_model",
            description=(
                "Start the guided model-provider setup when the user wants to add or replace "
                "a model connection. The host runs the interactive flow after this call."
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_connect_model,
        )
    )

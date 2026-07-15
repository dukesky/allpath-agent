from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class InboundMessage:
    connector_id: str
    conversation_id: str
    sender_id: str
    message_id: str
    text: str
    received_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboundMessage:
    conversation_id: str
    text: str
    reply_to_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectorStatus:
    id: str
    connected: bool
    detail: str


class Connector(Protocol):
    id: str

    def status(self) -> ConnectorStatus: ...

    def poll(self) -> tuple[InboundMessage, ...]: ...

    def send(self, message: OutboundMessage) -> None: ...

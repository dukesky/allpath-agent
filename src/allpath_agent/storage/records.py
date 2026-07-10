from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SessionRecord:
    id: str
    title: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MessageRecord:
    id: int
    session_id: str
    role: str
    content: str
    tool_call_id: str | None
    created_at: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MemoryRecord:
    id: int
    scope: str
    key: str
    content: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CapabilityProgressRecord:
    capability_id: str
    status: str
    offer_count: int
    success_count: int
    sessions_since_offer: int | None
    updated_at: str

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .database import Database
from .records import CapabilityProgressRecord, MemoryRecord, MessageRecord, SessionRecord


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _message_record(row: Any) -> MessageRecord:
    values = dict(row)
    values["metadata"] = json.loads(values.pop("metadata_json"))
    return MessageRecord(**values)


class SessionRepository:
    def __init__(self, database: Database):
        self._database = database

    def create(self, title: str | None = None, session_id: str | None = None) -> SessionRecord:
        record_id = session_id or str(uuid4())
        now = utc_now()
        with self._database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (record_id, title, now, now),
            )
        return SessionRecord(record_id, title, now, now)

    def get(self, session_id: str) -> SessionRecord | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return SessionRecord(**dict(row)) if row else None

    def list_recent(self, limit: int = 20) -> list[SessionRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [SessionRecord(**dict(row)) for row in rows]


class MessageRepository:
    _VALID_ROLES = frozenset({"system", "user", "assistant", "tool"})

    def __init__(self, database: Database):
        self._database = database

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MessageRecord:
        if role not in self._VALID_ROLES:
            raise ValueError(f"invalid message role: {role}")
        message_metadata = metadata or {}
        if role == "tool" and not tool_call_id:
            raise ValueError("tool messages require a tool_call_id")
        if role != "tool" and tool_call_id:
            raise ValueError("only tool messages can contain a tool_call_id")
        if not content and not (role == "assistant" and message_metadata.get("tool_calls")):
            raise ValueError("message content cannot be empty")
        now = utc_now()
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO messages(
                    session_id, role, content, tool_call_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, tool_call_id, now, _json(message_metadata)),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return MessageRecord(
            cursor.lastrowid,
            session_id,
            role,
            content,
            tool_call_id,
            now,
            message_metadata,
        )

    def list_for_session(self, session_id: str) -> list[MessageRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [_message_record(row) for row in rows]


class RoutingDecisionRepository:
    def __init__(self, database: Database):
        self._database = database

    def record(
        self,
        session_id: str,
        task_id: str,
        profile: str,
        model: str,
        reason: str,
        complexity_score: int,
    ) -> int:
        if complexity_score < 0:
            raise ValueError("complexity score cannot be negative")
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO routing_decisions(
                    session_id, task_id, profile, model, reason, complexity_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, task_id, profile, model, reason, complexity_score, utc_now()),
            )
        return cursor.lastrowid

    def list_for_task(self, session_id: str, task_id: str) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM routing_decisions
                WHERE session_id = ? AND task_id = ?
                ORDER BY id
                """,
                (session_id, task_id),
            ).fetchall()
        return [dict(row) for row in rows]


class MemoryRepository:
    def __init__(self, database: Database):
        self._database = database

    def set(self, key: str, content: str, scope: str = "user") -> MemoryRecord:
        if not key.strip() or not content.strip():
            raise ValueError("memory key and content cannot be empty")
        now = utc_now()
        with self._database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO memories(scope, key, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope, key) DO UPDATE SET
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (scope, key, content, now, now),
            )
            row = connection.execute(
                "SELECT * FROM memories WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()
        return MemoryRecord(**dict(row))

    def get(self, key: str, scope: str = "user") -> MemoryRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()
        return MemoryRecord(**dict(row)) if row else None

    def list_scope(self, scope: str = "user") -> list[MemoryRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE scope = ? ORDER BY key",
                (scope,),
            ).fetchall()
        return [MemoryRecord(**dict(row)) for row in rows]


class CapabilityProgressRepository:
    def __init__(self, database: Database):
        self._database = database

    def save(
        self,
        capability_id: str,
        status: str,
        offer_count: int = 0,
        success_count: int = 0,
        sessions_since_offer: int | None = None,
    ) -> CapabilityProgressRecord:
        if offer_count < 0 or success_count < 0:
            raise ValueError("capability counters cannot be negative")
        now = utc_now()
        with self._database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO capability_progress(
                    capability_id, status, offer_count, success_count,
                    sessions_since_offer, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                    status = excluded.status,
                    offer_count = excluded.offer_count,
                    success_count = excluded.success_count,
                    sessions_since_offer = excluded.sessions_since_offer,
                    updated_at = excluded.updated_at
                """,
                (
                    capability_id,
                    status,
                    offer_count,
                    success_count,
                    sessions_since_offer,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM capability_progress WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        return CapabilityProgressRecord(**dict(row))

    def list_all(self) -> dict[str, CapabilityProgressRecord]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM capability_progress ORDER BY capability_id").fetchall()
        records = [CapabilityProgressRecord(**dict(row)) for row in rows]
        return {record.capability_id: record for record in records}


class ToolExecutionRepository:
    def __init__(self, database: Database):
        self._database = database

    def start(
        self,
        session_id: str,
        task_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> int:
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO tool_executions(
                    session_id, task_id, tool_name, arguments_json, status, created_at
                ) VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (session_id, task_id, tool_name, _json(arguments), utc_now()),
            )
        return cursor.lastrowid

    def finish(self, execution_id: int, status: str, result: Any) -> None:
        if status not in {"succeeded", "failed", "interrupted"}:
            raise ValueError(f"invalid terminal tool status: {status}")
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE tool_executions
                SET result_json = ?, status = ?, completed_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (_json(result), status, utc_now(), execution_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("tool execution is missing or already finished")

    def get(self, execution_id: int) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tool_executions WHERE id = ?",
                (execution_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["arguments"] = json.loads(result.pop("arguments_json"))
        result["result"] = json.loads(result.pop("result_json")) if result["result_json"] else None
        return result

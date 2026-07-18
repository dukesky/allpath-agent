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

    def set_title(self, session_id: str, title: str) -> None:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("session title cannot be empty")
        now = utc_now()
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (cleaned, now, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"session does not exist: {session_id}")


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
        provider: str = "default",
    ) -> int:
        if complexity_score < 0:
            raise ValueError("complexity score cannot be negative")
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO routing_decisions(
                    session_id, task_id, profile, model, reason,
                    complexity_score, created_at, provider
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    profile,
                    model,
                    reason,
                    complexity_score,
                    utc_now(),
                    provider,
                ),
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

    def latest_for_session(self, session_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM routing_decisions
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row is not None else None


class ConnectorSessionRepository:
    def __init__(self, database: Database):
        self._database = database

    def bind(self, connector_id: str, conversation_id: str, session_id: str) -> None:
        if not connector_id or not conversation_id:
            raise ValueError("connector and conversation IDs cannot be empty")
        with self._database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO connector_sessions(
                    connector_id, conversation_id, session_id, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (connector_id, conversation_id, session_id, utc_now()),
            )

    def session_for(self, connector_id: str, conversation_id: str) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT session_id FROM connector_sessions
                WHERE connector_id = ? AND conversation_id = ?
                """,
                (connector_id, conversation_id),
            ).fetchone()
        return row["session_id"] if row is not None else None


class ConnectorConfigRepository:
    def __init__(self, database: Database):
        self._database = database

    def save(self, connector_id: str, status: str, detail: str) -> None:
        if status not in {"active", "disabled", "error"}:
            raise ValueError(f"invalid connector status: {status}")
        now = utc_now()
        with self._database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO connector_configs(
                    connector_id, status, detail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(connector_id) DO UPDATE SET
                    status = excluded.status,
                    detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (connector_id, status, detail, now, now),
            )

    def get(self, connector_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM connector_configs WHERE connector_id = ?",
                (connector_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_all(self) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM connector_configs ORDER BY connector_id"
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

    def get(self, capability_id: str) -> CapabilityProgressRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM capability_progress WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        return CapabilityProgressRecord(**dict(row)) if row else None


class CurriculumSessionRepository:
    def __init__(self, database: Database):
        self._database = database

    def start_once(self, session_id: str) -> bool:
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO curriculum_sessions(session_id, started_at) VALUES (?, ?)",
                (session_id, utc_now()),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                """
                UPDATE capability_progress
                SET sessions_since_offer = sessions_since_offer + 1,
                    updated_at = ?
                WHERE sessions_since_offer IS NOT NULL
                """,
                (utc_now(),),
            )
        return True


class CapabilitySuggestionRepository:
    def __init__(self, database: Database):
        self._database = database

    def record(self, session_id: str, capability_id: str, message: str) -> int:
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO capability_suggestions(
                    session_id, capability_id, message, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (session_id, capability_id, message, utc_now()),
            )
        return cursor.lastrowid

    def get_for_session(self, session_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM capability_suggestions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None


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

    def list_for_task(self, session_id: str, task_id: str) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tool_executions
                WHERE session_id = ? AND task_id = ?
                ORDER BY id
                """,
                (session_id, task_id),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["arguments"] = json.loads(record.pop("arguments_json"))
            result_json = record.pop("result_json")
            record["result"] = json.loads(result_json) if result_json else None
            records.append(record)
        return records


class ToolApprovalRepository:
    def __init__(self, database: Database):
        self._database = database

    def record(
        self,
        session_id: str,
        task_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        decision: str,
        reason: str | None = None,
    ) -> int:
        if decision not in {"allowed", "denied"}:
            raise ValueError(f"invalid approval decision: {decision}")
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO tool_approvals(
                    session_id, task_id, tool_name, arguments_json,
                    decision, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    tool_name,
                    _json(arguments),
                    decision,
                    reason,
                    utc_now(),
                ),
            )
        return cursor.lastrowid

    def list_for_task(self, session_id: str, task_id: str) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tool_approvals
                WHERE session_id = ? AND task_id = ?
                ORDER BY id
                """,
                (session_id, task_id),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["arguments"] = json.loads(record.pop("arguments_json"))
            records.append(record)
        return records


class WorkflowRunRepository:
    def __init__(self, database: Database):
        self._database = database

    def create(
        self,
        workflow_id: str,
        session_id: str,
        current_step: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        now = utc_now()
        with self._database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO workflow_runs(
                    id, workflow_id, session_id, status, current_step,
                    state_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_id,
                    session_id,
                    current_step,
                    _json(state),
                    now,
                    now,
                ),
            )
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return _workflow_record(row) if row else None

    def get_active(self, session_id: str, workflow_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM workflow_runs
                WHERE session_id = ? AND workflow_id = ? AND status = 'running'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id, workflow_id),
            ).fetchone()
        return _workflow_record(row) if row else None

    def update(
        self,
        run_id: str,
        current_step: str | None,
        state: dict[str, Any],
        status: str = "running",
    ) -> dict[str, Any]:
        if status not in {"running", "succeeded", "failed", "cancelled"}:
            raise ValueError(f"invalid workflow status: {status}")
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE workflow_runs
                SET status = ?, current_step = ?, state_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, current_step, _json(state), utc_now(), run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"workflow run does not exist: {run_id}")
        return self.get(run_id)


def _workflow_record(row: Any) -> dict[str, Any]:
    record = dict(row)
    record["state"] = json.loads(record.pop("state_json"))
    return record


class AutomationJobRepository:
    def __init__(self, database: Database):
        self._database = database

    def create(
        self,
        *,
        name: str,
        prompt: str,
        schedule_kind: str,
        schedule_expression: str,
        timezone: str,
        session_id: str,
        next_run_at: str,
        model_role: str = "auto",
        destination_connector_id: str | None = None,
        destination_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if schedule_kind not in {"once", "cron"}:
            raise ValueError("automation schedule kind must be once or cron")
        if model_role not in {"auto", "fast", "standard", "advanced"}:
            raise ValueError("invalid automation model role")
        if not name.strip() or not prompt.strip():
            raise ValueError("automation name and prompt cannot be empty")
        if (destination_connector_id is None) != (destination_conversation_id is None):
            raise ValueError("automation destination requires both connector and conversation IDs")
        job_id = str(uuid4())
        now = utc_now()
        with self._database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO automation_jobs(
                    id, name, prompt, schedule_kind, schedule_expression,
                    timezone, session_id, model_role, destination_connector_id,
                    destination_conversation_id, enabled, next_run_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    job_id,
                    name.strip(),
                    prompt.strip(),
                    schedule_kind,
                    schedule_expression,
                    timezone,
                    session_id,
                    model_role,
                    destination_connector_id,
                    destination_conversation_id,
                    next_run_at,
                    now,
                    now,
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM automation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _automation_job_record(row) if row else None

    def list_all(self) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM automation_jobs ORDER BY created_at, id"
            ).fetchall()
        return [_automation_job_record(row) for row in rows]

    def set_enabled(self, job_id: str, enabled: bool) -> dict[str, Any]:
        with self._database.connect() as connection, connection:
            if enabled:
                row = connection.execute(
                    "SELECT next_run_at FROM automation_jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"automation job does not exist: {job_id}")
                if row["next_run_at"] is None:
                    raise ValueError("automation has no future run to enable")
            cursor = connection.execute(
                "UPDATE automation_jobs SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), utc_now(), job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"automation job does not exist: {job_id}")
        return self.get(job_id)

    def complete_schedule(
        self,
        job_id: str,
        *,
        last_run_at: str,
        next_run_at: str | None,
        disable: bool,
    ) -> None:
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE automation_jobs
                SET last_run_at = ?, next_run_at = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (last_run_at, next_run_at, int(not disable), utc_now(), job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"automation job does not exist: {job_id}")

    def delete(self, job_id: str) -> bool:
        with self._database.connect() as connection, connection:
            cursor = connection.execute("DELETE FROM automation_jobs WHERE id = ?", (job_id,))
        return cursor.rowcount == 1


class AutomationRunRepository:
    def __init__(self, database: Database):
        self._database = database

    def claim_due(self, now: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT jobs.* FROM automation_jobs AS jobs
                WHERE jobs.enabled = 1
                  AND jobs.next_run_at IS NOT NULL
                  AND jobs.next_run_at <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM automation_runs AS runs
                      WHERE runs.job_id = jobs.id
                        AND runs.scheduled_for = jobs.next_run_at
                  )
                ORDER BY jobs.next_run_at, jobs.created_at
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            run_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO automation_runs(id, job_id, status, scheduled_for)
                VALUES (?, ?, 'claimed', ?)
                """,
                (run_id, row["id"], row["next_run_at"]),
            )
            connection.commit()
        return {"run": self.get(run_id), "job": _automation_job_record(row)}

    def claim_now(self, job_id: str, scheduled_for: str) -> dict[str, Any]:
        run_id = str(uuid4())
        with self._database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO automation_runs(id, job_id, status, scheduled_for)
                VALUES (?, ?, 'claimed', ?)
                """,
                (run_id, job_id, scheduled_for),
            )
        return self.get(run_id)

    def start(self, run_id: str, task_id: str | None = None) -> dict[str, Any]:
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE automation_runs
                SET status = 'running', task_id = ?, started_at = ?
                WHERE id = ? AND status = 'claimed'
                """,
                (task_id, utc_now(), run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("automation run is missing or already started")
        return self.get(run_id)

    def finish(
        self,
        run_id: str,
        status: str,
        *,
        task_id: str | None = None,
        output_text: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "interrupted"}:
            raise ValueError("invalid automation run terminal status")
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE automation_runs
                SET status = ?, task_id = COALESCE(?, task_id), completed_at = ?,
                    output_text = ?, error_type = ?, error_message = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    status,
                    task_id,
                    utc_now(),
                    output_text,
                    error_type,
                    error_message[:240] if error_message else None,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("automation run is missing or already terminal")
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM automation_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_for_job(self, job_id: str) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM automation_runs WHERE job_id = ? ORDER BY scheduled_for, id",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def _automation_job_record(row: Any) -> dict[str, Any]:
    record = dict(row)
    record["enabled"] = bool(record["enabled"])
    return record

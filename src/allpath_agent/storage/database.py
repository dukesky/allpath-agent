from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
                content TEXT NOT NULL,
                tool_call_id TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX messages_session_id_id ON messages(session_id, id)",
            """
            CREATE TABLE routing_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL,
                profile TEXT NOT NULL,
                model TEXT NOT NULL,
                reason TEXT NOT NULL,
                complexity_score INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX routing_decisions_session_task ON routing_decisions(session_id, task_id)",
            """
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(scope, key)
            )
            """,
            """
            CREATE TABLE capability_progress (
                capability_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                offer_count INTEGER NOT NULL DEFAULT 0 CHECK (offer_count >= 0),
                success_count INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
                sessions_since_offer INTEGER CHECK (sessions_since_offer IS NULL OR sessions_since_offer >= 0),
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE tool_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                result_json TEXT,
                status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'interrupted')),
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """,
            "CREATE INDEX tool_executions_session_task ON tool_executions(session_id, task_id)",
            """
            CREATE TABLE workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
                status TEXT NOT NULL,
                current_step TEXT,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        ),
    ),
    (
        2,
        (
            "ALTER TABLE messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
        ),
    ),
    (
        3,
        (
            """
            CREATE TABLE tool_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (decision IN ('allowed', 'denied')),
                reason TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX tool_approvals_session_task ON tool_approvals(session_id, task_id)",
        ),
    ),
    (
        4,
        (
            """
            CREATE TABLE curriculum_sessions (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE capability_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
                capability_id TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX capability_suggestions_capability ON capability_suggestions(capability_id)",
        ),
    ),
    (
        5,
        (
            "ALTER TABLE routing_decisions ADD COLUMN provider TEXT NOT NULL DEFAULT 'default'",
        ),
    ),
    (
        6,
        (
            """
            CREATE TABLE connector_sessions (
                connector_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                PRIMARY KEY(connector_id, conversation_id),
                UNIQUE(session_id)
            )
            """,
        ),
    ),
    (
        7,
        (
            """
            CREATE TABLE connector_configs (
                connector_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('active', 'disabled', 'error')),
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        ),
    ),
    (
        8,
        (
            """
            CREATE TABLE automation_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                schedule_kind TEXT NOT NULL CHECK(schedule_kind IN ('once', 'cron')),
                schedule_expression TEXT NOT NULL,
                timezone TEXT NOT NULL,
                session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
                model_role TEXT NOT NULL CHECK(model_role IN ('auto', 'fast', 'standard', 'advanced')),
                destination_connector_id TEXT,
                destination_conversation_id TEXT,
                enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                next_run_at TEXT,
                last_run_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (
                    (destination_connector_id IS NULL AND destination_conversation_id IS NULL)
                    OR
                    (destination_connector_id IS NOT NULL AND destination_conversation_id IS NOT NULL)
                )
            )
            """,
            "CREATE INDEX automation_jobs_due ON automation_jobs(enabled, next_run_at)",
            """
            CREATE TABLE automation_runs (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES automation_jobs(id) ON DELETE CASCADE,
                task_id TEXT,
                status TEXT NOT NULL CHECK(status IN ('claimed', 'running', 'succeeded', 'failed', 'interrupted')),
                scheduled_for TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                output_text TEXT,
                error_type TEXT,
                error_message TEXT,
                output_message_id TEXT,
                UNIQUE(job_id, scheduled_for)
            )
            """,
            "CREATE INDEX automation_runs_job_scheduled ON automation_runs(job_id, scheduled_for)",
        ),
    ),
)


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            applied = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for version, statements in MIGRATIONS:
                if version in applied:
                    continue
                with connection:
                    for statement in statements:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version) VALUES (?)",
                        (version,),
                    )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

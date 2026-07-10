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

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.storage import (
    CapabilityProgressRepository,
    Database,
    MemoryRepository,
    MessageRepository,
    RoutingDecisionRepository,
    SessionRepository,
    ToolExecutionRepository,
    WorkflowRunRepository,
)


class StorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_initialize_is_idempotent_and_applies_migration(self) -> None:
        self.database.initialize()
        with self.database.connect() as connection:
            versions = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual([row["version"] for row in versions], [1, 2, 3, 4, 5, 6, 7])

    def test_session_messages_and_routing_are_persisted(self) -> None:
        sessions = SessionRepository(self.database)
        messages = MessageRepository(self.database)
        routing = RoutingDecisionRepository(self.database)
        session = sessions.create("First conversation", session_id="session-1")

        messages.append(session.id, "user", "Hello")
        messages.append(session.id, "assistant", "Hi there")
        routing.record(
            session.id,
            "task-1",
            "fast",
            "fast-model",
            "simple task",
            1,
            provider="openai",
        )

        self.assertEqual([message.role for message in messages.list_for_session(session.id)], ["user", "assistant"])
        self.assertEqual(routing.list_for_task(session.id, "task-1")[0]["profile"], "fast")
        self.assertEqual(routing.list_for_task(session.id, "task-1")[0]["provider"], "openai")
        self.assertEqual(routing.latest_for_session(session.id)["task_id"], "task-1")
        self.assertEqual(sessions.get(session.id).title, "First conversation")

    def test_session_title_can_be_updated(self) -> None:
        sessions = SessionRepository(self.database)
        session = sessions.create(session_id="session-title")
        sessions.set_title(session.id, "Plan tomorrow")
        self.assertEqual(sessions.get(session.id).title, "Plan tomorrow")

    def test_memory_upsert_preserves_identity(self) -> None:
        memories = MemoryRepository(self.database)
        original = memories.set("response_style", "concise")
        updated = memories.set("response_style", "detailed")

        self.assertEqual(original.id, updated.id)
        self.assertEqual(memories.get("response_style").content, "detailed")

    def test_capability_progress_round_trip(self) -> None:
        progress = CapabilityProgressRepository(self.database)
        progress.save("memory", "offered", offer_count=1, sessions_since_offer=0)
        progress.save("memory", "succeeded", offer_count=1, success_count=1)

        saved = progress.list_all()["memory"]
        self.assertEqual(saved.status, "succeeded")
        self.assertEqual(saved.success_count, 1)

    def test_tool_execution_has_single_terminal_transition(self) -> None:
        session = SessionRepository(self.database).create(session_id="session-1")
        executions = ToolExecutionRepository(self.database)
        execution_id = executions.start(session.id, "task-1", "current_time", {"timezone": "UTC"})
        executions.finish(execution_id, "succeeded", {"time": "12:00"})

        record = executions.get(execution_id)
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["arguments"], {"timezone": "UTC"})
        self.assertEqual(record["result"], {"time": "12:00"})
        with self.assertRaises(ValueError):
            executions.finish(execution_id, "failed", {"error": "late failure"})

    def test_messages_require_existing_session(self) -> None:
        with self.assertRaises(Exception):
            MessageRepository(self.database).append("missing", "user", "Hello")

    def test_workflow_run_state_round_trip(self) -> None:
        session = SessionRepository(self.database).create(session_id="workflow-session")
        workflows = WorkflowRunRepository(self.database)
        created = workflows.create(
            "provider_connection",
            session.id,
            "choose_provider",
            {"language": "en"},
        )
        updated = workflows.update(
            created["id"],
            "choose_model",
            {"language": "en", "provider": "openai"},
        )

        self.assertEqual(updated["state"]["provider"], "openai")
        self.assertEqual(
            workflows.get_active(session.id, "provider_connection")["current_step"],
            "choose_model",
        )


if __name__ == "__main__":
    unittest.main()

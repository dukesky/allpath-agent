from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.secrets import SecretStore
from allpath_agent.storage import (
    ConnectorConfigRepository,
    Database,
    SessionRepository,
    WorkflowRunRepository,
)
from allpath_agent.workflows import TelegramConnectionWorkflow


class TelegramConnectionWorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name)
        self.database = Database(self.home / "state.db")
        self.database.initialize()
        self.session = SessionRepository(self.database).create(session_id="session-1")
        self.runs = WorkflowRunRepository(self.database)
        self.secrets = SecretStore(self.home / "secrets.json")
        self.configs = ConnectorConfigRepository(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_verified_token_activates_telegram_without_persisting_secret_in_sqlite(self) -> None:
        workflow = TelegramConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda token: "@allpath_bot",
        )

        started = workflow.handle(self.session.id, "连接 Telegram")
        completed = workflow.submit_secret(self.session.id, "private-token")

        self.assertTrue(started.request_secret)
        self.assertIn("@BotFather", started.messages[0])
        self.assertTrue(completed.completed)
        self.assertEqual(self.secrets.values()["TELEGRAM_BOT_TOKEN"], "private-token")
        self.assertEqual(self.configs.get("telegram")["status"], "active")
        self.assertEqual(self.configs.get("telegram")["detail"], "@allpath_bot")
        with self.database.connect() as connection:
            state = connection.execute(
                "SELECT state_json FROM workflow_runs WHERE workflow_id = ?",
                ("telegram_connection",),
            ).fetchone()["state_json"]
        self.assertNotIn("private-token", state)

    def test_failed_verification_keeps_setup_resumable_and_secret_unsaved(self) -> None:
        workflow = TelegramConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda token: (_ for _ in ()).throw(ValueError("invalid token")),
        )
        workflow.handle(self.session.id, "connect Telegram")

        failed = workflow.submit_secret(self.session.id, "bad-token")

        self.assertTrue(failed.request_secret)
        self.assertTrue(workflow.active(self.session.id))
        self.assertEqual(self.secrets.values(), {})
        self.assertEqual(self.configs.get("telegram")["status"], "error")


if __name__ == "__main__":
    unittest.main()

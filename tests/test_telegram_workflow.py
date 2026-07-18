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

    def advance_to_token(self, workflow: TelegramConnectionWorkflow):
        result = None
        for _ in range(4):
            result = workflow.handle(self.session.id, "继续")
        return result

    def test_verified_token_activates_telegram_without_persisting_secret_in_sqlite(self) -> None:
        workflow = TelegramConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda token: "@allpath_bot",
        )

        started = workflow.handle(self.session.id, "连接 Telegram")
        token_request = self.advance_to_token(workflow)
        completed = workflow.submit_secret(self.session.id, "private-token")

        self.assertFalse(started.request_secret)
        self.assertIn("[1/4]", started.messages[0])
        self.assertIn("@BotFather", started.messages[0])
        self.assertTrue(token_request.request_secret)
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
        self.advance_to_token(workflow)

        failed = workflow.submit_secret(self.session.id, "bad-token")

        self.assertTrue(failed.request_secret)
        self.assertTrue(workflow.active(self.session.id))
        self.assertEqual(self.secrets.values(), {})
        self.assertEqual(self.configs.get("telegram")["status"], "error")

    def test_progress_back_and_restart_resume(self) -> None:
        workflow = TelegramConnectionWorkflow(
            self.runs, self.secrets, self.configs, verifier=lambda token: "@bot"
        )
        workflow.handle(self.session.id, "连接 Telegram")
        second = workflow.handle(self.session.id, "继续")
        back = workflow.handle(self.session.id, "返回")
        workflow.handle(self.session.id, "继续")

        resumed = TelegramConnectionWorkflow(
            self.runs, self.secrets, self.configs, verifier=lambda token: "@bot"
        )
        status = resumed.handle(self.session.id, "状态")

        self.assertIn("[2/4]", second.messages[0])
        self.assertIn("[1/4]", back.messages[0])
        self.assertIn("[2/4]", status.messages[0])
        self.assertIn("Telegram 设置 2/4", resumed.input_hint(self.session.id))


if __name__ == "__main__":
    unittest.main()

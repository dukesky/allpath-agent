from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.secrets import SecretStore
from allpath_agent.storage import ConnectorConfigRepository, Database, SessionRepository, WorkflowRunRepository
from allpath_agent.workflows import SlackConnectionWorkflow


class SlackConnectionWorkflowTestCase(unittest.TestCase):
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

    def test_two_hidden_tokens_are_verified_and_never_persisted_in_workflow_state(self) -> None:
        captured = []
        workflow = SlackConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda bot, app: captured.append((bot, app)) or "Workspace / allpath",
        )

        started = workflow.handle(self.session.id, "connect Slack")
        next_secret = workflow.submit_secret(self.session.id, "xoxb-private")
        completed = workflow.submit_secret(self.session.id, "xapp-private")

        self.assertTrue(started.request_secret)
        self.assertIn("Socket Mode", started.messages[0])
        self.assertTrue(next_secret.request_secret)
        self.assertTrue(completed.completed)
        self.assertEqual(captured, [("xoxb-private", "xapp-private")])
        self.assertEqual(self.configs.get("slack")["status"], "active")
        self.assertEqual(
            set(self.secrets.values()),
            {"SLACK_APP_TOKEN", "SLACK_BOT_TOKEN"},
        )
        with self.database.connect() as connection:
            state = connection.execute(
                "SELECT state_json FROM workflow_runs WHERE workflow_id = ?",
                ("slack_connection",),
            ).fetchone()["state_json"]
        self.assertNotIn("xoxb-private", state)
        self.assertNotIn("xapp-private", state)

    def test_restart_requires_bot_token_again(self) -> None:
        workflow = SlackConnectionWorkflow(self.runs, self.secrets, self.configs, verifier=lambda bot, app: "ok")
        workflow.handle(self.session.id, "connect Slack")
        workflow.submit_secret(self.session.id, "xoxb-private")

        resumed = SlackConnectionWorkflow(self.runs, self.secrets, self.configs, verifier=lambda bot, app: "ok")
        result = resumed.submit_secret(self.session.id, "xapp-private")

        self.assertTrue(result.request_secret)
        self.assertIn("Bot Token again", result.messages[0])
        self.assertEqual(self.secrets.values(), {})


if __name__ == "__main__":
    unittest.main()

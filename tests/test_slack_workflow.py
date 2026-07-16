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

    def advance_to_tokens(self, workflow: SlackConnectionWorkflow):
        result = None
        for _ in range(7):
            result = workflow.handle(self.session.id, "继续")
        return result

    def test_two_hidden_tokens_are_verified_and_never_persisted_in_workflow_state(self) -> None:
        captured = []
        workflow = SlackConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda bot, app: captured.append((bot, app)) or "Workspace / allpath",
        )

        started = workflow.handle(self.session.id, "connect Slack")
        token_request = self.advance_to_tokens(workflow)
        next_secret = workflow.submit_secret(self.session.id, "xoxb-private")
        completed = workflow.submit_secret(self.session.id, "xapp-private")

        self.assertFalse(started.request_secret)
        self.assertIn("[1/7]", started.messages[0])
        self.assertIn("Create New App", started.messages[0])
        self.assertTrue(token_request.request_secret)
        self.assertIn("xoxb-", token_request.messages[0])
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
        self.advance_to_tokens(workflow)
        workflow.submit_secret(self.session.id, "xoxb-private")

        resumed = SlackConnectionWorkflow(self.runs, self.secrets, self.configs, verifier=lambda bot, app: "ok")
        result = resumed.submit_secret(self.session.id, "xapp-private")

        self.assertTrue(result.request_secret)
        self.assertIn("Bot Token again", result.messages[0])
        self.assertEqual(self.secrets.values(), {})

    def test_progress_back_status_and_restart_resume_the_same_step(self) -> None:
        workflow = SlackConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda bot, app: "ok",
        )

        first = workflow.handle(self.session.id, "连接 Slack")
        second = workflow.handle(self.session.id, "继续")
        status = workflow.handle(self.session.id, "状态")
        back = workflow.handle(self.session.id, "返回")
        workflow.handle(self.session.id, "继续")

        resumed = SlackConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda bot, app: "ok",
        )
        resumed_status = resumed.handle(self.session.id, "状态")

        self.assertIn("[1/7]", first.messages[0])
        self.assertIn("[2/7]", second.messages[0])
        self.assertIn("`chat:write`", status.messages[0])
        self.assertIn("[1/7]", back.messages[0])
        self.assertIn("[2/7]", resumed_status.messages[0])
        self.assertIn("Slack 设置 2/7", resumed.input_hint(self.session.id))

    def test_unrelated_text_does_not_advance_setup(self) -> None:
        workflow = SlackConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda bot, app: "ok",
        )
        workflow.handle(self.session.id, "connect Slack")

        result = workflow.handle(self.session.id, "I cannot find that button")

        self.assertFalse(result.request_secret)
        self.assertIn("type “continue”", result.messages[0])
        self.assertIn("1/7", workflow.input_hint(self.session.id))


if __name__ == "__main__":
    unittest.main()

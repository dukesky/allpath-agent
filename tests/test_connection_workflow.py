from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from allpath_agent.config import load_config
from allpath_agent.provider_runtime import build_provider_pool
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import Database, SessionRepository, WorkflowRunRepository
from allpath_agent.workflows import ProviderConnectionWorkflow


class ProviderConnectionWorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name)
        self.database = Database(self.home / "state.db")
        self.database.initialize()
        self.session = SessionRepository(self.database).create(session_id="session-1")
        self.runs = WorkflowRunRepository(self.database)
        self.secrets = SecretStore(self.home / "secrets.json")
        self.verifications = []

        def verify(provider, profile, secret):
            self.verifications.append((provider, profile, secret))

        self.verify = verify

        self.workflow = ProviderConnectionWorkflow(
            self.home / "config.toml",
            self.runs,
            self.secrets,
            verifier=verify,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_api_key_flow_is_resumable_and_keeps_secret_out_of_workflow_state(self) -> None:
        started = self.workflow.handle(self.session.id, "连接模型")
        selected = self.workflow.handle(self.session.id, "1")

        resumed = ProviderConnectionWorkflow(
            self.home / "config.toml",
            self.runs,
            self.secrets,
            verifier=self.verify,
        )
        model = resumed.handle(self.session.id, "test-model")
        completed = resumed.submit_secret(self.session.id, "secret-value")

        self.assertTrue(started.handled)
        self.assertIn("OpenAI", started.messages[0])
        self.assertIn("模型 ID", selected.messages[0])
        self.assertTrue(model.request_secret)
        self.assertTrue(completed.completed)
        config = load_config(self.home / "config.toml")
        self.assertEqual(config.models[0].model, "test-model")
        self.assertEqual(self.secrets.values()["OPENAI_API_KEY"], "secret-value")
        self.assertEqual(stat.S_IMODE(self.secrets.path.stat().st_mode), 0o600)
        self.assertNotIn(
            "secret-value",
            (self.home / "config.toml").read_text(encoding="utf-8"),
        )
        with self.database.connect() as connection:
            stored_state = connection.execute(
                "SELECT state_json FROM workflow_runs WHERE workflow_id = ?",
                ("provider_connection",),
            ).fetchone()["state_json"]
        self.assertNotIn("secret-value", stored_state)
        self.assertEqual(self.verifications[0][2], "secret-value")
        pool = build_provider_pool(
            config,
            self.secrets.merged_environment({}),
        )
        self.assertEqual(pool.ids(), ("openai",))

    def test_failed_verification_does_not_write_config_or_secret(self) -> None:
        def fail_verification(provider, profile, secret):
            raise RuntimeError("unavailable")

        workflow = ProviderConnectionWorkflow(
            self.home / "config.toml",
            self.runs,
            self.secrets,
            verifier=fail_verification,
        )
        (self.home / "config.toml").write_text("existing-config", encoding="utf-8")
        workflow.handle(self.session.id, "connect a model")
        workflow.handle(self.session.id, "2")
        request = workflow.handle(self.session.id, "test-model")
        failed = workflow.submit_secret(self.session.id, "not-saved")

        self.assertTrue(request.request_secret)
        self.assertTrue(failed.request_secret)
        self.assertEqual(
            (self.home / "config.toml").read_text(encoding="utf-8"),
            "existing-config",
        )
        self.assertEqual(self.secrets.values(), {})

    def test_cancel_marks_resumable_run_terminal(self) -> None:
        self.workflow.handle(self.session.id, "connect model")
        cancelled = self.workflow.handle(self.session.id, "cancel")

        self.assertIn("cancelled", cancelled.messages[0])
        self.assertFalse(self.workflow.active(self.session.id))


if __name__ == "__main__":
    unittest.main()

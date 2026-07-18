from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.secrets import SecretStore
from allpath_agent.storage import ConnectorConfigRepository, Database, SessionRepository, WorkflowRunRepository
from allpath_agent.workflows import WhatsAppConnectionWorkflow


class WhatsAppConnectionWorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name)
        self.database = Database(self.home / "state.db")
        self.database.initialize()
        self.session = SessionRepository(self.database).create()
        self.runs = WorkflowRunRepository(self.database)
        self.secrets = SecretStore(self.home / "secrets.json")
        self.configs = ConnectorConfigRepository(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def advance_to_credentials(self, workflow: WhatsAppConnectionWorkflow):
        result = None
        for _ in range(5):
            result = workflow.handle(self.session.id, "继续")
        return result

    def test_four_hidden_values_activate_connector_without_workflow_secret_persistence(self) -> None:
        calls = []
        workflow = WhatsAppConnectionWorkflow(
            self.runs, self.secrets, self.configs,
            verifier=lambda access, phone: calls.append((access, phone)) or "Allpath / +15551234567",
        )

        started = workflow.handle(self.session.id, "连接 WhatsApp")
        credential_request = self.advance_to_credentials(workflow)
        first = workflow.submit_secret(self.session.id, "access-token")
        second = workflow.submit_secret(self.session.id, "phone-id")
        third = workflow.submit_secret(self.session.id, "app-secret")
        run_id = self.runs.get_active(self.session.id, "whatsapp_connection")["id"]
        completed = workflow.submit_secret(self.session.id, "verify-token")

        self.assertFalse(started.request_secret)
        self.assertIn("[1/9]", started.messages[0])
        self.assertTrue(credential_request.request_secret)
        self.assertTrue(first.request_secret and second.request_secret and third.request_secret)
        self.assertFalse(completed.completed)
        self.assertIn("[6/9]", completed.messages[0])
        self.assertEqual(calls, [("access-token", "phone-id")])
        self.assertEqual(self.configs.get("whatsapp")["status"], "active")
        self.assertEqual(set(self.secrets.values()), {
            "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN",
        })
        run = self.runs.get(run_id)
        self.assertNotIn("access-token", repr(run))
        self.assertNotIn("app-secret", repr(run))

    def test_post_credential_steps_require_explicit_end_to_end_confirmation(self) -> None:
        workflow = WhatsAppConnectionWorkflow(
            self.runs,
            self.secrets,
            self.configs,
            verifier=lambda access, phone: "Allpath / +15551234567",
        )
        workflow.handle(self.session.id, "connect WhatsApp")
        self.advance_to_credentials(workflow)
        for secret in ("access", "phone", "app-secret", "verify"):
            result = workflow.submit_secret(self.session.id, secret)

        tunnel = workflow.handle(self.session.id, "continue")
        webhook = workflow.handle(self.session.id, "continue")
        test_step = workflow.handle(self.session.id, "continue")
        completed = workflow.handle(self.session.id, "continue")

        self.assertIn("[7/9]", tunnel.messages[0])
        self.assertIn("[8/9]", webhook.messages[0])
        self.assertIn("[9/9]", test_step.messages[0])
        self.assertTrue(completed.completed)
        self.assertFalse(workflow.active(self.session.id))

    def test_restart_resumes_non_secret_webhook_step(self) -> None:
        workflow = WhatsAppConnectionWorkflow(
            self.runs, self.secrets, self.configs, verifier=lambda access, phone: "ok"
        )
        workflow.handle(self.session.id, "连接 WhatsApp")
        self.advance_to_credentials(workflow)
        for secret in ("access", "phone", "secret", "verify"):
            workflow.submit_secret(self.session.id, secret)
        workflow.handle(self.session.id, "继续")

        resumed = WhatsAppConnectionWorkflow(
            self.runs, self.secrets, self.configs, verifier=lambda access, phone: "ok"
        )
        status = resumed.handle(self.session.id, "状态")

        self.assertIn("[7/9]", status.messages[0])
        self.assertIn("WhatsApp 设置 7/9", resumed.input_hint(self.session.id))

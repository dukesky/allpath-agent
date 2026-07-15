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

    def test_four_hidden_values_activate_connector_without_workflow_secret_persistence(self) -> None:
        calls = []
        workflow = WhatsAppConnectionWorkflow(
            self.runs, self.secrets, self.configs,
            verifier=lambda access, phone: calls.append((access, phone)) or "Allpath / +15551234567",
        )

        started = workflow.handle(self.session.id, "连接 WhatsApp")
        first = workflow.submit_secret(self.session.id, "access-token")
        second = workflow.submit_secret(self.session.id, "phone-id")
        third = workflow.submit_secret(self.session.id, "app-secret")
        run_id = self.runs.get_active(self.session.id, "whatsapp_connection")["id"]
        completed = workflow.submit_secret(self.session.id, "verify-token")

        self.assertTrue(started.request_secret)
        self.assertTrue(first.request_secret and second.request_secret and third.request_secret)
        self.assertTrue(completed.completed)
        self.assertEqual(calls, [("access-token", "phone-id")])
        self.assertEqual(self.configs.get("whatsapp")["status"], "active")
        self.assertEqual(set(self.secrets.values()), {
            "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN",
        })
        run = self.runs.get(run_id)
        self.assertNotIn("access-token", repr(run))
        self.assertNotIn("app-secret", repr(run))

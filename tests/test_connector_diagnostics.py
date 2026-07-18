from __future__ import annotations

import unittest
from types import SimpleNamespace

from allpath_agent.connectors import diagnose_connectors


class ConnectorDiagnosticsTestCase(unittest.TestCase):
    def test_reports_missing_credentials_without_constructing_connector(self) -> None:
        diagnostics = diagnose_connectors(
            [{"connector_id": "slack", "status": "active"}],
            {"SLACK_BOT_TOKEN": "xoxb-present"},
            factories={"slack": lambda *values: self.fail("factory should not run")},
        )

        self.assertEqual(diagnostics[0].credentials, "missing: app token")
        self.assertEqual(diagnostics[0].verification, "not run")

    def test_verifies_connector_without_exposing_credentials(self) -> None:
        captured = []

        class Connector:
            def status(self):
                return SimpleNamespace(connected=True, detail="Workspace / allpath")

        diagnostics = diagnose_connectors(
            [{"connector_id": "slack", "status": "active"}],
            {"SLACK_BOT_TOKEN": "xoxb-private", "SLACK_APP_TOKEN": "xapp-private"},
            factories={"slack": lambda *values: captured.append(values) or Connector()},
        )

        self.assertEqual(captured, [("xoxb-private", "xapp-private")])
        self.assertEqual(diagnostics[0].credentials, "present")
        self.assertIn("verified", diagnostics[0].verification)
        self.assertNotIn("private", repr(diagnostics[0]))

    def test_whatsapp_reports_webhook_runtime_separately(self) -> None:
        class Connector:
            def status(self):
                return SimpleNamespace(connected=True, detail="Allpath / +1555")

        diagnostics = diagnose_connectors(
            [{"connector_id": "whatsapp", "status": "active"}],
            {
                "WHATSAPP_ACCESS_TOKEN": "access",
                "WHATSAPP_PHONE_NUMBER_ID": "phone",
                "WHATSAPP_APP_SECRET": "secret",
                "WHATSAPP_VERIFY_TOKEN": "verify",
            },
            factories={"whatsapp": lambda *values: Connector()},
            whatsapp_probe=lambda: False,
        )

        self.assertIn("not reachable", diagnostics[0].runtime)
        self.assertIn("gateway", diagnostics[0].runtime)

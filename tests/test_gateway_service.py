from __future__ import annotations

import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from allpath_agent.gateway_service import GatewayServiceManager


class GatewayServiceManagerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.commands = []

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def runner(self, command):
        self.commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "running", "")

    def test_macos_install_writes_secret_free_launch_agent_and_bootstraps(self) -> None:
        manager = GatewayServiceManager(
            self.root / "allpath-home",
            platform_name="darwin",
            user_home=self.root,
            executable="/usr/local/bin/allpath-agent",
            runner=self.runner,
            user_id=501,
        )

        status = manager.install()
        payload = plistlib.loads(manager.service_path.read_bytes())

        self.assertTrue(status.installed and status.running)
        self.assertEqual(payload["ProgramArguments"][-1], "gateway")
        self.assertNotIn("TOKEN", repr(payload).upper())
        self.assertIn(("launchctl", "bootstrap", "gui/501", str(manager.service_path)), self.commands)

    def test_linux_install_restart_and_uninstall_are_idempotent(self) -> None:
        manager = GatewayServiceManager(
            self.root / "allpath-home",
            platform_name="linux",
            user_home=self.root,
            executable="/usr/bin/allpath-agent",
            runner=self.runner,
        )

        manager.install()
        unit = manager.service_path.read_text(encoding="utf-8")
        manager.restart()
        status = manager.uninstall()

        self.assertIn("ExecStart=", unit)
        self.assertNotIn("WHATSAPP_ACCESS_TOKEN", unit)
        self.assertFalse(status.installed)
        self.assertFalse(manager.service_path.exists())

    def test_status_reports_not_installed_without_running_commands(self) -> None:
        manager = GatewayServiceManager(
            self.root / "home",
            platform_name="darwin",
            user_home=self.root,
            runner=self.runner,
        )

        status = manager.status()

        self.assertFalse(status.installed)
        self.assertEqual(self.commands, [])

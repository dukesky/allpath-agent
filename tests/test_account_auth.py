from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from allpath_agent.cli.account_auth import ensure_codex_login


class AccountAuthTestCase(unittest.TestCase):
    @patch("allpath_agent.cli.account_auth.shutil.which", return_value="/usr/bin/codex")
    @patch("allpath_agent.cli.account_auth.subprocess.run")
    def test_reuses_existing_codex_login(self, run: Mock, which: Mock) -> None:
        run.return_value = Mock(returncode=0)
        connected, message = ensure_codex_login()
        self.assertTrue(connected)
        self.assertIn("already signed in", message)
        run.assert_called_once()

    @patch("allpath_agent.cli.account_auth.shutil.which", return_value="/usr/bin/codex")
    @patch("allpath_agent.cli.account_auth.subprocess.run")
    def test_starts_official_login_when_needed(self, run: Mock, which: Mock) -> None:
        run.side_effect = [Mock(returncode=1), Mock(returncode=0)]
        connected, message = ensure_codex_login()
        self.assertTrue(connected)
        self.assertIn("connected", message)
        self.assertEqual(run.call_args_list[1].args[0], ["codex", "login"])


if __name__ == "__main__":
    unittest.main()

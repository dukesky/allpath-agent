from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

# scripts/run_tests.py discovers this package with `tests/` itself as the
# discovery top-level directory, so the repository root is not on sys.path
# and `tests.test_cli` would not be importable as a dotted module. Add the
# root explicitly (harmless no-op under `python3.12 -m unittest
# tests.test_golden_path`, where it is already on sys.path) so the import
# below works under both invocations.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from allpath_agent.cli.main import main
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import (
    AutomationJobRepository,
    AutomationRunRepository,
    CapabilityProgressRepository,
    CapabilitySuggestionRepository,
    ConnectorConfigRepository,
    ConnectorSessionRepository,
    Database,
    SessionRepository,
)
from allpath_agent.workflows.provider_connection import (
    CHOICES,
    _model_profile,
    _provider_config,
    _write_config_atomic,
)

from tests.test_cli import ROOT, run_cli


class FakeTelegramConnector:
    sent: list[tuple[str, str]] = []

    def __init__(self, token: str):
        self.id = "telegram"
        self.token = token

    def status(self):  # pragma: no cover - not used by tick
        raise AssertionError("status is not part of the tick path")

    def start(self) -> None:  # pragma: no cover
        pass

    def stop(self) -> None:  # pragma: no cover
        pass

    def poll(self):  # pragma: no cover
        return []

    def send(self, message) -> str:
        FakeTelegramConnector.sent.append((message.conversation_id, message.text))
        return "fake-msg-1"


class GoldenPathTestCase(unittest.TestCase):
    def test_model_to_telegram_daily_briefing_end_to_end(self) -> None:
        FakeTelegramConnector.sent = []
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            fake_bin = self._install_fake_claude(home)
            database = Database(home / "state.db")
            database.initialize()
            self._seed_telegram(home, database)

            previous_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}:{previous_path}"
            try:
                creation = run_cli(
                    home,
                    "create automation\n"
                    "Morning brief\n"
                    "Use web_lookup on https://example.com and summarize it\n"
                    "0 8 * * *\n"
                    "UTC\n"
                    "1\n"
                    "confirm\n"
                    "/exit\n",
                )
            finally:
                os.environ["PATH"] = previous_path
            self.assertEqual(creation.returncode, 0, creation.stderr)
            self.assertIn("confirm", creation.stdout.lower())

            jobs = AutomationJobRepository(database).list_all()
            self.assertEqual(len(jobs), 1)
            job = jobs[0]
            self.assertEqual(job["schedule_kind"], "cron")
            self.assertEqual(job["destination_connector_id"], "telegram")
            self.assertEqual(job["destination_conversation_id"], "chat-9")

            progress = CapabilityProgressRepository(database)
            self.assertEqual(progress.get("daily_briefing").status, "succeeded")

            with database.connect() as connection, connection:
                connection.execute(
                    "UPDATE automation_jobs SET next_run_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
                    (job["id"],),
                )

            buffer = StringIO()
            previous_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}:{previous_path}"
            try:
                with patch("allpath_agent.cli.main.TelegramConnector", FakeTelegramConnector):
                    with redirect_stdout(buffer):
                        exit_code = main(["--home", str(home), "automations", "tick"])
            finally:
                os.environ["PATH"] = previous_path

            self.assertEqual(exit_code, 0, buffer.getvalue())
            self.assertEqual(len(FakeTelegramConnector.sent), 1)
            conversation_id, delivered_text = FakeTelegramConnector.sent[0]
            self.assertEqual(conversation_id, "chat-9")
            self.assertTrue(delivered_text)

            runs = AutomationRunRepository(database).list_for_job(job["id"])
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "succeeded")
            self.assertEqual(runs[0]["output_message_id"], "fake-msg-1")
            self.assertEqual(runs[0]["output_text"], delivered_text)

            suggestions = CapabilitySuggestionRepository(database)
            self.assertIsNone(suggestions.get_for_session(job["session_id"]))

    def _install_fake_claude(self, home: Path) -> Path:
        # Mirror tests/test_cli.py's fake-claude pattern: a stub executable on
        # PATH plus a config.toml pointing the live provider at it. The stub
        # script body is copied verbatim from
        # test_conversation_connects_fake_claude_code_and_switches_live; the
        # config.toml is produced by the same production writer
        # (_write_config_atomic) that the real connect flow calls, using the
        # "claude-code" choice from provider_connection.CHOICES, so the shape
        # matches exactly what a live connect flow would have written. The
        # returned fake_bin directory is prepended onto PATH by the caller
        # around each call that needs the stub (run_cli's subprocess, and the
        # in-process `automations tick` invocation), restoring PATH in a
        # finally block afterwards, per run_cli copying os.environ at call
        # time.
        fake_bin = home / "fake-bin"
        fake_bin.mkdir()
        fake_claude = fake_bin / "claude"
        fake_claude.write_text(
            "#!/bin/sh\nprintf '%s\\n' "
            "' {\"type\":\"result\",\"subtype\":\"success\","
            "\"result\":\"OK\"}'\n",
            encoding="utf-8",
        )
        fake_claude.chmod(0o755)
        previous_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}:{previous_path}"
        try:
            choice = next(item for item in CHOICES if item.id == "claude-code")
            provider = _provider_config(choice)
            profile = _model_profile(choice, choice.default_model, "fast")
            _write_config_atomic(home / "config.toml", provider, profile)
        finally:
            os.environ["PATH"] = previous_path
        return fake_bin

    def _seed_telegram(self, home: Path, database: Database) -> None:
        ConnectorConfigRepository(database).save("telegram", "active", "@fake_bot")
        SecretStore(home / "secrets.json").set("TELEGRAM_BOT_TOKEN", "123:fake")
        session = SessionRepository(database).create(title="telegram:chat-9")
        ConnectorSessionRepository(database).bind("telegram", "chat-9", session.id)


if __name__ == "__main__":
    unittest.main()

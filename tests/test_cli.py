from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from allpath_agent.cli.main import _chat
from allpath_agent.storage import (
    CapabilityProgressRepository,
    Database,
    MemoryRepository,
    MessageRepository,
)


ROOT = Path(__file__).resolve().parents[1]


def run_cli(home: Path, input_text: str = "", *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "allpath_agent.cli.main",
            "--home",
            str(home),
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


class CliEndToEndTestCase(unittest.TestCase):
    def test_demo_chat_creates_and_resumes_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first = run_cli(home, "hello\n/exit\n", "--demo")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("Agent [fast]> Demo response: hello", first.stdout)
            session_match = re.search(r"Session: ([0-9a-f-]+)", first.stdout)
            self.assertIsNotNone(session_match)
            session_id = session_match.group(1)

            second = run_cli(
                home,
                "continue\n/exit\n",
                "--demo",
                "--session",
                session_id,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            messages = MessageRepository(Database(home / "state.db")).list_for_session(session_id)
            self.assertEqual([message.role for message in messages], ["user", "assistant", "user", "assistant"])
            self.assertEqual(first.stdout.count("Tip ["), 1)
            self.assertEqual(second.stdout.count("Tip ["), 0)

    def test_demo_time_tool_runs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = run_cli(home, "what time is it?\n/exit\n", "--demo")
            progress = CapabilityProgressRepository(Database(home / "state.db"))
            current_time_status = progress.get("current_time").status
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Demo tool result", result.stdout)
        self.assertIn("UTC", result.stdout)
        self.assertEqual(current_time_status, "succeeded")

    def test_complex_demo_task_routes_to_advanced_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(Path(directory), "请深入分析这个问题\n/exit\n", "--demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Agent [advanced]>", result.stdout)

    def test_terminal_approval_allows_memory_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = run_cli(
                home,
                "remember concise answers\ny\n/exit\n",
                "--demo",
            )
            memory = MemoryRepository(Database(home / "state.db")).get("demo_note")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Approval required: memory_set", result.stdout)
        self.assertIsNotNone(memory)
        self.assertEqual(memory.content, "concise answers")

    def test_capability_suggestion_can_be_dismissed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = run_cli(home, "hello\n/dismiss\n/exit\n", "--demo")
            progress = CapabilityProgressRepository(Database(home / "state.db")).list_all()
            dismissed = [record for record in progress.values() if record.status == "dismissed"]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Capability suggestion dismissed.", result.stdout)
        self.assertEqual(len(dismissed), 1)

    def test_capabilities_command_lists_curriculum_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(Path(directory), "/capabilities\n/exit\n", "--demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("basic_chat", result.stdout)
        self.assertIn("live_provider", result.stdout)

    def test_init_and_missing_live_config_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            missing = run_cli(home)
            initialized = run_cli(home, "", "init")
            repeated = run_cli(home, "", "init")

        self.assertEqual(missing.returncode, 2)
        self.assertIn("allpath-agent init", missing.stderr)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(repeated.returncode, 2)
        self.assertIn("already exists", repeated.stderr)

    def test_sessions_command_lists_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            chat = run_cli(home, "hello\n/exit\n", "--demo")
            session_id = re.search(r"Session: ([0-9a-f-]+)", chat.stdout).group(1)
            listed = run_cli(home, "", "sessions")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(session_id, listed.stdout)
        self.assertIn("hello", listed.stdout)


class CliInterruptTestCase(unittest.TestCase):
    def test_keyboard_interrupt_at_prompt_saves_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()
            outputs: list[str] = []

            def interrupting_input(prompt: str) -> str:
                raise KeyboardInterrupt

            result = _chat(
                home,
                database,
                True,
                None,
                interrupting_input,
                outputs.append,
                outputs.append,
            )

        self.assertEqual(result, 130)
        self.assertIn("Interrupted. Session state is saved.", outputs)


if __name__ == "__main__":
    unittest.main()

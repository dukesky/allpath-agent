from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from allpath_agent.cli.main import _chat, _run_connection_selectors
from allpath_agent.config import load_config
from allpath_agent.storage import (
    CapabilityProgressRepository,
    Database,
    MemoryRepository,
    MessageRepository,
    SessionRepository,
    WorkflowRunRepository,
)
from allpath_agent.secrets import SecretStore
from allpath_agent.workflows import ProviderConnectionWorkflow


ROOT = Path(__file__).resolve().parents[1]


def run_cli(home: Path, input_text: str = "", *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("ANTHROPIC_API_KEY", None)
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
            self.assertIn("Agent [fast]> Hello! I'm running locally.", first.stdout)
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

    def test_demo_writes_structured_logs_without_conversation_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            secret_message = "private-message-that-must-not-be-logged"
            result = run_cli(home, f"{secret_message}\n/exit\n", "--demo")
            log_text = (home / "logs" / "agent.jsonl").read_text(encoding="utf-8")
            records = [json.loads(line) for line in log_text.splitlines()]

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(secret_message, log_text)
        self.assertEqual(records[0]["event"], "task_started")
        self.assertEqual(records[-1]["event"], "task_completed")

    def test_demo_time_tool_runs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = run_cli(home, "what time is it?\n/exit\n", "--demo")
            progress = CapabilityProgressRepository(Database(home / "state.db"))
            current_time_status = progress.get("current_time").status
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The current time in UTC", result.stdout)
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
        self.assertRegex(result.stdout, r"live_provider\s+unavailable")

    def test_starter_conversation_introduces_provider_setup_on_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(
                Path(directory),
                "hello\nhow do I connect a model?\ncancel\n/exit\n",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Let's connect a model in this conversation", result.stdout)
        self.assertIn("Model connection cancelled", result.stdout)

    def test_conversation_connects_fake_claude_code_and_switches_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
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
                result = run_cli(
                    home,
                    "connect a model\n6\n\n/exit\n",
                )
            finally:
                os.environ["PATH"] = previous_path

            config = load_config(home / "config.toml")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Claude Code account is connected and verified", result.stdout)
        self.assertEqual(config.models[0].provider, "claude-code")
        self.assertEqual(config.models[0].model, "sonnet")
        self.assertFalse(config.models[0].supports_tools)

    def test_starter_understands_natural_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(
                Path(directory),
                "what is 4+3\n4×(2+1)等于多少\n/exit\n",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The result is 7.", result.stdout)
        self.assertIn("结果是 12。", result.stdout)

    def test_starter_explains_reasoning_limit_instead_of_echoing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(Path(directory), "??\n/exit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("without a reasoning model", result.stdout)
        self.assertNotIn("Demo response", result.stdout)

    def test_starter_matches_chinese_and_answers_capability_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(
                Path(directory),
                "你好\n你能做什么\n/exit\n",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("你好！我正在本地运行", result.stdout)
        self.assertIn("目前在本地模式下，我可以帮你安全计算", result.stdout)
        self.assertNotIn("Tip [model_routing]", result.stdout)
        self.assertNotIn("Tip [live_provider]", result.stdout)

    def test_first_launch_enters_local_starter_mode_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first_launch = run_cli(home, "hello\n/exit\n")
            initialized = run_cli(home, "", "init")
            repeated = run_cli(home, "", "init")

        self.assertEqual(first_launch.returncode, 0, first_launch.stderr)
        self.assertIn("local starter mode", first_launch.stdout)
        self.assertIn("Hello! I'm running locally.", first_launch.stdout)
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

    def test_providers_command_shows_protocol_and_auth_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            initialized = run_cli(home, "", "init")
            providers = run_cli(home, "", "providers")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(providers.returncode, 0, providers.stderr)
        self.assertIn("openai", providers.stdout)
        self.assertIn("anthropic_messages", providers.stdout)
        self.assertIn("missing", providers.stdout)


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

    def test_invalid_terminal_character_does_not_crash_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()
            outputs: list[str] = []
            calls = iter((UnicodeDecodeError("utf-8", b"\xbd", 0, 1, "invalid"), "/exit"))

            def recovering_input(prompt: str) -> str:
                value = next(calls)
                if isinstance(value, Exception):
                    raise value
                return value

            result = _chat(
                home,
                database,
                True,
                None,
                recovering_input,
                outputs.append,
                outputs.append,
            )

        self.assertEqual(result, 0)
        self.assertTrue(any("Please type it again" in message for message in outputs))

    def test_failed_codex_verification_does_not_repeat_selector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()
            session = SessionRepository(database).create()
            workflow = ProviderConnectionWorkflow(
                home / "config.toml",
                WorkflowRunRepository(database),
                SecretStore(home / "secrets.json"),
                verifier=lambda provider, profile, secret: (_ for _ in ()).throw(
                    RuntimeError("provider rejected request")
                ),
            )
            initial = workflow.handle(session.id, "connect model")
            selections = iter((1, 0))
            selection_count = 0

            def selector(title, items, searchable):
                nonlocal selection_count
                selection_count += 1
                return next(selections)

            with patch(
                "allpath_agent.cli.main.ensure_codex_login",
                return_value=(True, "signed in", "codex"),
            ):
                result = _run_connection_selectors(
                    workflow,
                    session.id,
                    initial,
                    selector,
                    lambda message: None,
                )

        self.assertEqual(selection_count, 2)
        self.assertIn("verification failed", result.messages[0].lower())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from allpath_agent.automations import AutomationService
from allpath_agent.cli.main import (
    _build_application,
    _chat,
    _completed_daily_briefing,
    _directive_trigger_message,
    _run_connection_selectors,
    _run_gateway,
)
from allpath_agent.config import ConfigError, load_config
from allpath_agent.hooks import HookBus
from allpath_agent.models import ProviderError
from allpath_agent.storage import (
    AutomationJobRepository,
    AutomationRunRepository,
    CapabilityProgressRepository,
    Database,
    MemoryRepository,
    MessageRepository,
    SessionRepository,
    WorkflowRunRepository,
    ConnectorConfigRepository,
)
from allpath_agent.secrets import SecretStore
from allpath_agent.workflows import AutomationCreationWorkflow, ProviderConnectionWorkflow


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
            self.assertIn("ALLPATH · FAST", first.stdout)
            self.assertIn("│  Hello! I'm running locally.", first.stdout)
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
            self.assertEqual(first.stdout.count("NEXT ·"), 1)
            self.assertEqual(second.stdout.count("NEXT ·"), 0)

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
        self.assertIn("ALLPATH · ADVANCED", result.stdout)

    def test_route_command_explains_latest_model_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(
                Path(directory),
                "请深入分析这个问题\n/route\n/exit\n",
                "--demo",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Routed to: advanced", result.stdout)
        self.assertIn("Reason: advanced task complexity score", result.stdout)
        self.assertIn("Provider: default", result.stdout)
        self.assertIn("Model: demo-advanced", result.stdout)

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
        self.assertIn("APPROVAL · memory_set", result.stdout)
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

    def test_automations_command_records_curriculum_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_cli(home, "/automations\n/exit\n", "--demo")
            database = Database(home / "state.db")
            progress = CapabilityProgressRepository(database).get("scheduled_automations")

        self.assertIsNotNone(progress)
        self.assertEqual(progress.status, "tried")

    def test_mcp_command_degrades_cleanly_and_records_curriculum_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = run_cli(home, "/mcp\n/exit\n", "--demo")
            database = Database(home / "state.db")
            progress = CapabilityProgressRepository(database).get("mcp_tools")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MCP Python SDK:", result.stdout)
        self.assertIn("No MCP servers configured.", result.stdout)
        self.assertIsNotNone(progress)
        self.assertEqual(progress.status, "tried")

    def test_browser_command_reports_runtime_and_records_curriculum_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = run_cli(home, "/browser\n/exit\n", "--demo")
            database = Database(home / "state.db")
            progress = CapabilityProgressRepository(database).get("browser_tasks")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Structured browser runtime:", result.stdout)
        self.assertIn("Playwright package:", result.stdout)
        self.assertIn("System Chrome:", result.stdout)
        self.assertIn("Next:", result.stdout)
        self.assertIn("Isolated profile:", result.stdout)
        self.assertIsNotNone(progress)
        self.assertEqual(progress.status, "tried")

    def test_natural_browser_setup_request_returns_diagnostics_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(Path(directory), "setup browser\n/exit\n", "--demo")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ALLPATH · SETUP", result.stdout)
        self.assertIn("Structured browser is", result.stdout)
        self.assertIn("Isolated profile:", result.stdout)

    def test_browser_reset_requires_confirmation_and_deletes_isolated_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            profile = home / "browser-profile"
            profile.mkdir()
            (profile / "Cookies").write_text("isolated", encoding="utf-8")
            result = run_cli(home, "/browser reset\ny\n/exit\n", "--demo")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("APPROVAL · browser_reset", result.stdout)
        self.assertIn("Browser profile reset.", result.stdout)
        self.assertFalse(profile.exists())

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
                    "connect a model\n8\n\n1\n/model\n/exit\n",
                )
            finally:
                os.environ["PATH"] = previous_path

            config = load_config(home / "config.toml")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Claude Code account is connected and verified", result.stdout)
        self.assertEqual(config.models[0].provider, "claude-code")
        self.assertEqual(config.models[0].name, "fast")
        self.assertEqual(config.models[0].model, "sonnet")
        self.assertFalse(config.models[0].supports_tools)
        self.assertIn("No model has been used in this session yet", result.stdout)
        self.assertIn("fast       sonnet", result.stdout)
        self.assertIn("provider=claude-code", result.stdout)
        success_tail = result.stdout.split("Switching to live model sonnet now.", 1)[1]
        self.assertNotIn("Try: 连接模型", success_tail)
        self.assertIn("Connect a messaging channel", success_tail)

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
        self.assertNotIn("NEXT · model_routing", result.stdout)
        self.assertNotIn("NEXT · live_provider", result.stdout)

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
            selections = iter((1, 0, 0))
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

        self.assertEqual(selection_count, 3)
        self.assertIn("verification failed", result.messages[0].lower())

    def test_gateway_once_uses_active_telegram_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()
            ConnectorConfigRepository(database).save("telegram", "active", "@test_bot")
            SecretStore(home / "secrets.json").set("TELEGRAM_BOT_TOKEN", "test-token")
            outputs = []

            class FakeTelegram:
                id = "telegram"

                def status(self):
                    from allpath_agent.connectors import ConnectorStatus

                    return ConnectorStatus("telegram", True, "@test_bot")

                def poll(self):
                    return ()

                def start(self):
                    return None

                def stop(self):
                    return None

                def send(self, message):
                    raise AssertionError("no message should be sent")

            with patch("allpath_agent.cli.main.TelegramConnector", return_value=FakeTelegram()), patch(
                "allpath_agent.cli.main._build_application",
                return_value=SimpleNamespace(hooks=HookBus()),
            ):
                result = _run_gateway(home, database, True, 0, outputs.append, outputs.append)

        self.assertEqual(result, 0)
        self.assertTrue(any("@test_bot" in message for message in outputs))

    def test_gateway_once_requires_connectors_or_automations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()
            outputs = []

            with self.assertRaises(ConfigError) as context:
                _run_gateway(home, database, True, 0, outputs.append, outputs.append)

        self.assertIn(
            "No active connectors or enabled automations",
            str(context.exception),
        )


class CompletedDailyBriefingTestCase(unittest.TestCase):
    def test_empty_job_list_is_not_completed(self) -> None:
        self.assertFalse(_completed_daily_briefing([]))

    def test_single_job_without_destination_is_not_completed(self) -> None:
        jobs = [
            {"created_at": "2026-07-20T00:00:00+00:00", "schedule_kind": "once", "destination_connector_id": None}
        ]
        self.assertFalse(_completed_daily_briefing(jobs))

    def test_cron_job_without_destination_is_not_completed(self) -> None:
        jobs = [
            {"created_at": "2026-07-20T00:00:00+00:00", "schedule_kind": "cron", "destination_connector_id": None}
        ]
        self.assertFalse(_completed_daily_briefing(jobs))

    def test_newest_cron_job_with_destination_is_completed(self) -> None:
        jobs = [
            {"created_at": "2026-07-19T00:00:00+00:00", "schedule_kind": "once", "destination_connector_id": None},
            {"created_at": "2026-07-20T00:00:00+00:00", "schedule_kind": "cron", "destination_connector_id": "telegram"},
        ]
        self.assertTrue(_completed_daily_briefing(jobs))


class DirectiveTriggerMessageTestCase(unittest.TestCase):
    def test_channel_setup_maps_to_connect_phrase(self) -> None:
        from allpath_agent.tools.assistant_directives import AssistantDirective

        self.assertEqual(
            _directive_trigger_message(AssistantDirective("channel_setup", channel="telegram")),
            "connect telegram",
        )
        self.assertEqual(
            _directive_trigger_message(
                AssistantDirective("channel_setup", channel="slack", reconnect=True)
            ),
            "reconnect slack",
        )
        self.assertEqual(
            _directive_trigger_message(AssistantDirective("model_setup")),
            "connect model",
        )
        self.assertIsNone(
            _directive_trigger_message(AssistantDirective("automation_setup")),
        )


class DirectiveDrainReentersLoopTestCase(unittest.TestCase):
    def test_channel_setup_directive_reenters_loop_with_synthetic_trigger(self) -> None:
        from allpath_agent.tools.assistant_directives import AssistantDirective

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()
            outputs: list[str] = []

            class FakeApplication:
                def __init__(self, sink) -> None:
                    self.hooks = HookBus()
                    self._sink = sink
                    self.sent_messages: list[str] = []

                def start_session(self, session_id: str) -> None:
                    return None

                def capability_progress(self):
                    return ()

                def record_capability_success(self, capability_id: str) -> None:
                    return None

                def record_capability_tried(self, capability_id: str) -> None:
                    return None

                def dismiss_suggestion(self, session_id: str, capability_id: str | None = None) -> bool:
                    return False

                def send(self, session_id: str, message: str):
                    self.sent_messages.append(message)
                    # Simulate the model calling the channel_connect tool, which
                    # leaves a directive for the CLI to drain after this turn.
                    self._sink.set(AssistantDirective("channel_setup", channel="telegram"))
                    return SimpleNamespace(
                        agent=SimpleNamespace(
                            content="Let's get Telegram connected.",
                            model_profile="fast",
                            usage_reported=False,
                            model_calls=1,
                            total_tokens=0,
                            estimated_cost_usd=0.0,
                        ),
                        suggestion=None,
                    )

            captured: dict[str, object] = {}

            def fake_build_application(*args, **kwargs):
                sink = kwargs["directive_sink"]
                application = FakeApplication(sink)
                captured["application"] = application
                return application

            calls = iter(("hello", "/exit"))

            def scripted_input(prompt: str) -> str:
                return next(calls)

            with patch("allpath_agent.cli.main._build_application", side_effect=fake_build_application):
                result = _chat(
                    home,
                    database,
                    True,
                    None,
                    scripted_input,
                    outputs.append,
                    outputs.append,
                )

        self.assertEqual(result, 0)
        application = captured["application"]
        # The model turn ran once for "hello"; the drained directive produced a
        # synthetic "connect telegram" message that re-entered the loop and hit
        # the existing trigger-detection gate (no live model configured yet),
        # without consuming another real input from the user.
        self.assertEqual(application.sent_messages, ["hello"])
        self.assertTrue(
            any(
                "Connect a reasoning model first, then connect a messaging channel." in line
                for line in outputs
            )
        )


class StaleDirectiveDiscardedOnFailedTurnTestCase(unittest.TestCase):
    def test_directive_set_before_a_failed_send_does_not_fire_on_the_next_turn(self) -> None:
        from allpath_agent.tools.assistant_directives import AssistantDirective

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()
            outputs: list[str] = []

            class FakeApplication:
                def __init__(self, sink) -> None:
                    self.hooks = HookBus()
                    self._sink = sink
                    self.sent_messages: list[str] = []
                    self._calls = 0

                def start_session(self, session_id: str) -> None:
                    return None

                def capability_progress(self):
                    return ()

                def record_capability_success(self, capability_id: str) -> None:
                    return None

                def record_capability_tried(self, capability_id: str) -> None:
                    return None

                def dismiss_suggestion(self, session_id: str, capability_id: str | None = None) -> bool:
                    return False

                def send(self, session_id: str, message: str):
                    self.sent_messages.append(message)
                    self._calls += 1
                    if self._calls == 1:
                        # Simulate a directive tool running, then the turn
                        # itself failing (e.g. the provider errored out
                        # after the tool call).
                        self._sink.set(AssistantDirective("channel_setup", channel="telegram"))
                        raise ProviderError("simulated provider failure")
                    return SimpleNamespace(
                        agent=SimpleNamespace(
                            content="ok",
                            model_profile="fast",
                            usage_reported=False,
                            model_calls=1,
                            total_tokens=0,
                            estimated_cost_usd=0.0,
                        ),
                        suggestion=None,
                    )

            captured: dict[str, object] = {}

            def fake_build_application(*args, **kwargs):
                sink = kwargs["directive_sink"]
                application = FakeApplication(sink)
                captured["application"] = application
                return application

            calls = iter(("hello", "hi again", "/exit"))

            def scripted_input(prompt: str) -> str:
                return next(calls)

            with patch("allpath_agent.cli.main._build_application", side_effect=fake_build_application):
                result = _chat(
                    home,
                    database,
                    True,
                    None,
                    scripted_input,
                    outputs.append,
                    outputs.append,
                )

        self.assertEqual(result, 0)
        application = captured["application"]
        # Both turns were sent to the application: the first failed after
        # setting a directive, the second succeeded without setting one.
        self.assertEqual(application.sent_messages, ["hello", "hi again"])
        # The stale directive from the failed turn must not have fired on
        # the following successful turn.
        self.assertFalse(
            any(
                "Connect a reasoning model first, then connect a messaging channel." in line
                for line in outputs
            )
        )


class AutomationSetupDirectiveDrainTestCase(unittest.TestCase):
    def test_automation_setup_directive_starts_workflow_at_destination_step(self) -> None:
        from allpath_agent.tools.assistant_directives import AssistantDirective

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()
            outputs: list[str] = []
            session = SessionRepository(database).create()

            class FakeApplication:
                def __init__(self, sink) -> None:
                    self.hooks = HookBus()
                    self._sink = sink
                    self.sent_messages: list[str] = []

                def start_session(self, session_id: str) -> None:
                    return None

                def capability_progress(self):
                    return ()

                def record_capability_success(self, capability_id: str) -> None:
                    return None

                def record_capability_tried(self, capability_id: str) -> None:
                    return None

                def dismiss_suggestion(self, session_id: str, capability_id: str | None = None) -> bool:
                    return False

                def send(self, session_id: str, message: str):
                    self.sent_messages.append(message)
                    self._sink.set(
                        AssistantDirective(
                            "automation_setup",
                            prefill={
                                "name": "Brief",
                                "prompt": "Summarize",
                                "schedule": "0 8 * * *",
                                "timezone": "UTC",
                            },
                        )
                    )
                    return SimpleNamespace(
                        agent=SimpleNamespace(
                            content="Let's set that up.",
                            model_profile="fast",
                            usage_reported=False,
                            model_calls=1,
                            total_tokens=0,
                            estimated_cost_usd=0.0,
                        ),
                        suggestion=None,
                    )

            def fake_build_application(*args, **kwargs):
                sink = kwargs["directive_sink"]
                return FakeApplication(sink)

            calls = iter(("create an automation", "/exit"))

            def scripted_input(prompt: str) -> str:
                return next(calls)

            with patch("allpath_agent.cli.main._build_application", side_effect=fake_build_application):
                result = _chat(
                    home,
                    database,
                    True,
                    session.id,
                    scripted_input,
                    outputs.append,
                    outputs.append,
                )

            automation_workflow = AutomationCreationWorkflow(
                WorkflowRunRepository(database),
                AutomationService(
                    AutomationJobRepository(database),
                    AutomationRunRepository(database),
                    SessionRepository(database),
                ),
                lambda: (),
            )
            workflow_active = automation_workflow.active(session.id)

        self.assertEqual(result, 0)
        # All four prefill fields were valid, so the workflow should have
        # skipped straight to the destination step.
        self.assertTrue(workflow_active)
        self.assertTrue(any("Where should results go?" in line for line in outputs))


class GatewayStaysDirectiveFreeTestCase(unittest.TestCase):
    def test_application_without_directive_sink_has_no_channel_connect_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()

            application = _build_application(
                home,
                database,
                True,
                lambda prompt: "",
                lambda message: None,
                interactive_approvals=False,
            )

            registry = application._loop._tool_executor._registry
            tool_names = {schema["function"]["name"] for schema in registry.schemas()}

        self.assertNotIn("channel_connect", tool_names)
        self.assertNotIn("create_automation", tool_names)
        self.assertNotIn("connect_model", tool_names)

    def test_gateway_surface_threads_into_application(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()

            gateway_application = _build_application(
                home,
                database,
                True,
                lambda prompt: "",
                lambda message: None,
                interactive_approvals=False,
                surface="gateway",
            )
            terminal_application = _build_application(
                home,
                database,
                True,
                lambda prompt: "",
                lambda message: None,
                interactive_approvals=False,
            )

        self.assertEqual(gateway_application._surface, "gateway")
        self.assertEqual(terminal_application._surface, "terminal")


class ChatApplicationRegistersDirectiveToolsTestCase(unittest.TestCase):
    def test_application_with_directive_sink_has_channel_connect_and_automation_tools(self) -> None:
        from allpath_agent.tools.assistant_directives import DirectiveSink

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = Database(home / "state.db")
            database.initialize()

            application = _build_application(
                home,
                database,
                True,
                lambda prompt: "",
                lambda message: None,
                interactive_approvals=False,
                directive_sink=DirectiveSink(),
            )

            registry = application._loop._tool_executor._registry
            tool_names = {schema["function"]["name"] for schema in registry.schemas()}

        self.assertIn("channel_connect", tool_names)
        self.assertIn("create_automation", tool_names)


if __name__ == "__main__":
    unittest.main()

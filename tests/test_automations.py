from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from allpath_agent.automations import AutomationService, parse_cron, parse_once
from allpath_agent.cli.main import build_parser, main
from allpath_agent.storage import (
    AutomationJobRepository,
    AutomationRunRepository,
    Database,
    SessionRepository,
)


class FakeApplication:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.started = []
        self.messages = []

    def start_session(self, session_id: str) -> None:
        self.started.append(session_id)

    def send(self, session_id: str, message: str):
        self.messages.append((session_id, message))
        if self.error:
            raise self.error
        return SimpleNamespace(task_id="task-1", agent=SimpleNamespace(content=f"done: {message}"))


class ScheduleParserTestCase(unittest.TestCase):
    def test_once_uses_named_timezone_for_naive_input(self) -> None:
        moment = parse_once("2026-07-20T08:00:00", "America/Los_Angeles")
        self.assertEqual(moment, datetime(2026, 7, 20, 15, 0, tzinfo=UTC))

    def test_weekday_cron_calculates_next_utc_occurrence(self) -> None:
        schedule = parse_cron("0 8 * * 1-5", "America/Los_Angeles")
        next_run = schedule.next_after(datetime(2026, 7, 20, 14, 0, tzinfo=UTC))
        self.assertEqual(next_run, datetime(2026, 7, 20, 15, 0, tzinfo=UTC))

    def test_invalid_cron_and_timezone_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "five fields"):
            parse_cron("0 8 * *", "UTC")
        with self.assertRaisesRegex(ValueError, "unknown IANA"):
            parse_cron("0 8 * * *", "Mars/Olympus")


class AutomationLifecycleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.sessions = SessionRepository(self.database)
        self.jobs = AutomationJobRepository(self.database)
        self.runs = AutomationRunRepository(self.database)
        self.now = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_create_once_persists_dedicated_session_and_future_run(self) -> None:
        service = AutomationService(
            self.jobs, self.runs, self.sessions, now=lambda: self.now
        )

        job = service.create_once(
            "Proposal reminder",
            "Remind me to send the proposal",
            "2026-07-20T09:00:00",
            "America/Los_Angeles",
        )

        self.assertEqual(job["next_run_at"], "2026-07-20T16:00:00+00:00")
        self.assertEqual(self.sessions.get(job["session_id"]).title, "automation:Proposal reminder")

    def test_due_once_job_executes_once_and_disables_after_success(self) -> None:
        session = self.sessions.create("automation:test")
        job = self.jobs.create(
            name="Due task",
            prompt="Prepare update",
            schedule_kind="once",
            schedule_expression="2026-07-20T14:00:00+00:00",
            timezone="UTC",
            session_id=session.id,
            next_run_at="2026-07-20T14:00:00+00:00",
        )
        application = FakeApplication()
        service = AutomationService(
            self.jobs, self.runs, self.sessions, application, now=lambda: self.now
        )

        run = service.tick()
        second = service.tick()

        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["output_text"], "done: Prepare update")
        self.assertIsNone(second)
        self.assertFalse(self.jobs.get(job["id"])["enabled"])
        self.assertEqual(application.started, [session.id])

    def test_recurring_job_coalesces_missed_runs_and_schedules_future(self) -> None:
        session = self.sessions.create("automation:daily")
        job = self.jobs.create(
            name="Daily",
            prompt="Daily plan",
            schedule_kind="cron",
            schedule_expression="0 8 * * *",
            timezone="America/Los_Angeles",
            session_id=session.id,
            next_run_at="2026-07-18T15:00:00+00:00",
        )
        service = AutomationService(
            self.jobs, self.runs, self.sessions, FakeApplication(), now=lambda: self.now
        )

        run = service.tick()
        updated = self.jobs.get(job["id"])

        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(updated["next_run_at"], "2026-07-21T15:00:00+00:00")
        self.assertEqual(len(self.runs.list_for_job(job["id"])), 1)

    def test_failure_is_terminal_and_preserves_bounded_error(self) -> None:
        session = self.sessions.create("automation:failure")
        job = self.jobs.create(
            name="Failure",
            prompt="Fail safely",
            schedule_kind="once",
            schedule_expression="2026-07-20T14:00:00+00:00",
            timezone="UTC",
            session_id=session.id,
            next_run_at="2026-07-20T14:00:00+00:00",
        )
        service = AutomationService(
            self.jobs,
            self.runs,
            self.sessions,
            FakeApplication(ValueError("provider unavailable")),
            now=lambda: self.now,
        )

        run = service.tick()

        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error_type"], "ValueError")
        self.assertEqual(run["error_message"], "provider unavailable")
        failed_job = self.jobs.get(job["id"])
        self.assertIsNone(failed_job["next_run_at"])
        self.assertFalse(failed_job["enabled"])

    def test_claim_due_is_atomic_for_one_schedule_occurrence(self) -> None:
        session = self.sessions.create("automation:claim")
        self.jobs.create(
            name="Claim",
            prompt="Claim once",
            schedule_kind="once",
            schedule_expression="2026-07-20T14:00:00+00:00",
            timezone="UTC",
            session_id=session.id,
            next_run_at="2026-07-20T14:00:00+00:00",
        )

        first = self.runs.claim_due(self.now.isoformat())
        second = self.runs.claim_due(self.now.isoformat())

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_missing_application_does_not_claim_due_job(self) -> None:
        session = self.sessions.create("automation:no-app")
        job = self.jobs.create(
            name="No app",
            prompt="Wait",
            schedule_kind="once",
            schedule_expression="2026-07-20T14:00:00+00:00",
            timezone="UTC",
            session_id=session.id,
            next_run_at="2026-07-20T14:00:00+00:00",
        )
        service = AutomationService(
            self.jobs, self.runs, self.sessions, now=lambda: self.now
        )

        with self.assertRaisesRegex(RuntimeError, "AgentApplication"):
            service.tick()

        self.assertEqual(self.runs.list_for_job(job["id"]), [])


class AutomationCliParserTestCase(unittest.TestCase):
    def test_parses_creation_and_execution_commands(self) -> None:
        once = build_parser().parse_args(
            ["automations", "add-once", "--name", "Reminder", "--prompt", "Do it", "--at", "2026-08-01T09:00"]
        )
        run = build_parser().parse_args(["automations", "run", "job-1"])

        self.assertEqual(once.action, "add-once")
        self.assertEqual(once.timezone, "UTC")
        self.assertEqual(run.job_id, "job-1")

    def test_cli_creates_and_lists_one_time_job_without_model_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = StringIO()
            with redirect_stdout(output):
                created = main(
                    [
                        "--home",
                        temporary_directory,
                        "automations",
                        "add-once",
                        "--name",
                        "Reminder",
                        "--prompt",
                        "Send proposal",
                        "--at",
                        "2099-08-01T09:00:00",
                        "--timezone",
                        "UTC",
                    ]
                )
                listed = main(["--home", temporary_directory, "automations", "list"])

        self.assertEqual((created, listed), (0, 0))
        self.assertIn("Created one-time automation", output.getvalue())
        self.assertIn("Reminder", output.getvalue())


if __name__ == "__main__":
    unittest.main()

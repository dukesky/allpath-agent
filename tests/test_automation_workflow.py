from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from allpath_agent.automations import AutomationService
from allpath_agent.storage import (
    AutomationJobRepository,
    AutomationRunRepository,
    Database,
    SessionRepository,
    WorkflowRunRepository,
)
from allpath_agent.workflows.automation_creation import AutomationCreationWorkflow


class AutomationCreationWorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.sessions = SessionRepository(self.database)
        self.sessions.create(session_id="session-1")
        self.jobs = AutomationJobRepository(self.database)
        self.runs = AutomationRunRepository(self.database)
        self.now = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)
        self.service = AutomationService(
            self.jobs, self.runs, self.sessions, now=lambda: self.now
        )
        self.bindings: list[dict] = []
        self.workflow = AutomationCreationWorkflow(
            WorkflowRunRepository(self.database),
            self.service,
            lambda: self.bindings,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _drive(self, *messages: str):
        return [self.workflow.handle("session-1", message) for message in messages]

    def test_unrelated_message_is_not_handled(self) -> None:
        result = self.workflow.handle("session-1", "what is an automation?")
        self.assertFalse(result.handled)

    def test_full_cron_flow_without_destination_creates_job(self) -> None:
        results = self._drive(
            "create automation",
            "Morning brief",
            "Prepare my morning brief",
            "0 8 * * 1-5",
            "Asia/Shanghai",
            "none",
            "confirm",
        )

        self.assertTrue(all(result.handled for result in results))
        self.assertTrue(results[-1].completed)
        jobs = self.jobs.list_all()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["name"], "Morning brief")
        self.assertEqual(jobs[0]["schedule_kind"], "cron")
        self.assertEqual(jobs[0]["schedule_expression"], "0 8 * * 1-5")
        self.assertEqual(jobs[0]["timezone"], "Asia/Shanghai")
        self.assertIsNone(jobs[0]["destination_connector_id"])
        self.assertFalse(self.workflow.active("session-1"))

    def test_confirmation_echo_precedes_save(self) -> None:
        results = self._drive(
            "create automation",
            "Morning brief",
            "Prepare my morning brief",
            "0 8 * * 1-5",
            "UTC",
            "none",
        )

        summary = "\n".join(results[-1].messages)
        self.assertIn("Morning brief", summary)
        self.assertIn("0 8 * * 1-5", summary)
        self.assertIn("UTC", summary)
        self.assertEqual(self.jobs.list_all(), [])

    def test_destination_is_selected_from_bindings(self) -> None:
        self.bindings.append(
            {"connector_id": "telegram", "conversation_id": "chat-9", "session_id": "s-x"}
        )

        self._drive(
            "create automation",
            "Daily plan",
            "Prepare my daily plan",
            "0 8 * * *",
            "UTC",
            "1",
            "confirm",
        )

        job = self.jobs.list_all()[0]
        self.assertEqual(job["destination_connector_id"], "telegram")
        self.assertEqual(job["destination_conversation_id"], "chat-9")

    def test_invalid_schedule_reprompts_without_advancing(self) -> None:
        results = self._drive(
            "create automation",
            "Morning brief",
            "Prepare my morning brief",
            "tomorrow at eight",
        )

        self.assertTrue(results[-1].handled)
        self.assertFalse(results[-1].completed)
        again = self.workflow.handle("session-1", "0 8 * * 1-5")
        self.assertTrue(again.handled)
        self.assertEqual(self.jobs.list_all(), [])

    def test_past_once_schedule_returns_to_schedule_step(self) -> None:
        results = self._drive(
            "create automation",
            "Old reminder",
            "Remind me",
            "2020-01-01T08:00:00",
            "UTC",
            "none",
            "confirm",
        )

        self.assertFalse(results[-1].completed)
        self.assertEqual(self.jobs.list_all(), [])
        recovered = self._drive("2026-12-01T08:00:00", "UTC", "none", "confirm")
        self.assertTrue(recovered[-1].completed)
        self.assertEqual(self.jobs.list_all()[0]["schedule_kind"], "once")

    def test_cancel_stops_the_flow(self) -> None:
        self._drive("create automation", "Morning brief")
        result = self.workflow.handle("session-1", "cancel")

        self.assertTrue(result.handled)
        self.assertFalse(self.workflow.active("session-1"))
        self.assertEqual(self.jobs.list_all(), [])

    def test_flow_resumes_across_instances(self) -> None:
        self._drive("create automation", "Morning brief", "Prepare my morning brief")

        fresh = AutomationCreationWorkflow(
            WorkflowRunRepository(self.database), self.service, lambda: self.bindings
        )
        self.assertTrue(fresh.active("session-1"))
        result = fresh.handle("session-1", "0 8 * * 1-5")
        self.assertTrue(result.handled)

    def test_chinese_trigger_uses_chinese_prompts(self) -> None:
        result = self.workflow.handle("session-1", "创建定时任务")

        self.assertTrue(result.handled)
        self.assertTrue(any("名称" in message for message in result.messages))

    def test_repeated_trigger_while_active_is_consumed_as_answer(self) -> None:
        self._drive("create automation")

        result = self.workflow.handle("session-1", "status")

        self.assertTrue(result.handled)
        self.assertTrue(self.workflow.active("session-1"))
        self.assertEqual(self.jobs.list_all(), [])

    def test_start_with_full_prefill_begins_at_destination(self) -> None:
        result = self.workflow.start(
            "session-1",
            "en",
            {
                "name": "Morning brief",
                "prompt": "Summarize the news",
                "schedule": "0 8 * * *",
                "timezone": "UTC",
            },
        )

        self.assertTrue(result.handled)
        self.assertIn("none", "\n".join(result.messages).lower())
        finished = self._drive("none", "confirm")
        self.assertTrue(finished[-1].completed)
        job = self.jobs.list_all()[0]
        self.assertEqual(job["name"], "Morning brief")
        self.assertEqual(job["schedule_expression"], "0 8 * * *")

    def test_start_drops_invalid_prefill_and_asks_for_it(self) -> None:
        result = self.workflow.start(
            "session-1",
            "en",
            {"name": "Brief", "prompt": "Summarize", "schedule": "tomorrow-ish", "timezone": "UTC"},
        )

        self.assertTrue(result.handled)
        self.assertIn("cron", "\n".join(result.messages).lower())

    def test_start_without_prefill_matches_trigger_behavior(self) -> None:
        via_start = self.workflow.start("session-1", "en")
        self.workflow.handle("session-1", "cancel")
        via_trigger = self.workflow.handle("session-1", "create automation")

        self.assertEqual(via_start.messages, via_trigger.messages)

    def test_start_while_active_rerenders_instead_of_restarting(self) -> None:
        self.workflow.start("session-1", "en", {"name": "Brief"})

        again = self.workflow.start("session-1", "en", {"name": "Other"})

        self.assertTrue(again.handled)
        state_run = self.workflow.handle("session-1", "Summarize")
        self.assertTrue(state_run.handled)
        jobs_after = self.jobs.list_all()
        self.assertEqual(jobs_after, [])

    def test_default_destination_skips_destination_step(self) -> None:
        self.workflow.start(
            "session-1", "en", None, default_destination=("telegram", "chat-9")
        )

        results = self._drive("Morning brief", "Summarize the news", "0 8 * * *", "UTC")

        summary = "\n".join(results[-1].messages)
        self.assertIn("confirm", summary.lower())
        self.assertIn("this conversation", summary)
        finished = self.workflow.handle("session-1", "confirm")
        self.assertTrue(finished.completed)
        job = self.jobs.list_all()[0]
        self.assertEqual(job["destination_connector_id"], "telegram")
        self.assertEqual(job["destination_conversation_id"], "chat-9")

    def test_default_destination_with_full_prefill_starts_at_confirm(self) -> None:
        result = self.workflow.start(
            "session-1",
            "en",
            {"name": "Brief", "prompt": "Summarize", "schedule": "0 8 * * *", "timezone": "UTC"},
            default_destination=("slack", "D123"),
        )

        self.assertIn("this conversation", "\n".join(result.messages))
        finished = self.workflow.handle("session-1", "confirm")
        self.assertTrue(finished.completed)
        self.assertEqual(self.jobs.list_all()[0]["destination_conversation_id"], "D123")

    def test_without_default_destination_step_still_asked(self) -> None:
        self.workflow.start("session-1", "en")

        results = self._drive("Morning brief", "Summarize the news", "0 8 * * *", "UTC")

        self.assertIn("results go", "\n".join(results[-1].messages).lower())

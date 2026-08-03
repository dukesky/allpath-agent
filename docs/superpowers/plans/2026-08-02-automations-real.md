# Automations Become Real (Milestone 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduled automations creatable in conversation, executable unattended by the gateway, and deliverable to a messaging connector — closing the gap where the curriculum teaches a flow the user cannot complete.

**Architecture:** `AutomationService` gains destination pass-through, an injected delivery callable, and denied-approval detection (`needs_attention`). The gateway loop drains due jobs after each connector poll using the same `AgentApplication`. A new `AutomationCreationWorkflow` reuses the persisted `workflow_runs` resume mechanism (same pattern as the connector workflows) to collect name → prompt → schedule → timezone → destination, echo a summary, and save only after explicit confirmation. Destinations are offered from existing `connector_sessions` bindings so users never have to know raw conversation IDs.

**Tech Stack:** Python 3.11+ stdlib only. SQLite migration 9 adds one column (`automation_runs.needs_attention`); the destination and model-role columns already exist from migration 8.

## Global Constraints

- No third-party dependencies may be added (`pyproject.toml` deps stay unchanged).
- Every meaningful change updates `CHANGELOG.md` under `Unreleased`.
- Full validation is `python3 scripts/run_tests.py` (use `python3.12` on this machine — default `python3` is 3.9) and must pass at every commit.
- Curriculum state must never be injected into the model system prompt.
- Delivery happens ONLY when both `destination_connector_id` and `destination_conversation_id` are set on the job (DB CHECK already enforces both-or-neither).
- A delivery failure marks the run `failed` with `error_type="DeliveryError"` but RETAINS `output_text` (never silently discard generated work).
- Unattended runs keep default-deny side effects; a denied approval marks the run `needs_attention = 1` instead of failing it.
- Secrets never enter workflow state, conversation history, or SQLite message content.
- Tests are stdlib `unittest`, `from __future__ import annotations` at top, matching existing files.

---

### Task 1: AutomationService — destinations, delivery, needs-attention

**Files:**
- Modify: `src/allpath_agent/storage/database.py` (append migration 9)
- Modify: `src/allpath_agent/storage/repositories.py` (`AutomationRunRepository.finish`)
- Modify: `src/allpath_agent/automations.py`
- Modify: `src/allpath_agent/cli/main.py` (argparse `--connector`/`--conversation` + pass-through in `_manage_automations`)
- Modify: `tests/test_storage.py` (migration version list)
- Test: `tests/test_automations.py`

**Interfaces:**
- Produces: `AutomationService.__init__(..., approvals: ToolApprovalRepository | None = None, deliver: Callable[[str, str, str], str] | None = None)` — `deliver(connector_id, conversation_id, text) -> message_id`.
- Produces: `create_once(name, prompt, at, timezone, *, model_role="auto", destination_connector_id=None, destination_conversation_id=None)` and the same keyword tail on `create_cron`. Task 3 calls these.
- Produces: `AutomationRunRepository.finish(..., output_message_id: str | None = None, needs_attention: bool = False)`.
- Run records now carry `needs_attention` (SQLite int 0/1). Task 2 reads it for display.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_automations.py` (imports: add `ToolApprovalRepository` to the existing `allpath_agent.storage` import):

```python
class AutomationDeliveryTestCase(unittest.TestCase):
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

    def _due_job(self, destination: tuple[str, str] | None = ("telegram", "chat-9")):
        session = self.sessions.create("automation:test")
        connector, conversation = destination if destination else (None, None)
        return self.jobs.create(
            name="Due task",
            prompt="Prepare update",
            schedule_kind="once",
            schedule_expression="2026-07-20T14:00:00+00:00",
            timezone="UTC",
            session_id=session.id,
            next_run_at="2026-07-20T14:00:00+00:00",
            destination_connector_id=connector,
            destination_conversation_id=conversation,
        )

    def test_creation_persists_destination_and_model_role(self) -> None:
        service = AutomationService(self.jobs, self.runs, self.sessions, now=lambda: self.now)

        job = service.create_cron(
            "Brief",
            "Prepare my brief",
            "0 8 * * 1-5",
            "UTC",
            destination_connector_id="telegram",
            destination_conversation_id="chat-9",
        )

        self.assertEqual(job["destination_connector_id"], "telegram")
        self.assertEqual(job["destination_conversation_id"], "chat-9")
        self.assertEqual(job["model_role"], "auto")

    def test_successful_delivery_records_message_id(self) -> None:
        self._due_job()
        sent = []

        def deliver(connector_id: str, conversation_id: str, text: str) -> str:
            sent.append((connector_id, conversation_id, text))
            return "msg-42"

        service = AutomationService(
            self.jobs, self.runs, self.sessions, FakeApplication(),
            now=lambda: self.now, deliver=deliver,
        )

        run = service.tick()

        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["output_message_id"], "msg-42")
        self.assertFalse(run["needs_attention"])
        self.assertEqual(sent, [("telegram", "chat-9", "done: Prepare update")])

    def test_delivery_failure_marks_run_failed_and_keeps_output(self) -> None:
        self._due_job()

        def deliver(connector_id: str, conversation_id: str, text: str) -> str:
            raise RuntimeError("network down")

        service = AutomationService(
            self.jobs, self.runs, self.sessions, FakeApplication(),
            now=lambda: self.now, deliver=deliver,
        )

        run = service.tick()

        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error_type"], "DeliveryError")
        self.assertIn("network down", run["error_message"])
        self.assertEqual(run["output_text"], "done: Prepare update")
        self.assertTrue(run["needs_attention"])

    def test_destination_without_deliverer_fails_loudly(self) -> None:
        self._due_job()
        service = AutomationService(
            self.jobs, self.runs, self.sessions, FakeApplication(), now=lambda: self.now
        )

        run = service.tick()

        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error_type"], "DeliveryError")
        self.assertEqual(run["output_text"], "done: Prepare update")

    def test_no_destination_never_calls_deliverer(self) -> None:
        self._due_job(destination=None)

        def deliver(connector_id: str, conversation_id: str, text: str) -> str:
            raise AssertionError("deliverer must not be called without a destination")

        service = AutomationService(
            self.jobs, self.runs, self.sessions, FakeApplication(),
            now=lambda: self.now, deliver=deliver,
        )

        run = service.tick()

        self.assertEqual(run["status"], "succeeded")
        self.assertIsNone(run["output_message_id"])

    def test_denied_side_effect_marks_needs_attention(self) -> None:
        self._due_job(destination=None)
        approvals = ToolApprovalRepository(self.database)

        class DenyingApplication(FakeApplication):
            def send(self, session_id: str, message: str):
                approvals.record(
                    session_id, "task-1", "terminal", {"argv": ["rm"]},
                    "denied", "unattended run",
                )
                return super().send(session_id, message)

        service = AutomationService(
            self.jobs, self.runs, self.sessions, DenyingApplication(),
            now=lambda: self.now, approvals=approvals,
        )

        run = service.tick()

        self.assertEqual(run["status"], "succeeded")
        self.assertTrue(run["needs_attention"])
```

In `tests/test_storage.py`, update the migration assertion to include version 9:

```python
        self.assertEqual([row["version"] for row in versions], [1, 2, 3, 4, 5, 6, 7, 8, 9])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automations.AutomationDeliveryTestCase tests.test_storage -v`
Expected: `test_storage` migration test FAILS (`[1..8] != [1..9]`); the delivery tests FAIL with `TypeError` (unexpected keyword `deliver`/`approvals`) or missing-column errors.

- [ ] **Step 3: Add migration 9 and extend `finish`**

In `src/allpath_agent/storage/database.py`, append to the `MIGRATIONS` tuple after the migration-8 entry:

```python
    (
        9,
        (
            "ALTER TABLE automation_runs ADD COLUMN needs_attention INTEGER NOT NULL DEFAULT 0",
        ),
    ),
```

In `src/allpath_agent/storage/repositories.py`, change `AutomationRunRepository.finish` to:

```python
    def finish(
        self,
        run_id: str,
        status: str,
        *,
        task_id: str | None = None,
        output_text: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        output_message_id: str | None = None,
        needs_attention: bool = False,
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "interrupted"}:
            raise ValueError("invalid automation run terminal status")
        with self._database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE automation_runs
                SET status = ?, task_id = COALESCE(?, task_id), completed_at = ?,
                    output_text = ?, error_type = ?, error_message = ?,
                    output_message_id = ?, needs_attention = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    status,
                    task_id,
                    utc_now(),
                    output_text,
                    error_type,
                    error_message[:240] if error_message else None,
                    output_message_id,
                    int(needs_attention),
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("automation run is missing or already terminal")
        return self.get(run_id)
```

- [ ] **Step 4: Extend `AutomationService`**

In `src/allpath_agent/automations.py`:

Add `ToolApprovalRepository` to the storage import and define the deliverer type below the imports:

```python
from allpath_agent.storage import (
    AutomationJobRepository,
    AutomationRunRepository,
    SessionRepository,
    ToolApprovalRepository,
)
```

```python
Deliverer = Callable[[str, str, str], str]
```

Extend the constructor:

```python
    def __init__(
        self,
        jobs: AutomationJobRepository,
        runs: AutomationRunRepository,
        sessions: SessionRepository,
        application: AutomationApplication | None = None,
        now: Callable[[], datetime] | None = None,
        hooks: HookBus | None = None,
        approvals: ToolApprovalRepository | None = None,
        deliver: Deliverer | None = None,
    ):
        self.jobs = jobs
        self.runs = runs
        self.sessions = sessions
        self.application = application
        self._now = now or (lambda: datetime.now(UTC))
        self._hooks = hooks or HookBus()
        self._approvals = approvals
        self._deliver_fn = deliver
```

Extend both creators with the keyword tail and pass-through (shown for `create_once`; `create_cron` gets the identical tail):

```python
    def create_once(
        self,
        name: str,
        prompt: str,
        at: str,
        timezone: str,
        *,
        model_role: str = "auto",
        destination_connector_id: str | None = None,
        destination_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        next_run = parse_once(at, timezone)
        if next_run <= self._now().astimezone(UTC):
            raise ValueError("one-time automation must be scheduled in the future")
        session = self.sessions.create(title=f"automation:{name.strip()}")
        return self.jobs.create(
            name=name,
            prompt=prompt,
            schedule_kind="once",
            schedule_expression=at.strip(),
            timezone=timezone,
            session_id=session.id,
            next_run_at=next_run.isoformat(),
            model_role=model_role,
            destination_connector_id=destination_connector_id,
            destination_conversation_id=destination_conversation_id,
        )
```

Replace the success branch of `_execute` and add the two helpers:

```python
    def _execute(
        self,
        job: dict[str, Any],
        run: dict[str, Any],
        *,
        advance_schedule: bool,
    ) -> dict[str, Any]:
        self.runs.start(run["id"])
        try:
            self.application.start_session(job["session_id"])
            result = self.application.send(job["session_id"], job["prompt"])
            needs_attention = self._denied_side_effects(job["session_id"], result.task_id)
            delivered_id, delivery_error = self._deliver(job, result.agent.content)
            if delivery_error is None:
                finished = self.runs.finish(
                    run["id"],
                    "succeeded",
                    task_id=result.task_id,
                    output_text=result.agent.content,
                    output_message_id=delivered_id,
                    needs_attention=needs_attention,
                )
            else:
                finished = self.runs.finish(
                    run["id"],
                    "failed",
                    task_id=result.task_id,
                    output_text=result.agent.content,
                    error_type="DeliveryError",
                    error_message=delivery_error,
                    needs_attention=True,
                )
        except KeyboardInterrupt:
            finished = self.runs.finish(run["id"], "interrupted", error_type="KeyboardInterrupt", error_message="automation interrupted")
        except Exception as error:
            finished = self.runs.finish(
                run["id"],
                "failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
        if advance_schedule:
            self._advance(job, finished)
        self._hooks.emit(
            "automation_run_completed",
            job_id=job["id"],
            run_id=finished["id"],
            status=finished["status"],
            session_id=job["session_id"],
        )
        return finished

    def _denied_side_effects(self, session_id: str, task_id: str) -> bool:
        if self._approvals is None:
            return False
        return any(
            record["decision"] == "denied"
            for record in self._approvals.list_for_task(session_id, task_id)
        )

    def _deliver(self, job: dict[str, Any], text: str) -> tuple[str | None, str | None]:
        if job["destination_connector_id"] is None:
            return None, None
        if self._deliver_fn is None:
            return None, "no delivery channel is available in this process"
        try:
            message_id = self._deliver_fn(
                job["destination_connector_id"],
                job["destination_conversation_id"],
                text,
            )
        except Exception as error:
            return None, f"{type(error).__name__}: {str(error)[:160]}"
        return message_id, None
```

- [ ] **Step 5: CLI destination flags**

In `src/allpath_agent/cli/main.py`, after the existing `--timezone` argument of the `automations` subparser, add:

```python
    automations.add_argument("--connector", help="Destination connector id for results")
    automations.add_argument("--conversation", help="Destination conversation id for results")
```

In `_manage_automations`, pass them through both creators, e.g. for `add-once`:

```python
            job = service.create_once(
                args.name,
                args.prompt,
                args.at,
                args.timezone,
                destination_connector_id=args.connector,
                destination_conversation_id=args.conversation,
            )
```

(and the same two keywords on the `create_cron` call).

- [ ] **Step 6: Run tests, full suite, commit**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automations tests.test_storage -v` — Expected: PASS.
Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add src/allpath_agent/storage/database.py src/allpath_agent/storage/repositories.py src/allpath_agent/automations.py src/allpath_agent/cli/main.py tests/test_automations.py tests/test_storage.py
git commit -m "feat: add automation destinations, connector delivery, and needs-attention runs"
```

---

### Task 2: Gateway executes due automations; CLI run/tick deliver

**Files:**
- Modify: `src/allpath_agent/cli/main.py` (`_run_gateway`, `_manage_automations`, new helpers)
- Test: `tests/test_cli.py` (gateway error-message update + any new assertions), `tests/test_automations.py`

**Interfaces:**
- Consumes: Task 1's `AutomationService(..., approvals=..., deliver=...)` and `needs_attention` run field.
- Produces: `_active_connector_instances(home: Path, database: Database) -> list` and `_registry_deliverer(registry: ConnectorRegistry) -> Callable[[str, str, str], str]`, both module-level in `cli/main.py`.

- [ ] **Step 1: Extract connector construction**

In `cli/main.py`, add module-level helpers (the body is moved verbatim from `_run_gateway`'s current construction block; `OutboundMessage` joins the existing `allpath_agent.connectors` import):

```python
def _active_connector_instances(home: Path, database: Database) -> list:
    configs = ConnectorConfigRepository(database).list_all()
    active_ids = {record["connector_id"] for record in configs if record["status"] == "active"}
    secrets = SecretStore(home / "secrets.json").values()
    connectors = []
    if "telegram" in active_ids:
        token = secrets.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ConfigError("Telegram token is missing; reconnect Telegram")
        connectors.append(TelegramConnector(token))
    if "slack" in active_ids:
        bot_token = secrets.get("SLACK_BOT_TOKEN")
        app_token = secrets.get("SLACK_APP_TOKEN")
        if not bot_token or not app_token:
            raise ConfigError("Slack tokens are missing; reconnect Slack")
        connectors.append(SlackConnector(bot_token, app_token))
    if "whatsapp" in active_ids:
        access_token = secrets.get("WHATSAPP_ACCESS_TOKEN")
        phone_number_id = secrets.get("WHATSAPP_PHONE_NUMBER_ID")
        app_secret = secrets.get("WHATSAPP_APP_SECRET")
        verify_token = secrets.get("WHATSAPP_VERIFY_TOKEN")
        if not all((access_token, phone_number_id, app_secret, verify_token)):
            raise ConfigError("WhatsApp credentials are missing; reconnect WhatsApp")
        connectors.append(
            WhatsAppConnector(access_token, phone_number_id, app_secret, verify_token)
        )
    return connectors


def _registry_deliverer(registry: ConnectorRegistry):
    def deliver(connector_id: str, conversation_id: str, text: str) -> str:
        connector = registry.get(connector_id)
        return connector.send(OutboundMessage(conversation_id=conversation_id, text=text))

    return deliver
```

- [ ] **Step 2: Rework `_run_gateway`**

Replace the construction block with the helper, allow an automation-only gateway, build the automation service, and drain due jobs each loop:

```python
    connectors = _active_connector_instances(home, database)
    enabled_jobs = [job for job in AutomationJobRepository(database).list_all() if job["enabled"]]
    if not connectors and not enabled_jobs:
        raise ConfigError(
            "No active connectors or enabled automations. Connect a channel or create an automation first"
        )
    statuses = [connector.status() for connector in connectors]
    failed = next((status for status in statuses if not status.connected), None)
    if failed:
        raise ConfigError(f"{failed.id} verification failed: {failed.detail}")
```

After `runtime = ConnectorRuntime(...)` add:

```python
    automation_service = AutomationService(
        AutomationJobRepository(database),
        AutomationRunRepository(database),
        SessionRepository(database),
        application,
        hooks=application.hooks,
        approvals=ToolApprovalRepository(database),
        deliver=_registry_deliverer(registry),
    )
```

Adjust the startup line so an automation-only gateway is not confusing:

```python
    if statuses:
        output("Allpath gateway running: " + ", ".join(f"{status.id} {status.detail}" for status in statuses))
    else:
        output("Allpath gateway running: automations only (no messaging connectors)")
    output("Side-effecting tools are denied unless a channel-safe approval flow is added.")
```

Inside the loop, after the connector polling `for` block and before the `if once:` check:

```python
            while True:
                automation_run = automation_service.tick()
                if automation_run is None:
                    break
                note = " (needs attention)" if automation_run["needs_attention"] else ""
                output(
                    f"automation run {automation_run['id']}: {automation_run['status']}{note}"
                )
```

(`ToolApprovalRepository` joins the existing `allpath_agent.storage` import in `cli/main.py` if not already there.)

- [ ] **Step 3: Wire delivery into `_manage_automations` run/tick**

In the `run`/`tick` branch of `_manage_automations` (after `application = _build_application(...)`), build the service with delivery support:

```python
        registry = ConnectorRegistry(tuple(_active_connector_instances(home, database)))
        service = AutomationService(
            jobs,
            runs,
            sessions,
            application,
            hooks=getattr(application, "hooks", None),
            approvals=ToolApprovalRepository(database),
            deliver=_registry_deliverer(registry),
        )
```

And extend the result line:

```python
        note = " (needs attention)" if run["needs_attention"] else ""
        output(f"Automation run {run['id']}: {run['status']}{note}")
```

- [ ] **Step 4: Update affected tests and add coverage**

- If any existing `tests/test_cli.py` gateway test asserts the old error text `"No active connectors. Connect Telegram, Slack, or WhatsApp in Allpath first"`, update it to the new message from Step 2.
- Add to `tests/test_cli.py` (mirror the existing temp-home CLI test pattern): running `main(["gateway", "--once"])` on a fresh home with no connectors and no jobs exits with the new error message.
- Add to `tests/test_automations.py` `AutomationCliParserTestCase`: `build_parser()` accepts `automations add-cron --name x --prompt y --cron "0 8 * * 1-5" --connector telegram --conversation chat-9` and the parsed namespace carries both values.

If the existing gateway-once CLI test's fixture cannot reasonably be extended to a due automation without real network, do NOT force it — the tick/delivery path is already covered at service level in Task 1; note the gap in your report.

- [ ] **Step 5: Run the full suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add src/allpath_agent/cli/main.py tests/test_cli.py tests/test_automations.py
git commit -m "feat: run due automations inside the gateway and deliver results"
```

---

### Task 3: Conversational automation creation workflow

**Files:**
- Create: `src/allpath_agent/workflows/automation_creation.py`
- Modify: `src/allpath_agent/workflows/__init__.py` (export `AutomationCreationWorkflow`)
- Modify: `src/allpath_agent/storage/repositories.py` (`ConnectorSessionRepository.list_all`)
- Modify: `src/allpath_agent/cli/main.py` (instantiate, dispatch, input hint, `/automations add`)
- Test: `tests/test_automation_workflow.py` (new)

**Interfaces:**
- Consumes: `ConnectionFlowResult(handled, messages=(), request_secret=False, completed=False)` from `workflows.provider_connection`; `WorkflowRunRepository` (`create/get_active/update`); Task 1's `create_once`/`create_cron` keyword tails; `parse_cron`/`parse_once` from `allpath_agent.automations`.
- Produces: `AutomationCreationWorkflow(runs: WorkflowRunRepository, service: AutomationService, list_bindings: Callable[[], list[dict]])` with `active(session_id)`, `input_hint(session_id)`, `handle(session_id, message) -> ConnectionFlowResult` (no secrets involved).
- Produces: `ConnectorSessionRepository.list_all() -> list[dict]` with `connector_id`, `conversation_id`, `session_id` keys.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automation_workflow.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automation_workflow -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'allpath_agent.workflows.automation_creation'`.

- [ ] **Step 3: Implement the workflow module**

Add to `src/allpath_agent/storage/repositories.py`, inside `ConnectorSessionRepository`:

```python
    def list_all(self) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT connector_id, conversation_id, session_id
                FROM connector_sessions ORDER BY connector_id, conversation_id
                """
            ).fetchall()
        return [dict(row) for row in rows]
```

Create `src/allpath_agent/workflows/automation_creation.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from allpath_agent.automations import AutomationService, parse_cron, parse_once
from allpath_agent.storage import WorkflowRunRepository

from .provider_connection import ConnectionFlowResult

WORKFLOW_ID = "automation_creation"
STEPS = ("name", "prompt", "schedule", "timezone", "destination", "confirm")

BindingsLister = Callable[[], list[dict[str, Any]]]

_TRIGGERS_EN = ("create automation", "new automation", "add automation")
_TRIGGERS_ZH = ("创建自动化", "新建自动化", "添加自动化", "创建定时任务", "新建定时任务")

_HINTS = {
    "name": {"en": "automation name · cancel", "zh": "自动化名称 · 取消"},
    "prompt": {"en": "task instruction · back · cancel", "zh": "任务指令 · 返回 · 取消"},
    "schedule": {
        "en": "cron “0 8 * * 1-5” or ISO time · back · cancel",
        "zh": "cron “0 8 * * 1-5” 或 ISO 时间 · 返回 · 取消",
    },
    "timezone": {"en": "IANA timezone or “default” · back", "zh": "IANA 时区或“默认” · 返回"},
    "destination": {"en": "number, or “none” · back", "zh": "编号，或“无” · 返回"},
    "confirm": {"en": "confirm · back · cancel", "zh": "确认 · 返回 · 取消"},
}


class AutomationCreationWorkflow:
    def __init__(
        self,
        runs: WorkflowRunRepository,
        service: AutomationService,
        list_bindings: BindingsLister,
    ):
        self._runs = runs
        self._service = service
        self._list_bindings = list_bindings

    def active(self, session_id: str) -> bool:
        return self._runs.get_active(session_id, WORKFLOW_ID) is not None

    def input_hint(self, session_id: str) -> str | None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None or active["current_step"] not in _HINTS:
            return None
        language = active["state"].get("language", "en")
        return _HINTS[active["current_step"]][language]

    def handle(self, session_id: str, message: str) -> ConnectionFlowResult:
        cleaned = message.strip()
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            if not _is_trigger(cleaned):
                return ConnectionFlowResult(False)
            language = "zh" if _has_chinese(cleaned) else "en"
            self._runs.create(WORKFLOW_ID, session_id, "name", {"language": language})
            return ConnectionFlowResult(True, (self._prompt("name", {"language": language}),))
        state = dict(active["state"])
        language = state.get("language", "en")
        command = cleaned.lower()
        if command in {"cancel", "取消"}:
            self._runs.update(active["id"], None, state, status="cancelled")
            return ConnectionFlowResult(
                True,
                (_text(language, "Automation creation cancelled.", "已取消创建自动化。"),),
            )
        if command in {"status", "状态"}:
            return ConnectionFlowResult(True, (self._prompt(active["current_step"], state),))
        if command in {"back", "previous", "返回", "上一步"}:
            index = STEPS.index(active["current_step"])
            step = STEPS[max(index - 1, 0)]
            self._runs.update(active["id"], step, state)
            return ConnectionFlowResult(True, (self._prompt(step, state),))
        return self._advance(active, state, language, cleaned)

    def _advance(
        self,
        active: dict[str, Any],
        state: dict[str, Any],
        language: str,
        cleaned: str,
    ) -> ConnectionFlowResult:
        step = active["current_step"]
        if step == "name":
            if len(cleaned) > 60:
                return ConnectionFlowResult(
                    True,
                    (_text(language, "Keep the name under 60 characters.", "名称请控制在 60 个字符以内。"),),
                )
            state["name"] = cleaned
            return self._move(active, state, "prompt")
        if step == "prompt":
            state["prompt"] = cleaned
            return self._move(active, state, "schedule")
        if step == "schedule":
            kind = _schedule_kind(cleaned)
            if kind is None:
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            "Enter a five-field cron expression such as “0 8 * * 1-5”, or an ISO time such as “2026-12-01T08:00”.",
                            "请输入五段 cron 表达式（例如“0 8 * * 1-5”）或 ISO 时间（例如“2026-12-01T08:00”）。",
                        ),
                    ),
                )
            state["schedule_kind"] = kind
            state["schedule_expression"] = cleaned
            return self._move(active, state, "timezone")
        if step == "timezone":
            zone = "UTC" if cleaned.lower() in {"default", "utc", "默认"} else cleaned
            try:
                ZoneInfo(zone)
            except ZoneInfoNotFoundError:
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            f"Unknown IANA timezone: {zone}. Examples: UTC, America/Los_Angeles.",
                            f"未知的 IANA 时区：{zone}。示例：UTC、Asia/Shanghai。",
                        ),
                    ),
                )
            state["timezone"] = zone
            return self._move(active, state, "destination")
        if step == "destination":
            bindings = self._list_bindings()
            if cleaned.lower() in {"none", "no", "无", "不发送"}:
                state["destination_connector_id"] = None
                state["destination_conversation_id"] = None
                return self._move(active, state, "confirm")
            if cleaned.isdigit() and 1 <= int(cleaned) <= len(bindings):
                binding = bindings[int(cleaned) - 1]
                state["destination_connector_id"] = binding["connector_id"]
                state["destination_conversation_id"] = binding["conversation_id"]
                return self._move(active, state, "confirm")
            return ConnectionFlowResult(True, (self._prompt("destination", state),))
        if cleaned.lower() in {"confirm", "yes", "确认", "是"}:
            try:
                job = self._create(state)
            except ValueError as error:
                self._runs.update(active["id"], "schedule", state)
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            f"Could not save: {error}. Enter the schedule again.",
                            f"保存失败：{error}。请重新输入执行时间。",
                        ),
                    ),
                )
            self._runs.update(active["id"], None, state, status="succeeded")
            return ConnectionFlowResult(
                True,
                (
                    _text(
                        language,
                        f"Automation “{job['name']}” saved. Next run: {job['next_run_at']}. "
                        "It executes while `allpath-agent gateway` runs.",
                        f"自动化“{job['name']}”已保存，下次执行：{job['next_run_at']}。"
                        "它会在 `allpath-agent gateway` 运行期间自动执行。",
                    ),
                ),
                completed=True,
            )
        return ConnectionFlowResult(True, (self._prompt("confirm", state),))

    def _move(self, active: dict[str, Any], state: dict[str, Any], step: str) -> ConnectionFlowResult:
        self._runs.update(active["id"], step, state)
        return ConnectionFlowResult(True, (self._prompt(step, state),))

    def _create(self, state: dict[str, Any]) -> dict[str, Any]:
        kwargs = {
            "destination_connector_id": state.get("destination_connector_id"),
            "destination_conversation_id": state.get("destination_conversation_id"),
        }
        if state["schedule_kind"] == "cron":
            return self._service.create_cron(
                state["name"], state["prompt"], state["schedule_expression"], state["timezone"], **kwargs
            )
        return self._service.create_once(
            state["name"], state["prompt"], state["schedule_expression"], state["timezone"], **kwargs
        )

    def _prompt(self, step: str, state: dict[str, Any]) -> str:
        language = state.get("language", "en")
        if step == "name":
            return _text(language, "What should this automation be called? (e.g. “Morning brief”)", "给这个自动化起个名字？（例如“晨间简报”）")
        if step == "prompt":
            return _text(language, "What should Allpath do each time it runs? Describe the task in one message.", "每次执行时 Allpath 应该做什么？用一条消息描述任务。")
        if step == "schedule":
            return _text(
                language,
                "When should it run? Enter a five-field cron expression (“0 8 * * 1-5”) or a one-time ISO time (“2026-12-01T08:00”).",
                "什么时候执行？输入五段 cron 表达式（“0 8 * * 1-5”）或一次性 ISO 时间（“2026-12-01T08:00”）。",
            )
        if step == "timezone":
            return _text(
                language,
                "Which IANA timezone? Type “default” for UTC, or e.g. America/Los_Angeles.",
                "使用哪个 IANA 时区？输入“默认”使用 UTC，或例如 Asia/Shanghai。",
            )
        if step == "destination":
            bindings = self._list_bindings()
            if not bindings:
                return _text(
                    language,
                    "Where should results go? No connected conversations exist yet, so type “none” to keep results local. Message your bot once after connecting a channel to register a destination.",
                    "结果发送到哪里？当前还没有已连接的会话，输入“无”将结果保留在本地。连接消息渠道后先给机器人发一条消息即可注册投递目标。",
                )
            lines = [
                _text(
                    language,
                    "Where should results go? Type a number, or “none” to keep results local:",
                    "结果发送到哪里？输入编号，或输入“无”保留在本地：",
                )
            ]
            for index, binding in enumerate(bindings, start=1):
                lines.append(f"{index}. {binding['connector_id']} · {binding['conversation_id']}")
            return "\n".join(lines)
        summary = _text(
            language,
            "Please confirm this automation:\n"
            f"• Name: {state.get('name')}\n"
            f"• Task: {state.get('prompt')}\n"
            f"• Schedule ({state.get('schedule_kind')}): {state.get('schedule_expression')}\n"
            f"• Timezone: {state.get('timezone')}\n"
            f"• Destination: {_destination_text(state)}\n"
            "Type “confirm” to save, “back” to adjust, or “cancel”.",
            "请确认这个自动化：\n"
            f"• 名称：{state.get('name')}\n"
            f"• 任务：{state.get('prompt')}\n"
            f"• 计划（{state.get('schedule_kind')}）：{state.get('schedule_expression')}\n"
            f"• 时区：{state.get('timezone')}\n"
            f"• 投递目标：{_destination_text(state)}\n"
            "输入“确认”保存，“返回”修改，或“取消”。",
        )
        return summary


def _destination_text(state: dict[str, Any]) -> str:
    connector = state.get("destination_connector_id")
    if connector is None:
        return "local only / 仅本地"
    return f"{connector} · {state.get('destination_conversation_id')}"


def _schedule_kind(value: str) -> str | None:
    try:
        parse_cron(value, "UTC")
        return "cron"
    except ValueError:
        pass
    try:
        parse_once(value, "UTC")
        return "once"
    except ValueError:
        return None


def _text(language: str, english: str, chinese: str) -> str:
    return chinese if language == "zh" else english


def _has_chinese(value: str) -> bool:
    return any("一" <= character <= "鿿" for character in value)


def _is_trigger(message: str) -> bool:
    lowered = message.lower()
    if any(phrase in lowered for phrase in _TRIGGERS_EN):
        return True
    return any(phrase in message for phrase in _TRIGGERS_ZH)
```

Export it from `src/allpath_agent/workflows/__init__.py` following the existing export pattern there.

- [ ] **Step 4: Run the workflow tests**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automation_workflow -v`
Expected: PASS (all).

- [ ] **Step 5: Wire into the chat loop**

In `cli/main.py` `_run_chat` setup, after `whatsapp_workflow = ...`:

```python
    automation_workflow = AutomationCreationWorkflow(
        WorkflowRunRepository(database),
        AutomationService(
            AutomationJobRepository(database),
            AutomationRunRepository(database),
            sessions,
        ),
        ConnectorSessionRepository(database).list_all,
    )
```

In the composer-hint chain, after the `telegram_workflow.input_hint` fallback and before the live-mode curriculum hint:

```python
            if input_hint is None:
                input_hint = automation_workflow.input_hint(active_session_id)
```

Replace the `/automations` command branch with:

```python
        if user_message == "/automations" or user_message.startswith("/automations "):
            action = user_message.removeprefix("/automations").strip()
            application.record_capability_tried("scheduled_automations")
            if action == "add":
                automation_result = automation_workflow.handle(active_session_id, "create automation")
                for message in automation_result.messages:
                    chat_ui.assistant(message, "setup")
            elif action:
                error_output("Usage: /automations [add]")
            else:
                _list_automations(AutomationJobRepository(database), output)
            continue
```

In the message-dispatch chain, after the `telegram_result` block and before `connection_workflow.handle`:

```python
        automation_result = automation_workflow.handle(active_session_id, user_message)
        if automation_result.handled:
            application.record_capability_tried("scheduled_automations")
            for message in automation_result.messages:
                chat_ui.assistant(message, "setup")
            if automation_result.completed:
                application.record_capability_success("scheduled_automations")
            continue
```

(`AutomationCreationWorkflow` joins the workflows import; `ConnectorSessionRepository` is already imported.)

- [ ] **Step 6: Run the full suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add src/allpath_agent/workflows/automation_creation.py src/allpath_agent/workflows/__init__.py src/allpath_agent/storage/repositories.py src/allpath_agent/cli/main.py tests/test_automation_workflow.py
git commit -m "feat: create automations conversationally with confirmation and destinations"
```

---

### Task 4: Teach only what works — lesson, hints, help, docs, changelog

**Files:**
- Modify: `src/allpath_agent/curriculum/catalog.py`
- Modify: `src/allpath_agent/cli/banner.py`
- Modify: `src/allpath_agent/cli/main.py` (`/help` line)
- Modify: `docs/AUTOMATIONS.md`
- Modify: `CHANGELOG.md`
- Test: existing suites (copy changes only; update any test asserting the old strings)

**Interfaces:** none — text and documentation only.

- [ ] **Step 1: Update the curriculum lesson**

In `src/allpath_agent/curriculum/catalog.py`, replace the `scheduled_automations` lesson string with:

```python
            lesson="Say “create automation” (or /automations add) and I will collect the schedule, confirm the details, and save the job.",
```

- [ ] **Step 2: Update the banner hint**

In `src/allpath_agent/cli/banner.py` `CAPABILITY_HINTS`, replace the `scheduled_automations` value with:

```python
    "scheduled_automations": "Try: create automation",
```

- [ ] **Step 3: Update `/help`**

In the `/help` output string in `cli/main.py`, change `/automations` to `/automations [add]`.

- [ ] **Step 4: Update `docs/AUTOMATIONS.md`**

- In "Initial commands", the `/automations add` line is now real — no change needed to the list, but replace the paragraph after it ("Natural-language creation remains a resumable workflow...") with:

```markdown
Conversational creation is a resumable workflow: say “create automation” (or
`/automations add`), answer name, task, schedule, timezone, and destination
prompts, review the echoed summary, and type “confirm” before anything is
saved. Destinations are chosen from conversations Allpath has already seen on
a connected channel; message the bot once to register one.
```

- Replace the final paragraph of "Implemented MVP slice" ("This slice stores results locally. Conversational creation, automatic runner service integration, and connector delivery remain subsequent slices.") with:

```markdown
Conversational creation, gateway execution, and connector delivery are now
implemented. The gateway (foreground `allpath-agent gateway` or the installed
background service) drains due jobs after each connector poll, so no external
cron invocation of `tick` is required; `tick` remains available for debugging.
Results are delivered when a job carries an explicitly configured destination
connector and conversation; a delivery failure marks the run failed with
`DeliveryError` while retaining the generated output. Unattended runs keep
side-effecting tools default-denied; a denied request marks the run
“needs attention” in run records and CLI output instead of failing silently.
```

- [ ] **Step 5: Update `CHANGELOG.md`**

Under `## Unreleased`, add:

```markdown
### Added

- Added conversational automation creation as a resumable bilingual workflow with schedule and timezone validation, destination selection from connected conversations, and an explicit confirmation echo before saving.
- Added automation execution to the gateway loop so due jobs run unattended in the foreground gateway and the installed background service without external cron invocation.
- Added connector delivery of automation results with explicit destination configuration, recorded delivered message IDs, and failure retention of generated output.
- Added needs-attention marking for unattended runs whose side-effect tool requests were denied, surfaced in gateway and CLI run output.
- Added `--connector` and `--conversation` destination flags to `allpath-agent automations add-once` and `add-cron`.
```

- [ ] **Step 6: Fix any string-dependent tests, run the full suite, and commit**

Run: `python3.12 scripts/run_tests.py`
Expected: PASS. If a test asserts the old lesson/hint text (`grep -rn "Try /automations" tests/ src/` to check), update it to the new strings.

```bash
git add src/allpath_agent/curriculum/catalog.py src/allpath_agent/cli/banner.py src/allpath_agent/cli/main.py docs/AUTOMATIONS.md CHANGELOG.md docs/superpowers/plans/2026-08-02-automations-real.md
git commit -m "docs: teach the real automation flow across lesson, hints, and design doc"
```

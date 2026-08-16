# Channel Automation Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create scheduled automations from inside a messaging channel (Telegram/Slack/WhatsApp) — the same guided creation flow the terminal has — with the delivery destination defaulting to the conversation they are typing in, and give gateway conversations a system-prompt variant that only advertises capabilities that actually work there.

**Architecture:** `ConnectorRuntime.dispatch` gains an optional pre-model hook: an injected `AutomationCreationWorkflow`. Before sending to the model, dispatch checks (a) an active creation run for the session, or (b) `/automations add` / trigger phrases; handled turns reply through the connector without touching the model. `AutomationCreationWorkflow.start()` accepts an optional `default_destination=(connector_id, conversation_id)`: when set, the destination step is pre-seeded and the confirm summary shows “this conversation”. A separate static `GATEWAY_SURFACE_NOTE` replaces the terminal-oriented command list in gateway-built applications (`_build_application(surface="gateway")`).

**Tech Stack:** Python 3.11+ stdlib only. No schema changes.

## Global Constraints

- No third-party dependencies; `python3.12 scripts/run_tests.py` (default `python3` is 3.9) must pass at every commit.
- Every meaningful change updates `CHANGELOG.md` under `Unreleased`.
- The terminal creation flow and the golden-path test must remain unchanged in behavior.
- Secrets never enter channels; this flow has none. Directive tools stay excluded from the gateway.
- Handled channel turns emit the same `connector_message_received` / `connector_reply_sent` hooks as model turns (observability parity), but do NOT call `application.send`.
- Curly quotes in user-facing copy.

---

### Task 1: `start()` accepts a default destination

**Files:**
- Modify: `src/allpath_agent/workflows/automation_creation.py`
- Test: `tests/test_automation_workflow.py`

**Interfaces:**
- Produces: `start(session_id, language="en", prefill=None, *, default_destination: tuple[str, str] | None = None)`. When provided and the four core fields are all prefilled, the flow starts at `confirm` with the destination pre-seeded; when core fields are missing, the destination is stored in state so the destination step is SKIPPED later (`_move` from timezone jumps to confirm). The confirm summary renders a pre-seeded destination as `<connector> · this conversation`.
- Produces: `handle()` learns to skip the destination step when `state["destination_preselected"]` is true.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_automation_workflow.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automation_workflow -v`
Expected: the two default-destination tests FAIL (`TypeError: unexpected keyword 'default_destination'`); the third passes already (documents existing behavior).

- [ ] **Step 3: Implement**

In `src/allpath_agent/workflows/automation_creation.py`:

Change the `start` signature and seed state:

```python
    def start(
        self,
        session_id: str,
        language: str = "en",
        prefill: dict[str, str] | None = None,
        *,
        default_destination: tuple[str, str] | None = None,
    ) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is not None:
            return ConnectionFlowResult(True, (self._prompt(active["current_step"], dict(active["state"])),))
        state: dict[str, Any] = {"language": language}
        if default_destination is not None:
            state["destination_connector_id"] = default_destination[0]
            state["destination_conversation_id"] = default_destination[1]
            state["destination_preselected"] = True
```

(the prefill loop stays as is). Change the first-unfilled-step selection so a preselected destination lands on `confirm` when everything else is present:

```python
        step = next(
            (
                candidate
                for candidate, key in (
                    ("name", "name"),
                    ("prompt", "prompt"),
                    ("schedule", "schedule_expression"),
                    ("timezone", "timezone"),
                )
                if key not in state
            ),
            "confirm" if state.get("destination_preselected") else "destination",
        )
```

In `_advance`'s timezone branch, replace `return self._move(active, state, "destination")` with:

```python
            return self._move(
                active,
                state,
                "confirm" if state.get("destination_preselected") else "destination",
            )
```

In the `back` handling inside `handle()`, make “back” from `confirm` skip the destination step when preselected — replace the back branch with:

```python
        if command in {"back", "previous", "返回", "上一步"}:
            index = STEPS.index(active["current_step"])
            step = STEPS[max(index - 1, 0)]
            if step == "destination" and state.get("destination_preselected"):
                step = "timezone"
            self._runs.update(active["id"], step, state)
            return ConnectionFlowResult(True, (self._prompt(step, state),))
```

Update `_destination_text`:

```python
def _destination_text(state: dict[str, Any]) -> str:
    connector = state.get("destination_connector_id")
    if connector is None:
        return "local only / 仅本地"
    if state.get("destination_preselected"):
        return f"{connector} · this conversation / 当前会话"
    return f"{connector} · {state.get('destination_conversation_id')}"
```

- [ ] **Step 4: Run tests and the full suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automation_workflow -v` — Expected: PASS.
Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/workflows/automation_creation.py tests/test_automation_workflow.py
git commit -m "feat: let automation creation preselect the current conversation as destination"
```

---

### Task 2: Gateway dispatch runs the creation workflow before the model

**Files:**
- Modify: `src/allpath_agent/connectors/runtime.py`
- Modify: `src/allpath_agent/cli/main.py` (`_run_gateway` wiring)
- Test: `tests/test_connectors.py`

**Interfaces:**
- Consumes: Task 1's `start(..., default_destination=...)`, plus existing `active()`/`handle()`.
- Produces: `ConnectorRuntime.__init__(..., automation_workflow: AutomationCreationWorkflow | None = None)`. `dispatch()` returns the session id as before.
- Channel command surface: `/automations add` and `/automations` (list) are handled deterministically; trigger phrases (`create automation`, `创建定时任务`, ...) start the flow via `start(..., default_destination=(connector_id, conversation_id))`; an active run consumes every message until it completes or is cancelled.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_connectors.py` (reuse `FakeConnector`, `FakeApplication`, `InboundMessage` already defined there; add the workflow imports):

```python
from allpath_agent.automations import AutomationService
from allpath_agent.storage import (
    AutomationJobRepository,
    AutomationRunRepository,
    WorkflowRunRepository,
)
from allpath_agent.workflows.automation_creation import AutomationCreationWorkflow


class ConnectorAutomationCreationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.sessions = SessionRepository(self.database)
        self.bindings = ConnectorSessionRepository(self.database)
        self.jobs = AutomationJobRepository(self.database)
        self.workflow = AutomationCreationWorkflow(
            WorkflowRunRepository(self.database),
            AutomationService(self.jobs, AutomationRunRepository(self.database), self.sessions),
            self.bindings.list_all,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _runtime(self, connector, application):
        return ConnectorRuntime(
            application,
            ConnectorRegistry((connector,)),
            self.sessions,
            self.bindings,
            automation_workflow=self.workflow,
        )

    def _messages(self, *texts):
        return tuple(
            InboundMessage("fake", "chat-1", "user-1", str(index), text, "now")
            for index, text in enumerate(texts, start=10)
        )

    def test_slash_add_flow_creates_job_targeting_this_conversation(self) -> None:
        connector = FakeConnector(
            self._messages(
                "/automations add",
                "Morning brief",
                "Summarize the news",
                "0 8 * * *",
                "UTC",
                "confirm",
            )
        )
        application = FakeApplication()

        self._runtime(connector, application).poll_once("fake")

        self.assertEqual(application.messages, [])
        jobs = self.jobs.list_all()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["destination_connector_id"], "fake")
        self.assertEqual(jobs[0]["destination_conversation_id"], "chat-1")
        self.assertIn("this conversation", " ".join(m.text for m in connector.sent))
        self.assertTrue(connector.sent[-1].text.lower().startswith("automation"))

    def test_trigger_phrase_starts_flow_and_model_is_bypassed_until_done(self) -> None:
        connector = FakeConnector(self._messages("create automation", "cancel", "hello again"))
        application = FakeApplication()

        self._runtime(connector, application).poll_once("fake")

        self.assertEqual([m[1] for m in application.messages], ["hello again"])
        self.assertIn("cancel", connector.sent[1].text.lower())

    def test_slash_list_replies_without_model(self) -> None:
        connector = FakeConnector(self._messages("/automations"))
        application = FakeApplication()

        self._runtime(connector, application).poll_once("fake")

        self.assertEqual(application.messages, [])
        self.assertEqual(len(connector.sent), 1)

    def test_runtime_without_workflow_keeps_legacy_behavior(self) -> None:
        connector = FakeConnector(self._messages("/automations add"))
        application = FakeApplication()
        ConnectorRuntime(
            application, ConnectorRegistry((connector,)), self.sessions, self.bindings
        ).poll_once("fake")

        self.assertEqual([m[1] for m in application.messages], ["/automations add"])
```

Check `FakeApplication.messages` shape in the file (it appends `(session_id, message)` or similar) and adapt the two index accesses (`m[1]`) accordingly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_connectors -v`
Expected: the new tests FAIL (`TypeError: unexpected keyword 'automation_workflow'`), except `test_runtime_without_workflow_keeps_legacy_behavior` which passes.

- [ ] **Step 3: Implement dispatch pre-model handling**

In `src/allpath_agent/connectors/runtime.py`:

Add the import (`TYPE_CHECKING`-guarded to avoid a cycle if any; if `allpath_agent.workflows` imports nothing from connectors it can be a plain import — check first):

```python
from allpath_agent.workflows.automation_creation import AutomationCreationWorkflow
```

Extend the constructor:

```python
    def __init__(
        self,
        application: AgentApplication,
        registry: ConnectorRegistry,
        sessions: SessionRepository,
        bindings: ConnectorSessionRepository,
        hooks: HookBus | None = None,
        automation_workflow: AutomationCreationWorkflow | None = None,
    ):
        self._application = application
        self._registry = registry
        self._sessions = sessions
        self._bindings = bindings
        self._hooks = hooks or getattr(application, "hooks", HookBus())
        self._automation_workflow = automation_workflow
```

In `dispatch`, after the session id is resolved/bound and BEFORE `self._application.start_session(session_id)`, insert:

```python
        handled_reply = self._handle_channel_command(event, session_id)
        if handled_reply is not None:
            self._registry.get(event.connector_id).send(
                OutboundMessage(
                    conversation_id=event.conversation_id,
                    text=handled_reply,
                    reply_to_message_id=event.message_id,
                    metadata=event.metadata,
                )
            )
            self._hooks.emit(
                "connector_reply_sent",
                connector_id=event.connector_id,
                conversation_id=event.conversation_id,
                source_message_id=event.message_id,
                session_id=session_id,
                task_id=None,
            )
            return session_id
```

Add the helper method:

```python
    def _handle_channel_command(self, event: InboundMessage, session_id: str) -> str | None:
        workflow = self._automation_workflow
        if workflow is None:
            return None
        text = event.text.strip()
        lowered = text.lower()
        if lowered == "/automations":
            return self._automation_list_text()
        if lowered == "/automations add":
            result = workflow.start(
                session_id,
                _language_of(text),
                None,
                default_destination=(event.connector_id, event.conversation_id),
            )
            return "\n\n".join(result.messages)
        if workflow.active(session_id):
            result = workflow.handle(session_id, text)
            return "\n\n".join(result.messages) if result.handled else None
        if _is_creation_trigger(text):
            result = workflow.start(
                session_id,
                _language_of(text),
                None,
                default_destination=(event.connector_id, event.conversation_id),
            )
            return "\n\n".join(result.messages)
        return None

    def _automation_list_text(self) -> str:
        jobs = self._automation_workflow.list_jobs()
        if not jobs:
            return "No automations yet. Send “/automations add” to create one."
        lines = ["Automations:"]
        for job in jobs:
            state = "on" if job["enabled"] else "off"
            lines.append(
                f"• {job['name']} — {job['schedule_kind']} {job['schedule_expression']} "
                f"({job['timezone']}) · {state} · next {job['next_run_at'] or '—'}"
            )
        return "\n".join(lines)
```

and module-level helpers:

```python
def _language_of(text: str) -> str:
    return "zh" if any("一" <= character <= "鿿" for character in text) else "en"


def _is_creation_trigger(text: str) -> bool:
    from allpath_agent.workflows.automation_creation import _is_trigger

    return _is_trigger(text)
```

`_is_trigger` is private in the workflow module; expose it properly instead of importing a private name: in `automation_creation.py`, add a public method `is_trigger(message: str) -> bool` on `AutomationCreationWorkflow` returning `_is_trigger(message)`, and add `list_jobs()` returning `self._service.jobs.list_all()`. Then in runtime.py use `workflow.is_trigger(text)` and `workflow.list_jobs()` and drop the `_is_creation_trigger` helper.

- [ ] **Step 4: Wire the workflow into `_run_gateway`**

In `src/allpath_agent/cli/main.py` `_run_gateway`, build the workflow before the runtime and pass it:

```python
    automation_workflow = AutomationCreationWorkflow(
        WorkflowRunRepository(database),
        AutomationService(
            AutomationJobRepository(database),
            AutomationRunRepository(database),
            SessionRepository(database),
        ),
        ConnectorSessionRepository(database).list_all,
    )
    runtime = ConnectorRuntime(
        application,
        registry,
        SessionRepository(database),
        ConnectorSessionRepository(database),
        automation_workflow=automation_workflow,
    )
```

(`AutomationCreationWorkflow`, `WorkflowRunRepository` are already imported in main.py — verify.)

- [ ] **Step 5: Run tests and the full suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_connectors -v` — Expected: PASS.
Run: `python3.12 scripts/run_tests.py` — Expected: PASS (golden path unchanged: it uses `automations tick`, not the runtime dispatch).

- [ ] **Step 6: Commit**

```bash
git add src/allpath_agent/connectors/runtime.py src/allpath_agent/workflows/automation_creation.py src/allpath_agent/cli/main.py tests/test_connectors.py
git commit -m "feat: create automations from messaging channels with the current conversation as destination"
```

---

### Task 3: Gateway-surface system prompt

**Files:**
- Modify: `src/allpath_agent/application.py`
- Modify: `src/allpath_agent/cli/main.py` (`_build_application(surface=...)`)
- Test: `tests/test_agent_loop.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `application.py`: `GATEWAY_SURFACE_NOTE: str` (static) and `_runtime_system_prompt(system_prompt, profile, surface: str = "terminal")` choosing `ALLPATH_COMMANDS` for terminal and `GATEWAY_SURFACE_NOTE` for gateway; `AgentApplication.__init__(..., surface: str = "terminal")` threads it into every `send`.
- Produces: `_build_application(..., surface: str = "terminal")`; `_run_gateway` passes `surface="gateway"`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_loop.py`, add next to the existing prompt test:

```python
    def test_gateway_surface_prompt_advertises_only_channel_capabilities(self) -> None:
        prompt = _runtime_system_prompt(
            "base", ModelProfile("fast", "m", quality=1, cost=1), surface="gateway"
        )

        self.assertIn("/automations add", prompt)
        self.assertIn("messaging channel", prompt)
        self.assertNotIn("channel_connect", prompt)
        self.assertNotIn("/models", prompt)
        self.assertIn("Allpath Agent", prompt)
```

In `tests/test_cli.py`, extend `GatewayStaysDirectiveFreeTestCase` (or add a sibling) asserting the gateway-built application's system prompt contains `"messaging channel"` — introspect via the same private path the class already uses for the registry (`application._system_prompt` exists on `AgentApplication`; confirm the attribute name).

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_agent_loop -v` — Expected: FAIL (`TypeError: unexpected keyword 'surface'`).

- [ ] **Step 3: Implement**

In `src/allpath_agent/application.py`, add below `ALLPATH_COMMANDS`:

```python
GATEWAY_SURFACE_NOTE = (
    "You are Allpath Agent replying inside a messaging channel (Telegram, Slack, or WhatsApp). "
    "Introduce yourself as Allpath Agent, a personal assistant; do not describe yourself as a "
    "coding assistant. In this channel the user can send “/automations” to list scheduled "
    "automations and “/automations add” (or say “create automation”) to start a guided flow "
    "that schedules a recurring or one-time task delivered back to this conversation; the host "
    "handles that flow — tell the user to send that command rather than describing steps. "
    "Model connections and channel setup are managed from the Allpath terminal, not from this "
    "channel. Side-effecting tools are unavailable here; read-only lookups still work. "
    "Never claim a capability does not exist without checking /help or the terminal."
)
```

Change `_runtime_system_prompt`:

```python
def _runtime_system_prompt(
    system_prompt: str,
    profile: ModelProfile,
    surface: str = "terminal",
) -> str:
    ...
    surface_note = GATEWAY_SURFACE_NOTE if surface == "gateway" else ALLPATH_COMMANDS
    return (
        f"{system_prompt}\n\n"
        "Runtime identity (authoritative): "
        f"role={profile.name}, provider={profile.provider}, model={profile.model}. "
        f"{tool_access}{external_boundary} "
        "When asked which model or permissions are active, report these exact values and do not guess.\n\n"
        f"{surface_note}"
    )
```

`AgentApplication.__init__` gains `surface: str = "terminal"` stored as `self._surface`, and `send` passes `_runtime_system_prompt(self._system_prompt, decision.profile, self._surface)`.

In `cli/main.py`, `_build_application` gains `surface: str = "terminal"` forwarded to `AgentApplication(...)`; `_run_gateway`'s `_build_application(...)` call passes `surface="gateway"`. (Automation `run`/`tick` in `_manage_automations` keep the terminal default — unattended runs use the base prompt semantics; the surface note is about the human-facing channel.)

- [ ] **Step 4: Run the suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add src/allpath_agent/application.py src/allpath_agent/cli/main.py tests/test_agent_loop.py tests/test_cli.py
git commit -m "feat: give messaging channels a surface-specific system prompt"
```

---

### Task 4: Docs and changelog

**Files:**
- Modify: `docs/AUTOMATIONS.md`, `docs/CONNECTORS.md`, `CHANGELOG.md`

- [ ] **Step 1: `docs/AUTOMATIONS.md`** — after the conversational-creation paragraph, add:

```markdown
Creation also works from inside a connected messaging channel: send
`/automations add` (or say “create automation”) to the bot. The same guided
flow runs there, and the delivery destination is preselected as the
conversation you are typing in, so results come back to the same chat.
`/automations` lists jobs from the channel as well.
```

- [ ] **Step 2: `docs/CONNECTORS.md`** — add a short “Channel commands” section:

```markdown
## Channel commands

Inside a connected channel, Allpath handles these before the model sees them:
`/automations` (list) and `/automations add` (start guided creation, results
delivered back to this conversation). While a creation flow is active, every
message in that conversation answers the flow until it completes or you send
“cancel”. Model connections and channel setup remain terminal-only, and
side-effecting tools stay disabled in channels.
```

- [ ] **Step 3: `CHANGELOG.md`** under `## Unreleased` `### Added`, append:

```markdown
- Added automation creation from messaging channels: `/automations add` and the trigger phrases start the guided flow inside Telegram, Slack, or WhatsApp with the current conversation preselected as the delivery destination, and `/automations` lists jobs; handled turns bypass the model.
- Added a gateway-surface system prompt so channel conversations advertise only capabilities that work there and the assistant identifies as Allpath Agent.
```

- [ ] **Step 4: Run the suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add docs/AUTOMATIONS.md docs/CONNECTORS.md CHANGELOG.md docs/superpowers/plans/2026-08-02-channel-automation-creation.md
git commit -m "docs: describe channel-side automation creation and commands"
```

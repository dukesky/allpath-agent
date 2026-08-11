# Model-Driven Intent Routing (Milestone 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let tool-capable models route user intent themselves: read-only `channel_status` answers state questions; directive tools `channel_connect` / `create_automation` / `connect_model` hand off to the existing deterministic guided flows. Exact trigger phrases stay as a deterministic fast path (required for external-CLI providers that do not support tool calling), so nothing regresses for account-auth connections.

**Architecture:** OpenClaw-style directives. A `DirectiveSink` is shared between the tool handlers and the chat loop. Directive tools have NO side effects — they only record a pending directive and tell the model the host takes over. After each `send()`, the CLI drains the sink: channel/model directives re-enter the loop as a synthetic trigger message (reusing every existing interaction block — secrets, selectors — unchanged); automation directives call a new `AutomationCreationWorkflow.start()` that accepts validated prefill from the model and begins at the first unfilled step. The tools are registered only in interactive chat sessions (never in the gateway or unattended runs). The system prompt gains OpenClaw's ASK-vs-CONNECT rule and Hermes's "absence is not evidence of non-existence" rule.

**Tech Stack:** Python 3.11+ stdlib only. No schema changes.

## Global Constraints

- No third-party dependencies; `python3.12 scripts/run_tests.py` (default `python3` is 3.9) must pass at every commit.
- Every meaningful change updates `CHANGELOG.md` under `Unreleased`.
- Directive tools are READ_ONLY risk (they cause no side effect themselves; the flows they start are user-driven and cancellable). Secrets continue to flow only through hidden input, never through tools or model context.
- Existing trigger phrases keep working exactly as today in every mode (fast path); the golden-path test must pass unmodified.
- Directive tools must NOT be registered for gateway or `automations run/tick` application instances.
- The system-prompt block stays fully static (prompt-cache friendly).
- User-facing quoted phrases use curly quotes (“ ”).

---

### Task 1: Directive sink and assistant tools

**Files:**
- Create: `src/allpath_agent/tools/assistant_directives.py`
- Test: `tests/test_assistant_directives.py` (new)

**Interfaces:**
- Produces: `AssistantDirective(kind: str, channel: str | None = None, reconnect: bool = False, prefill: dict[str, str] = {})` dataclass; `DirectiveSink` with `set(directive)` and `take() -> AssistantDirective | None` (take clears); `register_assistant_tools(registry: ToolRegistry, configs: ConnectorConfigRepository, sink: DirectiveSink) -> None` registering four READ_ONLY tools: `channel_status`, `channel_connect`, `create_automation`, `connect_model`.
- Task 3 consumes all of these.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_assistant_directives.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.storage import ConnectorConfigRepository, Database
from allpath_agent.tools.assistant_directives import (
    AssistantDirective,
    DirectiveSink,
    register_assistant_tools,
)
from allpath_agent.tools.registry import ToolRegistry, ToolRisk


class AssistantDirectiveToolsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.configs = ConnectorConfigRepository(self.database)
        self.sink = DirectiveSink()
        self.registry = ToolRegistry()
        register_assistant_tools(self.registry, self.configs, self.sink)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _call(self, name: str, arguments: dict):
        return self.registry.get(name).handler(arguments)

    def test_all_four_tools_are_read_only(self) -> None:
        for name in ("channel_status", "channel_connect", "create_automation", "connect_model"):
            self.assertIs(self.registry.get(name).risk, ToolRisk.READ_ONLY)

    def test_channel_status_reports_all_channels_without_config(self) -> None:
        result = self._call("channel_status", {})

        statuses = {entry["channel"]: entry["status"] for entry in result["channels"]}
        self.assertEqual(
            statuses,
            {"telegram": "not_configured", "slack": "not_configured", "whatsapp": "not_configured"},
        )
        self.assertIsNone(self.sink.take())

    def test_channel_status_reports_single_active_channel(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self._call("channel_status", {"channel": "telegram"})

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["detail"], "@my_bot")

    def test_channel_connect_sets_directive_for_unconnected_channel(self) -> None:
        result = self._call("channel_connect", {"channel": "telegram"})

        self.assertEqual(result["directive"], "channel_setup")
        directive = self.sink.take()
        self.assertEqual(directive.kind, "channel_setup")
        self.assertEqual(directive.channel, "telegram")
        self.assertFalse(directive.reconnect)

    def test_channel_connect_on_active_channel_returns_status_without_directive(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self._call("channel_connect", {"channel": "telegram"})

        self.assertTrue(result["already_connected"])
        self.assertEqual(result["detail"], "@my_bot")
        self.assertIsNone(self.sink.take())

    def test_channel_connect_reconnect_overrides_active_guard(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self._call("channel_connect", {"channel": "telegram", "reconnect": True})

        self.assertEqual(result["directive"], "channel_setup")
        self.assertTrue(self.sink.take().reconnect)

    def test_channel_connect_rejects_unknown_channel(self) -> None:
        with self.assertRaises(ValueError):
            self._call("channel_connect", {"channel": "discord"})
        self.assertIsNone(self.sink.take())

    def test_create_automation_carries_only_provided_prefill(self) -> None:
        result = self._call(
            "create_automation",
            {"prompt": "Summarize the news", "schedule": "0 8 * * *"},
        )

        self.assertEqual(result["directive"], "automation_setup")
        directive = self.sink.take()
        self.assertEqual(directive.kind, "automation_setup")
        self.assertEqual(
            directive.prefill,
            {"prompt": "Summarize the news", "schedule": "0 8 * * *"},
        )

    def test_connect_model_sets_model_setup_directive(self) -> None:
        result = self._call("connect_model", {})

        self.assertEqual(result["directive"], "model_setup")
        self.assertEqual(self.sink.take().kind, "model_setup")

    def test_sink_take_clears_and_last_set_wins(self) -> None:
        self.sink.set(AssistantDirective("model_setup"))
        self.sink.set(AssistantDirective("channel_setup", channel="slack"))

        first = self.sink.take()
        self.assertEqual(first.channel, "slack")
        self.assertIsNone(self.sink.take())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_assistant_directives -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'allpath_agent.tools.assistant_directives'`.

- [ ] **Step 3: Implement the module**

Create `src/allpath_agent/tools/assistant_directives.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from allpath_agent.storage import ConnectorConfigRepository

from .registry import ToolDefinition, ToolRegistry

SUPPORTED_CHANNELS = ("telegram", "slack", "whatsapp")
_PREFILL_FIELDS = ("name", "prompt", "schedule", "timezone")
_HANDOFF_NOTE = (
    "The host chat now starts the guided flow with the user. "
    "Tell the user the setup questions come next; do not describe the steps yourself."
)


@dataclass
class AssistantDirective:
    kind: str
    channel: str | None = None
    reconnect: bool = False
    prefill: dict[str, str] = field(default_factory=dict)


class DirectiveSink:
    def __init__(self):
        self._pending: AssistantDirective | None = None

    def set(self, directive: AssistantDirective) -> None:
        self._pending = directive

    def take(self) -> AssistantDirective | None:
        pending, self._pending = self._pending, None
        return pending


def register_assistant_tools(
    registry: ToolRegistry,
    configs: ConnectorConfigRepository,
    sink: DirectiveSink,
) -> None:
    def _entry(channel: str) -> dict[str, Any]:
        record = configs.get(channel)
        if record is None:
            return {"channel": channel, "status": "not_configured", "detail": "never connected"}
        return {"channel": channel, "status": record["status"], "detail": record["detail"]}

    def _channel_status(arguments: dict[str, Any]) -> dict[str, Any]:
        channel = arguments.get("channel")
        if channel:
            if channel not in SUPPORTED_CHANNELS:
                raise ValueError(f"unsupported channel: {channel}")
            return _entry(channel)
        return {"channels": [_entry(channel) for channel in SUPPORTED_CHANNELS]}

    def _channel_connect(arguments: dict[str, Any]) -> dict[str, Any]:
        channel = arguments["channel"]
        if channel not in SUPPORTED_CHANNELS:
            raise ValueError(f"unsupported channel: {channel}")
        reconnect = bool(arguments.get("reconnect", False))
        record = configs.get(channel)
        if record is not None and record["status"] == "active" and not reconnect:
            return {
                "already_connected": True,
                "channel": channel,
                "detail": record["detail"],
                "note": (
                    "This channel is already connected. Tell the user, and only call again "
                    "with reconnect=true if they explicitly want to reconfigure it."
                ),
            }
        sink.set(AssistantDirective("channel_setup", channel=channel, reconnect=reconnect))
        return {"directive": "channel_setup", "channel": channel, "note": _HANDOFF_NOTE}

    def _create_automation(arguments: dict[str, Any]) -> dict[str, Any]:
        prefill = {
            fieldname: str(arguments[fieldname]).strip()
            for fieldname in _PREFILL_FIELDS
            if arguments.get(fieldname)
        }
        sink.set(AssistantDirective("automation_setup", prefill=prefill))
        return {"directive": "automation_setup", "prefilled": sorted(prefill), "note": _HANDOFF_NOTE}

    def _connect_model(arguments: dict[str, Any]) -> dict[str, Any]:
        sink.set(AssistantDirective("model_setup"))
        return {"directive": "model_setup", "note": _HANDOFF_NOTE}

    registry.register(
        ToolDefinition(
            name="channel_status",
            description=(
                "Report whether the Telegram, Slack, and WhatsApp messaging channels are "
                "connected. Use this whenever the user asks ABOUT a channel or its state. "
                "Read-only; never starts setup."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": list(SUPPORTED_CHANNELS)},
                },
                "additionalProperties": False,
            },
            handler=_channel_status,
        )
    )
    registry.register(
        ToolDefinition(
            name="channel_connect",
            description=(
                "Start the guided setup for a messaging channel when the user asks to CONNECT "
                "one. The host runs the interactive tutorial after this call — do not describe "
                "the steps yourself. Set reconnect=true only when the user explicitly wants to "
                "reconfigure an already-connected channel."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": list(SUPPORTED_CHANNELS)},
                    "reconnect": {"type": "boolean"},
                },
                "required": ["channel"],
                "additionalProperties": False,
            },
            handler=_channel_connect,
        )
    )
    registry.register(
        ToolDefinition(
            name="create_automation",
            description=(
                "Start the guided creation of a scheduled automation (one-time or recurring, "
                "with optional delivery to a connected channel). Pass any values you can "
                "extract from the user's request: name, prompt (the task instruction), "
                "schedule (a five-field cron expression or an ISO date-time), and timezone "
                "(IANA name). The host collects anything missing and always asks the user to "
                "confirm before saving."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "prompt": {"type": "string"},
                    "schedule": {"type": "string"},
                    "timezone": {"type": "string"},
                },
                "additionalProperties": False,
            },
            handler=_create_automation,
        )
    )
    registry.register(
        ToolDefinition(
            name="connect_model",
            description=(
                "Start the guided model-provider setup when the user wants to add or replace "
                "a model connection. The host runs the interactive flow after this call."
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_connect_model,
        )
    )
```

(If `ToolDefinition` requires an explicit risk argument, pass `risk=ToolRisk.READ_ONLY` and import it — check `tools/registry.py` first; the default already is READ_ONLY per `current_datetime`.)

- [ ] **Step 4: Run tests and the full suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_assistant_directives -v` — Expected: PASS.
Run: `python3.12 scripts/run_tests.py` — Expected: PASS (module is not yet registered anywhere, so no other behavior changes).

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/tools/assistant_directives.py tests/test_assistant_directives.py
git commit -m "feat: add read-only channel status and directive handoff tools"
```

---

### Task 2: `AutomationCreationWorkflow.start()` with validated prefill

**Files:**
- Modify: `src/allpath_agent/workflows/automation_creation.py`
- Test: `tests/test_automation_workflow.py`

**Interfaces:**
- Produces: `start(session_id: str, language: str = "en", prefill: dict[str, str] | None = None) -> ConnectionFlowResult`. Validates each prefill field with the workflow's existing validators (name length; schedule via `_schedule_kind`; timezone via `ZoneInfo`; prompt non-empty), silently DROPS invalid fields, seeds the run state, and begins at the first unfilled step in `("name", "prompt", "schedule", "timezone")` order — or at `"destination"` when all four are present. If a run is already active for the session, re-renders the current step instead of restarting.
- The existing trigger branch in `handle()` is refactored to call `start(session_id, language)` so both entrances share one code path. Task 3 consumes `start`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_automation_workflow.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automation_workflow -v`
Expected: the new tests FAIL with `AttributeError: ... has no attribute 'start'`.

- [ ] **Step 3: Implement `start` and refactor the trigger branch**

In `src/allpath_agent/workflows/automation_creation.py`, add to the class:

```python
    def start(
        self,
        session_id: str,
        language: str = "en",
        prefill: dict[str, str] | None = None,
    ) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is not None:
            return ConnectionFlowResult(True, (self._prompt(active["current_step"], dict(active["state"])),))
        state: dict[str, Any] = {"language": language}
        for fieldname, value in (prefill or {}).items():
            cleaned = str(value).strip()
            if not cleaned:
                continue
            if fieldname == "name" and len(cleaned) <= 60:
                state["name"] = cleaned
            elif fieldname == "prompt":
                state["prompt"] = cleaned
            elif fieldname == "schedule":
                kind = _schedule_kind(cleaned)
                if kind is not None:
                    state["schedule_kind"] = kind
                    state["schedule_expression"] = cleaned
            elif fieldname == "timezone":
                zone = "UTC" if cleaned.lower() in {"default", "utc", "默认"} else cleaned
                try:
                    ZoneInfo(zone)
                except ZoneInfoNotFoundError:
                    continue
                state["timezone"] = zone
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
            "destination",
        )
        self._runs.create(WORKFLOW_ID, session_id, step, state)
        return ConnectionFlowResult(True, (self._prompt(step, state),))
```

Refactor `handle()`'s trigger branch to delegate:

```python
        if active is None:
            if not _is_trigger(cleaned):
                return ConnectionFlowResult(False)
            language = "zh" if _has_chinese(cleaned) else "en"
            return self.start(session_id, language)
```

- [ ] **Step 4: Run the workflow tests and the full suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automation_workflow -v` — Expected: PASS (all, including the pre-existing flow tests).
Run: `python3.12 scripts/run_tests.py` — Expected: PASS (golden path unchanged — the trigger path now routes through `start` with identical output).

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/workflows/automation_creation.py tests/test_automation_workflow.py
git commit -m "feat: let automation creation start with validated model-extracted prefill"
```

---

### Task 3: CLI wiring — register tools, drain directives, synthetic trigger re-entry

**Files:**
- Modify: `src/allpath_agent/cli/main.py`
- Test: `tests/test_cli.py` (unit tests for the new pure helpers; loop-level behavior is inherited from existing suites)

**Interfaces:**
- Consumes: Task 1's `DirectiveSink`/`register_assistant_tools`; Task 2's `start`.
- Produces in `cli/main.py`: `_directive_trigger_message(directive) -> str | None` (pure) mapping `channel_setup` → `"connect <channel>"` / `"reconnect <channel>"` and `model_setup` → `"connect model"`, `automation_setup` → `None` (handled directly, not via synthetic message).

- [ ] **Step 1: Thread the sink into application construction**

- `_build_application` gains a keyword parameter `directive_sink=None`. After `registry = create_builtin_registry(...)`, add:

```python
    if directive_sink is not None:
        register_assistant_tools(registry, ConnectorConfigRepository(database), directive_sink)
```

(import `register_assistant_tools`, `DirectiveSink`, `AssistantDirective` from `allpath_agent.tools.assistant_directives`.)

- In `_run_chat`'s setup, create `directive_sink = DirectiveSink()` and pass `directive_sink=directive_sink` to EVERY `_build_application` call inside the chat path (initial build plus the rebuilds after `/models` changes). Do NOT pass it in `_run_gateway` or `_manage_automations` — those stay directive-free.

- [ ] **Step 2: Add the pure mapping helper**

Module-level in `cli/main.py`:

```python
def _directive_trigger_message(directive) -> str | None:
    if directive.kind == "channel_setup":
        verb = "reconnect" if directive.reconnect else "connect"
        return f"{verb} {directive.channel}"
    if directive.kind == "model_setup":
        return "connect model"
    return None
```

- [ ] **Step 3: Drain the sink after each model turn and re-enter the loop**

- At the top of the prompt loop, add synthetic-message support. Before the loop starts: `pending_trigger: str | None = None`. Where the loop currently reads input, change to:

```python
            if pending_trigger is not None:
                user_message = pending_trigger
                pending_trigger = None
            else:
                ... existing input_hint computation and chat_ui.read_message(...) try-block unchanged ...
```

(The hint computation stays inside the `else`; keep the existing exception handling untouched.)

- After the block that renders `application.send(...)`'s result (response panel + suggestion card), drain the sink:

```python
        directive = directive_sink.take()
        if directive is not None:
            if directive.kind == "automation_setup":
                language = "zh" if any("一" <= char <= "鿿" for char in user_message) else "en"
                application.record_capability_tried("scheduled_automations")
                automation_result = automation_workflow.start(
                    active_session_id, language, directive.prefill
                )
                for message in automation_result.messages:
                    chat_ui.assistant(message, "setup")
            else:
                pending_trigger = _directive_trigger_message(directive)
        continue
```

(Adapt to the loop's actual tail structure: the drain runs only on the model path — the branch where `application.send` was called — and `continue` is whatever the existing block ends with.)

- The synthetic `"connect telegram"` / `"reconnect telegram"` / `"connect model"` message re-enters the loop and hits the EXISTING trigger dispatch, reusing all the secret-input and selector interaction blocks unchanged. Note the quickfix guards are compatible by construction: `channel_connect` already refuses to emit a directive for an active channel unless `reconnect=true`, and `"reconnect <channel>"` passes `is_reconnect_request`.

- [ ] **Step 4: Unit tests**

Add to `tests/test_cli.py`:

```python
class DirectiveTriggerMessageTestCase(unittest.TestCase):
    def test_channel_setup_maps_to_connect_phrase(self) -> None:
        from allpath_agent.tools.assistant_directives import AssistantDirective
        from allpath_agent.cli.main import _directive_trigger_message

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
```

Also verify the gateway stays directive-free: add to the existing gateway tests (or a small new test) an assertion that a gateway-built application's registry does NOT contain `channel_connect` — if the existing test structure makes registry introspection impractical from outside, verify by code reading and say so in your report.

- [ ] **Step 5: Run the full suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS. The golden-path and demo tests must pass unmodified (triggers unchanged; directive tools only add capabilities).

```bash
git add src/allpath_agent/cli/main.py tests/test_cli.py
git commit -m "feat: route model directives into the deterministic guided flows"
```

---

### Task 4: ASK/CONNECT system prompt, docs, changelog

**Files:**
- Modify: `src/allpath_agent/application.py` (`ALLPATH_COMMANDS` content)
- Modify: `tests/test_agent_loop.py` (assertion update)
- Modify: `docs/NEXT_PHASE_PLAN.md`, `docs/AGENT_EVOLUTION_PLAN.md`, `CHANGELOG.md`

**Interfaces:** none new — text only. The constant stays static.

- [ ] **Step 1: Update the failing test first**

In `tests/test_agent_loop.py`, replace the body of `test_runtime_system_prompt_lists_allpath_flows` assertions with:

```python
        self.assertIn("channel_status", prompt)
        self.assertIn("channel_connect", prompt)
        self.assertIn("create_automation", prompt)
        self.assertIn("connect Telegram", prompt)
        self.assertIn("does not exist", prompt)
```

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_agent_loop -v` — Expected: the updated test FAILS.

- [ ] **Step 2: Replace the constant**

In `src/allpath_agent/application.py`, replace `ALLPATH_COMMANDS` with:

```python
ALLPATH_COMMANDS = (
    "Allpath routing rules: "
    "When the user asks ABOUT a messaging channel or its state, call channel_status — never guess "
    "and never start setup for a question. "
    "When the user asks to CONNECT a channel, call channel_connect right away; when they want a "
    "scheduled or recurring task, call create_automation and pass any name, task, schedule, or "
    "timezone you can extract from their request; when they want to add or replace a model "
    "connection, call connect_model. After any of these calls the host runs the guided flow — "
    "tell the user the questions come next and do not describe the steps yourself. "
    "If those tools are not available in this session, direct the user to type the exact phrase: "
    "“connect Telegram”, “connect Slack”, “connect WhatsApp”, “create automation” "
    "(or /automations add), or “connect a model”. "
    "Slash commands: /help, /model, /models, /route, /sessions, /connectors, /automations, "
    "/skills, /mcp, /browser, /capabilities, /dismiss. "
    "This list is not Allpath's complete capability set: never tell the user a capability "
    "does not exist without first checking channel_status, /help, or the skills index."
)
```

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_agent_loop -v` — Expected: PASS.

- [ ] **Step 3: Documentation**

- `docs/NEXT_PHASE_PLAN.md`: append a new section before "## Explicitly parked":

```markdown
## Milestone 4: Model-driven intent routing (shipped with this change)

Tool-capable models now route intent themselves: `channel_status` answers
channel state questions read-only; `channel_connect`, `create_automation`
(with validated prefill extracted from the request), and `connect_model` hand
off to the existing deterministic guided flows via side-effect-free
directives. Exact trigger phrases remain a deterministic fast path because
external-CLI providers (Claude Code and Codex account connections) do not
receive tool schemas. Directive tools are registered only in interactive chat
sessions, never in the gateway or unattended runs.
```

- `docs/AGENT_EVOLUTION_PLAN.md`: in Stage 5, append a bullet:

```markdown
- Route intent through model tools (`channel_status`, `channel_connect`, `create_automation`, `connect_model`) with deterministic trigger phrases retained as the fast path for providers without tool support. **Implemented.**
```

- `CHANGELOG.md` under `Unreleased` (create `### Added` above the existing `### Fixed`):

```markdown
### Added

- Added model-driven intent routing for tool-capable connections: a read-only `channel_status` tool for state questions, and side-effect-free `channel_connect`, `create_automation`, and `connect_model` directive tools that hand off to the existing guided flows; `create_automation` accepts validated name/prompt/schedule/timezone prefill extracted from the user's request so the guided flow only asks for what is missing.
- Kept exact trigger phrases as a deterministic fast path so account-auth (external-CLI) connections without tool support keep full setup access, and excluded directive tools from gateway and unattended sessions.
- Replaced the system-prompt command list with ASK-vs-CONNECT routing rules and a capability-verification rule so the model checks `channel_status` or /help before ever claiming a capability does not exist.
```

- [ ] **Step 4: Run the full suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add src/allpath_agent/application.py tests/test_agent_loop.py docs/NEXT_PHASE_PLAN.md docs/AGENT_EVOLUTION_PLAN.md CHANGELOG.md docs/superpowers/plans/2026-08-02-model-driven-intent.md
git commit -m "docs: teach ask-versus-connect routing in the static system prompt"
```

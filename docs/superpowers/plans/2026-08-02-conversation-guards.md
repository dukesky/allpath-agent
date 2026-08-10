# Conversation Guards Quick Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop connector-setup workflows from hijacking state questions, from re-teaching already-connected channels, and from trapping users mid-tutorial; teach the model what Allpath's conversational flows are so it redirects instead of claiming a capability is missing. (This is the deterministic quick fix; the model-driven intent routing is a separate upcoming milestone.)

**Architecture:** Three shared helpers land in `workflows/connector_onboarding.py` (the existing shared engine): `is_state_question`, `is_reconnect_request`, `connection_status_reply`. Each connector workflow's trigger branch consults them plus the already-injected `ConnectorConfigRepository` before starting a tutorial, and each workflow's fallback reminder gains a status line and an explicit cancel exit. A static `ALLPATH_COMMANDS` block joins the runtime system prompt.

**Tech Stack:** Python 3.11+ stdlib only. No schema changes, no new files.

## Global Constraints

- No third-party dependencies; `python3.12 scripts/run_tests.py` (default `python3` is 3.9 and cannot run this codebase) must pass at every commit.
- Every meaningful change updates `CHANGELOG.md` under `Unreleased`.
- User-facing quoted phrases use curly quotes (“ ”).
- The system-prompt addition must be STATIC text (identical every task) to stay prompt-cache friendly; no dynamic state may enter it.
- Behavior changes apply identically to Telegram, Slack, and WhatsApp workflows.
- `reconnect <channel>` (and 重新连接/重新配置/重连) must still start the tutorial even when the channel is active. Note `"reconnect telegram"` contains the substring `"connect"`, so the existing `_is_trigger` fires for it — no trigger change needed.

---

### Task 1: Connector workflow guards (status questions, already-active, mid-tutorial exit)

**Files:**
- Modify: `src/allpath_agent/workflows/connector_onboarding.py` (shared helpers)
- Modify: `src/allpath_agent/workflows/telegram_connection.py`
- Modify: `src/allpath_agent/workflows/slack_connection.py`
- Modify: `src/allpath_agent/workflows/whatsapp_connection.py`
- Test: `tests/test_telegram_workflow.py`, `tests/test_slack_workflow.py`, `tests/test_whatsapp_workflow.py`

**Interfaces:**
- Produces in `connector_onboarding.py`:
  - `is_state_question(message: str) -> bool`
  - `is_reconnect_request(message: str) -> bool`
  - `connection_status_reply(display_name: str, record: dict | None, language: str) -> str`
- Consumes: each workflow's existing `self._configs` (`ConnectorConfigRepository`, has `.get(connector_id) -> dict | None` with `status` and `detail` keys).

- [ ] **Step 1: Write the failing tests**

Read each of the three workflow test files first and match their fixture style (they construct the workflow with a temp `Database`, `WorkflowRunRepository`, `SecretStore`, `ConnectorConfigRepository`, and a fake verifier). Add to `tests/test_telegram_workflow.py` (adapting constructor calls to the file's fixtures; `self.configs` below means the test's `ConnectorConfigRepository`):

```python
    def test_state_question_returns_status_instead_of_tutorial(self) -> None:
        result = self.workflow.handle("session-1", "have we connect telegram right now?")

        self.assertTrue(result.handled)
        self.assertIn("not connected", "\n".join(result.messages).lower())
        self.assertFalse(self.workflow.active("session-1"))

    def test_chinese_state_question_reports_active_connection(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self.workflow.handle("session-1", "你看看我现在连接telegram了吗")

        self.assertTrue(result.handled)
        self.assertIn("已连接", "\n".join(result.messages))
        self.assertIn("@my_bot", "\n".join(result.messages))
        self.assertFalse(self.workflow.active("session-1"))

    def test_trigger_with_active_connection_reports_status_not_tutorial(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self.workflow.handle("session-1", "connect telegram")

        self.assertTrue(result.handled)
        self.assertIn("@my_bot", "\n".join(result.messages))
        self.assertFalse(self.workflow.active("session-1"))

    def test_reconnect_starts_tutorial_despite_active_connection(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self.workflow.handle("session-1", "reconnect telegram")

        self.assertTrue(result.handled)
        self.assertTrue(self.workflow.active("session-1"))

    def test_mid_tutorial_question_mentions_cancel_and_status(self) -> None:
        self.workflow.handle("session-1", "connect telegram")

        result = self.workflow.handle("session-1", "你看看我连了吗，连了就不用继续了")

        text = "\n".join(result.messages)
        self.assertIn("取消", text)
        self.assertIn("未连接", text)
        self.assertTrue(self.workflow.active("session-1"))
```

Add the equivalent two most important cases to `tests/test_slack_workflow.py` and `tests/test_whatsapp_workflow.py` (state question → status without tutorial; trigger while active → status without tutorial), using each file's fixture style and connector id (`slack` / `whatsapp`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_telegram_workflow tests.test_slack_workflow tests.test_whatsapp_workflow -v`
Expected: the new tests FAIL (state question currently starts the tutorial; active connection currently re-teaches; reminder lacks the status line).

- [ ] **Step 3: Add the shared helpers**

In `src/allpath_agent/workflows/connector_onboarding.py`, append:

```python
_STATE_QUESTION_MARKERS = ("吗", "是否", "有没有", "了没")
_STATE_QUESTION_PREFIXES = (
    "have ", "has ", "did ", "is ", "are ", "was ", "were ", "am ",
)


def is_state_question(message: str) -> bool:
    stripped = message.strip()
    if any(marker in stripped for marker in _STATE_QUESTION_MARKERS):
        return True
    lowered = stripped.lower()
    if lowered.startswith(_STATE_QUESTION_PREFIXES):
        return True
    return "already" in lowered


def is_reconnect_request(message: str) -> bool:
    lowered = message.lower()
    if "reconnect" in lowered:
        return True
    return any(phrase in message for phrase in ("重新连接", "重新配置", "重连"))


def connection_status_reply(display_name: str, record: dict | None, language: str) -> str:
    connected = record is not None and record.get("status") == "active"
    if language == "zh":
        if connected:
            return (
                f"{display_name} 已连接（{record['detail']}）。"
                f"要重新配置请说“reconnect {display_name}”。"
            )
        return f"{display_name} 尚未连接。说“connect {display_name}”开始配置。"
    if connected:
        return (
            f"{display_name} is connected ({record['detail']}). "
            f"Say “reconnect {display_name}” to reconfigure."
        )
    return f"{display_name} is not connected yet. Say “connect {display_name}” to set it up."
```

- [ ] **Step 4: Guard each workflow's trigger branch and enrich its reminder**

In `src/allpath_agent/workflows/telegram_connection.py`, import the helpers:

```python
from .connector_onboarding import (
    ConnectorOnboardingGuide,
    OnboardingStep,
    connection_status_reply,
    is_reconnect_request,
    is_state_question,
)
```

Replace the trigger branch of `handle()` (`if active is None:` block) with:

```python
        if active is None:
            if not _is_trigger(cleaned):
                return ConnectionFlowResult(False)
            language = "zh" if any("一" <= char <= "鿿" for char in cleaned) else "en"
            record = self._configs.get("telegram")
            already_active = record is not None and record["status"] == "active"
            if is_state_question(cleaned) or (already_active and not is_reconnect_request(cleaned)):
                return ConnectionFlowResult(
                    True,
                    (connection_status_reply("Telegram", record, language),),
                )
            first_step = GUIDE.first_id()
            self._runs.create(WORKFLOW_ID, session_id, first_step, {"language": language})
            return ConnectionFlowResult(True, (GUIDE.render(first_step, language),))
```

Replace the fallback reminder (currently lines 134-135):

```python
        record = self._configs.get("telegram")
        connected = record is not None and record["status"] == "active"
        if language == "zh":
            status_line = "Telegram 当前已连接。" if connected else "Telegram 当前未连接。"
            reminder = (
                f"{status_line}教程进行中：完成当前步骤后输入“继续”，"
                "或输入“返回”“状态”查看；输入“取消”可随时退出教程并恢复正常对话。"
            )
        else:
            status_line = "Telegram is currently connected." if connected else "Telegram is not connected yet."
            reminder = (
                f"{status_line} Tutorial in progress: finish the current step and type “continue”, "
                "or use “back”/“status”; type “cancel” anytime to leave the tutorial and chat normally."
            )
        return ConnectionFlowResult(True, (reminder,))
```

Apply the SAME two changes to `slack_connection.py` and `whatsapp_connection.py`, with these local adaptations only:
- connector id `"slack"` / `"whatsapp"`; display name `"Slack"` / `"WhatsApp"`;
- those two workflows compute `cleaned` AFTER the trigger branch — use the raw `message` for `_is_trigger`/`is_state_question`/`is_reconnect_request` there, matching each file's existing structure;
- each file's reminder location (slack ~lines 187-192, whatsapp ~lines 222-223) gets the same status+cancel template with its own display name.

- [ ] **Step 5: Run the three workflow suites, then the full suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_telegram_workflow tests.test_slack_workflow tests.test_whatsapp_workflow -v` — Expected: PASS.
Run: `python3.12 scripts/run_tests.py` — Expected: PASS. If any existing CLI test drove a setup flow with a message the new guards now intercept (e.g. a test typing “connect telegram” after activating it), read the failure and update that test's expectation to the new status reply — the behavior change is intended; note every such update in your report.

- [ ] **Step 6: Commit**

```bash
git add src/allpath_agent/workflows/connector_onboarding.py src/allpath_agent/workflows/telegram_connection.py src/allpath_agent/workflows/slack_connection.py src/allpath_agent/workflows/whatsapp_connection.py tests/test_telegram_workflow.py tests/test_slack_workflow.py tests/test_whatsapp_workflow.py
git commit -m "fix: answer connector state questions instead of hijacking them into tutorials"
```

---

### Task 2: Teach the model Allpath's conversational commands

**Files:**
- Modify: `src/allpath_agent/application.py`
- Modify: `CHANGELOG.md`
- Test: `tests/test_agent_loop.py` (it already imports `_runtime_system_prompt`)

**Interfaces:**
- Produces: module constant `ALLPATH_COMMANDS: str` in `application.py`, appended inside `_runtime_system_prompt` (static — identical for every task and profile).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_loop.py` (match its existing `_runtime_system_prompt` test style — read the file's existing usage first; it constructs a `ModelProfile`):

```python
    def test_runtime_system_prompt_lists_allpath_flows(self) -> None:
        prompt = _runtime_system_prompt("base", ModelProfile("fast", "m", quality=1, cost=1))

        self.assertIn("connect Telegram", prompt)
        self.assertIn("create automation", prompt)
        self.assertIn("/automations", prompt)
        self.assertIn("do not claim it is unavailable", prompt)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_agent_loop -v`
Expected: the new test FAILS (`'connect Telegram' not found`).

- [ ] **Step 3: Implement**

In `src/allpath_agent/application.py`, add near the top (below imports):

```python
ALLPATH_COMMANDS = (
    "Allpath built-in conversational flows (handled by deterministic code outside this model): "
    "“connect a model” configures a model provider; “connect Telegram”, “connect Slack”, and "
    "“connect WhatsApp” run guided messaging-channel setup; “create automation” (or /automations add) "
    "schedules one-time or recurring jobs with optional delivery to a connected channel; "
    "“setup browser” prepares the structured browser. "
    "Slash commands: /help, /model, /models, /route, /sessions, /connectors, /automations, /skills, "
    "/mcp, /browser, /capabilities, /dismiss. "
    "When the user wants one of these capabilities, do not claim it is unavailable — reply with the exact "
    "phrase or command to type."
)
```

In `_runtime_system_prompt`, append it to the returned string:

```python
    return (
        f"{system_prompt}\n\n"
        "Runtime identity (authoritative): "
        f"role={profile.name}, provider={profile.provider}, model={profile.model}. "
        f"{tool_access}{external_boundary} "
        "When asked which model or permissions are active, report these exact values and do not guess.\n\n"
        f"{ALLPATH_COMMANDS}"
    )
```

- [ ] **Step 4: Update CHANGELOG**

Under `## Unreleased`, add (create the `### Fixed` subsection if absent):

```markdown
### Fixed

- Answered connector state questions (“have we connected Telegram?” / “连了吗”) with the actual connection status instead of hijacking them into the setup tutorial, and stopped re-teaching channels that are already connected unless the user says “reconnect”.
- Gave mid-tutorial replies a current-status line and an explicit “cancel” exit so users are never trapped in a setup flow.
- Listed Allpath's built-in conversational flows and slash commands in the static system prompt so the model directs users to the exact phrase instead of claiming the capability is unavailable.
```

- [ ] **Step 5: Run the full suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add src/allpath_agent/application.py tests/test_agent_loop.py CHANGELOG.md docs/superpowers/plans/2026-08-02-conversation-guards.md
git commit -m "feat: teach the model Allpath's conversational flows in the static system prompt"
```

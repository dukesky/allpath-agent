# Onboarding Funnel Completion (Milestone 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all three curriculum teaching surfaces (launch card, composer hint, post-task tip) actually reachable, fix the browser evidence gap, add missing tests for intent/evidence detection, and correct stale documentation.

**Architecture:** All hint selection lives in `cli/banner.py` as a pure function `next_capability_hint()` shared by the launch card and the composer. Curriculum state continues to flow through the existing `application.capability_progress()` list of `(capability_id, title, status)` tuples — no storage or engine changes. Evidence fixes are additive entries in `application.py`'s tool map.

**Tech Stack:** Python 3.11+ stdlib only, `unittest`, existing SQLite repositories. No new dependencies.

## Global Constraints

- No third-party dependencies may be added (`pyproject.toml` deps stay unchanged).
- Every meaningful change updates `CHANGELOG.md` under `Unreleased`.
- Full validation is `python3 scripts/run_tests.py` (compiles all sources, then runs the unittest suite). It must pass at every commit.
- Curriculum state must never be injected into the model system prompt (existing invariant).
- Statuses that mean "do not teach this" are exactly: `succeeded`, `habitual`, `dismissed`, `unavailable`.
- Tests are stdlib `unittest` classes, `test_*` methods, `from __future__ import annotations` at top, matching existing files.

---

### Task 1: Curriculum-driven launch hint (`next_capability_hint`)

The launch card currently early-returns "Next: connect Telegram / Slack / WhatsApp" until ALL three connectors are active (`banner.py:65-73`), so curriculum hints are unreachable for real users. Replace the three early returns with one shared hint selector: messaging is suggested first while NO connector is configured (and not dismissed); ONE active connector satisfies it; after that, hints advance through the capability list.

**Files:**
- Modify: `src/allpath_agent/cli/banner.py`
- Test: `tests/test_banner.py`

**Interfaces:**
- Produces: `next_capability_hint(capability_progress: Iterable[tuple[str, str, str]], *, configured_connectors: Iterable[str] = ()) -> str | None` — returns the hint string for the first unlearned capability in `HINT_ORDER`, or `None` when everything is learned/dismissed/unavailable. Task 2 imports this from `allpath_agent.cli.banner`.
- Produces: `HINT_ORDER: tuple[str, ...]` module constant (exported for the coverage test).
- `launch_lines()` signature is unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_banner.py`, update the import line to:

```python
from allpath_agent.cli.banner import CAPABILITY_HINTS, HINT_ORDER, launch_lines, next_capability_hint
```

Delete these three tests (their semantics — demanding all three platforms in sequence — are the bug):
- `test_live_banner_prioritizes_telegram_before_advanced_lessons`
- `test_live_banner_prioritizes_slack_after_telegram`
- `test_live_banner_prioritizes_whatsapp_after_slack`

Add in their place:

```python
    def test_live_banner_suggests_one_messaging_channel_when_none_configured(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-789",
                configured_roles=("standard",),
            )
        )

        self.assertIn("Next: Connect a messaging channel", text)
        self.assertNotIn("remember that I prefer", text)

    def test_live_banner_advances_to_capability_lessons_after_one_connector(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-one-connector",
                configured_roles=("standard",),
                configured_connectors=("telegram",),
            )
        )

        self.assertIn("remember that I prefer concise answers", text)
        self.assertNotIn("connect Slack", text)
        self.assertNotIn("connect WhatsApp", text)

    def test_live_banner_skips_messaging_after_dismissal(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-dismissed",
                configured_roles=("standard",),
                capability_progress=(
                    ("messaging_connectors", "Messaging connectors", "dismissed"),
                ),
            )
        )

        self.assertIn("remember that I prefer concise answers", text)
        self.assertNotIn("messaging channel", text)

    def test_next_capability_hint_skips_unavailable_and_exhausts_to_none(self) -> None:
        suppressed = [
            (capability_id, capability_id, "unavailable") for capability_id in HINT_ORDER
        ]
        self.assertIsNone(next_capability_hint(suppressed))

        learned = [
            (capability_id, capability_id, "habitual") for capability_id in HINT_ORDER
        ]
        self.assertIsNone(next_capability_hint(learned, configured_connectors=("telegram",)))

    def test_banner_falls_back_to_capabilities_when_everything_is_learned(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-done",
                configured_roles=("standard",),
                configured_connectors=("telegram",),
                capability_progress=tuple(
                    (capability_id, capability_id, "habitual") for capability_id in HINT_ORDER
                ),
            )
        )

        self.assertIn("Next: Explore: /capabilities", text)

    def test_hint_order_covers_every_capability_hint(self) -> None:
        self.assertEqual(set(HINT_ORDER), set(CAPABILITY_HINTS))
```

Keep `test_starter_banner_prioritizes_conversation_first_setup` and `test_live_banner_shows_models_and_next_unlearned_capability` unchanged — they must still pass after the rewrite.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_banner -v`
Expected: FAIL — `ImportError: cannot import name 'HINT_ORDER'`.

- [ ] **Step 3: Implement the hint selector and rewrite the live branch**

In `src/allpath_agent/cli/banner.py`, change the `messaging_connectors` hint text (the old text produced an awkward "Next: Connect: …" line):

```python
    "messaging_connectors": "Connect a messaging channel: try “connect Telegram”",
```

Below `CAPABILITY_HINTS`, add:

```python
HINT_ORDER = (
    "messaging_connectors",
    "durable_memory",
    "current_time",
    "session_management",
    "model_routing",
    "tool_approvals",
    "live_provider",
    "scheduled_automations",
    "workspace_files",
    "terminal_tasks",
    "skills",
    "mcp_tools",
    "browser_tasks",
)

_LEARNED_STATUSES = frozenset({"succeeded", "habitual", "dismissed", "unavailable"})


def next_capability_hint(
    capability_progress: Iterable[tuple[str, str, str]],
    *,
    configured_connectors: Iterable[str] = (),
) -> str | None:
    statuses = {capability_id: status for capability_id, _, status in capability_progress}
    if tuple(configured_connectors):
        statuses["messaging_connectors"] = "succeeded"
    for capability_id in HINT_ORDER:
        if statuses.get(capability_id, "unseen") not in _LEARNED_STATUSES:
            return CAPABILITY_HINTS[capability_id]
    return None
```

Replace everything in `launch_lines` from `if "telegram" not in set(configured_connectors):` down to the final `return tuple(lines)` (the old lines 65-84) with:

```python
    hint = next_capability_hint(
        capability_progress,
        configured_connectors=configured_connectors,
    )
    lines.append(f"  Next: {hint if hint is not None else 'Explore: /capabilities'}")
    return tuple(lines)
```

- [ ] **Step 4: Run banner tests, then the full suite**

Run: `PYTHONPATH=src python3 -m unittest tests.test_banner -v`
Expected: PASS (all tests).

Run: `python3 scripts/run_tests.py`
Expected: PASS. If any `tests/test_cli.py` assertion still expects the old "Next: connect Telegram" launch text, update that assertion to match the new messaging hint — the CLI behavior change is intended.

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/cli/banner.py tests/test_banner.py tests/test_cli.py
git commit -m "fix: drive the launch card from curriculum state"
```

---

### Task 2: Curriculum-driven composer hint

The composer hint (`cli/main.py:255-263`) only serves setup workflows plus one hardcoded starter line; the evolution plan's second teaching surface was never wired. Show the next-capability hint whenever live mode is idle (no workflow needs input). Connector state must be read fresh each prompt so the hint advances immediately after a mid-session `connect Telegram`.

**Files:**
- Modify: `src/allpath_agent/cli/main.py`
- Test: selection logic is already unit-tested in Task 1's `tests/test_banner.py`; this task is thin glue verified by the full suite (Step 3) and a demo-mode manual check (Step 4). Only adjust existing `tests/test_cli.py` assertions if exact-output comparisons break.

**Interfaces:**
- Consumes: `next_capability_hint(...)` and `HINT_ORDER` from Task 1.
- Produces: `_active_connector_ids(database: Database) -> tuple[str, ...]` module-level helper in `cli/main.py`.

- [ ] **Step 1: Extract the active-connector helper**

In `src/allpath_agent/cli/main.py`, add a module-level function next to the other `_`-prefixed helpers:

```python
def _active_connector_ids(database: Database) -> tuple[str, ...]:
    return tuple(
        record["connector_id"]
        for record in ConnectorConfigRepository(database).list_all()
        if record["status"] == "active"
    )
```

Replace the startup computation (currently at lines 238-242):

```python
        configured_connectors = tuple(
            record["connector_id"]
            for record in ConnectorConfigRepository(database).list_all()
            if record["status"] == "active"
        )
```

with:

```python
        configured_connectors = _active_connector_ids(database)
```

- [ ] **Step 2: Wire the composer hint**

Update the import at the top of `cli/main.py` from:

```python
from .banner import launch_lines
```

to:

```python
from .banner import launch_lines, next_capability_hint
```

In the prompt loop, after the `telegram_workflow.input_hint(...)` fallback and BEFORE the starter-mode fallback, insert the live-mode curriculum hint so the block reads:

```python
            input_hint = connection_workflow.input_hint(active_session_id)
            if input_hint is None:
                input_hint = slack_workflow.input_hint(active_session_id)
            if input_hint is None:
                input_hint = whatsapp_workflow.input_hint(active_session_id)
            if input_hint is None:
                input_hint = telegram_workflow.input_hint(active_session_id)
            if input_hint is None and live_mode:
                input_hint = next_capability_hint(
                    application.capability_progress(),
                    configured_connectors=_active_connector_ids(database),
                )
            if input_hint is None and not live_mode:
                input_hint = "Try: 连接模型 · connect Telegram · what can you do"
            user_message = chat_ui.read_message(input_hint)
```

- [ ] **Step 3: Run the full suite**

Run: `python3 scripts/run_tests.py`
Expected: PASS. Demo-mode CLI tests must be unaffected (the new branch is `live_mode` only). If a live-mode CLI test (e.g. the fake Claude Code connection test in `tests/test_cli.py`) now shows a hint line in its stdout, adjust only assertions that use exact-output equality; substring assertions should be unaffected.

- [ ] **Step 4: Manual verification of both modes**

Run: `printf 'hello\n/exit\n' | python3 -m allpath_agent.cli.main --demo 2>/dev/null || printf 'hello\n/exit\n' | allpath-agent --demo`
Expected: starter hint line still shows `Try: 连接模型 · connect Telegram · what can you do`; no crash.

(Live-mode hint rendering is covered by the unit-tested selector; a full live-mode PTY check happens in the milestone smoke test.)

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/cli/main.py tests/test_cli.py
git commit -m "feat: show curriculum-driven composer hints in live mode"
```

---

### Task 3: Browser evidence gap and missing intent/evidence tests

`_task_evidence` (`application.py:114-145`) omits `browser_screenshot` and `browser_download`, so screenshot/download-only browser tasks never count as `browser_tasks` success. `detect_intents` and `_task_evidence` — the two deterministic inputs that drive all curriculum progress — have no direct tests.

**Files:**
- Modify: `src/allpath_agent/application.py`
- Create: `tests/test_application.py`

**Interfaces:**
- Consumes: `AgentApplication`, `detect_intents` from `allpath_agent.application`; `Database`, `ToolExecutionRepository`, `ToolApprovalRepository` from `allpath_agent.storage`.
- Produces: no new public interfaces — two new entries in the private `tool_capabilities` map.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_application.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.application import AgentApplication, detect_intents
from allpath_agent.storage import (
    Database,
    ToolApprovalRepository,
    ToolExecutionRepository,
)


class DetectIntentsTestCase(unittest.TestCase):
    def test_plain_greeting_carries_only_chat_intent(self) -> None:
        self.assertEqual(detect_intents("hello"), {"chat"})

    def test_detects_english_intents(self) -> None:
        self.assertIn("time", detect_intents("what date is it today?"))
        self.assertIn("automation", detect_intents("create a cron job for me"))
        self.assertIn("workspace", detect_intents("search files for TODO"))

    def test_detects_chinese_intents(self) -> None:
        self.assertIn("memory", detect_intents("记住我喜欢简洁的回答"))
        self.assertIn("browser", detect_intents("帮我打开网站看看"))
        self.assertIn("terminal", detect_intents("帮我运行测试"))

    def test_one_message_can_carry_multiple_intents(self) -> None:
        intents = detect_intents("remember to calculate my time budget")
        self.assertLessEqual({"chat", "memory", "calculation", "time"}, intents)


class TaskEvidenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.tool_executions = ToolExecutionRepository(self.database)
        self.approvals = ToolApprovalRepository(self.database)
        self.application = AgentApplication(
            loop=None,
            router=None,
            routing_decisions=None,
            tool_executions=self.tool_executions,
            approvals=self.approvals,
            curriculum=None,
            system_prompt="",
            live_provider=True,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _finish_tool(self, tool_name: str, status: str = "succeeded") -> None:
        execution_id = self.tool_executions.start("session-1", "task-1", tool_name, {})
        self.tool_executions.finish(execution_id, status, {"ok": True})

    def test_browser_screenshot_counts_as_browser_evidence(self) -> None:
        self._finish_tool("browser_screenshot")

        evidence = self.application._task_evidence("session-1", "task-1", "fast")

        self.assertIn("browser_tasks", evidence)

    def test_browser_download_counts_as_browser_evidence(self) -> None:
        self._finish_tool("browser_download")

        evidence = self.application._task_evidence("session-1", "task-1", "fast")

        self.assertIn("browser_tasks", evidence)

    def test_failed_tools_produce_no_capability_evidence(self) -> None:
        self._finish_tool("browser_screenshot", status="failed")

        evidence = self.application._task_evidence("session-1", "task-1", "fast")

        self.assertNotIn("browser_tasks", evidence)

    def test_advanced_profile_mcp_and_approvals_evidence(self) -> None:
        self._finish_tool("mcp__github__search")
        self.approvals.record("session-1", "task-1", "memory_set", {}, "allowed")

        evidence = self.application._task_evidence("session-1", "task-1", "advanced")

        self.assertEqual(
            {"basic_chat", "live_provider", "model_routing", "mcp_tools", "tool_approvals"},
            evidence,
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify the browser cases fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_application -v`
Expected: `test_browser_screenshot_counts_as_browser_evidence` and `test_browser_download_counts_as_browser_evidence` FAIL with `AssertionError: 'browser_tasks' not found`; all other tests PASS (they document existing behavior).

- [ ] **Step 3: Add the two missing map entries**

In `src/allpath_agent/application.py`, inside `_task_evidence`'s `tool_capabilities` dict, after `"browser_type": "browser_tasks",` add:

```python
            "browser_screenshot": "browser_tasks",
            "browser_download": "browser_tasks",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.test_application -v`
Expected: PASS (all).

Run: `python3 scripts/run_tests.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/application.py tests/test_application.py
git commit -m "fix: count browser artifacts as curriculum evidence and test intent detection"
```

---

### Task 4: Correct stale documentation and update the changelog

Three documents contradict the shipped code (the structured browser exists; WeChat does not). Fix them and record this milestone under `Unreleased`.

**Files:**
- Modify: `docs/BROWSER_COMPUTER_BOUNDARY.md`
- Modify: `docs/AGENT_EVOLUTION_PLAN.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update `docs/BROWSER_COMPUTER_BOUNDARY.md`**

Replace line 3:

```markdown
Allpath does not currently expose raw browser or desktop control. This is intentional, not an unfinished hidden feature.
```

with:

```markdown
Allpath ships a structured, approval-gated browser (see [Browser](BROWSER.md)): isolated profile, public-network URL enforcement, bounded snapshots with stable element references, and controlled screenshots and downloads. Raw pixel-level browser control and desktop computer use remain intentionally unexposed.
```

Replace the "Browser implementation gate" section body (line 7) with:

```markdown
The shipped browser satisfies this gate: structured navigation, snapshots, stable element references, approval-gated click/type actions, bounded downloads and screenshots in private fixed directories, and repeated public-URL validation on navigation, redirects, and subresource requests. Form submission, authentication, purchases, external communication, and destructive actions remain approval-gated through the standard side-effect boundary.
```

- [ ] **Step 2: Update `docs/AGENT_EVOLUTION_PLAN.md` Stage 6**

Replace lines 84-85:

```markdown
- Add structured browser navigation, snapshots, element actions, and form approvals before raw desktop control. **Safety contract documented; implementation deferred.**
- Add computer use last, disabled by default and preferably isolated from the user's primary desktop. **Safety contract documented; implementation deferred.**
```

with:

```markdown
- Add structured browser navigation, snapshots, element actions, and form approvals before raw desktop control. **Implemented: isolated profile, public-URL enforcement, stable element refs, approval-gated actions, controlled screenshots and downloads.**
- Add computer use last, disabled by default and preferably isolated from the user's primary desktop. **Safety contract documented; implementation deferred.**
```

- [ ] **Step 3: Remove WeChat from the README onboarding sequence**

In `README.md` line 20, replace:

```markdown
such as Telegram, Slack, WhatsApp, or WeChat, then recurring automations. The
```

with:

```markdown
such as Telegram, Slack, or WhatsApp, then recurring automations. The
```

- [ ] **Step 4: Record the milestone in `CHANGELOG.md`**

Under `## Unreleased` / `### Added`, the browser entries already exist. Add a new `### Fixed` subsection directly after the `Unreleased` `### Added` block:

```markdown
### Fixed

- Made the live launch card curriculum-driven: one active messaging connector (or an explicit dismissal) advances startup guidance to the next unlearned capability instead of demanding all three platforms.
- Connected the composer hint to curriculum state so idle live sessions suggest the next unlearned capability action.
- Counted successful browser screenshots and downloads as `browser_tasks` curriculum evidence.
- Corrected stale browser-status statements in the boundary and evolution documents and removed the unshipped WeChat mention from the README onboarding sequence.
```

- [ ] **Step 5: Run the full suite and commit**

Run: `python3 scripts/run_tests.py`
Expected: PASS.

```bash
git add docs/BROWSER_COMPUTER_BOUNDARY.md docs/AGENT_EVOLUTION_PLAN.md README.md CHANGELOG.md docs/NEXT_PHASE_PLAN.md docs/superpowers/plans/2026-08-02-onboarding-funnel-completion.md
git commit -m "docs: refresh browser status, onboarding sequence, and next phase plan"
```

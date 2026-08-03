# The Golden Path (Milestone 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the end-to-end golden path — a read-only `web_lookup` tool, a daily-briefing curriculum destination after a messaging connector succeeds, a deterministic fake-transport integration test of install→model→Telegram→briefing→delivery, plus the Milestone 2 follow-up fixes (curriculum pollution from unattended runs, robustness hardening).

**Architecture:** `web_lookup` is a stdlib urllib tool in a new `tools/web.py`, reusing `validate_public_url` from `tools/browser.py` (importable without Playwright) and re-validating every redirect hop; text extraction uses `html.parser`. Unattended automation runs pass `record_curriculum=False` through `AgentApplication.send` so phantom curriculum offers stop. `daily_briefing` becomes the sixteenth capability, evidenced deterministically when the creation workflow saves a cron job with a destination. The golden-path test drives the real CLI (subprocess for the chat phase with the existing fake-claude harness; in-process `main()` with a patched `TelegramConnector` for the tick phase).

**Tech Stack:** Python 3.11+ stdlib only. No schema changes.

## Global Constraints

- No third-party dependencies (`pyproject.toml` unchanged).
- Every meaningful change updates `CHANGELOG.md` under `Unreleased`.
- Full validation `python3.12 scripts/run_tests.py` (default `python3` on this machine is 3.9 and cannot run the codebase) must pass at every commit.
- Curriculum state never enters the model system prompt.
- `web_lookup` is READ_ONLY risk, refuses non-public addresses at the initial URL and at every redirect hop, caps body reads at 512000 bytes and returned content at 8000 characters, and never executes page scripts.
- Unattended automation execution must not write curriculum progress or suggestions (`record_curriculum=False`); interactive chat and connector conversations keep recording.
- Tests are stdlib `unittest`, `from __future__ import annotations` at top.
- User-facing quoted phrases in lesson/hint/prompt strings use curly quotes (“ ”).

---

### Task 1: `web_lookup` read-only tool

**Files:**
- Create: `src/allpath_agent/tools/web.py`
- Modify: `src/allpath_agent/tools/builtin.py` (register unconditionally)
- Test: `tests/test_web_lookup.py` (new)

**Interfaces:**
- Produces: `register_web_tools(registry: ToolRegistry, fetch: Fetcher | None = None)` where `Fetcher = Callable[[str], tuple[int, str, bytes, str]]` returning `(status, content_type, body, final_url)`. Default fetcher `_http_fetch` uses urllib with redirect re-validation.
- Tool result shape (Tasks 3/5 reference it in copy): `{"url", "title", "content", "content_truncated", "status"}`.
- Reuses `validate_public_url`, `BrowserAccessError` from `tools.browser` (module imports Playwright inside try/except, so this import is safe without Playwright).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_lookup.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import patch

from allpath_agent.tools.registry import ToolRegistry, ToolRisk
from allpath_agent.tools.web import (
    MAX_CONTENT_CHARS,
    _RedirectValidator,
    _extract_html_text,
    register_web_tools,
)


def _registry_with_fake(responses):
    registry = ToolRegistry()

    def fetch(url):
        return responses[url]

    register_web_tools(registry, fetch=fetch)
    return registry


def _call(registry, url):
    return registry.get("web_lookup").handler({"url": url})


class WebLookupTestCase(unittest.TestCase):
    def test_tool_is_read_only(self) -> None:
        registry = _registry_with_fake({})
        self.assertIs(registry.get("web_lookup").risk, ToolRisk.READ_ONLY)

    def test_html_page_returns_title_and_text(self) -> None:
        body = (
            b"<html><head><title>Weather Today</title>"
            b"<style>p{color:red}</style><script>alert(1)</script></head>"
            b"<body><h1>Forecast</h1><p>Sunny, 24 degrees.</p></body></html>"
        )
        registry = _registry_with_fake(
            {"https://example.com/weather": (200, "text/html; charset=utf-8", body, "https://example.com/weather")}
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            result = _call(registry, "https://example.com/weather")

        self.assertEqual(result["status"], 200)
        self.assertEqual(result["title"], "Weather Today")
        self.assertIn("Sunny, 24 degrees.", result["content"])
        self.assertNotIn("alert(1)", result["content"])
        self.assertNotIn("color:red", result["content"])
        self.assertFalse(result["content_truncated"])

    def test_long_content_is_truncated(self) -> None:
        body = b"<html><body>" + b"<p>word</p>" * 5000 + b"</body></html>"
        registry = _registry_with_fake(
            {"https://example.com/big": (200, "text/html", body, "https://example.com/big")}
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            result = _call(registry, "https://example.com/big")

        self.assertTrue(result["content_truncated"])
        self.assertLessEqual(len(result["content"]), MAX_CONTENT_CHARS)

    def test_plain_text_and_json_pass_through(self) -> None:
        registry = _registry_with_fake(
            {"https://example.com/data.json": (200, "application/json", b'{"ok": true}', "https://example.com/data.json")}
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            result = _call(registry, "https://example.com/data.json")

        self.assertEqual(result["content"], '{"ok": true}')
        self.assertIsNone(result["title"])

    def test_binary_content_type_is_rejected(self) -> None:
        registry = _registry_with_fake(
            {"https://example.com/app.zip": (200, "application/zip", b"PK", "https://example.com/app.zip")}
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            with self.assertRaisesRegex(ValueError, "content type"):
                _call(registry, "https://example.com/app.zip")

    def test_local_url_is_rejected_before_fetch(self) -> None:
        calls = []

        def fetch(url):
            calls.append(url)
            raise AssertionError("fetch must not run for rejected URLs")

        registry = ToolRegistry()
        register_web_tools(registry, fetch=fetch)

        with self.assertRaises(ValueError):
            registry.get("web_lookup").handler({"url": "http://localhost:8000/admin"})
        self.assertEqual(calls, [])

    def test_redirect_targets_are_revalidated(self) -> None:
        recorded = []

        def failing_validate(url):
            recorded.append(url)
            raise ValueError("private redirect target")

        validator = _RedirectValidator()
        with patch("allpath_agent.tools.web.validate_public_url", side_effect=failing_validate):
            with self.assertRaisesRegex(ValueError, "private redirect target"):
                validator.redirect_request(
                    None, None, 302, "Found", {}, "http://192.168.0.1/internal"
                )
        self.assertEqual(recorded, ["http://192.168.0.1/internal"])

    def test_extractor_collapses_whitespace(self) -> None:
        title, text = _extract_html_text("<body><p>a\n\n   b</p><div>c</div></body>")
        self.assertIsNone(title)
        self.assertEqual(text, "a b c")


if __name__ == "__main__":
    unittest.main()
```

Note: the `_call` helper assumes `ToolRegistry.get(name)` returns the `ToolDefinition`. Read `src/allpath_agent/tools/registry.py` first — if the lookup method is named differently, adapt the helper (and only the helper) to the real API.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_web_lookup -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'allpath_agent.tools.web'`.

- [ ] **Step 3: Implement the module**

Create `src/allpath_agent/tools/web.py`:

```python
from __future__ import annotations

import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser

from .browser import BrowserAccessError, validate_public_url
from .registry import ToolDefinition, ToolRegistry

MAX_BODY_BYTES = 512_000
MAX_CONTENT_CHARS = 8_000
FETCH_TIMEOUT_SECONDS = 20.0
_TEXT_CONTENT_PREFIXES = ("text/",)
_TEXT_CONTENT_TYPES = ("application/json", "application/xhtml+xml", "application/xml")
_SKIPPED_ELEMENTS = {"script", "style", "noscript", "template"}

Fetcher = Callable[[str], tuple[int, str, bytes, str]]


class _RedirectValidator(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            validate_public_url(newurl)
        except BrowserAccessError as error:
            raise ValueError(str(error)) from error
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._title_chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED_ELEMENTS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in _SKIPPED_ELEMENTS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self._title_chunks.append(data)
            return
        if data.strip():
            self._chunks.append(data)

    @property
    def title(self) -> str | None:
        title = " ".join(" ".join(self._title_chunks).split())
        return title or None

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._chunks).split())


def _extract_html_text(markup: str) -> tuple[str | None, str]:
    extractor = _TextExtractor()
    extractor.feed(markup)
    return extractor.title, extractor.text


def _http_fetch(url: str) -> tuple[int, str, bytes, str]:
    opener = urllib.request.build_opener(_RedirectValidator())
    request = urllib.request.Request(url, headers={"User-Agent": "AllpathAgent/1.0"})
    with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(MAX_BODY_BYTES + 1)
        content_type = response.headers.get("Content-Type", "")
        return response.status, content_type, body, response.geturl()


def register_web_tools(registry: ToolRegistry, fetch: Fetcher | None = None) -> None:
    fetch_fn = fetch or _http_fetch

    def _web_lookup(arguments: dict) -> dict:
        url = arguments["url"].strip()
        try:
            validate_public_url(url)
        except BrowserAccessError as error:
            raise ValueError(str(error)) from error
        status, content_type, body, final_url = fetch_fn(url)
        media_type = content_type.split(";", 1)[0].strip().lower()
        if not (
            media_type.startswith(_TEXT_CONTENT_PREFIXES)
            or media_type in _TEXT_CONTENT_TYPES
        ):
            raise ValueError(f"web_lookup does not support content type: {media_type or 'unknown'}")
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        truncated_body = body[:MAX_BODY_BYTES]
        text = truncated_body.decode(charset, errors="replace")
        title: str | None = None
        if media_type in {"text/html", "application/xhtml+xml"}:
            title, text = _extract_html_text(text)
        content_truncated = len(body) > MAX_BODY_BYTES or len(text) > MAX_CONTENT_CHARS
        return {
            "url": final_url,
            "title": title,
            "content": text[:MAX_CONTENT_CHARS],
            "content_truncated": content_truncated,
            "status": status,
        }

    registry.register(
        ToolDefinition(
            name="web_lookup",
            description=(
                "Fetch one public http(s) page and return bounded extracted text. "
                "Public networks only; redirects are re-validated; content is truncated."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 8},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=_web_lookup,
        )
    )
```

Note: `ToolDefinition`'s default risk is READ_ONLY (matching `current_datetime`); if the registry requires the risk explicitly, pass `risk=ToolRisk.READ_ONLY` and import `ToolRisk`.

In `src/allpath_agent/tools/builtin.py`, add the import and register unconditionally before the `if workspace_roots:` block:

```python
from .web import register_web_tools
```

```python
    register_web_tools(registry)
```

- [ ] **Step 4: Run tests to verify they pass, then the full suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_web_lookup -v` — Expected: PASS.
Run: `python3.12 scripts/run_tests.py` — Expected: PASS. If a test asserts the exact builtin tool list/schema order (tool schemas are alphabetized), update it for the new `web_lookup` entry and note it in your report.

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/tools/web.py src/allpath_agent/tools/builtin.py tests/test_web_lookup.py
git commit -m "feat: add public web_lookup tool with redirect revalidation and bounded text"
```

---

### Task 2: Milestone 2 follow-up fixes

**Files:**
- Modify: `src/allpath_agent/application.py` (`send` gains `record_curriculum`)
- Modify: `src/allpath_agent/automations.py` (protocol + unattended send + `_advance` hardening)
- Modify: `src/allpath_agent/storage/repositories.py` (`needs_attention` bool normalization)
- Modify: `src/allpath_agent/cli/main.py` (lazy connector construction in `_manage_automations`; drain-loop comment)
- Test: `tests/test_automations.py`

**Interfaces:**
- Produces: `AgentApplication.send(session_id, message, *, record_curriculum: bool = True)`. `AutomationApplication` protocol matches. `AutomationService` calls `send(..., record_curriculum=False)`.
- Run records now return `needs_attention` as `bool`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_automations.py`:

Update `FakeApplication.send` to record the flag:

```python
    def send(self, session_id: str, message: str, *, record_curriculum: bool = True):
        self.messages.append((session_id, message, record_curriculum))
        if self.error:
            raise self.error
        return SimpleNamespace(task_id="task-1", agent=SimpleNamespace(content=f"done: {message}"))
```

Update the one existing assertion that unpacks `self.messages` pairs if any test compares full tuples (search for `application.messages` and adjust expected tuples to include `False`).

Add to `AutomationLifecycleTestCase`:

```python
    def test_unattended_runs_suppress_curriculum_recording(self) -> None:
        session = self.sessions.create("automation:test")
        self.jobs.create(
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

        service.tick()

        self.assertEqual(
            application.messages,
            [(session.id, "Prepare update", False)],
        )

    def test_broken_cron_schedule_disables_job_instead_of_crashing(self) -> None:
        session = self.sessions.create("automation:test")
        job = self.jobs.create(
            name="Broken",
            prompt="Prepare update",
            schedule_kind="cron",
            schedule_expression="0 8 * * *",
            timezone="Mars/Olympus",
            session_id=session.id,
            next_run_at="2026-07-20T14:00:00+00:00",
        )
        service = AutomationService(
            self.jobs, self.runs, self.sessions, FakeApplication(), now=lambda: self.now
        )

        run = service.tick()

        self.assertEqual(run["status"], "succeeded")
        refreshed = self.jobs.get(job["id"])
        self.assertFalse(refreshed["enabled"])
        self.assertIsNone(refreshed["next_run_at"])

    def test_run_records_return_boolean_needs_attention(self) -> None:
        session = self.sessions.create("automation:test")
        self.jobs.create(
            name="Due task",
            prompt="Prepare update",
            schedule_kind="once",
            schedule_expression="2026-07-20T14:00:00+00:00",
            timezone="UTC",
            session_id=session.id,
            next_run_at="2026-07-20T14:00:00+00:00",
        )
        service = AutomationService(
            self.jobs, self.runs, self.sessions, FakeApplication(), now=lambda: self.now
        )

        run = service.tick()

        self.assertIs(run["needs_attention"], False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automations -v`
Expected: the three new tests FAIL (`send` flag tuple mismatch / `ValueError` from `_advance` / `assertIs` failing on `0`); some pre-existing tests may fail on the widened `messages` tuple until Step 3.

- [ ] **Step 3: Implement**

`src/allpath_agent/application.py` — change `send` and gate curriculum:

```python
    def send(
        self,
        session_id: str,
        message: str,
        *,
        record_curriculum: bool = True,
    ) -> ApplicationResult:
        task_id = str(uuid4())
        intents = detect_intents(message)
        if record_curriculum:
            self._record_curriculum_attempts(intents)
        signals = analyze_task(message)
        decision = self._router.route(signals)
        self._routing_decisions.record(
            session_id,
            task_id,
            decision.profile.name,
            decision.profile.model,
            decision.reason,
            signals.complexity(),
            provider=decision.profile.provider,
        )
        result = self._loop.run(
            session_id,
            task_id,
            message,
            _runtime_system_prompt(self._system_prompt, decision.profile),
            decision.profile,
        )
        suggestion = None
        if record_curriculum:
            evidence = self._task_evidence(session_id, task_id, decision.profile.name)
            suggestion = self._curriculum.after_task(session_id, intents, evidence)
        return ApplicationResult(result, task_id, decision.reason, suggestion)
```

`src/allpath_agent/automations.py`:

- Protocol: `def send(self, session_id: str, message: str, *, record_curriculum: bool = True) -> Any: ...`
- In `_execute`, call `self.application.send(job["session_id"], job["prompt"], record_curriculum=False)`.
- Harden `_advance` (broken schedule disables the job instead of raising out of the runner):

```python
    def _advance(self, job: dict[str, Any], run: dict[str, Any]) -> None:
        now = self._now().astimezone(UTC)
        if job["schedule_kind"] == "once":
            self.jobs.complete_schedule(
                job["id"],
                last_run_at=run["scheduled_for"],
                next_run_at=None,
                disable=True,
            )
            return
        try:
            schedule = parse_cron(job["schedule_expression"], job["timezone"])
            next_run = schedule.next_after(max(now, datetime.fromisoformat(run["scheduled_for"])))
        except ValueError:
            self.jobs.complete_schedule(
                job["id"],
                last_run_at=run["scheduled_for"],
                next_run_at=None,
                disable=True,
            )
            return
        self.jobs.complete_schedule(
            job["id"],
            last_run_at=run["scheduled_for"],
            next_run_at=next_run.isoformat(),
            disable=False,
        )
```

`src/allpath_agent/storage/repositories.py` — normalize run records; add below `_automation_job_record`:

```python
def _automation_run_record(row: Any) -> dict[str, Any]:
    record = dict(row)
    record["needs_attention"] = bool(record.get("needs_attention", 0))
    return record
```

and use it in `AutomationRunRepository.get` and `list_for_job` in place of `dict(row)`.

`src/allpath_agent/cli/main.py`:

- In `_manage_automations`, make connector construction lazy-tolerant so a local-only job still runs when an unrelated connector's secrets are missing:

```python
        try:
            registry = ConnectorRegistry(tuple(_active_connector_instances(home, database)))
        except ConfigError as error:
            output(f"Delivery channels unavailable: {error}. Jobs without destinations still run.")
            registry = ConnectorRegistry(())
```

- Above the gateway drain `while True:` loop, add the invariant comment:

```python
            # Termination invariant: each tick either advances next_run_at strictly
            # forward or disables the job, and claim_due cannot re-claim a
            # (job, scheduled_for) pair, so this drain loop always reaches None.
```

- [ ] **Step 4: Run tests and the full suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_automations -v` — Expected: PASS (all, including pre-existing).
Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/application.py src/allpath_agent/automations.py src/allpath_agent/storage/repositories.py src/allpath_agent/cli/main.py tests/test_automations.py
git commit -m "fix: suppress curriculum during unattended runs and harden automation execution"
```

---

### Task 3: `daily_briefing` curriculum capability

**Files:**
- Modify: `src/allpath_agent/curriculum/catalog.py`
- Modify: `src/allpath_agent/application.py` (`detect_intents` + `_record_curriculum_attempts`)
- Modify: `src/allpath_agent/cli/banner.py` (`CAPABILITY_HINTS` + `HINT_ORDER`)
- Modify: `src/allpath_agent/cli/main.py` (evidence on workflow completion)
- Test: `tests/test_curriculum.py`, `tests/test_application.py`, `tests/test_banner.py` (existing set-equality test covers itself)

**Interfaces:**
- Produces: capability id `daily_briefing` (prerequisite `messaging_connectors`, trigger intents `{"automation", "briefing"}`); new intent `briefing`.
- Evidence rule: when the automation-creation workflow completes AND the newest job is `cron` with a destination, the CLI records `daily_briefing` success (in addition to `scheduled_automations`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_curriculum.py` (match the file's existing helper style for building the engine/service — read it first; the test below shows intent, adapt constructor calls to the file's existing fixtures):

```python
    def test_daily_briefing_unlocks_after_messaging_and_matches_briefing_intent(self) -> None:
        progress = {
            "basic_chat": self._progress("basic_chat", "habitual"),
            "live_provider": self._progress("live_provider", "succeeded"),
            "messaging_connectors": self._progress("messaging_connectors", "succeeded"),
        }

        capability = self.engine.recommend({"chat", "briefing"}, progress, frozenset())

        self.assertIsNotNone(capability)
        self.assertEqual(capability.id, "daily_briefing")
```

(If `tests/test_curriculum.py` has no `_progress` helper, construct `CapabilityProgress` records the way its other tests do.)

Append to `tests/test_application.py` `DetectIntentsTestCase`:

```python
    def test_detects_briefing_intent(self) -> None:
        self.assertIn("briefing", detect_intents("send me a daily briefing"))
        self.assertIn("briefing", detect_intents("每天早上给我发简报"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_curriculum tests.test_application -v`
Expected: the two new tests FAIL (unknown capability / missing intent).

- [ ] **Step 3: Implement**

`src/allpath_agent/curriculum/catalog.py` — append after the `browser_tasks` entry:

```python
        Capability(
            id="daily_briefing",
            title="Daily briefing",
            base_priority=44,
            prerequisite_ids=("messaging_connectors",),
            trigger_intents=frozenset({"automation", "briefing"}),
            setup_effort=10,
            lesson=(
                "Say “create automation” to schedule a daily briefing: I can read public pages "
                "with web_lookup and deliver the summary to your connected channel every morning."
            ),
        ),
```

`src/allpath_agent/application.py`:

- `detect_intents` mappings — add:

```python
        "briefing": (
            "daily brief",
            "daily briefing",
            "morning brief",
            "briefing",
            "简报",
            "晨报",
            "早报",
        ),
```

- `_record_curriculum_attempts` map — add `"briefing": "daily_briefing",`.

`src/allpath_agent/cli/banner.py`:

- `CAPABILITY_HINTS` — add:

```python
    "daily_briefing": "Try: create automation — a daily briefing to your channel",
```

- `HINT_ORDER` — insert `"daily_briefing",` directly after `"messaging_connectors",` (the existing `test_hint_order_covers_every_capability_hint` keeps the two structures honest).

`src/allpath_agent/cli/main.py` — in the automation-workflow completion block, replace:

```python
            if automation_result.completed:
                application.record_capability_success("scheduled_automations")
```

with:

```python
            if automation_result.completed:
                application.record_capability_success("scheduled_automations")
                jobs = AutomationJobRepository(database).list_all()
                if jobs:
                    newest = max(jobs, key=lambda job: job["created_at"])
                    if newest["schedule_kind"] == "cron" and newest["destination_connector_id"]:
                        application.record_capability_success("daily_briefing")
            continue
```

(Keep the surrounding block structure; only the completion branch grows.)

- [ ] **Step 4: Run tests and the full suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_curriculum tests.test_application tests.test_banner -v` — Expected: PASS.
Run: `python3.12 scripts/run_tests.py` — Expected: PASS. If any test asserts the capability count (e.g. “fifteen”), update it and note it.

- [ ] **Step 5: Commit**

```bash
git add src/allpath_agent/curriculum/catalog.py src/allpath_agent/application.py src/allpath_agent/cli/banner.py src/allpath_agent/cli/main.py tests/test_curriculum.py tests/test_application.py
git commit -m "feat: add the daily briefing capability as the post-connector lesson"
```

---

### Task 4: Golden-path integration test (fake transports)

**Files:**
- Create: `tests/test_golden_path.py`
- Reference (read, do not modify): `tests/test_cli.py` (`run_cli` harness + the fake-claude test around line 226), `src/allpath_agent/cli/main.py` (`_manage_automations`, `TelegramConnector` import)

**Interfaces:**
- Consumes: everything shipped in Tasks 1-3 and Milestones 1-2. No production code changes — if the test exposes a real defect, STOP and report it (status BLOCKED with the failing evidence) instead of patching production code inside this task.

- [ ] **Step 1: Write the test**

Create `tests/test_golden_path.py`. The flow: fresh home → fake-claude live config → seeded active Telegram connector + conversation binding → briefing created through the real chat CLI (subprocess) → job forced due (direct SQLite update — deterministic surgery, same technique as other tests' fixed `now`) → `automations tick` executed in-process with a fake `TelegramConnector` → assert the message reached the fake transport and the run recorded delivery. Assert curriculum: `daily_briefing` succeeded after creation, and the automation session produced no capability suggestions.

```python
from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from allpath_agent.cli.main import main
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import (
    AutomationJobRepository,
    AutomationRunRepository,
    CapabilityProgressRepository,
    CapabilitySuggestionRepository,
    ConnectorConfigRepository,
    ConnectorSessionRepository,
    Database,
    SessionRepository,
)

from tests.test_cli import ROOT, run_cli


class FakeTelegramConnector:
    sent: list[tuple[str, str]] = []

    def __init__(self, token: str):
        self.id = "telegram"
        self.token = token

    def status(self):  # pragma: no cover - not used by tick
        raise AssertionError("status is not part of the tick path")

    def start(self) -> None:  # pragma: no cover
        pass

    def stop(self) -> None:  # pragma: no cover
        pass

    def poll(self):  # pragma: no cover
        return []

    def send(self, message) -> str:
        FakeTelegramConnector.sent.append((message.conversation_id, message.text))
        return "fake-msg-1"


class GoldenPathTestCase(unittest.TestCase):
    def test_model_to_telegram_daily_briefing_end_to_end(self) -> None:
        FakeTelegramConnector.sent = []
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self._install_fake_claude(home)
            database = Database(home / "state.db")
            database.initialize()
            self._seed_telegram(home, database)

            creation = run_cli(
                home,
                "create automation\n"
                "Morning brief\n"
                "Use web_lookup on https://example.com and summarize it\n"
                "0 8 * * *\n"
                "UTC\n"
                "1\n"
                "confirm\n"
                "/exit\n",
            )
            self.assertEqual(creation.returncode, 0, creation.stderr)
            self.assertIn("confirm", creation.stdout.lower())

            jobs = AutomationJobRepository(database).list_all()
            self.assertEqual(len(jobs), 1)
            job = jobs[0]
            self.assertEqual(job["schedule_kind"], "cron")
            self.assertEqual(job["destination_connector_id"], "telegram")
            self.assertEqual(job["destination_conversation_id"], "chat-9")

            progress = CapabilityProgressRepository(database)
            self.assertEqual(progress.get("daily_briefing").status, "succeeded")

            with database.connect() as connection, connection:
                connection.execute(
                    "UPDATE automation_jobs SET next_run_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
                    (job["id"],),
                )

            buffer = StringIO()
            with patch("allpath_agent.cli.main.TelegramConnector", FakeTelegramConnector):
                with redirect_stdout(buffer):
                    exit_code = main(["--home", str(home), "automations", "tick"])

            self.assertEqual(exit_code, 0, buffer.getvalue())
            self.assertEqual(len(FakeTelegramConnector.sent), 1)
            conversation_id, delivered_text = FakeTelegramConnector.sent[0]
            self.assertEqual(conversation_id, "chat-9")
            self.assertTrue(delivered_text)

            runs = AutomationRunRepository(database).list_for_job(job["id"])
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "succeeded")
            self.assertEqual(runs[0]["output_message_id"], "fake-msg-1")
            self.assertEqual(runs[0]["output_text"], delivered_text)

            suggestions = CapabilitySuggestionRepository(database)
            self.assertIsNone(suggestions.get_for_session(job["session_id"]))

    def _install_fake_claude(self, home: Path) -> None:
        # Mirror tests/test_cli.py's fake-claude pattern: a stub executable on
        # PATH plus a config.toml pointing the live provider at it. Copy the
        # exact stub script and config contents from the existing
        # test_conversation_connects_fake_claude_code_and_switches_live test;
        # write config.toml directly instead of driving the connect flow.
        raise NotImplementedError

    def _seed_telegram(self, home: Path, database: Database) -> None:
        ConnectorConfigRepository(database).save("telegram", "active", "@fake_bot")
        SecretStore(home / "secrets.json").set("TELEGRAM_BOT_TOKEN", "123:fake")
        session = SessionRepository(database).create(title="telegram:chat-9")
        ConnectorSessionRepository(database).bind("telegram", "chat-9", session.id)


if __name__ == "__main__":
    unittest.main()
```

`_install_fake_claude` is deliberately the one part you must derive from the existing fake-claude test rather than transcribe: read `tests/test_cli.py`'s `test_conversation_connects_fake_claude_code_and_switches_live` and `test_failed_codex_verification_does_not_repeat_selector` fixtures, reuse the same stub-script body, and write the same `config.toml` shape the connect flow produces (check `ProviderConnectionWorkflow`'s output or an existing test asserting `load_config`). The subprocess phase needs `PATH` to include the stub — extend the environment the same way that test does (note `run_cli` copies `os.environ`, so set `os.environ["PATH"]` around the call and restore it in a `finally`).

Also verify `SecretStore` exposes `set` (used by the connector workflows); if the method is named differently, use that name.

- [ ] **Step 2: Run the test — iterate until green**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_golden_path -v`
Expected: PASS. Debug fixture issues (config shape, stdin script, PATH) freely — but if the failure is in production behavior (delivery, evidence, suppression), STOP and report BLOCKED with the evidence.

- [ ] **Step 3: Run the full suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add tests/test_golden_path.py
git commit -m "test: cover the model-to-telegram daily briefing golden path end to end"
```

---

### Task 5: Documentation — golden-path quickstart, smoke checkpoint, changelog

**Files:**
- Modify: `README.md`
- Modify: `docs/VALIDATION.md`
- Modify: `CHANGELOG.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: README golden-path quickstart**

In `README.md`:

- Update the curriculum count sentence (currently “The current curriculum contains fifteen implemented capabilities.”) to:

```markdown
The current curriculum contains sixteen implemented capabilities.
```

- Directly after the “## Quick install” section's installer paragraph, add:

```markdown
### The golden path

The fastest way to feel what Allpath is for:

1. `allpath-agent`, then say “connect a model” and follow the conversation.
2. Say “connect Telegram” and follow the four-step tutorial, then message your bot once.
3. Say “create automation” and schedule a daily briefing — for example
   “Use web_lookup on your favorite news page and summarize it”, cron
   `0 8 * * *`, your timezone, delivered to your Telegram conversation.
4. Run `allpath-agent gateway` (or install the background service with
   `allpath-agent gateway install`). The next morning the briefing arrives in
   Telegram.
```

- [ ] **Step 2: `docs/VALIDATION.md` user-assisted smoke checkpoint**

Append a section:

```markdown
## Golden-path smoke test (user-assisted)

Automated coverage ends at fake transports (`tests/test_golden_path.py`). One
real-account checkpoint remains user-assisted because it requires a personal
Telegram bot:

1. Connect a live model and Telegram on a fresh install.
2. Message the bot once so the conversation is registered as a destination.
3. Create a cron briefing automation in chat delivered to that conversation,
   scheduled one or two minutes ahead.
4. Run `allpath-agent gateway` and wait for the scheduled minute.
5. Confirm the briefing message arrives in Telegram, `allpath-agent
   automations list` shows the advanced next run, and the run record carries
   the delivered message ID.
```

- [ ] **Step 3: CHANGELOG**

Under `## Unreleased` `### Added`, append:

```markdown
- Added a read-only `web_lookup` tool that fetches one public page with redirect re-validation, bounded body reads, script/style-free text extraction, and truncated output.
- Added the sixteenth curriculum capability, Daily briefing, offered after a messaging connector succeeds and evidenced by saving a cron automation with a delivery destination.
- Added a deterministic golden-path integration test: fresh home → fake live model → seeded Telegram → briefing created in chat → forced-due tick → delivery asserted against a fake Telegram transport.
```

Add a `### Fixed` subsection after it:

```markdown
### Fixed

- Stopped unattended automation runs from writing curriculum progress or suggestions; only interactive conversations teach and record capabilities now.
- Disabled automations with un-parseable schedules instead of crashing the gateway runner, and normalized `needs_attention` to a boolean in run records.
- Kept local-only automations runnable from `automations run`/`tick` when an unrelated connector's secrets are missing.
```

- [ ] **Step 4: Run the full suite and commit**

Run: `python3.12 scripts/run_tests.py` — Expected: PASS.

```bash
git add README.md docs/VALIDATION.md CHANGELOG.md docs/superpowers/plans/2026-08-02-golden-path.md
git commit -m "docs: describe the golden path and its user-assisted smoke checkpoint"
```

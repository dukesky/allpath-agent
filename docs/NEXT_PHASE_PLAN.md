# Next Phase Plan: Onboarding Funnel and the First Golden Path

Updated: 2026-08-02

## Objective

Close the gap between what the curriculum teaches and what a new user can
actually complete. The destination of this phase is one end-to-end golden
path: install → connect a model → connect Telegram → create a daily briefing
automation inside the conversation → receive the briefing in Telegram the
next morning.

Context: the previous phase (self-serve connectors and automations) is
complete except connector delivery. A project review on 2026-08-02 found
three product-level gaps that block the original goal of proactive,
progressive onboarding:

1. Only one and a half of the three teaching surfaces are wired. The launch
   card requires all three messaging connectors before curriculum hints
   appear, so most installations never see it. The composer hint is not
   connected to curriculum state at all.
2. The `scheduled_automations` lesson teaches a flow the user cannot
   complete: chat `/automations` only lists jobs, nothing executes due jobs
   unattended, and results cannot be delivered to a messaging channel.
3. The first-level "web lookup" capability from the product design does not
   exist, while deeper browser automation shipped ahead of it.

## Milestone 1: Complete the onboarding teaching surfaces

Acceptance criteria:

- the live-mode launch card always shows one curriculum-derived next step,
  regardless of connector state;
- one active connector (or an explicit `/dismiss messaging_connectors`)
  satisfies the messaging step; the card never demands all three platforms;
- the composer hint shows the next unlearned capability action whenever no
  setup workflow needs input in live mode;
- suppressed (`unavailable`) and `dismissed` capabilities never appear in
  launch or composer hints;
- successful `browser_screenshot` and `browser_download` executions count as
  `browser_tasks` curriculum evidence;
- `detect_intents` and `_task_evidence` have direct unit tests;
- stale documentation is corrected: `BROWSER_COMPUTER_BOUNDARY.md` and
  `AGENT_EVOLUTION_PLAN.md` Stage 6 acknowledge the shipped structured
  browser, and the README onboarding sequence no longer lists WeChat.

## Milestone 2: Automations become real

Create in chat, run unattended, deliver to a channel.

Acceptance criteria:

- a resumable conversational creation flow (natural language or
  `/automations add`) collects name, prompt, schedule, timezone, and optional
  destination, echoes the parsed job back, and saves only after explicit
  confirmation;
- the foreground gateway and the installed background service execute due
  automation jobs on an internal tick; no external cron invocation of
  `allpath-agent automations tick` is required (the subcommand remains for
  debugging);
- jobs accept an optional destination connector and conversation; results are
  delivered through the existing connector send path; explicit destination
  configuration is required before any result leaves the machine;
- unattended runs have a documented approval policy: side-effect tool
  requests are denied and the run is marked as needing attention instead of
  failing silently;
- the `scheduled_automations` lesson, `/help`, and `docs/AUTOMATIONS.md`
  describe only flows a user can actually complete.

## Milestone 3: The golden path

Acceptance criteria:

- a read-only `web_lookup` tool fetches a public URL and returns bounded
  extracted text, reusing the browser module's public-URL validation; no
  browser installation is required for it;
- after `messaging_connectors` succeeds, the curriculum offers a daily
  briefing as the next lesson, and the suggested flow works end to end;
- a scripted integration test walks the full path against fake transports:
  fresh home → model connected → Telegram connected → briefing created in
  chat → tick executes → the briefing message reaches the fake Telegram
  transport;
- a real-account Telegram briefing smoke test is documented as a
  user-assisted checkpoint;
- the README quickstart describes the golden path in order.

## Milestone 4: Model-driven intent routing (shipped with this change)

Tool-capable models now route intent themselves: `channel_status` answers
channel state questions read-only; `channel_connect`, `create_automation`
(with validated prefill extracted from the request), and `connect_model` hand
off to the existing deterministic guided flows via side-effect-free
directives. Exact trigger phrases remain a deterministic fast path because
external-CLI providers (Claude Code and Codex account connections) do not
receive tool schemas. Directive tools are registered only in interactive chat
sessions, never in the gateway or unattended runs.

## Explicitly parked

Not in this phase, recorded so drift is a decision rather than an accident:

- computer use;
- MCP HTTP transport, OAuth, resources, prompts, dynamic refresh;
- WeChat and any additional messaging connectors;
- browser expansion: tabs, visible mode, localhost access, cookie management;
- Slack channel mentions and allowlists; Telegram disconnect/token rotation;
- interactive side-effect approvals inside messaging channels (revisit after
  Milestone 2's needs-attention policy ships).

## Validation sequence

1. unit tests for hint selection, task evidence, and intent detection;
2. CLI integration tests with temporary Allpath homes;
3. full local suite through `python3 scripts/run_tests.py`;
4. golden-path integration test with fake connector transports;
5. user-assisted real Telegram daily-briefing smoke test.

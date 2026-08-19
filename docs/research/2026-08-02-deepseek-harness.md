# Research Notes: DeepSeek Harness (dsh) — what it is, what to borrow

Date: 2026-08-02. Source: read-only review of the local `deepseek-harness`
checkout (v0.1.0-rc.7, MIT, TypeScript, ~430K lines across `packages/`).
First-pass by the maintainer after the research agent hit a session limit;
deep-dive candidates are listed at the end.

## What it is

Not a personal assistant and not a coding agent — it is an **agent runtime
kit**: "everything is a plugin" on top of Cordis (a plugin/effect framework).
The model adapter, tool registry, session log, and even the agent loop are
replaceable plugins composed from ordered layers (profiles → bundles →
patch files). Web UI (`dsh web`, port 3080) + headless runner. Target
audience is people BUILDING agents, not end users. Developer preview,
explicitly breaking-compat.

## The three ideas actually worth copying

1. **"Model-visible means logged."** A runtime invariant: anything that
   reaches a model request must be reconstructable from the append-only
   session event log; new model-visible inputs require a new event type.
   Fork, resume, transcript, telemetry, and compaction all derive from one
   stream. Allpath already persists messages; what we lack is the
   *invariant* — compaction checkpoints, directive hand-offs, and injected
   context should land in the same log so the model's view is always
   replayable. Adopt this as a stated rule when building M5 compaction.

2. **Compaction as a locked, logged transaction** (`compaction/start` →
   summary → replacement checkpoint → `compaction/end`). Lock released LAST
   so a mid-operation crash leaves a detectable orphaned start rather than a
   false "done". Tool-result pruning runs as a separate optional pass before
   range selection and can advance the surface without a summary — the same
   "LLM-free first" conclusion as the Hermes/OpenClaw research. Region
   boundaries preserve tool-call/result pairing but not whole turns.
   Directly applicable to the `compactions` table design.

3. **Same-session Goals** (`ctx.goals`): a durable objective with phases
   `active | paused | blocked | complete`, a machine-routable block reason
   (`code` + human message), and a round cap; continuation policy decides
   whether another round may start. This is the piece Allpath's "proactive
   daily-life agent" direction is missing: an explicit, persisted objective
   the agent keeps working toward across turns, with bounded rounds and a
   typed reason when it stops. Far cheaper to adopt than sub-agents.

## Smaller items

- `user-questions` seam: provider-neutral "ask the human" with stable
  question ids, option labels doubling as model-facing values, and a typed
  presentation intent (`plan-review` with a named approve label — never
  positional). Our guided flows could expose one shared question shape so
  terminal, Telegram, and a future panel render the same prompt.
- `schedule`: session-local reminders that return as ordinary later turns in
  the SAME conversation, explicit time-zone boundary, fixed-rate minimum 5
  minutes. Closer to "remind me in 2 hours" than to our cron jobs; a light
  sibling of automations, not a replacement.
- `invariants` registry: package-owned runtime checks, allowlist/blocklist
  selected, fail-loud at startup. Nice discipline; low priority for us.

## What NOT to borrow

- The plugin-everything architecture (Cordis). Our differentiator is a
  *small, readable, stdlib-first* core; turning the loop itself into a plugin
  tree buys extensibility we don't need and costs the legibility we do.
- The Web UI stack and the 430K-line footprint generally.
- Nothing in dsh addresses progressive onboarding, curriculum, or end-user
  proactivity — it is a builder's kit. Our positioning does not overlap.

## Deep-dive candidates (when a research budget is available)

`packages/compaction/compaction-basic` (threshold/retained-tail policy),
`packages/goal/goal` (activation + continuation policy), `packages/schedule`,
`packages/core/agent-loop` (turn/step claiming), `docs/subsystems/plan.md`
and `workflow.md` (not yet read).

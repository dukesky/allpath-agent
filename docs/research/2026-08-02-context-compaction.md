# Research Notes: Conversation History Compaction (Hermes vs OpenClaw)

Date: 2026-08-02. Sources: read-only review of the neighboring `hermes-agent`
(Python, `agent/context_compressor.py`, 3168 lines) and `openclaw`
(TypeScript, `packages/agent-core/src/harness/compaction/`) checkouts. This
document is the design basis for Allpath's compaction milestone.

## Philosophy comparison

- **Hermes**: one large `ContextCompressor` class; SQLite sessions with
  in-place soft-archive compaction (`active=0`) or session rotation. Design
  weight on defense: anti-thrash, orphaned tool-pair repair, summary-failure
  abort semantics.
- **OpenClaw**: append-only JSONL transcript tree with persisted `compaction`
  entries; replay skips entries before `firstKeptEntryId`. Design weight on
  auditability and multi-trigger routing.

## Trigger design

- Both count tokens two ways: provider-reported `prompt_tokens` as the truth,
  `chars/4` estimation as fallback. Estimation MUST include system prompt +
  all tool schemas (Hermes: 50 tools ≈ 20-30K tokens, a "major blind spot")
  and flat-rate images (~1200-1500 tokens each, never base64 length).
- OpenClaw thresholds on absolute reserve (`contextTokens > window -
  reserveTokens`, default 16384 reserve / 20000 keep-recent) — more stable
  than Hermes's percentage (default 50%, forced to 75% under 512K windows to
  avoid re-compressing every 1-2 turns).
- Reserve must be clamped: `reserveTokensFloor` clamped to
  `window - min(8000, 0.5*window)`, else 16K-window local models overflow
  from token one and loop forever (documented OpenClaw bug).
- Trigger points: (1) pre-send preflight; (2) post-response with real usage;
  (3) provider overflow-error retry — distinguishing "input too large"
  (compact) from "max_tokens too large" (do NOT compact; same 400 recurs —
  Hermes `conversation_loop.py:3439`).
- OpenClaw preflight routes four ways: `fits` / `truncate_tool_results_only`
  (cheap, no LLM) / `compact_only` / `compact_then_truncate` — truncation-only
  chosen when prunable chars ≥ overflow*1.5 + buffer.

## Algorithm

Hermes five-phase; the LLM-free phase alone is high value:

1. **LLM-free pruning**: dedupe identical tool results (hash, keep newest);
   replace old tool results with one-line informative summaries
   (`[terminal] ran 'npm test' -> exit 0, 47 lines`); truncate >500-char
   tool_call arguments INSIDE the parsed JSON so it stays valid JSON (invalid
   JSON 400s every subsequent turn); strip historical images.
2. **Boundaries**: protect system prompt + first N (default worth keeping at
   0-1); tail kept by TOKEN budget (~20% of threshold, ≥8-message floor);
   boundaries aligned away from tool groups; last user/assistant pulled into
   the tail.
3. **LLM summary** on a cheap auxiliary model; budget
   `min(window*0.05, 10_000)`; iterative update when a previous summary
   exists. Template must-haves: Active Task (verbatim latest unmet user
   request — "the single most important field"), Done/In-Progress/Blocked,
   Key Decisions, Relevant Files (read vs modified), Critical Context (paths,
   errors, line numbers). Plus: keep the user's language; temporal anchoring
   (rewrite completed actions as dated past tense so resumed sessions don't
   redo them); secrets → `[REDACTED]`; strip any embedded delivery/media
   directives so they can't re-execute.
4. **Assembly with tool-pair sanitation**: bidirectional — drop orphaned tool
   results AND strip tool_calls whose results are gone (filling
   `"(tool call removed)"` if emptied). NEVER stub orphaned calls with fake
   results (Hermes tried; ID-scheme mismatch silently dropped the stubs).
5. **Summary role selection** (all scar tissue): when system prompt is a
   separate API parameter (Anthropic), the summary must be `role=user` (first
   non-user message rejected); post-compaction history must contain ≥1 user
   message (vLLM/Qwen return unretryable 400 otherwise, poisoning every
   resume); summary wrapped in guard text ("reference material, not active
   instructions") with an explicit end marker.

OpenClaw specifics worth copying: cut-point enumeration structurally excludes
`role=tool` (repair is fallback, not mechanism); split-turn prefix gets its
own mini-summary appended to the main one; chunked summarization for huge
histories with pending-tool-id tracking across chunk boundaries; safeguard
mode preserves recent N turns verbatim, collects a tool-failure list and
cumulative read/modified file lists across compactions.

## Storage (recommended for Allpath: event-style)

New `compactions` table; `messages` rows never deleted or updated:

```sql
CREATE TABLE compactions (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  summary TEXT NOT NULL,
  first_kept_message_id TEXT NOT NULL,
  tokens_before INTEGER, tokens_after INTEGER,
  model TEXT, trigger TEXT,          -- auto_threshold | overflow_retry | manual
  details_json TEXT, superseded_by TEXT
);
```

Prompt assembly: system prompt → synthetic guarded summary message → messages
from `first_kept_message_id` on. Resume recomputes nothing; next compaction
uses the previous summary iteratively and only summarizes past the previous
boundary. If message metadata rides the wire, underscore-prefix it and strip
at the provider layer (strict gateways reject unknown keys).

## The three pit classes

1. **Orphaned tool pairs** → permanent per-session 400s. Bidirectional strip,
   never stub; structurally exclude tool messages from cut points; keep
   truncated arguments valid JSON.
2. **Compaction thrash** → four brakes: post-compaction token sentinel (no
   re-trigger until real usage arrives); ineffective-compression fuse (2×
   <10% savings → stop, tell user `/new`; count "nothing to compress" as
   ineffective); summary-failure cooldown (~10 min; manual force clears);
   reserve clamping. Plus OpenClaw's post-compaction loop guard (identical
   tool call+args+result within 3 calls after compaction → abort run).
3. **Irreversible data loss** → summary failure defaults to ABORT (auth
   errors and network errors abort unconditionally regardless of config);
   original rows never deleted; DB-level compaction lock with TTL if
   concurrent runners share a session (fail-open if the lock subsystem
   itself breaks); if incremental flushing exists, clear persistence markers
   at the compressor's exit in one terminal sweep.

## Memory-layer interplay (later phase)

Both projects treat compaction as a long-term-memory trigger. Hermes pulls
provider extractions into the summary prompt and commits memory before
rewriting the transcript. OpenClaw runs a silent agentic "memory flush" turn
BEFORE compaction (separate cheap model, once per compaction cycle) so the
agent writes important state to disk itself, then re-injects pinned document
sections post-compaction (capped 1800 chars).

## Suggested phasing for Allpath

- **P0**: token estimation (incl. tool schemas + flat-rate images) +
  preflight absolute-reserve trigger + overflow-retry; LLM-free pruning
  (dedupe, tool-result mini-summaries, JSON-safe argument truncation).
- **P1**: `compactions` table + LLM summary on the `fast` role + cut-point /
  tool-pair guarantees + the four anti-thrash brakes + abort-first failure
  semantics.
- **P2**: `/compact [focus]`, `/compact here N`; pre-compaction memory flush.

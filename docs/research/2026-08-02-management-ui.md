# Research Notes: Management UI (OpenClaw / Hermes) and the Allpath Plan

Date: 2026-08-02. Sources: read-only review of the neighboring `openclaw` and
`hermes-agent` checkouts.

## What the reference projects built (and what it cost)

- **OpenClaw Control UI**: Vite + Lit SPA served by the gateway on one port;
  ~110K lines TS + 31K CSS across 22 routes (chat, overview, activity,
  agents, 9 settings pages, workboard, sessions, usage, debug, logs, skills,
  cron, tasks, nodes...). The chat page alone is 27.5K lines (¼ of the UI).
  Native SwiftUI/Kotlin apps add another ~292K lines. Transport: ONE
  WebSocket JSON-RPC (~200 methods) shared by Web/TUI/CLI/mobile — the CLI's
  `cron list` calls the same `cron.list` RPC as the web page. Config editing
  goes through `config.get/set/patch` with base-hash optimistic locking
  against the same file the CLI uses.
- **Hermes dashboard**: React 19 + Vite, ~46K lines; backend is ONE 17K-line
  FastAPI file with 219 REST routes (no shared contract layer) — the
  documented anti-pattern. Electron shell adds 163K lines.
- Security model worth copying (both agree): bind 127.0.0.1 by default;
  loopback → no auth; any non-loopback bind → mandatory token with NO
  insecure bypass; validate the Host header against a localhost whitelist
  (DNS-rebinding defense that CORS cannot provide); token in sessionStorage,
  stripped from the URL after load; document "never expose publicly — SSH
  tunnel / Tailscale".
- Notably: OpenClaw built a full generic wizard RPC schema and its own web UI
  never renders it (per-channel custom forms won) — generic wizard renderers
  are a low-priority abstraction.

## Minimal value slice (by OpenClaw's own code weight)

1. `logs.tail` — bounded cursor file-tail; server side is ~40 lines, page 630.
2. Overview — status cards + attention (error/warn) list + log tail (~1.3K).
3. Cron list + enable/disable + run-now + run history (~1.5-3K).
4. Sessions list (read-only).
5. Settings FORM editing — expensive (schema-driven + optimistic lock +
   secret handling); read-only view first.
6. Chat — the most expensive, least marginal value (terminal already excels).

## Allpath decision

Build a **read-only ops panel, no chat window**:

- Terminal is already the best chat surface; the panel's unique value is
  observation across time: did last night's cron run, which run failed, token
  spend, that error's context.
- Transport: stdlib `http.server` (ThreadingHTTPServer) + polling JSON REST.
  No WebSocket (stdlib has none; the need is 2-second refresh, not token
  streaming). Log tail via `?cursor=<byte_offset>` polling — OpenClaw's
  `logs.tail` is exactly this model under its WS wrapper.
- Frontend: ONE static HTML file with native ES modules + fetch polling,
  embedded as package data. No React/Vue, no bundler, no i18n, no Electron,
  no web terminal.
- Architecture rule (the one OpenClaw got right and Hermes got wrong):
  extract a pure-Python `management` module returning dataclasses/dicts;
  CLI subcommands AND HTTP handlers are thin wrappers over it. The HTTP
  layer must never grow its own business logic.
- Phase 0 scope (~<1500 lines Python, <800 lines HTML/JS):
  `GET /api/status` (uptime, version, config path, connectors, next cron),
  `GET /api/logs?cursor=&limit=&max_bytes=`,
  `GET /api/automations` + run-now/enable/disable,
  `GET /api/runs` (recent run ledger with needs-attention flags),
  single Overview page. `allpath-agent dashboard` command: check
  reachability → print/copy link → open browser.
- Phase 1: read-only config view, sessions list, token/cost rollup.
- Phase 2 (only on demand): config editing (REQUIRES base-hash optimistic
  locking), channel-setup forms.

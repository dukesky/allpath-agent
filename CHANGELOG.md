# Changelog

All meaningful changes to Allpath Agent are recorded in this file.

The format follows Keep a Changelog conventions. During development, changes accumulate under `Unreleased`. When a release is cut, those entries move into a versioned section with an ISO date.

## Unreleased

### Added

- Established Allpath Agent as an independent project from Hermes Agent.
- Added the initial product design for conversation-first onboarding and progressive capability discovery.
- Added the initial single-process architecture and package boundaries.
- Added a model router with hard requirement filtering and complexity-based selection.
- Added a capability curriculum engine with prerequisites, relevance scoring, fatigue penalties, and dismissal handling.
- Added initial tests for model routing and curriculum recommendations.
- Added a complete project README with goals, architecture, setup direction, and MVP scope.
- Added a testable local MVP implementation plan and acceptance criteria.
- Added a versioned SQLite migration runner with foreign keys, WAL mode, and idempotent initialization.
- Added repositories for sessions, messages, model-routing decisions, durable memory, capability progress, and tool execution records.
- Added the initial persistent workflow-run schema for future resumable setup flows.
- Added storage integration tests against temporary SQLite databases.
- Made the complete test suite compatible with Python's standard-library `unittest` runner as well as `pytest`.
- Added provider-neutral chat request, response, message, and tool-call contracts.
- Added a synchronous OpenAI-compatible provider with injectable transport and structured provider errors.
- Added a deterministic fake provider for full local integration tests without API access.
- Added the first persistent Agent Loop with model-call limits, tool execution, structured tool failures, and resumable message history.
- Added a message metadata migration so assistant tool calls survive session persistence and reconstruction.
- Added lifecycle validation for assistant tool calls and matching tool-result messages.
- Added GitHub Actions CI across Python 3.11, 3.12, and 3.13.
- Added one shared local and CI validation command that compiles source files and runs the complete test suite.
- Added milestone-specific validation standards covering unit, integration, E2E, and real-provider smoke tests.
- Added a deterministic tool registry with stable alphabetic schemas for prompt-cache-friendly requests.
- Added strict tool argument validation for required fields, unknown fields, primitive types, arrays, enums, and minimum string lengths.
- Added read-only and side-effect risk classifications with default-deny approval handling.
- Added persistent allowed and denied approval decisions linked to sessions and tasks.
- Added built-in current-time, durable-memory read/write, and safe arithmetic tools.
- Integrated registry-provided schemas, tool context, validation, and approval results into the Agent Loop.
- Added a zero-dependency TOML configuration system with separate environment-based API secrets.
- Added an offline deterministic demo provider so the complete local Agent can run without an API account.
- Added the `allpath-agent` terminal command with live and demo modes.
- Added terminal approval prompts, session creation, listing, titles, resumption, and in-chat session commands.
- Added task routing persistence and visible fast/advanced model-profile selection in the CLI.
- Added graceful EOF and Ctrl-C handling with interrupted-turn history repair.
- Added subprocess E2E tests for startup, chat, tools, approvals, session resume, routing, and configuration errors.
- Changed explicit deep-analysis requests to route directly to the advanced model profile.
- Prevented tool schemas from being sent to model profiles that do not support tool calling.
- Added an installed-console-entrypoint smoke test to every GitHub Actions Python job.
- Added an eight-capability curriculum covering chat, memory, time, calculation, sessions, model routing, approvals, and live providers.
- Added persistent curriculum-session and capability-suggestion records with one suggestion enforced per session.
- Added real behavior evidence from successful tools, advanced routing, approvals, session commands, and live-provider use.
- Added cross-session suggestion cooldowns, automatic succeeded/habitual progression, and durable dismissal.
- Added post-response CLI capability tips plus `/capabilities` and `/dismiss` commands.
- Kept curriculum state outside the system prompt so progressive learning does not invalidate conversation prompt caches.
- Added a provider catalog with explicit protocol and authentication contracts.
- Added per-model provider bindings and a provider pool so fast and advanced profiles can use different vendors.
- Added native Anthropic Messages API support alongside OpenAI-compatible API support.
- Added no-auth OpenAI-compatible endpoints for local providers such as Ollama.
- Added a Claude Code external provider that reuses an authenticated app session without copying private tokens.
- Added `allpath-agent providers` for safe provider and credential readiness checks.
- Added provider IDs to persisted routing decisions and retained compatibility with legacy single-provider configuration.
- Added multi-provider, native Anthropic, external CLI, status, configuration, and persistence tests.
- Added per-task model-call, normalized token, and optional estimated-USD-cost budgets.
- Added configurable per-model input and output token prices without hard-coded vendor pricing.
- Added usage and estimated-cost summaries for providers that report token usage.
- Added append-only JSONL events for task, model-call, and tool-call lifecycle boundaries.
- Kept prompts, conversation content, credentials, tool arguments, results, and provider bodies out of logs.
- Isolated logging write failures so observability cannot interrupt agent work.
- Added budget, usage normalization, cost estimation, log privacy, and CLI logging tests.

### Changed

- Defined the first release as a locally runnable terminal agent before messaging-channel integrations.

### Fixed

- None.

## Update rules

Update this file whenever a change affects:

- user-visible behavior;
- public configuration or commands;
- architecture or persistent data;
- model-routing or curriculum behavior;
- security and permissions;
- tests or documented guarantees.

Do not add entries for formatting-only edits or temporary local experiments.

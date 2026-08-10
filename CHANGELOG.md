# Changelog

All meaningful changes to Allpath Agent are recorded in this file.

The format follows Keep a Changelog conventions. During development, changes accumulate under `Unreleased`. When a release is cut, those entries move into a versioned section with an ISO date.

## Unreleased

### Fixed

- Answered connector state questions (“have we connected Telegram?” / “连了吗”) with the actual connection status instead of hijacking them into the setup tutorial, and stopped re-teaching channels that are already connected unless the user says “reconnect”.
- Gave mid-tutorial replies a current-status line and an explicit “cancel” exit so users are never trapped in a setup flow.
- Listed Allpath's built-in conversational flows and slash commands in the static system prompt so the model directs users to the exact phrase instead of claiming the capability is unavailable.

## [0.4.0] - 2026-08-02

### Added

- Added conversational automation creation as a resumable bilingual workflow with schedule and timezone validation, destination selection from connected conversations, and an explicit confirmation echo before saving.
- Added automation execution to the gateway loop so due jobs run unattended in the foreground gateway and the installed background service without external cron invocation.
- Added connector delivery of automation results with explicit destination configuration, recorded delivered message IDs, and failure retention of generated output.
- Added needs-attention marking for unattended runs whose side-effect tool requests were denied, surfaced in gateway and CLI run output.
- Added `--connector` and `--conversation` destination flags to `allpath-agent automations add-once` and `add-cron`.
- Added a read-only `web_lookup` tool that fetches one public page with redirect re-validation, bounded body reads, script/style-free text extraction, and truncated output.
- Added the sixteenth curriculum capability, Daily briefing, offered after a messaging connector succeeds and evidenced by saving a cron automation with a delivery destination.
- Added a deterministic golden-path integration test: fresh home → fake live model → seeded Telegram → briefing created in chat → forced-due tick → delivery asserted against a fake Telegram transport.

### Fixed

- Stopped unattended automation runs from writing curriculum progress or suggestions; only interactive conversations teach and record capabilities now.
- Disabled automations with un-parseable schedules instead of crashing the gateway runner, and normalized `needs_attention` to a boolean in run records.
- Kept local-only automations runnable from `automations run`/`tick` when an unrelated connector's secrets are missing.

## [0.3.0] - 2026-08-02

### Added

- Added the first structured browser core with an isolated Chrome/Chromium profile, public-network URL enforcement, bounded snapshots, stable element refs, and approval-gated click/type actions with typed-text audit redaction.
- Added self-service browser diagnostics, real navigation testing, approved Chromium installation, isolated-profile reset, and natural-language setup guidance.
- Added approval-gated browser screenshots and controlled downloads with private fixed directories, unique filenames, owner-only permissions, and artifact size limits.

### Fixed

- Made the live launch card curriculum-driven: one active messaging connector (or an explicit dismissal) advances startup guidance to the next unlearned capability instead of demanding all three platforms.
- Connected the composer hint to curriculum state so idle live sessions suggest the next unlearned capability action.
- Counted successful browser screenshots and downloads as `browser_tasks` curriculum evidence.
- Corrected stale browser-status statements in the boundary and evolution documents and removed the unshipped WeChat mention from the README onboarding sequence.

## [0.2.0] - 2026-07-29

### Added

- Added a scrollback-friendly terminal conversation UI with a visible user composer, distinct Allpath response panels, model-role labels, compact usage metadata, and separate progressive-learning suggestion cards.
- Added privacy-safe live task, model retry, and tool activity lines plus a bordered side-effect approval prompt.

- Added a bounded approval-gated terminal tool with argv execution, workspace cwd enforcement, secret-stripped environment, executable allowlist, timeout process-group termination, and bounded output.
- Added progressive Allpath Skills with built-in, user, and project discovery layers, `skills_list`, `skill_view`, `/skills`, and explicit slash invocation without system-prompt mutation.
- Added initial repository-analysis, Connector-setup, and Automation Skills.
- Added MCP stdio discovery and calls through the official Python SDK, including namespaced tools, schema normalization, secret allowlisting, workspace cwd enforcement, `/mcp` inspection, and approval gating.
- Added a typed Hook Bus used by Agent lifecycle logging, Connector receive/send events, and Automation completion events, with conditional subscriptions and handler-failure isolation.
- Documented explicit safety gates for future structured browser and isolated computer-use capabilities.
- Added approval-gated `write_file` and exact-text `patch` workspace tools with atomic replacement, size limits, permission preservation, and SQLite audit records.
- Added SHA-256 compare-and-swap protection so stale Agent writes cannot overwrite files changed since the latest read.
- Added bounded terminal previews for long approval arguments while retaining the original bounded arguments in local audit records.
- Added read-only workspace tools: bounded UTF-8 `read_file` and literal `search_files`, rooted at the CLI startup directory.
- Added filesystem safety boundaries for traversal, absolute paths, symlinks, oversized or binary files, common dependency directories, and credential-like files.
- Added Workspace File Understanding to the onboarding curriculum with verified tool-execution evidence.
- Added the Agent evolution roadmap covering evidence-driven onboarding, workspace tools, Skills, MCP, proactive triggers, browser automation, and computer use.
- Added curriculum entries for messaging connectors and scheduled automations.
- Added explicit `tried` learning-state recording so Allpath can distinguish attempted features from verified success and habitual use.

- Added a reusable connector-onboarding guide engine with numbered steps, bilingual instructions, progress hints, back/status/cancel navigation, and persistent resume points.
- Replaced Slack's one-paragraph setup prompt with a seven-step conversational tutorial covering app creation, bot scopes, App Home, events, Socket Mode, installation, and secure token collection.
- Migrated Telegram to a four-step BotFather tutorial with progress, navigation, restart recovery, and delayed hidden token collection.
- Migrated WhatsApp to a nine-step Meta Cloud API tutorial that separates credential verification from gateway, HTTPS tunnel, webhook, subscription, and real-message verification.
- Added `allpath-agent connectors --test` and `/connectors test` diagnostics for credential presence, live verification, runtime readiness, WhatsApp webhook reachability, and corrective actions.
- Added idempotent per-user background gateway service commands for macOS LaunchAgents and Linux user systemd, with safe status, restart, uninstall, and credential-free service files.
- Added the implementation-ready minimal automation design covering SQLite jobs and runs, schedule semantics, execution invariants, safe connector delivery, CLI surfaces, and deferred scope.
- Added Automation MVP persistence, timezone-aware one-time and five-field cron schedules, atomic due-run claims, run-now/tick execution through the existing AgentApplication, local result/error retention, and CLI lifecycle management.

## [0.1.0] - 2026-07-15

### Added

- Established Allpath Agent as an independent project from Hermes Agent.
- Added provider-neutral messaging connector contracts, registry, and runtime dispatch.
- Added persistent connector-conversation to Allpath-session bindings in SQLite.
- Added a Telegram reference adapter with health verification, update normalization, offset tracking, replies, injected test transport, and standard-library HTTPS transport.
- Added resumable conversational Telegram setup with BotFather guidance, hidden token input, real bot verification, and persisted activation status.
- Added `allpath-agent connectors` status and a foreground `allpath-agent gateway` runner with graceful interruption and default-deny side-effect approvals.
- Advanced live startup onboarding to Telegram after model setup and before optional capability lessons.
- Added a Slack Socket Mode connector using the official Python Slack SDK, including event acknowledgement, DM normalization, thread replies, and bot-event filtering.
- Added resumable conversational Slack setup with separate hidden Bot and App-Level tokens, real `auth.test` and `apps.connections.open` verification, and restart-safe secret re-entry.
- Extended the gateway to run Telegram and Slack together and advanced startup onboarding from Telegram to Slack.
- Added an official WhatsApp Cloud API connector with signed local webhooks, Graph API text replies, credential verification, conversational setup, and gateway integration.
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
- Added provider timeout configuration for API and external-CLI adapters.
- Added explicit timeout, connection, rate-limit, server, authentication, and response error classes.
- Added bounded exponential retries for transient provider failures with numeric `Retry-After` support.
- Counted every retry attempt against the existing per-task model-call budget.
- Added structured retry, terminal failure, and task interruption events without response-body logging.
- Marked interrupted tool executions terminal and repaired all unresolved tool-result messages in the Agent Loop.
- Added HTTP classification, retry-budget, backoff, timeout, and multi-tool interruption tests.
- Added a one-line Linux/macOS installer that manages Python, an isolated virtual environment, package installation, PATH, and first launch.
- Added an offline `--local` installation mode that links the current checkout for rapid development testing.
- Made fresh `allpath-agent` launches enter local starter mode instead of failing on a missing configuration.
- Added conversational provider-setup intent detection without forcing a first-run setup wizard.
- Added direct starter-mode provider guidance so explicit setup questions are never blocked by proactive-tip limits.
- Added safe natural-language arithmetic recognition for common English and Chinese expressions in starter mode.
- Replaced internal tool-result dictionaries with concise user-facing time, calculation, and memory responses.
- Replaced mechanical `Demo response` echoes with a useful greeting and transparent reasoning-limit guidance.
- Added Chinese/English response matching for starter greetings, tools, capability summaries, setup guidance, and fallbacks.
- Added direct answers for explicit “what can you do?” capability questions.
- Suppressed live-provider and advanced-routing lessons in starter mode and marked them unavailable until configured.
- Added resumable conversational model setup for OpenAI, Anthropic, OpenRouter, Ollama, and Claude Code.
- Added context-aware input hints for starter discovery and each model setup step.
- Added arrow-key provider/model selectors with searchable model lists.
- Added OpenAI Codex account auth through the official `codex login` and `codex exec` interfaces.
- Added account-aware Codex model discovery from the official CLI cache with offline fallbacks.
- Prefer the newest installed official Codex executable, including the ChatGPT app bundle on macOS.
- Surface Codex JSONL provider failures accurately and stop repeated verification loops.
- Recover from incomplete multibyte terminal input instead of crashing the chat session.
- Added xAI Grok API support through the official OpenAI-compatible endpoint.
- Added native Google Gemini `generateContent` API support.
- Documented why Gemini/Grok personal app OAuth is unavailable to third-party agents.
- Changed API setup to authenticate before model selection.
- Added live credential-aware model discovery for OpenAI, Anthropic, xAI, Gemini, and OpenRouter.
- Added conversational assignment of connected models to `fast`, `standard`, or `advanced` routing roles.
- Preserved existing providers and model roles when adding or replacing one model connection.
- Added an interactive `/models` manager for status, connection tests, role reassignment, safe removal, and model setup.
- Added `/route` to explain the latest role, reason, provider, and model selection in the current session.
- Added authoritative `/model` runtime identity and permission reporting.
- Added exact role, provider, model, tool availability, and Codex read-only sandbox facts to each routed task prompt.
- Fixed starter discovery hints remaining visible after a successful live model connection.
- Added a compact Allpath startup illustration with full session and command status.
- Added adaptive launch guidance that prioritizes conversational setup on first run and rotates through unlearned capabilities after models are connected.
- Kept launch guidance outside conversation history and model context.
- Made conversational model connection the focused first startup action, followed conceptually by messaging channels and automations.
- Added curated catalog fallback and restart-safe secret re-entry without persisting credentials in workflow state.
- Added hidden API-key input and a mode-`0600` local secret store excluded from messages, workflow state, logs, and config.
- Added real provider verification before atomic configuration replacement and same-session live-mode switching.
- Preserved existing configuration and discarded new secrets when verification fails.
- Added workflow persistence, secret-boundary, failure-safety, and fake Claude Code CLI E2E tests.
- Added an isolated, idempotent installer E2E test that launches the installed command.

### Changed

- Slack replies now stay in the main conversation for direct messages, preserve existing threads, and create threads for channel messages.

- Fixed Slack App-Level Token verification to pass the required explicit `app_token` argument to `apps.connections.open`.

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

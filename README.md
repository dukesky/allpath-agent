# Allpath Agent

Latest release: [v0.1.0](release_notes/v0.1.0.md)

[![CI](https://github.com/dukesky/allpath-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/dukesky/allpath-agent/actions/workflows/ci.yml)

Allpath Agent is a small personal AI agent that runs locally, learns its user's preferences, progressively teaches its own capabilities, and routes each task to an appropriate model.

The project is inspired by architectural lessons from Hermes Agent, but it is an independent implementation with a deliberately smaller core and a conversation-first onboarding experience.

Interactive startup opens with a compact Allpath illustration and a state-aware
launch card. A first run suggests conversational model setup and useful local
tasks; a configured installation shows ready model roles and rotates toward the
next capability the user has not yet learned. These hints are derived from
local configuration and curriculum state and are never added to model context.

The starter card deliberately highlights one foundational first action rather
than a menu of features: connecting a reasoning model in the conversation.
The intended onboarding sequence is model connection, then a messaging channel
such as Telegram, Slack, WhatsApp, or WeChat, then recurring automations. The
banner only presents steps that the current build can actually complete;
channel and automation walkthroughs become active as those connectors ship.

## Project status

**Current phase:** Locally runnable MVP — persistence, routing, Agent Loop, tools, approvals, terminal sessions, task budgets, structured logs, and progressive capability learning are implemented.

The first release target is a testable local agent, not a production multi-platform system. A successful MVP must let a user start the agent locally, hold a multi-turn conversation, invoke a small set of tools, persist sessions, and observe model-routing and capability-learning decisions.

See [MVP plan](docs/MVP_PLAN.md) for the acceptance criteria and implementation sequence.

## Product goals

- Start in a chat instead of a blocking setup wizard.
- Introduce capabilities gradually through useful, contextual suggestions.
- Remember durable user preferences across sessions.
- Use inexpensive models for simple tasks and advanced models for difficult tasks.
- Keep permissions, connections, and workflow state deterministic and verifiable.
- Keep the agent core small while adding integrations through connectors.
- Run locally with transparent configuration and inspectable data.

## Core ideas

### Progressive capability discovery

The agent maintains a curriculum of its own capabilities. It tracks whether each capability is locked, eligible, offered, tried, successful, habitual, or dismissed. After completing a task, it may recommend one relevant capability without interrupting the user's work.

The same progress also shapes the launch card: completed, habitual, and
dismissed lessons are skipped so startup guidance advances with the user rather
than repeating a permanent tutorial.

The current curriculum contains eight implemented capabilities. Suggestions appear only after the current answer, at most once per session. Recent suggestions receive a cross-session cooldown, successful actions advance progress automatically, and `/dismiss` suppresses unwanted lessons.

Examples:

- After repeated weather questions, offer a daily weather briefing.
- When the user asks to remember a preference, explain and activate durable memory.
- When a task repeats, offer to schedule it.
- When calendar access would unlock the requested task, offer an inline connection flow and resume the original task afterward.

### Model routing

Models are configured as logical profiles:

- `fast`: inexpensive conversation, classification, rewriting, and simple lookups.
- `standard`: normal planning and tool use.
- `advanced`: difficult reasoning, code changes, long-horizon tasks, and high-risk work.

The router chooses one model at the beginning of a task and only escalates upward when execution reveals greater difficulty. It does not switch models on every tool call.

Model setup and starter mode show contextual hints next to the terminal input.
The hint changes with the active step—for example, provider choices, the default
model accepted by pressing Enter, cancellation, and hidden API-key entry.

In an interactive terminal, provider and model setup use an arrow-key picker:
use `↑`/`↓`, press Enter to select, `/` to search model lists, and Esc to cancel.
OpenAI supports either a direct API key or an existing ChatGPT/Codex account via
the official Codex CLI. Allpath checks `codex login status`, starts `codex login`
when needed, and invokes `codex exec` without copying account tokens. Codex model
choices come from the account-aware local Codex model cache with curated offline
fallbacks.

API-provider setup is credential-first: after hidden key entry, Allpath queries
that provider's models endpoint and opens a searchable picker containing the
models available to that credential. OpenAI-compatible providers use bearer
authentication, Anthropic uses its native model catalog headers, and Gemini
filters its catalog to `generateContent` models. Network/catalog failures fall
back to a curated list, and the selected model is still verified before any
configuration or secret is committed.

After choosing a model, assign it to `fast`, `standard`, or `advanced`. Running
“connect model” again adds or replaces only the selected role; other configured
roles and providers remain available. This lets one installation use, for
example, an inexpensive OpenAI model for `fast` tasks and an Anthropic model
for `advanced` tasks without manually editing TOML.

Allpath also supports the official xAI Grok API and Google Gemini API through
hidden API-key setup. Personal Grok and Gemini web-app OAuth is intentionally
not offered: xAI does not publish a stable third-party Grok-account OAuth
contract, and Google explicitly directs third-party agents to Gemini API or
Vertex AI rather than reusing Gemini CLI personal OAuth credentials.

### Narrow core, capabilities at the edges

The core owns conversation state, model calls, tool execution, persistence, interruption, and workflow boundaries. Calendar, Slack, WhatsApp, and other integrations belong in connectors rather than inside the core loop.

## MVP scope

The first locally runnable MVP includes:

- a terminal chat interface;
- multiple model providers, including OpenAI-compatible APIs, native Anthropic, local endpoints, and Claude Code account auth;
- configurable `fast`, `standard`, and `advanced` model profiles;
- a synchronous model/tool conversation loop;
- a small stable tool registry;
- SQLite sessions, messages, routing decisions, and capability progress;
- durable user memory;
- progressive capability recommendations;
- clear tool approval boundaries;
- per-task model-call, token, and optional estimated-cost budgets;
- classified provider failures with bounded exponential retries;
- privacy-safe structured JSONL runtime logs;
- interruption and graceful shutdown;
- automated unit and local integration tests.

The MVP intentionally excludes subagents, browser automation, a desktop application, and hosted multi-user infrastructure. Those come after the local core is reliable.

The first messaging milestone is available: connector contracts, registry,
runtime dispatch, persistent platform-conversation session mapping, Telegram
setup with BotFather guidance and hidden token verification, and a foreground
gateway runner are implemented. Connect a model first, say `connect Telegram`,
then run `allpath-agent gateway` to receive and answer Telegram messages.

Slack is also supported through official Socket Mode. After Telegram—or
directly after model setup—say `connect Slack`, follow the in-chat Slack app
instructions, and enter the `xoxb-` Bot Token plus `xapp-` App-Level Token
through hidden inputs. Direct-message replies stay in the main conversation;
existing threads remain threaded, while channel replies start a thread to avoid
channel noise.

WhatsApp is supported through Meta's official Cloud API. Say `connect WhatsApp`
and provide the Access Token, Phone Number ID, App Secret, and a verify token
through hidden inputs. Then run `allpath-agent gateway`, expose local port
`8787` through an HTTPS tunnel, and configure the Meta webhook callback as
`https://<public-host>/webhooks/whatsapp` with the same verify token. Subscribe
the WhatsApp webhook to `messages`. Telegram, Slack, and WhatsApp can run in the
same gateway process.

The WhatsApp connector deliberately does not use unofficial QR-code or
WhatsApp Web automation. The official Cloud API requires a Meta Business app,
a public HTTPS webhook, and compliance with Meta's messaging policies. The
current MVP handles inbound and outbound text inside the customer-service
window; proactive conversations may require an approved message template.

## Architecture

```text
Terminal UI
    |
Application service
    |-- Agent loop
    |-- Model router
    |-- Tool registry
    |-- Capability curriculum
    |-- Setup workflow engine
    `-- SQLite repository
```

Planned package layout:

```text
src/allpath_agent/
├── agent/          # Conversation loop, prompts, task lifecycle
├── models/         # Provider interface and model routing
├── tools/          # Stable tool schemas and handlers
├── curriculum/     # Capability catalog and learning engine
├── workflows/      # Resumable setup and authorization flows
├── connectors/     # Future external services and channels
├── storage/        # SQLite repositories and migrations
├── api/            # Future local API
└── cli/            # Local terminal experience
```

Detailed design is documented in [Architecture](docs/ARCHITECTURE.md) and [Product design](docs/PRODUCT_DESIGN.md).

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/dukesky/allpath-agent/main/scripts/install.sh | sh
```

The installer manages Python and the virtual environment, installs the `allpath-agent` command, and opens the first local conversation. No API key or setup wizard is required to begin.

For local development from this checkout:

```bash
./scripts/install.sh --local
```

## Development setup

Requirements:

- Python 3.11 or newer
- A virtual environment
- Credentials for at least one configured live provider, or an authenticated Claude Code installation

```bash
cd /Users/tianzhang/Projects/allpath-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run tests:

```bash
python scripts/run_tests.py
```

The underlying standard-library suite can also run directly:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Run directly. Without a provider configuration, Allpath automatically enters deterministic local starter mode:

```bash
allpath-agent
```

Starter mode requires no API key and exercises natural arithmetic, time, memory, tools, approvals, SQLite persistence, and session resume. It follows Chinese or English input, answers capability questions directly, and explains when a request requires real model reasoning. Real-model routing lessons remain unavailable until a provider is connected. `allpath-agent --demo` remains available when explicit starter behavior is useful.

Connect a live provider from the conversation:

```text
You> connect a model
```

Allpath guides provider and model selection, uses hidden input for API keys, verifies the connection, and switches the current session to live mode. `allpath-agent init` remains available as a manual configuration fallback.

After a provider is connected, run normally:

```bash
allpath-agent
```

Useful commands:

```bash
allpath-agent providers
allpath-agent sessions
allpath-agent --session <session-id> --demo
allpath-agent --help
```

Inside chat, use `/new`, `/sessions`, `/resume <session-id>`, `/model`, `/models`, `/route`, `/capabilities`, `/dismiss`, `/help`, or `/exit`.

`/models` opens an arrow-key management menu that shows all three routing
roles, adds or replaces a connection, tests every configured model, moves a
model into an unconfigured role, and safely removes a role after confirmation.
The last model role cannot be removed. If removing a role leaves its provider
unused, the provider configuration is removed while its saved credential is
retained to avoid destructive secret deletion.

For scripting or terminals without interactive selection, use:

```text
/models test
/models move fast standard
/models remove advanced
/route
```

`/route` explains the latest decision in the current session, including the
role, routing reason, provider, and model ID.

`/model` is the authoritative current-runtime view. It reports the most
recently used role, provider, exact configured model ID, Allpath tool-schema
availability, and provider sandbox boundary. Natural-language model identity
questions receive the same runtime facts in the system prompt so the model
does not need to guess its backend identity.

## Configuration direction

Behavioral settings live in `~/.allpath-agent/config.toml`. Secrets such as API keys are loaded from the environment and are never written into conversation history or SQLite message content.

Each model profile names the provider that executes it. This allows cheap tasks and advanced tasks to use different vendors:

```toml
[providers.openai]
protocol = "openai_chat_completions"
auth = "api_key"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
timeout_seconds = 60.0

[providers.anthropic]
protocol = "anthropic_messages"
auth = "api_key"
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"
timeout_seconds = 60.0

[agent]
max_model_calls = 12
max_task_tokens = 100000
max_task_cost_usd = 0.0
provider_max_attempts = 3
retry_base_delay_seconds = 0.5
retry_max_delay_seconds = 8.0

[models.fast]
provider = "openai"
model = "gpt-4.1-mini"
quality = 4
cost = 1
supports_tools = true
supports_vision = false
max_context_tokens = 32000
input_cost_per_million = 0.0
output_cost_per_million = 0.0

[models.advanced]
provider = "anthropic"
model = "claude-sonnet-4-5"
quality = 10
cost = 8
supports_tools = true
supports_vision = true
max_context_tokens = 128000
input_cost_per_million = 0.0
output_cost_per_million = 0.0
```

Set model prices from the provider's current pricing page before enabling a nonzero cost budget. Runtime events are written to `~/.allpath-agent/logs/agent.jsonl` without conversation content, tool arguments, or credentials.

## Documentation

- [Product design](docs/PRODUCT_DESIGN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Installation](docs/INSTALLATION.md)
- [Model providers and authentication](docs/PROVIDERS.md)
- [Connector architecture](docs/CONNECTORS.md)
- [Conversational model setup](docs/CONVERSATIONAL_MODEL_SETUP.md)
- [Task budgets and structured logs](docs/BUDGETS_AND_LOGS.md)
- [Failure recovery](docs/FAILURE_RECOVERY.md)
- [MVP implementation plan](docs/MVP_PLAN.md)
- [Validation strategy](docs/VALIDATION.md)
- [Change log](CHANGELOG.md)

## Change discipline

Every meaningful change must update [CHANGELOG.md](CHANGELOG.md) under `Unreleased`. Released entries are grouped by version and date. The log records user-visible behavior, architecture decisions, fixes, tests, and documentation changes without duplicating commit-level noise.

Every change must also pass the same validation command locally and in GitHub Actions. See [Validation strategy](docs/VALIDATION.md) for the milestone-specific evidence required before work is considered complete.

## Design reference

Hermes Agent remains a read-only learning reference in the neighboring `hermes-agent` project. All Allpath Agent source code, tests, documentation, configuration, and assets belong in this repository.

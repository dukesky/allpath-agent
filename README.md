# Allpath Agent

Allpath Agent is a small personal AI agent that runs locally, learns its user's preferences, progressively teaches its own capabilities, and routes each task to an appropriate model.

The project is inspired by architectural lessons from Hermes Agent, but it is an independent implementation with a deliberately smaller core and a conversation-first onboarding experience.

## Project status

**Current phase:** MVP core implementation — persistence and the first Agent Loop are complete.

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

### Narrow core, capabilities at the edges

The core owns conversation state, model calls, tool execution, persistence, interruption, and workflow boundaries. Calendar, Slack, WhatsApp, and other integrations belong in connectors rather than inside the core loop.

## MVP scope

The first locally runnable MVP includes:

- a terminal chat interface;
- an OpenAI-compatible model provider;
- configurable `fast` and `advanced` model profiles;
- a synchronous model/tool conversation loop;
- a small stable tool registry;
- SQLite sessions, messages, routing decisions, and capability progress;
- durable user memory;
- progressive capability recommendations;
- clear tool approval boundaries;
- interruption and graceful shutdown;
- automated unit and local integration tests.

The MVP intentionally excludes Slack, WhatsApp, subagents, browser automation, a desktop application, and hosted multi-user infrastructure. Those come after the local core is reliable.

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

## Development setup

Requirements:

- Python 3.11 or newer
- A virtual environment
- An API key and endpoint for an OpenAI-compatible model provider once model execution is implemented

```bash
cd /Users/tianzhang/Projects/allpath-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run tests:

```bash
pytest
```

The core suite can also run before installing development dependencies:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The local run command will become:

```bash
allpath-agent
```

That command is part of the MVP acceptance criteria and is not implemented yet.

## Configuration direction

Behavioral settings will live in a local YAML configuration file. Secrets such as API keys will be loaded separately and will never be written into conversation history or SQLite message content.

Planned model configuration:

```yaml
models:
  fast:
    provider: openai_compatible
    model: example-fast-model
  advanced:
    provider: openai_compatible
    model: example-advanced-model

routing:
  default: fast
  allow_escalation: true
```

## Documentation

- [Product design](docs/PRODUCT_DESIGN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [MVP implementation plan](docs/MVP_PLAN.md)
- [Change log](CHANGELOG.md)

## Change discipline

Every meaningful change must update [CHANGELOG.md](CHANGELOG.md) under `Unreleased`. Released entries are grouped by version and date. The log records user-visible behavior, architecture decisions, fixes, tests, and documentation changes without duplicating commit-level noise.

## Design reference

Hermes Agent remains a read-only learning reference in the neighboring `hermes-agent` project. All Allpath Agent source code, tests, documentation, configuration, and assets belong in this repository.

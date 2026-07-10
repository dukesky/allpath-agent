# Architecture

## Shape

Allpath Agent starts as one Python process with internal modules, not a collection of microservices.

```text
User interface
    |
Application service
    |-- Agent loop
    |-- Model router
    |-- Tool registry
    |-- Capability curriculum
    |-- Setup workflow engine
    `-- SQLite repository
```

## Request lifecycle

1. Store the user message.
2. Inspect hard model requirements such as context size, modality, and tool support.
3. Score task complexity and select a model profile.
4. Run the model/tool loop with a stable prompt and stable tool schema.
5. Persist tool calls and the final response.
6. Record capability evidence from actual behavior.
7. After the task is complete, optionally select one contextual capability suggestion.

## Core boundaries

### Agent loop

Owns message ordering, model calls, tool execution, interruption boundaries, and final responses. It does not contain channel-specific logic or onboarding copy.

### Model router

First filters models by hard requirements, then ranks eligible profiles by task complexity, expected quality, cost policy, and user preference. A task pins its selected model. Escalation is monotonic for the remainder of that task.

### Tool registry

Tools provide stable schemas and handlers. Schemas are sorted by tool name so repeated requests remain byte-stable. Arguments are validated locally before a handler runs. Read-only tools execute directly, while side-effecting tools pass through an approval handler and persist the allowed or denied decision. The initial core remains deliberately small. External integrations are registered as connectors rather than added directly to the loop.

### Capability curriculum

Owns capability definitions and user learning state. It proposes lessons but cannot claim a setup succeeded. Success requires evidence emitted by a tool, connector, or verifier.

### Setup workflow engine

Owns resumable state machines for OAuth, QR pairing, secrets, and permission checks. Workflows are deterministic and persist their current step so application restarts do not lose progress.

### Storage

SQLite stores sessions, messages, tool executions, model decisions, workflow runs, connection metadata, and capability progress. Secrets are referenced from a separate encrypted store and are never written into message history.

## Prompt caching

The system prompt and tool schemas remain byte-stable during a conversation. Curriculum progress is not rewritten into the system prompt. Relevant state enters at turn boundaries through compact application context or explicit tool results.

Switching models generally loses provider-side prefix-cache reuse. The router therefore selects once per task and only escalates when necessary.

## Planned package layout

```text
src/allpath_agent/
  agent/
  curriculum/
  models/
  tools/
  workflows/
  connectors/
  storage/
  api/
```

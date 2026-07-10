# Local MVP Plan

## Objective

Deliver a testable agent that a developer can run locally from a terminal and use for a real multi-turn conversation. The MVP proves the agent loop, persistence, model routing, tools, memory, and progressive capability discovery before any messaging-platform work begins.

## Definition of done

The MVP is complete when all of the following can be demonstrated on a clean local installation.

### Startup and configuration

- `allpath-agent` starts an interactive terminal chat.
- The first launch creates an application home directory and SQLite database.
- Model profiles load from a documented local configuration file.
- API keys load separately from behavioral configuration.
- Missing or invalid configuration produces a conversational, actionable error.

### Conversation loop

- The user can hold a multi-turn conversation.
- System prompt and tool schemas remain stable for the conversation.
- Assistant messages, tool calls, tool results, and final responses preserve valid role ordering.
- A task stops at a configured iteration limit.
- Ctrl-C interrupts the active task without corrupting the session.

### Models

- At least `fast` and `advanced` profiles can be configured independently.
- Simple tasks route to `fast` under the default cost-saving policy.
- complex, high-risk, long-context, or explicitly deep tasks route to `advanced`.
- A running task can escalate once and remains pinned to the stronger model afterward.
- Every routing decision is persisted with a human-readable reason.

### Tools

- Tools are registered through a small stable registry.
- The model can invoke at least three useful tools.
- Tool arguments are validated before execution.
- Side-effecting tools require explicit approval.
- Tool failures return structured errors without crashing the conversation.

Initial tools should be:

1. current date and time;
2. durable memory read/write;
3. one local utility tool, selected when the loop is implemented.

### Persistence and memory

- SQLite stores sessions, messages, tool executions, routing decisions, and curriculum progress.
- The user can exit and resume a previous session.
- Durable preferences survive across sessions.
- Secrets are never stored in message history.
- Database migrations are versioned and tested.

### Progressive learning

- The curriculum contains at least eight capabilities across multiple levels.
- Prerequisites prevent advanced capabilities from being offered too early.
- At most one proactive capability suggestion appears per session.
- Dismissed capabilities enter a cooldown or remain suppressed.
- Successful real tool use updates capability progress.
- Suggestions are made after completing the current task, never instead of it.

### Tests

- Unit tests cover routing, curriculum scoring, tool validation, and storage repositories.
- Integration tests exercise a complete model -> tool -> model loop using a deterministic fake provider.
- Integration tests verify session resume and capability-state persistence against a temporary SQLite database.
- One manual smoke-test script documents the real-provider local run.
- GitHub Actions runs the shared validation suite on every push and pull request.

## Implementation sequence

### Milestone 1: Persistence foundation

Status: complete.

- Define SQLite schema and migration runner.
- Implement session, message, routing, memory, and curriculum repositories.
- Add temporary-database integration tests.

### Milestone 2: Provider and agent loop

Status: complete for the synchronous non-streaming loop; real-provider smoke testing remains deferred until configuration and CLI milestones.

- Define a provider-neutral chat interface.
- Implement an OpenAI-compatible provider.
- Implement strict message and tool-call lifecycle handling.
- Add deterministic fake-provider integration tests.

### Milestone 3: Tools and approvals

Status: complete for the core runtime; the interactive terminal approval prompt belongs to Milestone 4.

- Build the tool registry and argument validation.
- Add the first three tools.
- Add approval policy and structured tool failures.

### Milestone 4: Local CLI

Status: complete for local demo and OpenAI-compatible live mode. The real-provider smoke test remains before the MVP release.

- Add configuration loading and validation.
- Build the terminal conversation interface.
- Support session creation, listing, resumption, interruption, and graceful exit.

### Milestone 5: Curriculum integration

Status: complete with eight implemented capabilities, persistent evidence, one suggestion per session, cooldowns, dismissal, and CLI progress inspection.

- Define the first eight capability records.
- Convert successful actions into learning evidence.
- Add post-task contextual recommendations and cooldowns.

### Milestone 6: MVP hardening

- Add iteration and token budgets.
- Add structured local logs.
- Test recovery from provider, tool, and database failures.
- Run the real-provider smoke test and document known limitations.

## Explicitly deferred

- Slack and WhatsApp connectors;
- graphical onboarding cards and screenshots;
- web and desktop interfaces;
- scheduled background jobs;
- browser automation;
- subagents and multi-agent coordination;
- plugin marketplace;
- hosted accounts and multi-user isolation.

These features should not be started until the local MVP definition of done is met.

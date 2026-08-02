# Allpath Agent Evolution Plan

## Product direction

Allpath evolves from a conversation-first assistant into a small personal Agent system without losing its easiest differentiator: progressive, in-conversation onboarding.

The core remains narrow. Models, tools, skills, MCP servers, connectors, triggers, and user education integrate through stable contracts instead of being embedded in the Agent Loop.

## Current architecture

- SQLite persists sessions, messages, routing decisions, durable memory, curriculum progress, setup workflows, tool execution and approvals, connectors, and automation jobs/runs.
- The application analyzes each task, selects one model profile, records the routing decision, and starts the Agent Loop.
- The Agent Loop sends a stable system prompt, persisted conversation history, and eligible tool schemas to the selected model.
- Tool calls pass through validation, approval, execution logging, and a model continuation turn.
- Curriculum suggestions are stored separately from messages and appear only after the user's current task.

## Curriculum learning loop

Every capability follows:

```text
locked -> eligible -> offered -> tried -> succeeded -> habitual
                         \-> dismissed
```

- `offered`: Allpath surfaced a suggestion.
- `tried`: the user expressed relevant intent or started the flow.
- `succeeded`: deterministic evidence confirms successful use.
- `habitual`: successful use occurred repeatedly.
- `dismissed`: the user opted out; Allpath stops teaching it.

The Agent must never infer setup success from conversational wording alone. Evidence comes from tools, verified connections, routing records, workflow completion, connector health, or automation execution.

## Three retained teaching surfaces

1. **Launch guidance**: one high-value next step in the startup panel.
2. **Composer hint**: a short suggestion beside the input area, suppressed while setup or another workflow needs input.
3. **Post-task tip**: an occasional contextual suggestion after the current answer, limited to one per session with cooldown and dismissal.

These surfaces share curriculum state, but they do not inject changing curriculum text into the system prompt and do not interrupt the active task.

## Capability roadmap

### Stage 1: Onboarding foundation

- Make `tried`, `succeeded`, and `habitual` evidence-driven.
- Add messaging connectors and scheduled automations to the curriculum.
- Keep model connection first, then connectors, then proactive automation.
- Add diagnostics-oriented lessons when setup fails.
- Measure suggestions, attempts, verified successes, dismissals, and repeated use locally.

### Stage 2: Useful workspace tools

- Add workspace roots and read-only-by-default permissions. **Implemented for the CLI current directory.**
- Implement `read_file` and `search_files` first. **Implemented.**
- Add `write_file` and `patch` with approval, audit records, path traversal protection, symlink protection, size limits, and interruption-safe writes. **Implemented with atomic writes and SHA-256 conflict detection.**
- Add a bounded foreground terminal tool with cwd, timeout, output limits, command risk classification, and approval. **Implemented with an argv allowlist and no shell.**

### Stage 3: Skills

- Discover built-in, user, and project `SKILL.md` packages. **Implemented.**
- Use progressive disclosure through `skills_list` and `skill_view`. **Implemented.**
- Support safe relative supporting files and future `references/`, `templates/`, `scripts/`, and `assets/`. **Implemented.**
- Inject explicit skill invocations as user-turn context rather than mutating the system prompt. **Implemented.**
- Ship initial Skills for Connector setup, automations, and repository analysis. **Implemented.**

### Stage 4: MCP

- Support stdio MCP servers first. **Implemented with short-lived SDK sessions.**
- Discover tools and register them into the existing Tool Registry with names such as `mcp__server__tool`. **Implemented.**
- Namespace tools and treat MCP calls as approval-gated side effects. **Implemented.**
- Add timeout, schema normalization, secret allowlisting, and `/mcp` inspection. **Implemented.**
- Add HTTP transport, OAuth, resources, prompts, and dynamic refresh only after stdio is reliable.

### Stage 5: Proactive Agent behavior

- Generalize cron jobs through a typed Hook Bus carrying task, tool, Connector, and Automation events. **Hook foundation implemented; persistent user rules remain deferred.**
- Add completion notifications and destination-aware delivery.
- Generate reply suggestions only when useful and keep them separate from the user's authored message.
- Add daily briefs and recurring personal workflows as curriculum capabilities.

### Stage 6: Browser and computer tasks

- Add structured browser navigation, snapshots, element actions, and form approvals before raw desktop control. **Implemented: isolated profile, public-URL enforcement, stable element refs, approval-gated actions, controlled screenshots and downloads.**
- Add computer use last, disabled by default and preferably isolated from the user's primary desktop. **Safety contract documented; implementation deferred.**
- Require explicit confirmation for destructive, financial, authentication, and external-communication actions.

## Execution order

1. Complete the curriculum learning-state foundation.
2. Implement safe read-only workspace tools.
3. Add approved file mutation and bounded terminal execution.
4. Build the Skills loader on top of those tools.
5. Add stdio MCP through the same Tool Registry.
6. Generalize automations into hooks and conditional triggers.
7. Add browser and isolated computer-use capabilities.

Each stage requires unit tests, integration tests through the real application path, CLI behavior tests, documentation, and a changelog entry before moving forward.

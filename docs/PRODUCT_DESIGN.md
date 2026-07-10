# Product Design

## Product promise

Allpath Agent should be useful immediately. A user starts with a conversation, not a setup checklist. Configuration and education happen only when they unlock value for the task at hand.

## Principles

- Start with chat. Only model access is a hard prerequisite.
- Teach through useful work, never through a feature dump.
- Expose one new capability at a time.
- Preserve the user's original task across connection and authorization flows.
- Make every suggestion dismissible and apply cooldowns after rejection.
- Let deterministic code own permissions, connection state, and success verification.
- Let the model own intent understanding and natural language.
- Prefer a small stable core; add integrations at the edges.

## Capability curriculum

Each capability has prerequisites, teaching triggers, setup requirements, evidence of successful use, and a default priority.

User progress follows this lifecycle:

```text
locked -> eligible -> offered -> tried -> succeeded -> habitual
                         \-> dismissed
```

The curriculum recommends at most one proactive lesson per session. Recommendations are scored from:

- relevance to the current task;
- observed repeated need;
- commonness and expected user value;
- completed prerequisites;
- setup effort;
- recent suggestion fatigue;
- previous dismissal signals.

The first curriculum should contain four levels:

1. Immediate: chat, web lookup, summarization, writing.
2. Personal: memory, files, calendar, email.
3. Proactive: reminders, scheduled jobs, daily briefs, completion notifications.
4. Advanced: workflows, subagents, custom capabilities, and messaging channels.

## Conversational setup

When a task needs a missing connection, the agent offers an inline setup action. The UI may render OAuth buttons, QR codes, screenshots, or short step cards. The workflow engine verifies success and then resumes the original task.

Screenshots are curated, localized, and versioned. They are fallback guidance; deep links, OAuth, QR pairing, and automatic verification are preferred.

## Model experience

Users configure logical model profiles rather than hard-coding model names throughout the system:

- `fast`: cheap classification, rewriting, simple lookup, and lightweight conversation.
- `standard`: normal tool use and everyday planning.
- `advanced`: difficult reasoning, coding, long-horizon work, and high-risk decisions.

The router selects one profile at the beginning of a task. It may escalate upward when execution reveals unexpected difficulty, but it does not bounce between models during every tool call.

## MVP

The first useful release includes:

- one local chat surface;
- SQLite sessions and user memory;
- a provider-neutral model interface with OpenAI-compatible, native Anthropic, local, and account-auth adapters;
- `fast` and `advanced` model profiles;
- web lookup, memory, and one local utility tool;
- eight curriculum capabilities;
- one complete conversational connection flow;
- model routing with upward escalation;
- no Slack or WhatsApp until the local loop is reliable.

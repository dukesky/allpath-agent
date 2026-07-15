# Connector Architecture

Allpath connectors are edge adapters. They do not contain a second agent loop,
model router, memory system, or tool runtime.

## Contracts

Each platform normalizes inbound activity into `InboundMessage` and accepts
`OutboundMessage` replies. A connector exposes an ID, health status, polling,
and sending. `ConnectorRegistry` rejects duplicate IDs and provides stable
runtime lookup.

`ConnectorRuntime` performs the shared flow:

1. poll one platform adapter;
2. normalize platform events;
3. resolve a persistent `(connector, conversation) → session` binding;
4. create one Allpath session when no binding exists;
5. send the text through the existing `AgentApplication`;
6. deliver the answer through the originating connector.

The SQLite `connector_sessions` table preserves conversation continuity across
process restarts. Platform credentials do not belong in this table.

## Telegram reference adapter

`TelegramConnector` is the first reference implementation. It supports:

- bot identity verification through `getMe`;
- text update polling through `getUpdates`;
- monotonic update offsets;
- text-message normalization;
- reply delivery through `sendMessage`;
- reply-to message IDs;
- injected transport for deterministic offline tests;
- a standard-library HTTPS JSON transport for the future live runner.

Conversational bot-token setup and a foreground gateway runner are implemented.
Say `connect Telegram` after connecting a model, follow the BotFather guidance,
and enter the token through hidden input. Allpath verifies the bot with `getMe`
before storing the token and marking Telegram active.

Run:

```bash
allpath-agent connectors
allpath-agent gateway
```

`gateway` verifies the active bot, long-polls Telegram, preserves one Allpath
session per Telegram conversation, and replies through the same chat. Run
`allpath-agent gateway --once` for a one-cycle health/integration check.

The gateway is currently a foreground process. Background service installation,
bounded polling retry/backoff, and process supervision remain the next step.

## Safety boundaries

- Tokens are never included in normalized events, status details, messages, or
  test assertions.
- Platform metadata remains separate from user-visible text.
- Unsupported Telegram updates are skipped rather than guessed.
- One platform conversation maps to one persistent Allpath session.
- Platform adapters cannot bypass model routing, budgets, tool validation, or
  approvals.

## Next implementation

1. Add bounded polling retries and privacy-safe connector lifecycle logs.
2. Add background service installation and process supervision.
3. Add Telegram disconnect/rotate-token management.
4. Build the Slack adapter against the same contracts.

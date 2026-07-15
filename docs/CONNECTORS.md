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

The current milestone is the connector foundation. Conversational bot-token
setup, a managed long-running gateway command, retry/backoff, and process
supervision are intentionally the next step. Until those ship, the CLI must not
claim that Telegram is connected or ready for daily use.

## Safety boundaries

- Tokens are never included in normalized events, status details, messages, or
  test assertions.
- Platform metadata remains separate from user-visible text.
- Unsupported Telegram updates are skipped rather than guessed.
- One platform conversation maps to one persistent Allpath session.
- Platform adapters cannot bypass model routing, budgets, tool validation, or
  approvals.

## Next implementation

1. Add a resumable “connect Telegram” conversation workflow.
2. Store the bot token in the existing mode-`0600` secret store.
3. Verify with `getMe` before activation.
4. Add a foreground `allpath-agent gateway` runner with graceful shutdown.
5. Add bounded polling retries and privacy-safe connector lifecycle logs.
6. Advance startup onboarding to Telegram only after model setup is complete.

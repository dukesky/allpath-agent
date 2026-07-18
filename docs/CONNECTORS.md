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
Say `connect Telegram` after connecting a model. A four-step resumable guide
opens the official BotFather, creates the bot, selects a username, and safely
collects the token through hidden input. Allpath verifies the bot with `getMe`
before storing the token and marking Telegram active.

Run:

```bash
allpath-agent connectors
allpath-agent connectors --test
allpath-agent gateway
```

`connectors --test` and the in-chat `/connectors test` command report credential
presence, live platform verification, runtime readiness, and a corrective next
action without printing credential values. WhatsApp additionally checks whether
the local webhook listener is reachable on port `8787`.

`gateway` verifies the active bot, long-polls Telegram, preserves one Allpath
session per Telegram conversation, and replies through the same chat. Run
`allpath-agent gateway --once` for a one-cycle health/integration check.

The gateway can run in the foreground for debugging or as a per-user background
service. Bounded polling retry/backoff and richer process supervision remain
future reliability work.

Install the gateway as a per-user background service with:

```bash
allpath-agent gateway install
allpath-agent gateway status
allpath-agent gateway restart
allpath-agent gateway uninstall
```

macOS uses `~/Library/LaunchAgents/ai.allpath.gateway.plist`; Linux uses a user
systemd unit. Generated service files contain command paths and log locations,
but never connector credentials. Foreground `allpath-agent gateway` remains the
debugging path.

## Safety boundaries

- Tokens are never included in normalized events, status details, messages, or
  test assertions.
- Platform metadata remains separate from user-visible text.
- Unsupported Telegram updates are skipped rather than guessed.
- One platform conversation maps to one persistent Allpath session.
- Platform adapters cannot bypass model routing, budgets, tool validation, or
  approvals.

## Slack Socket Mode adapter

Slack uses the official Python Slack SDK and Socket Mode, so a local Allpath
installation does not need a public webhook URL. Setup requires two credentials:

- a Bot Token beginning with `xoxb-`;
- an App-Level Token beginning with `xapp-` and the `connections:write` scope.

The in-agent seven-step guide walks through Slack's app configuration:

1. Create an app at [Slack API apps](https://api.slack.com/apps).
2. Add the `chat:write` and `im:history` bot scopes.
3. Enable the App Home Messages tab.
4. Enable Event Subscriptions and subscribe to the `message.im` bot event.
5. Enable Socket Mode.
6. Create an App-Level Token with `connections:write`.
7. Install the app to the workspace and copy the Bot Token.
8. In Allpath, say `connect Slack` and enter both tokens through hidden input.
9. Restart `allpath-agent gateway`.

Allpath verifies the Bot Token with `auth.test` and verifies Socket Mode access
with `apps.connections.open` before activation. Socket envelopes are
acknowledged immediately, bot/subtype events are ignored, direct messages are
normalized into the shared connector contract, and replies remain in the
originating Slack thread.

Official references: [Slack Socket Mode client](https://docs.slack.dev/tools/python-slack-sdk/socket-mode/)
and [Python Slack SDK](https://docs.slack.dev/tools/python-slack-sdk/).

## WhatsApp Cloud API adapter

WhatsApp uses Meta's official Cloud API rather than unofficial QR-code or
WhatsApp Web automation. The nine-step resumable guide covers Meta Business app
creation, WhatsApp product setup, credentials, the local gateway, an HTTPS
tunnel, webhook verification, the `messages` subscription, and a real reply
test.

Credential verification and end-to-end verification are separate checkpoints.
Allpath first verifies the Access Token and Phone Number ID. It then keeps the
workflow active until the user configures `/webhooks/whatsapp`, subscribes to
`messages`, and confirms that a message sent from WhatsApp receives an Allpath
reply. Access tokens, App Secrets, and verify tokens use hidden input and never
enter workflow state.

## Next implementation

1. Add bounded polling retries and privacy-safe connector lifecycle logs.
2. Add background service installation and process supervision.
3. Add Telegram disconnect/rotate-token management.
4. Add channel mentions and explicit channel allowlists for Slack.

# Conversational Model Setup

Allpath connects its first or replacement model inside the normal chat instead of sending the user to a separate setup wizard.

Start with a natural request:

```text
You> connect a model
Agent [setup]> Let's connect a model in this conversation. Choose:
1. OpenAI API
2. Anthropic API
3. OpenRouter
4. Ollama (local)
5. Claude Code account
```

The workflow asks for a model ID, requests a credential only when the selected provider needs one, verifies a real response, writes configuration atomically, and rebuilds the running Agent application in live mode without changing the session.

## Authentication paths

- OpenAI, Anthropic, and OpenRouter request an API key through hidden terminal input.
- Ollama verifies its local OpenAI-compatible endpoint and requires no key.
- Claude Code invokes the existing authenticated `claude` command and never extracts its account token.

## Secret boundary

API keys are never submitted as ordinary chat messages. They are excluded from:

- session messages;
- workflow state in SQLite;
- JSONL runtime logs;
- `config.toml`.

Verified API keys are stored in `~/.allpath-agent/secrets.json` with file mode `0600`. The configuration stores only the environment-variable name used internally by the provider runtime.

The MVP secret store is local plaintext protected by operating-system file permissions. A future desktop or hosted edition should replace it with Keychain, Credential Manager, Secret Service, or another platform credential vault.

## Verification and failure safety

Before configuration changes, Allpath sends a minimal verification prompt through the selected provider. If verification fails:

- no new secret is persisted;
- the existing configuration remains unchanged;
- the workflow remains resumable at the credential or model step;
- the user can retry or type `cancel` / `取消`.

After verification succeeds, Allpath atomically replaces `config.toml`, marks the workflow succeeded, reloads the provider pool, and continues in the same session.

Workflow state is persisted in SQLite, so provider and model selection survive a process restart. Secret input is intentionally requested again after a restart because secrets are never placed in workflow state.

# Conversational Model Setup

Allpath connects its first or replacement model inside the normal chat instead of sending the user to a separate setup wizard.

Start with a natural request:

```text
You> connect a model
Agent [setup]> Let's connect a model in this conversation. Choose:
1. OpenAI API
2. OpenAI Codex / ChatGPT account
3. Anthropic API
4. xAI Grok API
5. Google Gemini API
6. OpenRouter
7. Ollama (local)
8. Claude Code account
```

In an interactive terminal, provider and model choices open an arrow-key picker.
Use `↑`/`↓`, Enter to select, Esc to cancel, and `/` to search the model list.
Non-interactive terminals retain the numbered/text fallback.

The workflow requests a credential only when the selected provider needs one,
verifies a real response, writes configuration atomically, and rebuilds the
running Agent application in live mode without changing the session.

## Authentication paths

- OpenAI, Anthropic, and OpenRouter request an API key through hidden terminal input.
- xAI Grok uses the official OpenAI-compatible xAI API with `XAI_API_KEY`.
- Google Gemini uses the official `generateContent` API with `GEMINI_API_KEY`.
- OpenAI Codex reuses the official Codex CLI. Allpath checks `codex login status`,
  starts `codex login` when necessary, and runs models through `codex exec`.
- Ollama verifies its local OpenAI-compatible endpoint and requires no key.
- Claude Code invokes the existing authenticated `claude` command and never extracts its account token.

Allpath never copies or stores Codex OAuth tokens. Codex model choices are read
from the official CLI's account-aware model cache and ordered by its priority
metadata. A curated list is used only when that cache is unavailable.

On macOS, Allpath compares the Codex executable on `PATH` with the executable
bundled in ChatGPT.app and uses the newer version. Provider failures such as an
outdated CLI, unavailable model, or account limit are shown directly and do not
trigger an automatic verification loop.

## Personal account OAuth boundary

Allpath does not reuse Gemini CLI personal OAuth. Google states that third-party
software must use Gemini API or Vertex AI instead of piggybacking on Gemini CLI
OAuth. xAI does not currently document a stable third-party OAuth contract for
Grok web-app subscriptions. Until an official contract exists, Allpath offers
API authentication only for Gemini and Grok and does not scrape cookies or copy
tokens from their apps.

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

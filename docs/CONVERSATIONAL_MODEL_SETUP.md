# Conversational Model Setup

Allpath connects and manages models inside the normal chat instead of sending the user to a separate setup wizard.

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

For API providers the workflow is credential-first:

1. choose a provider;
2. enter the API key through hidden input;
3. load the models available to that credential;
4. choose from the searchable model picker;
5. assign the model to `fast`, `standard`, or `advanced`;
6. verify a real response;
7. atomically save the secret and configuration.

The roles describe routing intent, not vendors. `fast` is optimized for cheap,
simple tasks, `standard` for balanced everyday work, and `advanced` for the
most complex tasks. Repeat “connect model” to configure another role. A
successful setup replaces only the selected provider entry and role while
preserving every other configured provider and model role.

The running Agent application then rebuilds in live mode without changing the
session.

## Managing connected models

Run `/models` inside chat to open the model-role manager. It displays
`fast`, `standard`, and `advanced` assignments and offers actions to add or
replace a model, test all connections, move a model to an empty role, remove a
role, or explain the latest routing decision. Removal requires confirmation,
cannot delete the final model role, and retains stored credentials.

Use `/route` after a response to inspect the selected role, reason, provider,
and model. Non-interactive equivalents are `/models test`,
`/models move <from> <to>`, and `/models remove <role>`.

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

After verification succeeds, Allpath atomically updates `config.toml`, marks the workflow succeeded, reloads the provider pool, and continues in the same session. Existing providers and model roles not selected by the current workflow remain unchanged.

Workflow state is persisted in SQLite, so provider, model, and role selection survive a process restart. Secret input is intentionally requested again after a restart because secrets are never placed in workflow state.

Discovered model IDs may be persisted in workflow state, but API keys never are.
If the process restarts after discovery but before verification, Allpath reuses
the safe model list and asks for the key again. If live catalog discovery is
unavailable, it shows a curated fallback list and still verifies the selected
model before saving anything.

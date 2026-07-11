# Installation

Allpath Agent uses a managed installation so users do not need to create or activate a Python environment manually.

## One-line installation

Linux and macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/dukesky/allpath-agent/main/scripts/install.sh | sh
```

The installer:

1. finds Python 3.11 or newer, or installs managed Python 3.11 through `uv`;
2. downloads Allpath Agent into `~/.allpath-agent/runtime/source`;
3. creates an isolated virtual environment under `~/.allpath-agent/runtime/venv`;
4. installs the package and creates `~/.local/bin/allpath-agent`;
5. adds that command directory to the user's shell PATH when necessary;
6. starts the first local conversation when a terminal is available.

Python still exists internally, but the installer owns it. Users do not activate the virtual environment or run `pip` themselves.

## Local checkout installation

From this repository:

```bash
./scripts/install.sh --local
```

Local mode creates the same isolated runtime but links its import path directly to the current checkout. Code edits are therefore visible on the next launch without reinstalling. It does not download packages and is intended for local development and MVP testing.

To install without immediately opening chat:

```bash
./scripts/install.sh --local --skip-launch
allpath-agent
```

The installer is idempotent. Running it again preserves sessions and local data under `~/.allpath-agent`.

## First launch

If no provider configuration exists, `allpath-agent` automatically enters local starter mode. It does not stop at a setup wizard and does not require an API key.

Starter mode validates tools, natural arithmetic, time, memory, sessions, routing, approvals, budgets, interruption recovery, and capability education using a deterministic local provider. It recognizes common English and Chinese arithmetic phrasing and presents tool results in user-facing language. When a request needs general reasoning, it states that limitation instead of echoing the input or pretending to understand it.

Starter responses follow the language of the user's latest message for Chinese and English. Explicit questions such as “what can you do?” or “你能做什么？” receive a direct capability summary. Capabilities that require a real model, including meaningful advanced-model routing, are marked unavailable and are not proactively taught until a live provider is configured.

When the user asks about connecting a model, the starter provider answers directly with supported options and the current provider setup step. This explicit answer is independent of the one-proactive-tip-per-session curriculum limit. Real providers remain optional until the user wants them.

## Custom paths

```bash
./scripts/install.sh --local \
  --home /tmp/allpath-home \
  --install-dir /tmp/allpath-runtime \
  --bin-dir /tmp/allpath-bin \
  --skip-launch \
  --no-path-update
```

These options support isolated tests and managed deployments without modifying the normal user installation.

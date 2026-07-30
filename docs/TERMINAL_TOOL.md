# Bounded Terminal Tool

Allpath exposes one `terminal` tool for foreground project commands. It intentionally does not expose a general shell.

## Contract

- Commands are argv arrays such as `["git", "status", "--short"]`.
- Every command requires explicit approval.
- The working directory defaults to the CLI startup directory and may only move to a real, non-symlinked subdirectory.
- Timeout defaults to 30 seconds and is capped at 120 seconds.
- Standard output and error are each capped at 20,000 characters.
- Timeout terminates the whole process group, then escalates to a forced kill if needed.
- Model API keys, Connector tokens, and other application secrets are removed from the child environment.

## Allowed executables

The MVP allowlist covers inspection and common development commands including Git, Python, pytest, Node, npm, ripgrep, find, sed, jq, and basic text utilities.

There is no `bash`, `zsh`, `sh`, arbitrary executable path, pipe, redirect, command substitution, or background process support. Destructive Git actions such as reset and clean are blocked even after approval.

This is intentionally narrower than Hermes. Allpath will expand the allowlist from concrete user needs rather than start with unrestricted shell execution.

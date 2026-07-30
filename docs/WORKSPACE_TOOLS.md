# Workspace File Tools

## Goal

Allpath can now inspect the project directory where it was started. This is the first step from a conversation-oriented assistant toward a workspace Agent.

The workspace layer includes read-only inspection plus approval-gated `write_file` and `patch`. Terminal execution remains a separate milestone.

## Workspace boundary

- The CLI registers its current working directory as the workspace root.
- Tool paths must be relative to that root.
- Absolute paths and `..` traversal are rejected.
- Paths passing through symbolic links are rejected, even when the target points back into the workspace.
- Registry construction accepts explicit roots so tests and future services do not receive ambient filesystem access by default.

Start Allpath in the project you want it to understand:

```bash
cd /path/to/project
allpath-agent
```

Then ask, for example:

```text
Read README.md and explain this project.
Search the Python files for ModelRouter and summarize where it is used.
```

## `read_file`

`read_file` reads UTF-8 text with optional `start_line` and `max_lines` bounds.

Safety limits:

- 100,000 bytes per file;
- 2,000 lines per call;
- binary and invalid UTF-8 files rejected;
- credential-like files rejected.

The result includes relative path, selected line range, total line count, and a truncation flag.
It also returns a SHA-256 digest for safe follow-up mutations.

## `search_files`

`search_files` performs case-insensitive literal text search and supports an optional relative glob.

Safety limits:

- 200 matches per call;
- 5,000 scanned files per call;
- 1,000,000 bytes per searched file;
- 500 characters per matching line excerpt;
- `.git`, virtual environments, `node_modules`, and Python caches skipped;
- binary, unreadable, oversized, symlinked, and credential-like files skipped.

## Credential boundary

The workspace tools do not expose common credential files, including:

- `.env` and `.env.*`;
- `secrets.json` and `credentials.json`;
- `.ssh` and `.gnupg` directories;
- common private-key and certificate containers.

Allpath provider and connector secrets remain outside the model-visible conversation and tool results.

## `write_file`

`write_file` creates or replaces one UTF-8 text file after explicit approval.

Rules:

- content is limited to 100,000 UTF-8 bytes;
- parent directories must already exist;
- replacing an existing file requires `expected_sha256` from `read_file`;
- a changed or stale file is rejected instead of overwritten;
- writes use a temporary file, file flush, `fsync`, permission preservation, and atomic `os.replace`;
- approval decisions and tool results are recorded in SQLite.

## `patch`

`patch` performs exact text replacement after explicit approval.

The caller provides:

- relative `path`;
- exact `old_text`;
- replacement `new_text`;
- `expected_sha256` from the latest read;
- optional `expected_occurrences`, defaulting to one.

The mutation fails if the file changed or if the old text appears a different number of times. This avoids ambiguous edits and accidental broad replacement.

## Approval display

The terminal shows the tool name, description, and arguments before asking for approval. Long string arguments are previewed with a 4,000-character display bound so a large replacement cannot flood the terminal. The original bounded tool arguments remain in the local SQLite audit record.

## Deferred terminal boundary

The next workspace milestone adds bounded foreground terminal execution with command classification, timeout, output limits, cwd control, interruption handling, and approval for risky commands.

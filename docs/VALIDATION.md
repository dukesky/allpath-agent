# Validation Strategy

Every implementation milestone must produce evidence that it works. A change is not complete only because its code has been written.

## Quality gate

Every meaningful change must satisfy all applicable checks before it is considered complete:

1. Public behavior and invariants are covered by tests.
2. The complete local validation suite passes.
3. Existing tests continue to pass.
4. `CHANGELOG.md` records the meaningful change under `Unreleased`.
5. Design or usage documentation is updated when a contract changes.
6. GitHub Actions passes on every supported Python version.

The shared validation command is:

```bash
python scripts/run_tests.py
```

It compiles the source and test trees before running the standard-library test suite. The same command runs locally and in CI.

After installing the package, CI also launches the real `allpath-agent` console entrypoint and completes one offline demo conversation.

## Validation layers

### Unit tests

Use unit tests for deterministic rules and small contracts:

- model eligibility and routing scores;
- curriculum prerequisites, scoring, cooldowns, and dismissal;
- message and tool-call validation;
- tool argument validation;
- approval-policy decisions.

### Integration tests

Use real internal components with temporary local resources:

- SQLite migrations and repositories against a temporary database;
- provider -> Agent Loop -> tool -> provider cycles with `FakeProvider`;
- session persistence and reconstruction;
- structured tool and provider failures.

Mocks should not replace SQLite or repository behavior when the integration itself is what needs proof.

### End-to-end tests

Once the CLI exists, launch it as a subprocess and verify:

- first startup;
- multi-turn input and output;
- session creation and resume;
- interruption and graceful exit;
- invalid configuration errors;
- a deterministic fake-provider conversation.

These subprocess checks are now part of the default validation suite and run in CI.

### Real-provider smoke tests

Real API tests are intentionally separate from default CI because they require secrets, cost money, and depend on external services. Before an MVP release, run a documented smoke test that verifies:

- authentication;
- one normal response;
- one real tool call;
- persisted session resume;
- no API key appears in logs or stored messages.

## Milestone evidence

### Milestone 1: Persistence

- Fresh database initialization.
- Idempotent migration execution.
- Repository round trips.
- Foreign-key enforcement.
- Session and memory persistence.

### Milestone 2: Provider and Agent Loop

- OpenAI-compatible payload serialization and response parsing.
- Deterministic fake-provider conversations.
- Assistant tool-call and tool-result history reconstruction.
- Structured tool failures.
- Model-call iteration limit.

### Milestone 3: Tools and approvals

- Unknown tools are rejected.
- Invalid arguments never reach handlers.
- Read-only tools can execute under policy.
- Side-effecting tools cannot execute without explicit approval.
- Approval and denial are persisted and returned to the model.

### Milestone 4: CLI

- Subprocess-based local E2E tests.
- Session list and resume behavior.
- Ctrl-C interruption without database corruption.
- Clean first-run configuration errors.

### Milestone 5: Curriculum

- At most one proactive recommendation per session.
- Prerequisites prevent premature lessons.
- Dismissal and cooldown behavior.
- Real successful actions advance learning state.
- Current work completes before a lesson is suggested.

## Supported environments

CI validates Python 3.11, 3.12, and 3.13 on Linux. Local macOS validation is performed during development. Additional operating systems can be added when platform-specific behavior enters the MVP.

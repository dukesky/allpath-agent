# Changelog

All meaningful changes to Allpath Agent are recorded in this file.

The format follows Keep a Changelog conventions. During development, changes accumulate under `Unreleased`. When a release is cut, those entries move into a versioned section with an ISO date.

## Unreleased

### Added

- Established Allpath Agent as an independent project from Hermes Agent.
- Added the initial product design for conversation-first onboarding and progressive capability discovery.
- Added the initial single-process architecture and package boundaries.
- Added a model router with hard requirement filtering and complexity-based selection.
- Added a capability curriculum engine with prerequisites, relevance scoring, fatigue penalties, and dismissal handling.
- Added initial tests for model routing and curriculum recommendations.
- Added a complete project README with goals, architecture, setup direction, and MVP scope.
- Added a testable local MVP implementation plan and acceptance criteria.
- Added a versioned SQLite migration runner with foreign keys, WAL mode, and idempotent initialization.
- Added repositories for sessions, messages, model-routing decisions, durable memory, capability progress, and tool execution records.
- Added the initial persistent workflow-run schema for future resumable setup flows.
- Added storage integration tests against temporary SQLite databases.
- Made the complete test suite compatible with Python's standard-library `unittest` runner as well as `pytest`.
- Added provider-neutral chat request, response, message, and tool-call contracts.
- Added a synchronous OpenAI-compatible provider with injectable transport and structured provider errors.
- Added a deterministic fake provider for full local integration tests without API access.
- Added the first persistent Agent Loop with model-call limits, tool execution, structured tool failures, and resumable message history.
- Added a message metadata migration so assistant tool calls survive session persistence and reconstruction.
- Added lifecycle validation for assistant tool calls and matching tool-result messages.
- Added GitHub Actions CI across Python 3.11, 3.12, and 3.13.
- Added one shared local and CI validation command that compiles source files and runs the complete test suite.
- Added milestone-specific validation standards covering unit, integration, E2E, and real-provider smoke tests.

### Changed

- Defined the first release as a locally runnable terminal agent before messaging-channel integrations.

### Fixed

- None.

## Update rules

Update this file whenever a change affects:

- user-visible behavior;
- public configuration or commands;
- architecture or persistent data;
- model-routing or curriculum behavior;
- security and permissions;
- tests or documented guarantees.

Do not add entries for formatting-only edits or temporary local experiments.

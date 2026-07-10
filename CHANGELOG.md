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

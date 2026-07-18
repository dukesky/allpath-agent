# Next Phase Plan: Self-Serve Connectors and Automations

Updated: 2026-07-18

## Objective

Move Allpath Agent from a developer-assisted MVP to a self-serve personal
agent that a new user can install, connect to messaging channels, keep running,
and schedule without leaving the conversation to search for instructions.

## Milestone 1: Guided connector onboarding

Apply the shared `ConnectorOnboardingGuide` to Slack, WhatsApp, and Telegram.

Acceptance criteria:

- each step names the exact external page, control, permission, or command;
- only one coherent external action is requested at a time;
- progress is visible as `current/total`;
- `continue`, `back`, `status`, and `cancel` work in English and Chinese;
- setup resumes at the same non-secret step after process restart;
- credentials use hidden input and never enter messages or workflow state;
- credential verification and end-to-end message verification are described as
  separate checkpoints;
- successful setup explains the exact command or user action required next.

## Milestone 2: Connector diagnostics

Add one shared diagnostic report for configured channels.

Acceptance criteria:

- report stored credential presence without revealing values;
- run platform credential or connection verification;
- report gateway reachability separately from provider authentication;
- provide platform-specific corrective actions for common failures;
- support a safe outbound/inbound test procedure where the platform permits it.

## Milestone 3: Background gateway service

Add platform-appropriate commands to install, inspect, restart, and remove a
per-user gateway service.

Acceptance criteria:

- macOS uses a user LaunchAgent;
- Linux uses a user systemd service when available;
- generated service files contain no credentials;
- status and logs are discoverable from the Allpath CLI;
- installation is idempotent and removal is safe;
- foreground `allpath-agent gateway` remains available for debugging.

## Milestone 4: Minimal automation system

Implement persistent scheduled prompts without adding scheduler logic to the
agent loop.

Acceptance criteria:

- create, list, enable, disable, run-now, and delete jobs;
- support one-time and cron-expression schedules;
- execute jobs through the existing application, routing, tools, and budgets;
- preserve one session per recurring job;
- record execution status, timestamps, and concise errors in SQLite;
- require explicit destination configuration before sending results to a
  messaging connector.

## Validation sequence

1. deterministic workflow and adapter unit tests;
2. CLI integration tests with temporary Allpath homes;
3. full local suite through `python3 scripts/run_tests.py`;
4. real account smoke tests for Telegram, Slack, and WhatsApp;
5. background-service restart test;
6. scheduled-job run-now and due-job integration tests.

Real WhatsApp end-to-end testing is a user-assisted checkpoint because it
requires the user's Meta Business account, public HTTPS tunnel, and phone
number configuration.

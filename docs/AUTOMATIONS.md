# Minimal Automation System Design

Updated: 2026-07-18

## Goal

Let a user create a small recurring or one-time agent task through conversation
without introducing a second agent core or embedding scheduler behavior inside
the conversation loop.

Examples:

- “Every weekday at 8 AM, prepare my daily plan.”
- “In two hours, remind me to send the proposal.”
- “Every Friday afternoon, summarize this week's project session.”

## Architecture

```text
CLI conversation / future messaging approval
    -> AutomationService
        -> AutomationRepository (SQLite)
        -> Schedule parser

Automation runner process
    -> claim due jobs
    -> existing AgentApplication
    -> existing model router, tools, budgets, sessions
    -> optional connector destination
    -> AutomationRunRepository (SQLite)
```

The runner is an edge service. It calls the same `AgentApplication` used by the
CLI and connector gateway. It does not own model clients, memory, tools, or a
second conversation loop.

## Initial commands

```text
/automations
/automations add
/automations run <job-id>
/automations enable <job-id>
/automations disable <job-id>
/automations delete <job-id>
```

The first implementation may also expose equivalent terminal commands for
deterministic testing:

```bash
allpath-agent automations list
allpath-agent automations run <job-id>
allpath-agent automations tick
```

Conversational creation is a resumable workflow: say “create automation” (or
`/automations add`), answer name, task, schedule, timezone, and destination
prompts, review the echoed summary, and type “confirm” before anything is
saved. Destinations are chosen from conversations Allpath has already seen on
a connected channel; message the bot once to register one.

Creation also works from inside a connected messaging channel: send
`/automations add` (or say “create automation”) to the bot. The same guided
flow runs there, and the delivery destination is preselected as the
conversation you are typing in, so results come back to the same chat.
`/automations` lists jobs from the channel as well.

## SQLite model

### `automation_jobs`

- `id`: stable UUID;
- `name`: short user-visible name;
- `prompt`: exact user-approved task instruction;
- `schedule_kind`: `once` or `cron`;
- `schedule_expression`: ISO timestamp or five-field cron expression;
- `timezone`: required IANA timezone;
- `session_id`: stable session reused across executions;
- `model_role`: `auto`, `fast`, `standard`, or `advanced`;
- `destination_connector_id`: nullable;
- `destination_conversation_id`: nullable;
- `enabled`: boolean;
- `next_run_at`, `last_run_at`, `created_at`, `updated_at`.

### `automation_runs`

- `id`, `job_id`, `task_id`;
- `status`: `claimed`, `running`, `succeeded`, `failed`, or `interrupted`;
- `scheduled_for`, `started_at`, `completed_at`;
- `error_type`, `error_message` with bounded, credential-free text;
- `output_message_id` when delivered through a connector.

## Execution invariants

- one runner atomically claims one due execution;
- a run has one terminal transition;
- retries create explicit attempts and never duplicate an already delivered
  connector message;
- one-time jobs disable after their first terminal execution; failed output is
  retained and can be retried explicitly with `run`;
- recurring jobs calculate the next run in the configured timezone;
- missed runs coalesce to one execution by default instead of replaying an
  unbounded backlog;
- disabled jobs cannot be claimed;
- all model and tool budgets remain active;
- side-effecting tools remain default-deny for unattended jobs until the user
  explicitly approves a durable policy in a future milestone.

## Delivery safety

The MVP supports local result persistence first. Connector delivery is enabled
only when both connector and conversation IDs were explicitly selected and the
connector remains active. A delivery failure marks the run failed and retains
the generated answer for inspection; it does not silently discard work.

## Implementation slices

1. SQLite migrations and repositories.
2. Deterministic schedule parsing and next-run calculation.
3. Create/list/enable/disable/delete service API.
4. `run-now` and one `tick` claim/execute path.
5. CLI commands and conversational confirmation workflow.
6. Background runner integration and connector delivery.
7. Real-timezone, interruption, duplicate-claim, and restart tests.

## Implemented MVP slice

The first executable slice now includes migrations 8, persistent jobs and runs,
five-field cron parsing, timezone-aware one-time schedules, atomic due-job
claims, run-now/tick execution through the existing `AgentApplication`, local
output/error retention, and terminal CLI management.

```bash
allpath-agent automations list
allpath-agent automations add-once --name "Reminder" --prompt "Remind me to send the proposal" --at "2026-08-01T09:00" --timezone America/Los_Angeles
allpath-agent automations add-cron --name "Daily plan" --prompt "Prepare my daily plan" --cron "0 8 * * 1-5" --timezone America/Los_Angeles
allpath-agent automations run <job-id>
allpath-agent automations tick
allpath-agent automations enable <job-id>
allpath-agent automations disable <job-id>
allpath-agent automations delete <job-id>
```

Conversational creation, gateway execution, and connector delivery are now
implemented. The gateway (foreground `allpath-agent gateway` or the installed
background service) drains due jobs after each connector poll, so no external
cron invocation of `tick` is required; `tick` remains available for debugging.
Results are delivered when a job carries an explicitly configured destination
connector and conversation; a delivery failure marks the run failed with
`DeliveryError` while retaining the generated output. Unattended runs keep
side-effecting tools default-denied; a denied request marks the run
“needs attention” in run records and CLI output instead of failing silently.

## Explicitly deferred

- distributed schedulers and multi-machine leases;
- visual calendar builders;
- arbitrary Python or shell as the schedule payload;
- automatic durable approval of side-effecting tools;
- complex retry policies and dead-letter queues;
- calendar-triggered, email-triggered, or webhook-triggered automations.

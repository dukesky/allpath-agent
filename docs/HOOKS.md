# Hook Bus and Proactive Triggers

Allpath now has a typed in-process Hook Bus. It is the narrow event boundary for future conditional triggers, reply suggestions, notifications, and plugins.

## Current events

The Agent Loop already emits task, model, and tool lifecycle events through the Hook Bus. Additional product events include:

- `connector_message_received`;
- `connector_reply_sent`;
- `automation_run_completed`.

Message text, model output, tool arguments, and credentials are intentionally absent from Connector and Automation hook metadata.

## Conditions

Subscribers may register for one event or all events and provide exact field conditions such as `status=failed` or `connector_id=slack`. A failing handler is isolated and recorded without stopping later handlers or the user's task.

## Current boundary

The bus is implemented and used internally. Persistent user-authored conditional rules, arbitrary hook scripts, and automatic reply generation are not enabled yet. Those require loop prevention, cooldowns, budgets, approvals, delivery guarantees, and clear UI before they are safe product features.

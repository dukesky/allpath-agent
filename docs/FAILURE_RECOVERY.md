# Failure Recovery

Allpath retries only failures that are likely to succeed without changing the request. The same model, messages, and stable tool schema are reused for every attempt.

## Retry policy

| Failure | Retry |
|---|---|
| Request or external CLI timeout | Yes |
| Network connection failure | Yes |
| HTTP 429 rate limit | Yes |
| HTTP 5xx provider failure | Yes |
| HTTP 401/403 authentication failure | No |
| Other HTTP 4xx request failure | No |
| Invalid JSON, message, or tool-call response | No |
| Local configuration or tool validation failure | No |

```toml
[agent]
provider_max_attempts = 3
retry_base_delay_seconds = 0.5
retry_max_delay_seconds = 8.0

[providers.openai]
timeout_seconds = 60.0
```

API providers default to 60 seconds. External CLI providers default to 300 seconds because local application startup and account-backed inference can take longer.

Retries use exponential backoff and honor a numeric HTTP `Retry-After` value, bounded by `retry_max_delay_seconds`. Every attempt counts toward `max_model_calls`, including failed attempts, so retries cannot bypass the task budget.

Structured logs emit `model_call_retry_scheduled` for retry decisions and `model_call_failed` when no safe attempt remains. They record only error types and timing metadata, not provider response bodies.

## Interruption recovery

If Ctrl-C arrives during a tool call:

1. the active `tool_executions` row becomes `interrupted`;
2. every unresolved tool call receives an `Interrupted` tool-result message;
3. the turn receives a final assistant interruption message;
4. a `task_interrupted` event is written;
5. the session remains valid for the next user message.

This repair lives in the Agent Loop rather than the CLI, so future interfaces receive the same message-lifecycle guarantee.

## Current boundary

Allpath does not automatically retry side-effecting tools. A model provider request can be repeated safely because it has not yet executed an Allpath tool. Once a tool starts, its own result or interruption state is persisted instead of silently running it again.

Database write recovery and a real-provider smoke-test matrix remain part of the final MVP hardening work.

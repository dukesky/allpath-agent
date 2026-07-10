# Task Budgets and Structured Logs

Allpath applies a fresh budget to every user task. Budgets prevent a tool loop from continuing after its configured model-call, token, or estimated-cost limit is reached.

## Configuration

```toml
[agent]
max_model_calls = 12
max_task_tokens = 100000
max_task_cost_usd = 1.0
provider_max_attempts = 3

[models.fast]
input_cost_per_million = 0.4
output_cost_per_million = 1.6
```

Use the current prices published by the selected provider. Allpath does not hard-code prices because vendors can change them. A zero token or cost limit disables that limit. A zero model price records tokens but produces a zero cost estimate.

Providers report usage using different keys. Allpath normalizes OpenAI-style `prompt_tokens` and `completion_tokens` and Anthropic-style `input_tokens` and `output_tokens` into one task total.

Limits are checked before each model call and before executing requested tools. A single provider response can exceed the remaining budget because its exact output size is unknown before the request. If that response is a final answer, Allpath returns it rather than discarding work already completed. If it requests tools, Allpath stops before executing them or making another model call.

Transient retry attempts also count as model calls. See [Failure recovery](FAILURE_RECOVERY.md) for classification and backoff behavior.

If a provider does not report usage, model-call limits still work, but token and estimated-cost limits cannot account for that response. The CLI only displays usage when the provider reports it.

## Structured logs

Runtime events are appended as JSON Lines to:

```text
~/.allpath-agent/logs/agent.jsonl
```

Events include task start/completion/failure, model-call duration and usage, and tool-call status. They include session and task IDs, provider, model, counters, durations, and error types.

Logs deliberately exclude:

- user and assistant message content;
- system prompts;
- API keys and OAuth credentials;
- tool arguments and tool results;
- provider error response bodies.

Logging failures are isolated from agent execution. If the log path is temporarily unavailable, the current task continues.

Inspect recent events with standard local tools:

```bash
tail -n 20 ~/.allpath-agent/logs/agent.jsonl
tail -f ~/.allpath-agent/logs/agent.jsonl
```

# Model Providers and Authentication

Allpath Agent separates model selection, wire protocol, and authentication. A model profile selects a provider by ID; the Provider Pool owns the protocol adapter and credential source for that provider.

## Supported provider modes

| Protocol | Authentication | Current use |
|---|---|---|
| `openai_chat_completions` | `api_key` | OpenAI API, OpenRouter, and compatible gateways |
| `openai_chat_completions` | `none` | Local servers such as Ollama's OpenAI-compatible endpoint |
| `anthropic_messages` | `api_key` | Native Anthropic Messages API |
| `external_cli` | `external_cli` | An already authenticated Claude Code installation |

Run `allpath-agent providers` after creating a configuration. It prints provider IDs, protocols, auth status, credential variable names, and associated model profiles. It never prints credential values.

## Mixed OpenAI and Anthropic example

```toml
[providers.openai]
protocol = "openai_chat_completions"
auth = "api_key"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"

[providers.anthropic]
protocol = "anthropic_messages"
auth = "api_key"
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"
max_output_tokens = 4096

[models.fast]
provider = "openai"
model = "your-fast-model"
quality = 4
cost = 1
supports_tools = true
supports_vision = false
max_context_tokens = 32000

[models.advanced]
provider = "anthropic"
model = "your-advanced-model"
quality = 10
cost = 8
supports_tools = true
supports_vision = true
max_context_tokens = 128000
```

Only providers referenced by an active model profile require credentials at startup.

## OpenRouter and custom gateways

OpenRouter and other OpenAI-compatible gateways use the same protocol with their own URL and API-key environment variable:

```toml
[providers.openrouter]
protocol = "openai_chat_completions"
auth = "api_key"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
```

## Local Ollama

```toml
[providers.ollama]
protocol = "openai_chat_completions"
auth = "none"
base_url = "http://127.0.0.1:11434/v1"
```

## Claude app authentication through Claude Code

Claude Pro and Max users can authenticate the official Claude Code application with their Claude account. Allpath can invoke that already authenticated CLI without reading, copying, or storing its OAuth credentials.

```toml
[providers.claude_app]
protocol = "external_cli"
auth = "external_cli"
external_command = "claude"

[models.advanced]
provider = "claude_app"
model = "sonnet"
quality = 10
cost = 8
supports_tools = false
supports_vision = false
max_context_tokens = 128000
```

The adapter runs Claude Code in non-interactive print mode with JSON output and plan permission mode. It is currently text-only from Allpath's perspective and does not receive Allpath tool schemas. Tasks requiring Allpath tools must route to another profile.

Anthropic documents Claude Code account authentication and its scripting interface:

- https://docs.anthropic.com/en/docs/claude-code/getting-started
- https://docs.anthropic.com/en/docs/claude-code/cli-usage

## ChatGPT and OpenAI account boundaries

OpenAI API usage is billed and authenticated separately from ordinary ChatGPT subscriptions. Allpath currently supports OpenAI through an API key. It does not read ChatGPT browser cookies or private application credentials.

Official references:

- https://platform.openai.com/docs/quickstart/make-your-first-api-request
- https://help.openai.com/en/articles/8156019

Future Codex account authentication will only use an official supported Codex surface. It will not be implemented by extracting tokens from another application.

## Prompt caching and routing

A task is pinned to one model profile. If the router selects a different provider for a later task, provider-side prompt caches are not assumed to transfer. Allpath does not switch providers between individual tool calls inside one task.

Provider usage is normalized for task budgets and local reporting. Configure current model prices and limits as described in [Task budgets and structured logs](BUDGETS_AND_LOGS.md).

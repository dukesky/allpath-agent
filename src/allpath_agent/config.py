from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from allpath_agent.models import AuthType, ModelProfile, ProviderProtocol


DEFAULT_CONFIG = """[providers.openai]
protocol = "openai_chat_completions"
auth = "api_key"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
timeout_seconds = 60.0

[providers.anthropic]
protocol = "anthropic_messages"
auth = "api_key"
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"
max_output_tokens = 4096
timeout_seconds = 60.0

[agent]
system_prompt = "You are Allpath Agent, a concise and helpful personal assistant."
max_model_calls = 12
max_task_tokens = 100000
max_task_cost_usd = 0.0
provider_max_attempts = 3
retry_base_delay_seconds = 0.5
retry_max_delay_seconds = 8.0
advanced_threshold = 6

[models.fast]
provider = "openai"
model = "replace-with-fast-model"
quality = 4
cost = 1
supports_tools = true
supports_vision = false
max_context_tokens = 32000
input_cost_per_million = 0.0
output_cost_per_million = 0.0

[models.advanced]
provider = "anthropic"
model = "replace-with-advanced-model"
quality = 10
cost = 8
supports_tools = true
supports_vision = true
max_context_tokens = 128000
input_cost_per_million = 0.0
output_cost_per_million = 0.0
"""


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    protocol: ProviderProtocol
    auth: AuthType
    base_url: str
    api_key_env: str = ""
    max_output_tokens: int = 4096
    external_command: str = ""
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class AgentConfig:
    system_prompt: str
    max_model_calls: int
    advanced_threshold: int
    max_task_tokens: int = 100_000
    max_task_cost_usd: float = 0.0
    provider_max_attempts: int = 3
    retry_base_delay_seconds: float = 0.5
    retry_max_delay_seconds: float = 8.0


@dataclass(frozen=True)
class AppConfig:
    providers: dict[str, ProviderConfig]
    agent: AgentConfig
    models: tuple[ModelProfile, ...]


def resolve_home(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override).expanduser()
    configured = os.environ.get("ALLPATH_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".allpath-agent"


def write_default_config(path: Path) -> None:
    if path.exists():
        raise ConfigError(f"configuration already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        raise ConfigError(
            f"configuration file not found: {path}. Run 'allpath-agent init' or use --demo."
        )
    try:
        with path.open("rb") as file:
            raw = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"could not read configuration: {error}") from error
    return _parse_config(raw)


def _parse_config(raw: dict[str, Any]) -> AppConfig:
    try:
        agent_raw = raw["agent"]
        models_raw = raw["models"]
        providers = _parse_providers(raw)
        agent = AgentConfig(
            system_prompt=_required_string(agent_raw, "system_prompt"),
            max_model_calls=_positive_integer(agent_raw, "max_model_calls"),
            advanced_threshold=_positive_integer(agent_raw, "advanced_threshold"),
            max_task_tokens=_non_negative_integer(agent_raw, "max_task_tokens", 100_000),
            max_task_cost_usd=_non_negative_number(agent_raw, "max_task_cost_usd", 0.0),
            provider_max_attempts=_positive_integer(
                agent_raw,
                "provider_max_attempts",
                3,
            ),
            retry_base_delay_seconds=_non_negative_number(
                agent_raw,
                "retry_base_delay_seconds",
                0.5,
            ),
            retry_max_delay_seconds=_non_negative_number(
                agent_raw,
                "retry_max_delay_seconds",
                8.0,
            ),
        )
        models = tuple(
            _model_profile(name, value)
            for name, value in sorted(models_raw.items())
            if isinstance(value, dict)
        )
    except (KeyError, TypeError) as error:
        raise ConfigError(f"configuration is missing required section or value: {error}") from error
    if not models:
        raise ConfigError("configuration requires at least one model profile")
    unknown = sorted({profile.provider for profile in models} - set(providers))
    if unknown:
        raise ConfigError(f"model profile references unknown provider: {unknown[0]}")
    incompatible = [
        profile.name
        for profile in models
        if profile.supports_tools
        and providers[profile.provider].protocol == ProviderProtocol.EXTERNAL_CLI
    ]
    if incompatible:
        raise ConfigError(
            f"external CLI model profile must set supports_tools = false: {incompatible[0]}"
        )
    return AppConfig(providers, agent, models)


def _parse_providers(raw: dict[str, Any]) -> dict[str, ProviderConfig]:
    configured = raw.get("providers")
    if isinstance(configured, dict):
        providers = {
            provider_id: _provider_config(provider_id, value)
            for provider_id, value in sorted(configured.items())
            if isinstance(value, dict)
        }
        if not providers:
            raise ConfigError("configuration requires at least one provider")
        return providers

    legacy = raw.get("provider")
    if not isinstance(legacy, dict):
        raise ConfigError("configuration requires a [providers.<id>] section")
    return {
        "default": ProviderConfig(
            id="default",
            protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            auth=AuthType.API_KEY,
            base_url=_required_string(legacy, "base_url"),
            api_key_env=_required_string(legacy, "api_key_env"),
        )
    }


def _provider_config(provider_id: str, raw: dict[str, Any]) -> ProviderConfig:
    try:
        protocol = ProviderProtocol(_required_string(raw, "protocol"))
        auth = AuthType(_required_string(raw, "auth"))
    except ValueError as error:
        raise ConfigError(f"provider {provider_id} has unsupported protocol or auth type") from error
    base_url = _optional_string(raw, "base_url", "")
    api_key_env = _optional_string(raw, "api_key_env", "")
    external_command = _optional_string(raw, "external_command", "")
    supported_auth = {
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS: {AuthType.API_KEY, AuthType.NONE},
        ProviderProtocol.ANTHROPIC_MESSAGES: {AuthType.API_KEY},
        ProviderProtocol.GEMINI_GENERATE_CONTENT: {AuthType.API_KEY},
        ProviderProtocol.EXTERNAL_CLI: {AuthType.EXTERNAL_CLI},
    }
    if auth not in supported_auth[protocol]:
        raise ConfigError(
            f"provider {provider_id} does not support auth={auth.value} "
            f"with protocol={protocol.value}"
        )
    if protocol != ProviderProtocol.EXTERNAL_CLI and not base_url:
        raise ConfigError(f"provider {provider_id} requires base_url")
    if auth == AuthType.API_KEY and not api_key_env:
        raise ConfigError(f"provider {provider_id} requires api_key_env")
    if auth == AuthType.EXTERNAL_CLI and not external_command:
        raise ConfigError(f"provider {provider_id} requires external_command")
    default_timeout = 300.0 if protocol == ProviderProtocol.EXTERNAL_CLI else 60.0
    return ProviderConfig(
        id=provider_id,
        protocol=protocol,
        auth=auth,
        base_url=base_url,
        api_key_env=api_key_env,
        max_output_tokens=_positive_integer(raw, "max_output_tokens", 4096),
        external_command=external_command,
        timeout_seconds=_positive_number(raw, "timeout_seconds", default_timeout),
    )


def _model_profile(name: str, raw: dict[str, Any]) -> ModelProfile:
    return ModelProfile(
        name=name,
        model=_required_string(raw, "model"),
        quality=_non_negative_integer(raw, "quality"),
        cost=_non_negative_integer(raw, "cost"),
        supports_tools=_boolean(raw, "supports_tools", True),
        supports_vision=_boolean(raw, "supports_vision", False),
        max_context_tokens=_positive_integer(raw, "max_context_tokens"),
        provider=_optional_string(raw, "provider", "default"),
        input_cost_per_million=_non_negative_number(
            raw,
            "input_cost_per_million",
            0.0,
        ),
        output_cost_per_million=_non_negative_number(
            raw,
            "output_cost_per_million",
            0.0,
        ),
    )


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(raw: dict[str, Any], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    return value.strip()


def _positive_integer(raw: dict[str, Any], key: str, default: int | None = None) -> int:
    value = raw.get(key, default) if default is not None else raw[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{key} must be a positive integer")
    return value


def _non_negative_integer(
    raw: dict[str, Any],
    key: str,
    default: int | None = None,
) -> int:
    value = raw.get(key, default) if default is not None else raw[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{key} must be a non-negative integer")
    return value


def _non_negative_number(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{key} must be a non-negative number")
    return float(value)


def _positive_number(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{key} must be a positive number")
    return float(value)


def _boolean(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from allpath_agent.models import ModelProfile


DEFAULT_CONFIG = """[provider]
base_url = "https://api.example.com/v1"
api_key_env = "ALLPATH_API_KEY"

[agent]
system_prompt = "You are Allpath Agent, a concise and helpful personal assistant."
max_model_calls = 12
advanced_threshold = 6

[models.fast]
model = "replace-with-fast-model"
quality = 4
cost = 1
supports_tools = true
supports_vision = false
max_context_tokens = 32000

[models.advanced]
model = "replace-with-advanced-model"
quality = 10
cost = 8
supports_tools = true
supports_vision = true
max_context_tokens = 128000
"""


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key_env: str


@dataclass(frozen=True)
class AgentConfig:
    system_prompt: str
    max_model_calls: int
    advanced_threshold: int


@dataclass(frozen=True)
class AppConfig:
    provider: ProviderConfig
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
        provider_raw = raw["provider"]
        agent_raw = raw["agent"]
        models_raw = raw["models"]
        provider = ProviderConfig(
            base_url=_required_string(provider_raw, "base_url"),
            api_key_env=_required_string(provider_raw, "api_key_env"),
        )
        max_model_calls = _positive_integer(agent_raw, "max_model_calls")
        advanced_threshold = _positive_integer(agent_raw, "advanced_threshold")
        agent = AgentConfig(
            system_prompt=_required_string(agent_raw, "system_prompt"),
            max_model_calls=max_model_calls,
            advanced_threshold=advanced_threshold,
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
    return AppConfig(provider, agent, models)


def _model_profile(name: str, raw: dict[str, Any]) -> ModelProfile:
    return ModelProfile(
        name=name,
        model=_required_string(raw, "model"),
        quality=_non_negative_integer(raw, "quality"),
        cost=_non_negative_integer(raw, "cost"),
        supports_tools=_boolean(raw, "supports_tools", True),
        supports_vision=_boolean(raw, "supports_vision", False),
        max_context_tokens=_positive_integer(raw, "max_context_tokens"),
    )


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string")
    return value.strip()


def _positive_integer(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{key} must be a positive integer")
    return value


def _non_negative_integer(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{key} must be a non-negative integer")
    return value


def _boolean(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value

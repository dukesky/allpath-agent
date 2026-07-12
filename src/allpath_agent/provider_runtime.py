from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Mapping

from allpath_agent.config import AppConfig, ConfigError, ProviderConfig
from allpath_agent.models import (
    AnthropicMessagesProvider,
    AuthType,
    ClaudeCodeProvider,
    CodexCliProvider,
    GeminiGenerateContentProvider,
    OpenAICompatibleProvider,
    ProviderPool,
    ProviderProtocol,
    builtin_provider_catalog,
)


@dataclass(frozen=True)
class ProviderStatus:
    id: str
    protocol: str
    auth: str
    connected: bool
    detail: str
    model_profiles: tuple[str, ...]


def build_provider_pool(
    config: AppConfig,
    environment: Mapping[str, str] | None = None,
) -> ProviderPool:
    values = environment if environment is not None else os.environ
    active_ids = {profile.provider for profile in config.models}
    providers = {}
    for provider_id in sorted(active_ids):
        provider_config = config.providers[provider_id]
        credential = _credential(provider_config, values)
        if provider_config.auth == AuthType.API_KEY and not credential:
            raise ConfigError(
                f"required API key environment variable is not set: "
                f"{provider_config.api_key_env}"
            )
        if provider_config.protocol == ProviderProtocol.OPENAI_CHAT_COMPLETIONS:
            providers[provider_id] = OpenAICompatibleProvider(
                provider_config.base_url,
                credential,
                timeout_seconds=provider_config.timeout_seconds,
            )
        elif provider_config.protocol == ProviderProtocol.ANTHROPIC_MESSAGES:
            providers[provider_id] = AnthropicMessagesProvider(
                provider_config.base_url,
                credential,
                max_output_tokens=provider_config.max_output_tokens,
                timeout_seconds=provider_config.timeout_seconds,
            )
        elif provider_config.protocol == ProviderProtocol.GEMINI_GENERATE_CONTENT:
            providers[provider_id] = GeminiGenerateContentProvider(
                provider_config.base_url,
                credential,
                timeout_seconds=provider_config.timeout_seconds,
            )
        elif provider_config.protocol == ProviderProtocol.EXTERNAL_CLI:
            if provider_config.auth != AuthType.EXTERNAL_CLI:
                raise ConfigError(
                    f"external CLI provider requires external_cli auth: {provider_id}"
                )
            if not shutil.which(provider_config.external_command):
                raise ConfigError(
                    f"external provider command is not available: "
                    f"{provider_config.external_command}"
                )
            provider_class = CodexCliProvider if provider_id == "openai-codex" else ClaudeCodeProvider
            providers[provider_id] = provider_class(
                provider_config.external_command,
                timeout_seconds=provider_config.timeout_seconds,
            )
        else:
            raise ConfigError(f"unsupported provider protocol: {provider_config.protocol}")
    return ProviderPool(providers)


def provider_statuses(
    config: AppConfig,
    environment: Mapping[str, str] | None = None,
) -> list[ProviderStatus]:
    values = environment if environment is not None else os.environ
    profile_map: dict[str, list[str]] = {}
    for profile in config.models:
        profile_map.setdefault(profile.provider, []).append(profile.name)

    statuses: list[ProviderStatus] = []
    for provider_id, provider in sorted(config.providers.items()):
        connected, detail = _connection_status(provider, values)
        statuses.append(
            ProviderStatus(
                id=provider_id,
                protocol=provider.protocol.value,
                auth=provider.auth.value,
                connected=connected,
                detail=detail,
                model_profiles=tuple(sorted(profile_map.get(provider_id, []))),
            )
        )
    return statuses


def available_provider_ids() -> tuple[str, ...]:
    return tuple(sorted(builtin_provider_catalog()))


def _credential(provider: ProviderConfig, environment: Mapping[str, str]) -> str:
    if provider.auth == AuthType.API_KEY:
        return environment.get(provider.api_key_env, "")
    return ""


def _connection_status(
    provider: ProviderConfig,
    environment: Mapping[str, str],
) -> tuple[bool, str]:
    if provider.auth == AuthType.API_KEY:
        connected = bool(environment.get(provider.api_key_env))
        detail = f"credential: {provider.api_key_env}"
        return connected, detail
    if provider.auth == AuthType.NONE:
        return True, "no credential required"
    if provider.auth == AuthType.EXTERNAL_CLI:
        connected = bool(shutil.which(provider.external_command))
        return (
            connected,
            f"external command: {provider.external_command}; auth verified on first request",
        )
    return False, "OAuth flow is not implemented yet"

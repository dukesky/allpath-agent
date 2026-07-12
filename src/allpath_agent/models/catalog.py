from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProviderProtocol(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    GEMINI_GENERATE_CONTENT = "gemini_generate_content"
    EXTERNAL_CLI = "external_cli"


class AuthType(StrEnum):
    API_KEY = "api_key"
    OAUTH = "oauth"
    EXTERNAL_CLI = "external_cli"
    NONE = "none"


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    label: str
    protocol: ProviderProtocol
    auth_type: AuthType
    default_base_url: str
    default_api_key_env: str = ""
    external_command: str = ""


BUILTIN_PROVIDERS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        id="openai",
        label="OpenAI API",
        protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        auth_type=AuthType.API_KEY,
        default_base_url="https://api.openai.com/v1",
        default_api_key_env="OPENAI_API_KEY",
    ),
    ProviderDescriptor(
        id="anthropic",
        label="Anthropic API",
        protocol=ProviderProtocol.ANTHROPIC_MESSAGES,
        auth_type=AuthType.API_KEY,
        default_base_url="https://api.anthropic.com",
        default_api_key_env="ANTHROPIC_API_KEY",
    ),
    ProviderDescriptor(
        id="xai",
        label="xAI Grok API",
        protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        auth_type=AuthType.API_KEY,
        default_base_url="https://api.x.ai/v1",
        default_api_key_env="XAI_API_KEY",
    ),
    ProviderDescriptor(
        id="gemini",
        label="Google Gemini API",
        protocol=ProviderProtocol.GEMINI_GENERATE_CONTENT,
        auth_type=AuthType.API_KEY,
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_api_key_env="GEMINI_API_KEY",
    ),
    ProviderDescriptor(
        id="openrouter",
        label="OpenRouter",
        protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        auth_type=AuthType.API_KEY,
        default_base_url="https://openrouter.ai/api/v1",
        default_api_key_env="OPENROUTER_API_KEY",
    ),
    ProviderDescriptor(
        id="ollama",
        label="Ollama",
        protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        auth_type=AuthType.NONE,
        default_base_url="http://127.0.0.1:11434/v1",
    ),
    ProviderDescriptor(
        id="claude-code",
        label="Claude Code account",
        protocol=ProviderProtocol.EXTERNAL_CLI,
        auth_type=AuthType.EXTERNAL_CLI,
        default_base_url="",
        external_command="claude",
    ),
)


def builtin_provider_catalog() -> dict[str, ProviderDescriptor]:
    return {provider.id: provider for provider in BUILTIN_PROVIDERS}

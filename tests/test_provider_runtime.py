from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from allpath_agent.config import AgentConfig, AppConfig, ConfigError, ProviderConfig
from allpath_agent.models import AuthType, ModelProfile, ProviderProtocol
from allpath_agent.provider_runtime import build_provider_pool, provider_statuses


def app_config(
    providers: dict[str, ProviderConfig],
    profiles: tuple[ModelProfile, ...],
) -> AppConfig:
    return AppConfig(
        providers=providers,
        agent=AgentConfig("Helpful", max_model_calls=4, advanced_threshold=6),
        models=profiles,
    )


class ProviderRuntimeTestCase(unittest.TestCase):
    def test_missing_active_api_key_is_rejected(self) -> None:
        config = app_config(
            {
                "openai": ProviderConfig(
                    "openai",
                    ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
                    AuthType.API_KEY,
                    "https://api.openai.com/v1",
                    "OPENAI_API_KEY",
                )
            },
            (ModelProfile("fast", "model", 4, 1, provider="openai"),),
        )
        with self.assertRaisesRegex(ConfigError, "OPENAI_API_KEY"):
            build_provider_pool(config, {})

    def test_provider_timeout_is_propagated_to_adapter(self) -> None:
        config = app_config(
            {
                "openai": ProviderConfig(
                    "openai",
                    ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
                    AuthType.API_KEY,
                    "https://api.openai.com/v1",
                    "OPENAI_API_KEY",
                    timeout_seconds=7.5,
                )
            },
            (ModelProfile("fast", "model", 4, 1, provider="openai"),),
        )
        with patch(
            "allpath_agent.provider_runtime.OpenAICompatibleProvider"
        ) as provider_factory:
            build_provider_pool(config, {"OPENAI_API_KEY": "secret"})

        provider_factory.assert_called_once_with(
            "https://api.openai.com/v1",
            "secret",
            timeout_seconds=7.5,
        )

    def test_unused_provider_does_not_require_credential(self) -> None:
        config = app_config(
            {
                "openai": ProviderConfig(
                    "openai",
                    ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
                    AuthType.API_KEY,
                    "https://api.openai.com/v1",
                    "OPENAI_API_KEY",
                ),
                "anthropic": ProviderConfig(
                    "anthropic",
                    ProviderProtocol.ANTHROPIC_MESSAGES,
                    AuthType.API_KEY,
                    "https://api.anthropic.com",
                    "ANTHROPIC_API_KEY",
                ),
            },
            (ModelProfile("fast", "model", 4, 1, provider="openai"),),
        )
        pool = build_provider_pool(config, {"OPENAI_API_KEY": "secret"})
        self.assertEqual(pool.ids(), ("openai",))

    def test_no_auth_local_provider_builds_without_key(self) -> None:
        config = app_config(
            {
                "ollama": ProviderConfig(
                    "ollama",
                    ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
                    AuthType.NONE,
                    "http://127.0.0.1:11434/v1",
                )
            },
            (ModelProfile("fast", "local", 3, 0, provider="ollama"),),
        )
        self.assertEqual(build_provider_pool(config, {}).ids(), ("ollama",))

    def test_status_reports_profiles_and_credentials_without_revealing_values(self) -> None:
        config = app_config(
            {
                "anthropic": ProviderConfig(
                    "anthropic",
                    ProviderProtocol.ANTHROPIC_MESSAGES,
                    AuthType.API_KEY,
                    "https://api.anthropic.com",
                    "ANTHROPIC_API_KEY",
                )
            },
            (ModelProfile("advanced", "claude-model", 10, 8, provider="anthropic"),),
        )
        status = provider_statuses(config, {"ANTHROPIC_API_KEY": "top-secret"})[0]
        self.assertTrue(status.connected)
        self.assertEqual(status.model_profiles, ("advanced",))
        self.assertIn("ANTHROPIC_API_KEY", status.detail)
        self.assertNotIn("top-secret", status.detail)

    def test_external_cli_provider_uses_command_availability_as_auth_status(self) -> None:
        config = app_config(
            {
                "claude-app": ProviderConfig(
                    "claude-app",
                    ProviderProtocol.EXTERNAL_CLI,
                    AuthType.EXTERNAL_CLI,
                    "",
                    external_command=sys.executable,
                )
            },
            (
                ModelProfile(
                    "advanced",
                    "sonnet",
                    10,
                    8,
                    supports_tools=False,
                    provider="claude-app",
                ),
            ),
        )
        status = provider_statuses(config, {})[0]
        self.assertTrue(status.connected)
        self.assertEqual(build_provider_pool(config, {}).ids(), ("claude-app",))


if __name__ == "__main__":
    unittest.main()

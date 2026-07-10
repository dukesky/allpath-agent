from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.config import ConfigError, load_config, write_default_config


class ConfigTestCase(unittest.TestCase):
    def test_default_config_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_default_config(path)
            config = load_config(path)

        self.assertEqual(config.providers["openai"].api_key_env, "OPENAI_API_KEY")
        self.assertEqual(config.providers["anthropic"].protocol, "anthropic_messages")
        self.assertEqual([profile.name for profile in config.models], ["advanced", "fast"])
        self.assertEqual(
            {profile.name: profile.provider for profile in config.models},
            {"advanced": "anthropic", "fast": "openai"},
        )
        self.assertEqual(config.agent.max_model_calls, 12)

    def test_legacy_single_provider_config_remains_supported(self) -> None:
        legacy = """[provider]
base_url = "https://example.test/v1"
api_key_env = "LEGACY_API_KEY"

[agent]
system_prompt = "Helpful"
max_model_calls = 4
advanced_threshold = 3

[models.fast]
model = "legacy-model"
quality = 3
cost = 1
max_context_tokens = 1000
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(legacy, encoding="utf-8")
            config = load_config(path)

        self.assertEqual(tuple(config.providers), ("default",))
        self.assertEqual(config.models[0].provider, "default")

    def test_default_config_does_not_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_default_config(path)
            with self.assertRaisesRegex(ConfigError, "already exists"):
                write_default_config(path)

    def test_missing_config_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ConfigError, "allpath-agent init"):
                load_config(Path(directory) / "config.toml")

    def test_external_cli_profile_must_disable_allpath_tools(self) -> None:
        config_text = """[providers.claude_app]
protocol = "external_cli"
auth = "external_cli"
external_command = "claude"

[agent]
system_prompt = "Helpful"
max_model_calls = 4
advanced_threshold = 3

[models.advanced]
provider = "claude_app"
model = "sonnet"
quality = 10
cost = 8
supports_tools = true
max_context_tokens = 1000
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(config_text, encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "supports_tools = false"):
                load_config(path)

    def test_unimplemented_auth_protocol_combination_is_rejected(self) -> None:
        config_text = """[providers.anthropic]
protocol = "anthropic_messages"
auth = "oauth"
base_url = "https://api.anthropic.com"

[agent]
system_prompt = "Helpful"
max_model_calls = 4
advanced_threshold = 3

[models.advanced]
provider = "anthropic"
model = "claude-model"
quality = 10
cost = 8
max_context_tokens = 1000
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(config_text, encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "does not support auth=oauth"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()

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

        self.assertEqual(config.provider.api_key_env, "ALLPATH_API_KEY")
        self.assertEqual([profile.name for profile in config.models], ["advanced", "fast"])
        self.assertEqual(config.agent.max_model_calls, 12)

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


if __name__ == "__main__":
    unittest.main()

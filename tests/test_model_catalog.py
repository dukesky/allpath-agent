from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from allpath_agent.models.model_catalog import available_models


class ModelCatalogTestCase(unittest.TestCase):
    def test_codex_models_follow_local_account_cache_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            (codex_home / "models_cache.json").write_text(
                json.dumps(
                    {
                        "models": [
                            {"slug": "later", "priority": 20},
                            {"slug": "hidden", "priority": 1, "visibility": "hidden"},
                            {"slug": "first", "priority": 10},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                models = available_models("openai-codex")

        self.assertEqual(models, ("first", "later"))

    def test_provider_without_live_catalog_uses_curated_fallback(self) -> None:
        self.assertIn("sonnet", available_models("claude-code"))
        self.assertTrue(available_models("xai")[0].startswith("grok-"))
        self.assertTrue(available_models("gemini")[0].startswith("gemini-"))


if __name__ == "__main__":
    unittest.main()

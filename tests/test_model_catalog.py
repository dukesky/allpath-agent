from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from allpath_agent.models.model_catalog import available_models, discover_provider_models


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


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

    @patch("allpath_agent.models.model_catalog.urlopen")
    def test_openai_compatible_catalog_uses_bearer_auth(self, urlopen) -> None:
        urlopen.return_value = FakeResponse({"data": [{"id": "grok-live"}]})

        models = discover_provider_models("xai", "https://api.x.ai/v1", "secret")

        request = urlopen.call_args.args[0]
        self.assertEqual(models, ("grok-live",))
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(request.full_url, "https://api.x.ai/v1/models")

    @patch("allpath_agent.models.model_catalog.urlopen")
    def test_gemini_catalog_only_includes_generate_content_models(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {
                "models": [
                    {
                        "baseModelId": "gemini-live",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "baseModelId": "embedding-only",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            }
        )

        models = discover_provider_models(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "secret",
        )

        request = urlopen.call_args.args[0]
        self.assertEqual(models, ("gemini-live",))
        self.assertIn("key=secret", request.full_url)
        self.assertIn("pageSize=1000", request.full_url)

    @patch("allpath_agent.models.model_catalog.urlopen", side_effect=OSError("offline"))
    def test_catalog_failure_uses_curated_fallback(self, urlopen) -> None:
        self.assertEqual(
            discover_provider_models("xai", "https://api.x.ai/v1", "secret"),
            available_models("xai"),
        )


if __name__ == "__main__":
    unittest.main()

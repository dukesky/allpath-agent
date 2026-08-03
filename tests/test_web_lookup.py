from __future__ import annotations

import unittest
from unittest.mock import patch

from allpath_agent.tools.registry import ToolRegistry, ToolRisk
from allpath_agent.tools.web import (
    MAX_CONTENT_CHARS,
    _RedirectValidator,
    _extract_html_text,
    register_web_tools,
)


def _registry_with_fake(responses):
    registry = ToolRegistry()

    def fetch(url):
        return responses[url]

    register_web_tools(registry, fetch=fetch)
    return registry


def _call(registry, url):
    return registry.get("web_lookup").handler({"url": url})


class WebLookupTestCase(unittest.TestCase):
    def test_tool_is_read_only(self) -> None:
        registry = _registry_with_fake({})
        self.assertIs(registry.get("web_lookup").risk, ToolRisk.READ_ONLY)

    def test_html_page_returns_title_and_text(self) -> None:
        body = (
            b"<html><head><title>Weather Today</title>"
            b"<style>p{color:red}</style><script>alert(1)</script></head>"
            b"<body><h1>Forecast</h1><p>Sunny, 24 degrees.</p></body></html>"
        )
        registry = _registry_with_fake(
            {"https://example.com/weather": (200, "text/html; charset=utf-8", body, "https://example.com/weather")}
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            result = _call(registry, "https://example.com/weather")

        self.assertEqual(result["status"], 200)
        self.assertEqual(result["title"], "Weather Today")
        self.assertIn("Sunny, 24 degrees.", result["content"])
        self.assertNotIn("alert(1)", result["content"])
        self.assertNotIn("color:red", result["content"])
        self.assertFalse(result["content_truncated"])

    def test_long_content_is_truncated(self) -> None:
        body = b"<html><body>" + b"<p>word</p>" * 5000 + b"</body></html>"
        registry = _registry_with_fake(
            {"https://example.com/big": (200, "text/html", body, "https://example.com/big")}
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            result = _call(registry, "https://example.com/big")

        self.assertTrue(result["content_truncated"])
        self.assertLessEqual(len(result["content"]), MAX_CONTENT_CHARS)

    def test_plain_text_and_json_pass_through(self) -> None:
        registry = _registry_with_fake(
            {"https://example.com/data.json": (200, "application/json", b'{"ok": true}', "https://example.com/data.json")}
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            result = _call(registry, "https://example.com/data.json")

        self.assertEqual(result["content"], '{"ok": true}')
        self.assertIsNone(result["title"])

    def test_binary_content_type_is_rejected(self) -> None:
        registry = _registry_with_fake(
            {"https://example.com/app.zip": (200, "application/zip", b"PK", "https://example.com/app.zip")}
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            with self.assertRaisesRegex(ValueError, "content type"):
                _call(registry, "https://example.com/app.zip")

    def test_local_url_is_rejected_before_fetch(self) -> None:
        calls = []

        def fetch(url):
            calls.append(url)
            raise AssertionError("fetch must not run for rejected URLs")

        registry = ToolRegistry()
        register_web_tools(registry, fetch=fetch)

        with self.assertRaises(ValueError):
            registry.get("web_lookup").handler({"url": "http://localhost:8000/admin"})
        self.assertEqual(calls, [])

    def test_redirect_targets_are_revalidated(self) -> None:
        recorded = []

        def failing_validate(url):
            recorded.append(url)
            raise ValueError("private redirect target")

        validator = _RedirectValidator()
        with patch("allpath_agent.tools.web.validate_public_url", side_effect=failing_validate):
            with self.assertRaisesRegex(ValueError, "private redirect target"):
                validator.redirect_request(
                    None, None, 302, "Found", {}, "http://192.168.0.1/internal"
                )
        self.assertEqual(recorded, ["http://192.168.0.1/internal"])

    def test_unknown_charset_falls_back_to_utf8(self) -> None:
        body = b"<html><body><p>Hello world</p></body></html>"
        registry = _registry_with_fake(
            {
                "https://example.com/bad-charset": (
                    200,
                    "text/html; charset=bogus-charset-name",
                    body,
                    "https://example.com/bad-charset",
                )
            }
        )

        with patch("allpath_agent.tools.web.validate_public_url", side_effect=lambda url: url):
            result = _call(registry, "https://example.com/bad-charset")

        self.assertIn("Hello world", result["content"])

    def test_extractor_collapses_whitespace(self) -> None:
        title, text = _extract_html_text("<body><p>a\n\n   b</p><div>c</div></body>")
        self.assertIsNone(title)
        self.assertEqual(text, "a b c")


if __name__ == "__main__":
    unittest.main()

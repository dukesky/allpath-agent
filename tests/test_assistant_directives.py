from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.storage import ConnectorConfigRepository, Database
from allpath_agent.tools.assistant_directives import (
    AssistantDirective,
    DirectiveSink,
    register_assistant_tools,
)
from allpath_agent.tools.registry import ToolRegistry, ToolRisk


class AssistantDirectiveToolsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.configs = ConnectorConfigRepository(self.database)
        self.sink = DirectiveSink()
        self.registry = ToolRegistry()
        register_assistant_tools(self.registry, self.configs, self.sink)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _call(self, name: str, arguments: dict):
        return self.registry.get(name).handler(arguments)

    def test_all_four_tools_are_read_only(self) -> None:
        for name in ("channel_status", "channel_connect", "create_automation", "connect_model"):
            self.assertIs(self.registry.get(name).risk, ToolRisk.READ_ONLY)

    def test_channel_status_reports_all_channels_without_config(self) -> None:
        result = self._call("channel_status", {})

        statuses = {entry["channel"]: entry["status"] for entry in result["channels"]}
        self.assertEqual(
            statuses,
            {"telegram": "not_configured", "slack": "not_configured", "whatsapp": "not_configured"},
        )
        self.assertIsNone(self.sink.take())

    def test_channel_status_reports_single_active_channel(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self._call("channel_status", {"channel": "telegram"})

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["detail"], "@my_bot")

    def test_channel_connect_sets_directive_for_unconnected_channel(self) -> None:
        result = self._call("channel_connect", {"channel": "telegram"})

        self.assertEqual(result["directive"], "channel_setup")
        directive = self.sink.take()
        self.assertEqual(directive.kind, "channel_setup")
        self.assertEqual(directive.channel, "telegram")
        self.assertFalse(directive.reconnect)

    def test_channel_connect_on_active_channel_returns_status_without_directive(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self._call("channel_connect", {"channel": "telegram"})

        self.assertTrue(result["already_connected"])
        self.assertEqual(result["detail"], "@my_bot")
        self.assertIsNone(self.sink.take())

    def test_channel_connect_reconnect_overrides_active_guard(self) -> None:
        self.configs.save("telegram", "active", "@my_bot")

        result = self._call("channel_connect", {"channel": "telegram", "reconnect": True})

        self.assertEqual(result["directive"], "channel_setup")
        self.assertTrue(self.sink.take().reconnect)

    def test_channel_connect_rejects_unknown_channel(self) -> None:
        with self.assertRaises(ValueError):
            self._call("channel_connect", {"channel": "discord"})
        self.assertIsNone(self.sink.take())

    def test_create_automation_carries_only_provided_prefill(self) -> None:
        result = self._call(
            "create_automation",
            {"prompt": "Summarize the news", "schedule": "0 8 * * *"},
        )

        self.assertEqual(result["directive"], "automation_setup")
        directive = self.sink.take()
        self.assertEqual(directive.kind, "automation_setup")
        self.assertEqual(
            directive.prefill,
            {"prompt": "Summarize the news", "schedule": "0 8 * * *"},
        )

    def test_connect_model_sets_model_setup_directive(self) -> None:
        result = self._call("connect_model", {})

        self.assertEqual(result["directive"], "model_setup")
        self.assertEqual(self.sink.take().kind, "model_setup")

    def test_sink_take_clears_and_last_set_wins(self) -> None:
        self.sink.set(AssistantDirective("model_setup"))
        self.sink.set(AssistantDirective("channel_setup", channel="slack"))

        first = self.sink.take()
        self.assertEqual(first.channel, "slack")
        self.assertIsNone(self.sink.take())


if __name__ == "__main__":
    unittest.main()

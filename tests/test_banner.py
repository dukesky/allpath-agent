from __future__ import annotations

import unittest

from allpath_agent.cli.banner import CAPABILITY_HINTS, HINT_ORDER, launch_lines, next_capability_hint


class LaunchBannerTestCase(unittest.TestCase):
    def test_starter_banner_prioritizes_conversation_first_setup(self) -> None:
        text = "\n".join(
            launch_lines(live_mode=False, session_id="session-123")
        )

        self.assertIn("ALLPATH", text)
        self.assertIn("local starter mode", text)
        self.assertIn("Session: session-123", text)
        self.assertIn("START HERE", text)
        self.assertIn("Connect your first reasoning model", text)
        self.assertIn("connect a model", text)
        self.assertIn("messaging channel", text)
        self.assertIn("automations", text)

    def test_live_banner_shows_models_and_next_unlearned_capability(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-456",
                configured_roles=("fast", "advanced"),
                configured_connectors=("telegram", "slack", "whatsapp"),
                capability_progress=(
                    ("durable_memory", "Durable memory", "habitual"),
                    ("current_time", "Current time", "unseen"),
                ),
            )
        )

        self.assertIn("live mode", text)
        self.assertIn("Models ready: fast, advanced", text)
        self.assertIn("/model", text)
        self.assertIn("what time is it", text)
        self.assertNotIn("remember that I prefer", text)

    def test_live_banner_suggests_one_messaging_channel_when_none_configured(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-789",
                configured_roles=("standard",),
            )
        )

        self.assertIn("Next: Connect a messaging channel", text)
        self.assertNotIn("remember that I prefer", text)

    def test_live_banner_advances_to_capability_lessons_after_one_connector(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-one-connector",
                configured_roles=("standard",),
                configured_connectors=("telegram",),
            )
        )

        self.assertIn("remember that I prefer concise answers", text)
        self.assertNotIn("connect Slack", text)
        self.assertNotIn("connect WhatsApp", text)

    def test_live_banner_skips_messaging_after_dismissal(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-dismissed",
                configured_roles=("standard",),
                capability_progress=(
                    ("messaging_connectors", "Messaging connectors", "dismissed"),
                ),
            )
        )

        self.assertIn("remember that I prefer concise answers", text)
        self.assertNotIn("messaging channel", text)

    def test_next_capability_hint_skips_unavailable_and_exhausts_to_none(self) -> None:
        suppressed = [
            (capability_id, capability_id, "unavailable") for capability_id in HINT_ORDER
        ]
        self.assertIsNone(next_capability_hint(suppressed))

        learned = [
            (capability_id, capability_id, "habitual") for capability_id in HINT_ORDER
        ]
        self.assertIsNone(next_capability_hint(learned, configured_connectors=("telegram",)))

    def test_banner_falls_back_to_capabilities_when_everything_is_learned(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-done",
                configured_roles=("standard",),
                configured_connectors=("telegram",),
                capability_progress=tuple(
                    (capability_id, capability_id, "habitual") for capability_id in HINT_ORDER
                ),
            )
        )

        self.assertIn("Next: Explore: /capabilities", text)

    def test_hint_order_covers_every_capability_hint(self) -> None:
        self.assertEqual(set(HINT_ORDER), set(CAPABILITY_HINTS))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from allpath_agent.cli.banner import launch_lines


class LaunchBannerTestCase(unittest.TestCase):
    def test_starter_banner_prioritizes_conversation_first_setup(self) -> None:
        text = "\n".join(
            launch_lines(live_mode=False, session_id="session-123")
        )

        self.assertIn("ALLPATH", text)
        self.assertIn("local starter mode", text)
        self.assertIn("Session: session-123", text)
        self.assertIn("TRY YOUR FIRST ACTION", text)
        self.assertIn("Calculate locally", text)
        self.assertIn("calculate 18 * (7 + 3)", text)
        self.assertIn("connect a model", text)

    def test_live_banner_shows_models_and_next_unlearned_capability(self) -> None:
        text = "\n".join(
            launch_lines(
                live_mode=True,
                session_id="session-456",
                configured_roles=("fast", "advanced"),
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


if __name__ == "__main__":
    unittest.main()

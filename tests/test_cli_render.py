from __future__ import annotations

import unittest

from allpath_agent.cli.render import TerminalChatUI
from allpath_agent.hooks import HookEvent


class TerminalChatUITestCase(unittest.TestCase):
    def test_input_composer_has_clear_identity_hint_and_boundary(self) -> None:
        output: list[str] = []
        prompts: list[str] = []

        def read(prompt: str) -> str:
            prompts.append(prompt)
            return "hello"

        ui = TerminalChatUI(read, output.append, color=False, width=60)
        message = ui.read_message("Try: connect a model")

        self.assertEqual(message, "hello")
        self.assertIn("╭─ YOU", output[1])
        self.assertEqual(output[2], "│  Try: connect a model")
        self.assertEqual(prompts, ["│  ❯ "])
        self.assertTrue(output[-1].startswith("╰"))

    def test_assistant_panel_preserves_multiline_content(self) -> None:
        output: list[str] = []
        ui = TerminalChatUI(lambda _: "", output.append, color=False, width=60)

        ui.assistant("first line\n\nsecond line", "advanced")

        self.assertIn("ALLPATH · ADVANCED", output[1])
        self.assertEqual(output[2:5], ["│  first line", "│", "│  second line"])
        self.assertTrue(output[-1].startswith("╰"))

    def test_suggestion_is_visually_separate_from_response(self) -> None:
        output: list[str] = []
        ui = TerminalChatUI(lambda _: "", output.append, color=False, width=60)

        ui.suggestion("skills", "Explore /skills")

        self.assertIn("NEXT · skills", output[1])
        self.assertEqual(output[2], "│  Explore /skills")

    def test_activity_events_show_model_and_tool_progress_without_arguments(self) -> None:
        output: list[str] = []
        ui = TerminalChatUI(lambda _: "", output.append, color=False, width=60)

        ui.handle_event(HookEvent("task_started", "now", {
            "profile": "advanced",
            "provider": "openai",
            "model": "gpt-test",
        }))
        ui.handle_event(HookEvent("tool_call_started", "now", {
            "tool": "read_file",
            "arguments": {"path": "secret.txt"},
        }))
        ui.handle_event(HookEvent("tool_call_completed", "now", {
            "tool": "read_file",
            "status": "succeeded",
            "duration_ms": 1250,
        }))

        text = "\n".join(output)
        self.assertIn("Working · advanced · openai/gpt-test", text)
        self.assertIn("tool · read_file · running", text)
        self.assertIn("✓ read_file · succeeded · 1.2s", text)
        self.assertNotIn("secret.txt", text)

    def test_approval_panel_keeps_confirmation_inside_boundary(self) -> None:
        output: list[str] = []
        prompts: list[str] = []

        def confirm(prompt: str) -> str:
            prompts.append(prompt)
            return "y"

        ui = TerminalChatUI(confirm, output.append, color=False, width=60)
        answer = ui.request_confirmation("write_file", "Write a file", '{"path": "note.md"}')

        self.assertEqual(answer, "y")
        self.assertIn("APPROVAL · write_file", output[1])
        self.assertIn("Allow this action?", prompts[0])
        self.assertTrue(output[-1].startswith("╰"))


if __name__ == "__main__":
    unittest.main()

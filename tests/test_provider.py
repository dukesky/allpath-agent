from __future__ import annotations

import unittest
from typing import Any

from allpath_agent.agent import ChatMessage, ChatRequest, ToolCall
from allpath_agent.models import OpenAICompatibleProvider


class OpenAICompatibleProviderTestCase(unittest.TestCase):
    def test_message_contract_rejects_invalid_tool_lifecycle(self) -> None:
        with self.assertRaises(ValueError):
            ChatMessage("tool", "result")
        with self.assertRaises(ValueError):
            ChatMessage("user", "hello", tool_calls=(ToolCall("call-1", "bad", {}),))

    def test_serializes_request_and_parses_tool_call(self) -> None:
        captured: dict[str, Any] = {}

        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> dict[str, Any]:
            captured.update(url=url, headers=headers, payload=payload, timeout=timeout)
            return {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "current_time",
                                        "arguments": '{"timezone":"UTC"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            }

        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "secret",
            transport=transport,
        )
        response = provider.complete(
            ChatRequest("fast-model", (ChatMessage("user", "What time is it?"),))
        )

        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["payload"]["messages"][0]["role"], "user")
        self.assertEqual(response.tool_calls[0].name, "current_time")
        self.assertEqual(response.tool_calls[0].arguments, {"timezone": "UTC"})
        self.assertEqual(response.usage["prompt_tokens"], 10)


if __name__ == "__main__":
    unittest.main()

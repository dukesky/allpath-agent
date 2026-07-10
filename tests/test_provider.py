from __future__ import annotations

import unittest
from typing import Any

from allpath_agent.agent import ChatMessage, ChatRequest, ChatResponse, ToolCall
from allpath_agent.models import (
    AnthropicMessagesProvider,
    ClaudeCodeProvider,
    CommandResult,
    FakeProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderPool,
)


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

    def test_empty_api_key_does_not_send_authorization_header(self) -> None:
        captured: dict[str, Any] = {}

        def transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float):
            captured["headers"] = headers
            return {"choices": [{"message": {"content": "local"}, "finish_reason": "stop"}]}

        provider = OpenAICompatibleProvider("http://localhost:11434/v1", transport=transport)
        provider.complete(ChatRequest("local-model", (ChatMessage("user", "hello"),)))
        self.assertNotIn("Authorization", captured["headers"])


class AnthropicMessagesProviderTestCase(unittest.TestCase):
    def test_converts_messages_tools_and_response_blocks(self) -> None:
        captured: dict[str, Any] = {}

        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> dict[str, Any]:
            captured.update(url=url, headers=headers, payload=payload)
            return {
                "content": [
                    {"type": "text", "text": "Checking"},
                    {
                        "type": "tool_use",
                        "id": "next-call",
                        "name": "current_datetime",
                        "input": {"timezone": "UTC"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 20, "output_tokens": 8},
            }

        provider = AnthropicMessagesProvider(
            "https://api.anthropic.com",
            "anthropic-secret",
            transport=transport,
        )
        response = provider.complete(
            ChatRequest(
                "claude-model",
                (
                    ChatMessage("system", "Be helpful"),
                    ChatMessage("user", "What time is it?"),
                    ChatMessage(
                        "assistant",
                        None,
                        tool_calls=(ToolCall("call-1", "current_datetime", {"timezone": "UTC"}),),
                    ),
                    ChatMessage("tool", '{"time":"12:00"}', tool_call_id="call-1"),
                ),
                tools=(
                    {
                        "type": "function",
                        "function": {
                            "name": "current_datetime",
                            "description": "Get time",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    },
                ),
            )
        )

        self.assertEqual(captured["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(captured["headers"]["x-api-key"], "anthropic-secret")
        self.assertEqual(captured["payload"]["system"], "Be helpful")
        self.assertEqual(captured["payload"]["tools"][0]["input_schema"]["type"], "object")
        self.assertEqual(captured["payload"]["messages"][-1]["role"], "user")
        self.assertEqual(
            captured["payload"]["messages"][-1]["content"][0]["type"],
            "tool_result",
        )
        self.assertEqual(response.content, "Checking")
        self.assertEqual(response.tool_calls[0].id, "next-call")


class ProviderPoolTestCase(unittest.TestCase):
    def test_routes_request_to_selected_provider(self) -> None:
        openai = FakeProvider([ChatResponse(content="openai")])
        anthropic = FakeProvider([])
        pool = ProviderPool({"openai": openai, "anthropic": anthropic})

        request = ChatRequest("model", (ChatMessage("user", "hello"),))
        pool.complete("openai", request)
        self.assertEqual(openai.requests, [request])
        self.assertEqual(anthropic.requests, [])


class ClaudeCodeProviderTestCase(unittest.TestCase):
    def test_uses_logged_in_cli_without_reading_credentials(self) -> None:
        captured: dict[str, Any] = {}

        def runner(arguments: list[str], timeout: float) -> CommandResult:
            captured["arguments"] = arguments
            captured["timeout"] = timeout
            return CommandResult(
                0,
                '{"type":"result","subtype":"success","result":"Claude response"}',
                "",
            )

        provider = ClaudeCodeProvider("claude", runner=runner)
        response = provider.complete(
            ChatRequest(
                "sonnet",
                (
                    ChatMessage("system", "Be helpful"),
                    ChatMessage("user", "Analyze this"),
                ),
            )
        )

        self.assertEqual(
            captured["arguments"][:8],
            [
                "claude",
                "-p",
                "--output-format",
                "json",
                "--permission-mode",
                "plan",
                "--model",
                "sonnet",
            ],
        )
        self.assertIn("SYSTEM: Be helpful", captured["arguments"][-1])
        self.assertEqual(response.content, "Claude response")

    def test_rejects_allpath_tool_schemas(self) -> None:
        provider = ClaudeCodeProvider(
            runner=lambda arguments, timeout: CommandResult(0, '{}', ''),
        )
        with self.assertRaisesRegex(ProviderError, "does not yet support"):
            provider.complete(
                ChatRequest(
                    "sonnet",
                    (ChatMessage("user", "hello"),),
                    tools=({"type": "function", "function": {"name": "tool"}},),
                )
            )


if __name__ == "__main__":
    unittest.main()

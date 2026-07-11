from __future__ import annotations

from .engine import Capability


def default_capabilities() -> list[Capability]:
    return [
        Capability(
            id="basic_chat",
            title="Basic conversation",
            base_priority=100,
            trigger_intents=frozenset({"chat"}),
            lesson="You can continue naturally across multiple turns in this session.",
        ),
        Capability(
            id="durable_memory",
            title="Durable memory",
            base_priority=90,
            prerequisite_ids=("basic_chat",),
            trigger_intents=frozenset({"memory"}),
            setup_effort=10,
            lesson="Try saying “remember that I prefer concise answers” to save a durable preference.",
        ),
        Capability(
            id="current_time",
            title="Current date and time",
            base_priority=85,
            prerequisite_ids=("basic_chat",),
            trigger_intents=frozenset({"time"}),
            lesson="You can ask for the current date or time in an IANA timezone.",
        ),
        Capability(
            id="calculator",
            title="Safe calculator",
            base_priority=80,
            prerequisite_ids=("basic_chat",),
            trigger_intents=frozenset({"calculation"}),
            lesson="Try “calculate 18 * (7 + 3)” for local arithmetic without code execution.",
        ),
        Capability(
            id="session_management",
            title="Session management",
            base_priority=75,
            prerequisite_ids=("basic_chat",),
            trigger_intents=frozenset({"session"}),
            lesson="Use /sessions and /resume <session-id> to continue an earlier conversation.",
        ),
        Capability(
            id="model_routing",
            title="Automatic model routing",
            base_priority=70,
            prerequisite_ids=("basic_chat",),
            trigger_intents=frozenset({"deep_analysis"}),
            lesson="Ask for a deep analysis when you want the task routed to the advanced model profile.",
        ),
        Capability(
            id="tool_approvals",
            title="Tool approvals",
            base_priority=65,
            prerequisite_ids=("basic_chat",),
            trigger_intents=frozenset({"approval", "memory"}),
            lesson="Side-effecting tools ask for approval; read-only tools can run directly.",
        ),
        Capability(
            id="live_provider",
            title="Live model provider",
            base_priority=50,
            prerequisite_ids=("basic_chat",),
            trigger_intents=frozenset({"provider"}),
            setup_effort=20,
            lesson="Ask me to connect a model and I will guide and verify the setup in this conversation.",
        ),
    ]

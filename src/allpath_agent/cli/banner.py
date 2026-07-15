from __future__ import annotations

from collections.abc import Iterable


ART = (
    "           ╭─╮",
    "       ╭───╯ ◇ ╰───╮",
    "       │  ALLPATH  │",
    "       ╰───╮   ╭───╯",
    "           ╰─╯",
)


CAPABILITY_HINTS = {
    "durable_memory": "Try: remember that I prefer concise answers",
    "current_time": "Try: what time is it in Asia/Shanghai?",
    "calculator": "Try: calculate 18 * (7 + 3)",
    "session_management": "Explore: /sessions and /new",
    "model_routing": "Explore: /route after a complex request",
    "tool_approvals": "Try: remember a preference to see safe approval",
    "live_provider": "Explore: /model and /models",
}


def launch_lines(
    *,
    live_mode: bool,
    session_id: str,
    configured_roles: Iterable[str] = (),
    configured_connectors: Iterable[str] = (),
    capability_progress: Iterable[tuple[str, str, str]] = (),
) -> tuple[str, ...]:
    roles = tuple(configured_roles)
    mode = "live" if live_mode else "local starter"
    lines = [
        *ART,
        f"       Allpath Agent ({mode} mode)",
        "",
        f"  Session: {session_id}",
        "  Type /help for commands or /exit to quit.",
        "",
    ]
    if not live_mode:
        lines.extend(
            (
                "  ╭─ START HERE ────────────────────────────────────╮",
                "  │ Connect your first reasoning model in chat.    │",
                "  │ Type: connect a model                          │",
                "  ╰────────────────────────────────────────────────╯",
                "  Next: connect a messaging channel, then create automations.",
            )
        )
        return tuple(lines)

    role_text = ", ".join(roles) if roles else "none"
    lines.append(f"  Models ready: {role_text}")
    lines.append("  Inspect: /model  ·  Manage: /models  ·  Help: /help")
    if "telegram" not in set(configured_connectors):
        lines.append("  Next: connect Telegram")
        return tuple(lines)
    if "slack" not in set(configured_connectors):
        lines.append("  Next: connect Slack")
        return tuple(lines)
    learned = {capability_id: status for capability_id, _, status in capability_progress}
    next_hint = next(
        (
            CAPABILITY_HINTS[capability_id]
            for capability_id in CAPABILITY_HINTS
            if learned.get(capability_id, "unseen") not in {"succeeded", "habitual", "dismissed"}
        ),
        "Explore: /capabilities",
    )
    lines.append(f"  Next: {next_hint}")
    return tuple(lines)

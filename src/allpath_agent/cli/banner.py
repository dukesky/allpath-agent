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
    "messaging_connectors": "Connect a messaging channel: try \"connect Telegram\"",
    "durable_memory": "Try: remember that I prefer concise answers",
    "current_time": "Try: what time is it in Asia/Shanghai?",
    "session_management": "Explore: /sessions and /new",
    "model_routing": "Explore: /route after a complex request",
    "tool_approvals": "Try: remember a preference to see safe approval",
    "live_provider": "Explore: /model and /models",
    "scheduled_automations": "Explore: /automations",
    "workspace_files": "Try: ask Allpath to explain this project",
    "terminal_tasks": "Try: ask Allpath to run this project's tests",
    "skills": "Explore: /skills",
    "mcp_tools": "Explore: /mcp",
    "browser_tasks": "Explore: /browser",
}

HINT_ORDER = (
    "messaging_connectors",
    "durable_memory",
    "current_time",
    "session_management",
    "model_routing",
    "tool_approvals",
    "live_provider",
    "scheduled_automations",
    "workspace_files",
    "terminal_tasks",
    "skills",
    "mcp_tools",
    "browser_tasks",
)

_LEARNED_STATUSES = frozenset({"succeeded", "habitual", "dismissed", "unavailable"})


def next_capability_hint(
    capability_progress: Iterable[tuple[str, str, str]],
    *,
    configured_connectors: Iterable[str] = (),
) -> str | None:
    statuses = {capability_id: status for capability_id, _, status in capability_progress}
    if tuple(configured_connectors):
        statuses["messaging_connectors"] = "succeeded"
    for capability_id in HINT_ORDER:
        if statuses.get(capability_id, "unseen") not in _LEARNED_STATUSES:
            return CAPABILITY_HINTS[capability_id]
    return None


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
    hint = next_capability_hint(
        capability_progress,
        configured_connectors=configured_connectors,
    )
    lines.append(f"  Next: {hint if hint is not None else 'Explore: /capabilities'}")
    return tuple(lines)

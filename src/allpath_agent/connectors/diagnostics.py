from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .slack import SlackConnector
from .telegram import TelegramConnector
from .whatsapp import WhatsAppConnector


@dataclass(frozen=True)
class ConnectorDiagnostic:
    connector_id: str
    credentials: str
    verification: str
    runtime: str
    action: str


def diagnose_connectors(
    records: list[dict[str, Any]],
    secrets: Mapping[str, str],
    *,
    factories: Mapping[str, Callable[..., Any]] | None = None,
    whatsapp_probe: Callable[[], bool] | None = None,
) -> tuple[ConnectorDiagnostic, ...]:
    connector_factories = dict(factories or _default_factories())
    probe = whatsapp_probe or _whatsapp_listener_reachable
    diagnostics = []
    for record in records:
        connector_id = record["connector_id"]
        required = _required_values(connector_id, secrets)
        missing = tuple(name for name, value in required if not value)
        if missing:
            diagnostics.append(
                ConnectorDiagnostic(
                    connector_id,
                    f"missing: {', '.join(missing)}",
                    "not run",
                    "not checked",
                    f"Reconnect {connector_id} in chat to replace the missing credentials.",
                )
            )
            continue
        factory = connector_factories.get(connector_id)
        if factory is None:
            diagnostics.append(
                ConnectorDiagnostic(
                    connector_id,
                    "present",
                    "unsupported connector type",
                    "not checked",
                    "Update Allpath Agent or remove the unknown connector configuration.",
                )
            )
            continue
        status = factory(*(value for _, value in required)).status()
        if status.connected:
            verification = f"verified: {status.detail}"
            action = "No credential action required."
        else:
            verification = f"failed: {status.detail}"
            action = _failure_action(connector_id, status.detail)
        runtime = (
            "local webhook listening on 127.0.0.1:8787"
            if connector_id == "whatsapp" and probe()
            else "local webhook not reachable; start `allpath-agent gateway`"
            if connector_id == "whatsapp"
            else "start or keep `allpath-agent gateway` running"
        )
        diagnostics.append(
            ConnectorDiagnostic(connector_id, "present", verification, runtime, action)
        )
    return tuple(diagnostics)


def _default_factories() -> dict[str, Callable[..., Any]]:
    return {
        "telegram": TelegramConnector,
        "slack": SlackConnector,
        "whatsapp": WhatsAppConnector,
    }


def _required_values(
    connector_id: str, secrets: Mapping[str, str]
) -> tuple[tuple[str, str | None], ...]:
    keys = {
        "telegram": (("bot token", "TELEGRAM_BOT_TOKEN"),),
        "slack": (("bot token", "SLACK_BOT_TOKEN"), ("app token", "SLACK_APP_TOKEN")),
        "whatsapp": (
            ("access token", "WHATSAPP_ACCESS_TOKEN"),
            ("phone number ID", "WHATSAPP_PHONE_NUMBER_ID"),
            ("app secret", "WHATSAPP_APP_SECRET"),
            ("verify token", "WHATSAPP_VERIFY_TOKEN"),
        ),
    }.get(connector_id, ())
    return tuple((label, secrets.get(key)) for label, key in keys)


def _failure_action(connector_id: str, detail: str) -> str:
    lowered = detail.lower()
    if "auth" in lowered or "token" in lowered or "401" in lowered or "403" in lowered:
        return f"Reconnect {connector_id}; its credential may be invalid, expired, or missing a required permission."
    if connector_id == "slack" and "connections" in lowered:
        return "Check that the xapp token has connections:write and Socket Mode is enabled."
    return f"Open the {connector_id} setup with `connect {connector_id}` and review its current step."


def _whatsapp_listener_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8787), timeout=0.2):
            return True
    except OSError:
        return False

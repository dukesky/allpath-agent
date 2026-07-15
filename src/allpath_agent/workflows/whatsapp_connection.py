from __future__ import annotations

from collections.abc import Callable

from allpath_agent.connectors import verify_whatsapp_credentials
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import ConnectorConfigRepository, WorkflowRunRepository

from .provider_connection import ConnectionFlowResult


WORKFLOW_ID = "whatsapp_connection"
ACCESS_TOKEN_KEY = "WHATSAPP_ACCESS_TOKEN"
PHONE_NUMBER_ID_KEY = "WHATSAPP_PHONE_NUMBER_ID"
APP_SECRET_KEY = "WHATSAPP_APP_SECRET"
VERIFY_TOKEN_KEY = "WHATSAPP_VERIFY_TOKEN"


class WhatsAppConnectionWorkflow:
    def __init__(
        self,
        runs: WorkflowRunRepository,
        secrets: SecretStore,
        configs: ConnectorConfigRepository,
        verifier: Callable[[str, str], str] = verify_whatsapp_credentials,
    ):
        self._runs = runs
        self._secrets = secrets
        self._configs = configs
        self._verifier = verifier
        self._pending: dict[str, dict[str, str]] = {}

    def active(self, session_id: str) -> bool:
        return self._runs.get_active(session_id, WORKFLOW_ID) is not None

    def secret_prompt(self, session_id: str) -> str:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        step = active["current_step"] if active else "awaiting_access_token"
        return {
            "awaiting_access_token": "WhatsApp access token (hidden)> ",
            "awaiting_phone_number_id": "WhatsApp Phone Number ID (hidden)> ",
            "awaiting_app_secret": "Meta App Secret (hidden)> ",
            "awaiting_verify_token": "Choose a webhook verify token (hidden)> ",
        }[step]

    def handle(self, session_id: str, message: str) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            if not _is_trigger(message):
                return ConnectionFlowResult(False)
            language = "zh" if any("\u4e00" <= char <= "\u9fff" for char in message) else "en"
            self._runs.create(WORKFLOW_ID, session_id, "awaiting_access_token", {"language": language})
            return ConnectionFlowResult(True, (_setup_prompt(language),), request_secret=True)
        if message.strip().lower() in {"cancel", "取消"}:
            self._pending.pop(active["id"], None)
            self._runs.update(active["id"], None, active["state"], status="cancelled")
            return ConnectionFlowResult(True, ("WhatsApp connection cancelled.",))
        return ConnectionFlowResult(True, ("Continue with the hidden setup inputs.",), request_secret=True)

    def submit_secret(self, session_id: str, secret: str) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            return ConnectionFlowResult(False)
        if not secret.strip():
            return ConnectionFlowResult(True, ("This value cannot be empty.",), request_secret=True)
        pending = self._pending.setdefault(active["id"], {})
        step = active["current_step"]
        if step == "awaiting_access_token":
            pending["access_token"] = secret
            return self._advance(active, "awaiting_phone_number_id", "Access token received. Enter the Phone Number ID.")
        if step == "awaiting_phone_number_id":
            pending["phone_number_id"] = secret
            return self._advance(active, "awaiting_app_secret", "Phone Number ID received. Enter the Meta App Secret.")
        if step == "awaiting_app_secret":
            pending["app_secret"] = secret
            return self._advance(active, "awaiting_verify_token", "App Secret received. Choose a webhook verify token.")
        required = {"access_token", "phone_number_id", "app_secret"}
        if not required.issubset(pending):
            self._pending.pop(active["id"], None)
            self._runs.update(active["id"], "awaiting_access_token", active["state"])
            return ConnectionFlowResult(True, ("Setup resumed securely. Enter all credentials again.",), request_secret=True)
        try:
            detail = self._verifier(pending["access_token"], pending["phone_number_id"])
        except Exception as error:
            self._configs.save("whatsapp", "error", f"{type(error).__name__}: {str(error)[:160]}")
            return ConnectionFlowResult(True, (f"WhatsApp verification failed: {str(error)[:200]}",), request_secret=True)
        self._secrets.set(ACCESS_TOKEN_KEY, pending["access_token"])
        self._secrets.set(PHONE_NUMBER_ID_KEY, pending["phone_number_id"])
        self._secrets.set(APP_SECRET_KEY, pending["app_secret"])
        self._secrets.set(VERIFY_TOKEN_KEY, secret)
        self._configs.save("whatsapp", "active", detail)
        self._pending.pop(active["id"], None)
        self._runs.update(active["id"], None, active["state"], status="succeeded")
        return ConnectionFlowResult(
            True,
            (
                f"WhatsApp {detail} credentials are verified. Run allpath-agent gateway, expose local port 8787 "
                "through an HTTPS tunnel, then set Meta's callback URL to https://<public-host>/webhooks/whatsapp "
                "with the verify token you just chose and subscribe to messages.",
            ),
            completed=True,
        )

    def _advance(self, active: dict, step: str, message: str) -> ConnectionFlowResult:
        self._runs.update(active["id"], step, active["state"])
        return ConnectionFlowResult(True, (message,), request_secret=True)


def _is_trigger(message: str) -> bool:
    lowered = message.lower()
    return "whatsapp" in lowered and any(
        phrase in lowered for phrase in ("connect", "setup", "set up", "连接", "配置", "设置")
    )


def _setup_prompt(language: str) -> str:
    if language == "zh":
        return (
            "连接官方 WhatsApp Cloud API：在 Meta for Developers 创建 Business app，添加 WhatsApp 产品，"
            "准备 Access Token、Phone Number ID 和 App Secret。Allpath 还会让你创建一个 webhook verify token。"
            "凭据验证后，需要把本地 8787 端口通过 HTTPS tunnel 暴露给 Meta。"
        )
    return (
        "Connect the official WhatsApp Cloud API: create a Business app in Meta for Developers, add WhatsApp, "
        "and prepare an Access Token, Phone Number ID, and App Secret. You will also choose a webhook verify token. "
        "After credential verification, expose local port 8787 through an HTTPS tunnel for Meta webhooks."
    )

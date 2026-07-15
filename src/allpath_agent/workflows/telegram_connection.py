from __future__ import annotations

from collections.abc import Callable

from allpath_agent.connectors import TelegramConnector
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import ConnectorConfigRepository, WorkflowRunRepository

from .provider_connection import ConnectionFlowResult


WORKFLOW_ID = "telegram_connection"
TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
TelegramVerifier = Callable[[str], str]


class TelegramConnectionWorkflow:
    def __init__(
        self,
        runs: WorkflowRunRepository,
        secrets: SecretStore,
        configs: ConnectorConfigRepository,
        verifier: TelegramVerifier | None = None,
    ):
        self._runs = runs
        self._secrets = secrets
        self._configs = configs
        self._verifier = verifier or verify_telegram_token

    def active(self, session_id: str) -> bool:
        return self._runs.get_active(session_id, WORKFLOW_ID) is not None

    def handle(self, session_id: str, message: str) -> ConnectionFlowResult:
        cleaned = message.strip()
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            if not _is_trigger(cleaned):
                return ConnectionFlowResult(False)
            language = "zh" if any("\u4e00" <= char <= "\u9fff" for char in cleaned) else "en"
            self._runs.create(WORKFLOW_ID, session_id, "awaiting_secret", {"language": language})
            return ConnectionFlowResult(
                True,
                (_setup_prompt(language),),
                request_secret=True,
            )
        language = active["state"].get("language", "en")
        if cleaned.lower() in {"cancel", "取消"}:
            self._runs.update(active["id"], None, active["state"], status="cancelled")
            return ConnectionFlowResult(
                True,
                ("Telegram 连接已取消。" if language == "zh" else "Telegram connection cancelled.",),
            )
        return ConnectionFlowResult(
            True,
            ("请通过隐藏输入提供 Bot Token。" if language == "zh" else "Enter the bot token through hidden input.",),
            request_secret=True,
        )

    def submit_secret(self, session_id: str, token: str) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            return ConnectionFlowResult(False)
        language = active["state"].get("language", "en")
        try:
            detail = self._verifier(token)
        except Exception as error:
            self._configs.save("telegram", "error", f"{type(error).__name__}: {str(error)[:160]}")
            return ConnectionFlowResult(
                True,
                ((f"Telegram 验证失败：{str(error)[:200]}" if language == "zh" else f"Telegram verification failed: {str(error)[:200]}"),),
                request_secret=True,
            )
        self._secrets.set(TOKEN_KEY, token)
        self._configs.save("telegram", "active", detail)
        self._runs.update(active["id"], None, active["state"], status="succeeded")
        return ConnectionFlowResult(
            True,
            ((f"Telegram {detail} 已连接。运行 allpath-agent gateway 开始接收消息。" if language == "zh" else f"Telegram {detail} is connected. Run allpath-agent gateway to receive messages."),),
            completed=True,
        )


def verify_telegram_token(token: str) -> str:
    status = TelegramConnector(token).status()
    if not status.connected:
        raise ValueError(status.detail)
    return status.detail


def _is_trigger(message: str) -> bool:
    lowered = message.lower()
    return "telegram" in lowered and any(
        phrase in lowered
        for phrase in ("connect", "setup", "set up", "连接", "配置", "设置")
    )


def _setup_prompt(language: str) -> str:
    if language == "zh":
        return (
            "连接 Telegram：先在 Telegram 中打开 @BotFather，发送 /newbot，"
            "按提示创建 bot，然后复制 Bot Token。下一步会隐藏输入 Token。"
        )
    return (
        "Connect Telegram: open @BotFather in Telegram, send /newbot, follow the prompts, "
        "then copy the Bot Token. The next input is hidden."
    )

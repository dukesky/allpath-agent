from __future__ import annotations

from collections.abc import Callable

from allpath_agent.connectors import TelegramConnector
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import ConnectorConfigRepository, WorkflowRunRepository

from .connector_onboarding import ConnectorOnboardingGuide, OnboardingStep
from .provider_connection import ConnectionFlowResult


WORKFLOW_ID = "telegram_connection"
TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
TelegramVerifier = Callable[[str], str]
TOKEN_STEP = "copy_token"
GUIDE = ConnectorOnboardingGuide(
    "Telegram",
    (
        OnboardingStep(
            "open_botfather",
            "Open the official BotFather",
            (
                "Open Telegram and navigate to https://t.me/BotFather.",
                "Confirm the account username is exactly `@BotFather` and it has Telegram's verification badge.",
            ),
            "打开官方 BotFather",
            (
                "打开 Telegram 并进入 https://t.me/BotFather。",
                "确认用户名准确为 `@BotFather`，并带有 Telegram 官方认证标记。",
            ),
        ),
        OnboardingStep(
            "create_bot",
            "Create a new bot",
            (
                "Send `/newbot` to BotFather.",
                "Choose the display name users will see, such as `Allpath Agent`.",
            ),
            "创建新 Bot",
            (
                "向 BotFather 发送 `/newbot`。",
                "设置用户看到的显示名称，例如 `Allpath Agent`。",
            ),
        ),
        OnboardingStep(
            "choose_username",
            "Choose the bot username",
            (
                "Enter a unique username that ends in `bot`, for example `my_allpath_agent_bot`.",
                "If BotFather says it is taken, choose another username and retry.",
            ),
            "设置 Bot 用户名",
            (
                "输入一个以 `bot` 结尾的唯一用户名，例如 `my_allpath_agent_bot`。",
                "如果 BotFather 提示已被占用，请换一个用户名重试。",
            ),
        ),
        OnboardingStep(
            TOKEN_STEP,
            "Copy the Bot Token",
            (
                "BotFather now displays an HTTP API token. Treat it like a password.",
                "Do not paste it into normal chat. The next Allpath input is hidden and excluded from conversation history.",
            ),
            "复制 Bot Token",
            (
                "BotFather 现在会显示 HTTP API Token，请把它当作密码保管。",
                "不要粘贴到普通对话中；下一次 Allpath 输入会隐藏，并且不会进入对话历史。",
            ),
        ),
    ),
)


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

    def input_hint(self, session_id: str) -> str | None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None or not GUIDE.contains(active["current_step"]):
            return None
        return GUIDE.input_hint(active["current_step"], active["state"].get("language", "en"))

    def handle(self, session_id: str, message: str) -> ConnectionFlowResult:
        cleaned = message.strip()
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            if not _is_trigger(cleaned):
                return ConnectionFlowResult(False)
            language = "zh" if any("\u4e00" <= char <= "\u9fff" for char in cleaned) else "en"
            first_step = GUIDE.first_id()
            self._runs.create(WORKFLOW_ID, session_id, first_step, {"language": language})
            return ConnectionFlowResult(True, (GUIDE.render(first_step, language),))
        language = active["state"].get("language", "en")
        command = cleaned.lower()
        if command in {"cancel", "取消"}:
            self._runs.update(active["id"], None, active["state"], status="cancelled")
            return ConnectionFlowResult(
                True,
                ("Telegram 连接已取消。" if language == "zh" else "Telegram connection cancelled.",),
            )
        if not GUIDE.contains(active["current_step"]):
            return ConnectionFlowResult(True, ("请通过隐藏输入提供 Bot Token。" if language == "zh" else "Enter the bot token through hidden input.",), request_secret=True)
        if command in {"status", "help", "状态", "帮助", ""}:
            return ConnectionFlowResult(True, (GUIDE.render(active["current_step"], language),))
        if command in {"back", "previous", "返回", "上一步"}:
            previous_step = GUIDE.previous_id(active["current_step"])
            if previous_step is not None:
                self._runs.update(active["id"], previous_step, active["state"])
                return ConnectionFlowResult(True, (GUIDE.render(previous_step, language),))
            return ConnectionFlowResult(True, (GUIDE.render(active["current_step"], language),))
        if command in {"continue", "next", "done", "继续", "下一步", "完成"}:
            if active["current_step"] == TOKEN_STEP:
                self._runs.update(active["id"], "awaiting_secret", active["state"])
                message = "现在通过隐藏输入粘贴 Bot Token。" if language == "zh" else "Now paste the Bot Token through the hidden input."
                return ConnectionFlowResult(True, (message,), request_secret=True)
            next_step = GUIDE.next_id(active["current_step"])
            self._runs.update(active["id"], next_step, active["state"])
            return ConnectionFlowResult(True, (GUIDE.render(next_step, language),))
        reminder = "完成当前步骤后输入“继续”；也可以输入“返回”“状态”或“取消”。" if language == "zh" else "Finish the current step, then type “continue”; or use “back”, “status”, or “cancel”."
        return ConnectionFlowResult(True, (reminder,))

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

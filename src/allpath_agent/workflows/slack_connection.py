from __future__ import annotations

from collections.abc import Callable

from allpath_agent.connectors import verify_slack_tokens
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import ConnectorConfigRepository, WorkflowRunRepository

from .connector_onboarding import ConnectorOnboardingGuide, OnboardingStep
from .provider_connection import ConnectionFlowResult


WORKFLOW_ID = "slack_connection"
BOT_TOKEN_KEY = "SLACK_BOT_TOKEN"
APP_TOKEN_KEY = "SLACK_APP_TOKEN"
GUIDE = ConnectorOnboardingGuide(
    "Slack",
    (
        OnboardingStep(
            "create_app",
            "Create the Slack app",
            (
                "Open https://api.slack.com/apps and select “Create New App”.",
                "Choose “From scratch”, name it “all-path-agent”, and select your workspace.",
            ),
            "创建 Slack App",
            (
                "打开 https://api.slack.com/apps，点击 “Create New App”。",
                "选择 “From scratch”，名称填写 “all-path-agent”，然后选择你的 Workspace。",
            ),
        ),
        OnboardingStep(
            "bot_permissions",
            "Add bot permissions",
            (
                "Open “OAuth & Permissions” in the left sidebar.",
                "Under “Bot Token Scopes”, add `chat:write` and `im:history`.",
            ),
            "添加 Bot 权限",
            (
                "打开左侧的 “OAuth & Permissions”。",
                "在 “Bot Token Scopes” 中添加 `chat:write` 和 `im:history`。",
            ),
        ),
        OnboardingStep(
            "app_home",
            "Allow users to message the app",
            (
                "Open “App Home” and enable the Messages Tab.",
                "Enable “Allow users to send Slash commands and messages from the messages tab”.",
            ),
            "允许用户给 App 发消息",
            (
                "打开 “App Home”，启用 Messages Tab。",
                "启用 “Allow users to send Slash commands and messages from the messages tab”。",
            ),
        ),
        OnboardingStep(
            "events",
            "Subscribe to direct-message events",
            (
                "Open “Event Subscriptions” and switch “Enable Events” on.",
                "Under “Subscribe to bot events”, add `message.im`.",
                "Socket Mode means you do not need to enter a public Request URL.",
            ),
            "订阅私聊消息事件",
            (
                "打开 “Event Subscriptions”，开启 “Enable Events”。",
                "在 “Subscribe to bot events” 中添加 `message.im`。",
                "使用 Socket Mode 时，不需要填写公开 Request URL。",
            ),
        ),
        OnboardingStep(
            "socket_mode",
            "Enable Socket Mode",
            (
                "Open “Socket Mode” and enable it.",
                "When Slack asks for an App-Level Token, name it `allpath-socket` and add `connections:write`.",
                "Copy the generated `xapp-` token somewhere temporary; Allpath will request it shortly.",
            ),
            "启用 Socket Mode",
            (
                "打开 “Socket Mode” 并启用。",
                "Slack 要求创建 App-Level Token 时，命名为 `allpath-socket`，并添加 `connections:write`。",
                "临时复制生成的 `xapp-` Token；Allpath 稍后会通过隐藏输入收集。",
            ),
        ),
        OnboardingStep(
            "install_app",
            "Install the app to the workspace",
            (
                "Open “Install App” or return to “OAuth & Permissions”.",
                "Select “Install to Workspace” and approve the requested permissions.",
                "Copy the “Bot User OAuth Token” beginning with `xoxb-`.",
            ),
            "安装 App 到 Workspace",
            (
                "打开 “Install App”，或返回 “OAuth & Permissions”。",
                "点击 “Install to Workspace” 并批准权限。",
                "复制以 `xoxb-` 开头的 “Bot User OAuth Token”。",
            ),
        ),
        OnboardingStep(
            "token_check",
            "Prepare both tokens",
            (
                "Confirm you now have the `xoxb-` Bot Token and `xapp-` App-Level Token.",
                "The next two inputs are hidden and excluded from conversation history.",
            ),
            "准备两个 Token",
            (
                "确认你已经有 `xoxb-` Bot Token 和 `xapp-` App-Level Token。",
                "接下来的两个输入会隐藏，并且不会写入对话历史。",
            ),
        ),
    ),
)


class SlackConnectionWorkflow:
    def __init__(
        self,
        runs: WorkflowRunRepository,
        secrets: SecretStore,
        configs: ConnectorConfigRepository,
        verifier: Callable[[str, str], str] = verify_slack_tokens,
    ):
        self._runs = runs
        self._secrets = secrets
        self._configs = configs
        self._verifier = verifier
        self._pending_bot_tokens: dict[str, str] = {}

    def active(self, session_id: str) -> bool:
        return self._runs.get_active(session_id, WORKFLOW_ID) is not None

    def input_hint(self, session_id: str) -> str | None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None or not GUIDE.contains(active["current_step"]):
            return None
        return GUIDE.input_hint(active["current_step"], active["state"].get("language", "en"))

    def secret_prompt(self, session_id: str) -> str:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        return "Slack App-Level Token xapp- (hidden)> " if active and active["current_step"] == "awaiting_app" else "Slack Bot Token xoxb- (hidden)> "

    def handle(self, session_id: str, message: str) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            if not _is_trigger(message):
                return ConnectionFlowResult(False)
            language = "zh" if any("\u4e00" <= char <= "\u9fff" for char in message) else "en"
            first_step = GUIDE.first_id()
            self._runs.create(WORKFLOW_ID, session_id, first_step, {"language": language})
            return ConnectionFlowResult(True, (GUIDE.render(first_step, language),))
        cleaned = message.strip().lower()
        language = active["state"].get("language", "en")
        if cleaned in {"cancel", "取消"}:
            self._pending_bot_tokens.pop(active["id"], None)
            self._runs.update(active["id"], None, active["state"], status="cancelled")
            return ConnectionFlowResult(
                True,
                ("Slack 设置已取消。" if language == "zh" else "Slack connection cancelled.",),
            )
        if not GUIDE.contains(active["current_step"]):
            return ConnectionFlowResult(True, ("Continue with hidden token input.",), request_secret=True)
        if cleaned in {"status", "help", "状态", "帮助", ""}:
            return ConnectionFlowResult(True, (GUIDE.render(active["current_step"], language),))
        if cleaned in {"back", "previous", "返回", "上一步"}:
            previous_step = GUIDE.previous_id(active["current_step"])
            if previous_step is None:
                return ConnectionFlowResult(True, (GUIDE.render(active["current_step"], language),))
            self._runs.update(active["id"], previous_step, active["state"])
            return ConnectionFlowResult(True, (GUIDE.render(previous_step, language),))
        if cleaned in {"continue", "next", "done", "继续", "下一步", "完成"}:
            next_step = GUIDE.next_id(active["current_step"])
            if next_step is not None:
                self._runs.update(active["id"], next_step, active["state"])
                return ConnectionFlowResult(True, (GUIDE.render(next_step, language),))
            self._runs.update(active["id"], "awaiting_bot", active["state"])
            prompt = (
                "教程步骤完成。现在通过隐藏输入粘贴 `xoxb-` Bot Token。"
                if language == "zh"
                else "Tutorial complete. Paste the `xoxb-` Bot Token through the hidden input."
            )
            return ConnectionFlowResult(True, (prompt,), request_secret=True)
        reminder = (
            "完成当前页面操作后输入“继续”；也可以输入“返回”“状态”或“取消”。"
            if language == "zh"
            else "Finish the current page action, then type “continue”; or use “back”, “status”, or “cancel”."
        )
        return ConnectionFlowResult(True, (reminder,))

    def submit_secret(self, session_id: str, secret: str) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            return ConnectionFlowResult(False)
        if active["current_step"] == "awaiting_bot":
            if not secret.startswith("xoxb-"):
                return ConnectionFlowResult(True, ("Slack Bot Token must start with xoxb-.",), request_secret=True)
            self._pending_bot_tokens[active["id"]] = secret
            self._runs.update(active["id"], "awaiting_app", active["state"])
            return ConnectionFlowResult(True, ("Bot Token received. Enter the App-Level Token next.",), request_secret=True)
        bot_token = self._pending_bot_tokens.get(active["id"])
        if bot_token is None:
            self._runs.update(active["id"], "awaiting_bot", active["state"])
            return ConnectionFlowResult(True, ("Setup resumed securely. Enter the Bot Token again.",), request_secret=True)
        try:
            detail = self._verifier(bot_token, secret)
        except Exception as error:
            self._configs.save("slack", "error", f"{type(error).__name__}: {str(error)[:160]}")
            return ConnectionFlowResult(True, (f"Slack verification failed: {str(error)[:200]}",), request_secret=True)
        self._secrets.set(BOT_TOKEN_KEY, bot_token)
        self._secrets.set(APP_TOKEN_KEY, secret)
        self._configs.save("slack", "active", detail)
        self._pending_bot_tokens.pop(active["id"], None)
        self._runs.update(active["id"], None, active["state"], status="succeeded")
        return ConnectionFlowResult(True, (f"Slack {detail} is connected. Restart allpath-agent gateway to activate it.",), completed=True)


def _is_trigger(message: str) -> bool:
    lowered = message.lower()
    return "slack" in lowered and any(phrase in lowered for phrase in ("connect", "setup", "set up", "连接", "配置", "设置"))

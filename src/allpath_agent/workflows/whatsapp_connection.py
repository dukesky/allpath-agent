from __future__ import annotations

from collections.abc import Callable

from allpath_agent.connectors import verify_whatsapp_credentials
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import ConnectorConfigRepository, WorkflowRunRepository

from .connector_onboarding import ConnectorOnboardingGuide, OnboardingStep
from .provider_connection import ConnectionFlowResult


WORKFLOW_ID = "whatsapp_connection"
ACCESS_TOKEN_KEY = "WHATSAPP_ACCESS_TOKEN"
PHONE_NUMBER_ID_KEY = "WHATSAPP_PHONE_NUMBER_ID"
APP_SECRET_KEY = "WHATSAPP_APP_SECRET"
VERIFY_TOKEN_KEY = "WHATSAPP_VERIFY_TOKEN"
CREDENTIAL_STEP = "credential_check"
POST_CREDENTIAL_STEP = "run_gateway"
GUIDE = ConnectorOnboardingGuide(
    "WhatsApp",
    (
        OnboardingStep(
            "create_app",
            "Create a Meta Business app",
            (
                "Open https://developers.facebook.com/apps and select “Create App”.",
                "Choose the Business use case, finish app creation, and open the new app dashboard.",
            ),
            "创建 Meta Business App",
            (
                "打开 https://developers.facebook.com/apps，点击 “Create App”。",
                "选择 Business 使用场景，完成创建并进入新 App 的 Dashboard。",
            ),
        ),
        OnboardingStep(
            "add_whatsapp",
            "Add the WhatsApp product",
            (
                "In the app dashboard, find WhatsApp and select “Set up”.",
                "Complete or select the requested Meta Business Portfolio.",
            ),
            "添加 WhatsApp 产品",
            (
                "在 App Dashboard 中找到 WhatsApp，点击 “Set up”。",
                "按页面要求创建或选择 Meta Business Portfolio。",
            ),
        ),
        OnboardingStep(
            "api_setup",
            "Open API Setup",
            (
                "Open WhatsApp > API Setup in the left sidebar.",
                "Locate the temporary Access Token and Phone Number ID; do not paste them into normal chat.",
                "A temporary token is suitable for testing; production use should later switch to a system-user token.",
            ),
            "打开 API Setup",
            (
                "打开左侧 WhatsApp > API Setup。",
                "找到临时 Access Token 和 Phone Number ID；不要把它们粘贴到普通对话中。",
                "临时 Token 适合测试；正式长期运行后续应改用 System User Token。",
            ),
        ),
        OnboardingStep(
            "app_secret",
            "Locate the Meta App Secret",
            (
                "Open App settings > Basic.",
                "Find App Secret and use “Show”; keep it private because Allpath uses it to verify webhook signatures.",
            ),
            "找到 Meta App Secret",
            (
                "打开 App settings > Basic。",
                "找到 App Secret 并点击 “Show”；请保密，Allpath 会用它验证 webhook 签名。",
            ),
        ),
        OnboardingStep(
            CREDENTIAL_STEP,
            "Prepare four connection values",
            (
                "Prepare the Access Token, Phone Number ID, and App Secret.",
                "Also choose a private random webhook verify token; it is a value you invent and enter identically in Meta and Allpath.",
                "The next four inputs are hidden and excluded from conversation history.",
            ),
            "准备四项连接信息",
            (
                "准备 Access Token、Phone Number ID 和 App Secret。",
                "另外创建一个私密随机的 Webhook Verify Token；这是你自定义的值，稍后在 Meta 和 Allpath 中必须完全一致。",
                "接下来的四次输入都会隐藏，并且不会进入对话历史。",
            ),
        ),
        OnboardingStep(
            POST_CREDENTIAL_STEP,
            "Start the local gateway",
            (
                "Open a second terminal and run `allpath-agent gateway`.",
                "Keep that process running. WhatsApp webhooks listen locally on `127.0.0.1:8787`.",
            ),
            "启动本地 Gateway",
            (
                "打开另一个终端，运行 `allpath-agent gateway`。",
                "保持该进程运行。WhatsApp webhook 会在本地监听 `127.0.0.1:8787`。",
            ),
        ),
        OnboardingStep(
            "https_tunnel",
            "Expose port 8787 through HTTPS",
            (
                "Start an HTTPS tunnel that forwards to `http://127.0.0.1:8787` using your preferred tunnel provider.",
                "Copy the public HTTPS hostname. Do not use an HTTP-only URL because Meta requires HTTPS.",
            ),
            "通过 HTTPS 暴露 8787 端口",
            (
                "使用你选择的 tunnel 服务，把公开 HTTPS 地址转发到 `http://127.0.0.1:8787`。",
                "复制公开 HTTPS 域名。Meta 要求 HTTPS，不能使用仅 HTTP 的地址。",
            ),
        ),
        OnboardingStep(
            "configure_webhook",
            "Configure the Meta webhook",
            (
                "Return to the Meta app and open WhatsApp > Configuration.",
                "Set Callback URL to `https://<public-host>/webhooks/whatsapp`.",
                "Enter the exact verify token you chose in Allpath, then select “Verify and save”.",
            ),
            "配置 Meta Webhook",
            (
                "回到 Meta App，打开 WhatsApp > Configuration。",
                "Callback URL 填写 `https://<public-host>/webhooks/whatsapp`。",
                "输入刚才在 Allpath 中设置的相同 Verify Token，然后点击 “Verify and save”。",
            ),
        ),
        OnboardingStep(
            "subscribe_and_test",
            "Subscribe to messages and test",
            (
                "In Webhook fields, subscribe to `messages`.",
                "From an allowed test recipient, send a WhatsApp text to the displayed business test number.",
                "Setup is complete only when the running gateway receives the message and Allpath replies in WhatsApp.",
            ),
            "订阅 messages 并测试",
            (
                "在 Webhook fields 中订阅 `messages`。",
                "使用已允许的测试收件人号码，向页面显示的 Business 测试号码发送 WhatsApp 文字消息。",
                "只有正在运行的 Gateway 收到消息并在 WhatsApp 中回复，才算完成端到端设置。",
            ),
        ),
    ),
)


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

    def input_hint(self, session_id: str) -> str | None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None or not GUIDE.contains(active["current_step"]):
            return None
        return GUIDE.input_hint(active["current_step"], active["state"].get("language", "en"))

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
            first_step = GUIDE.first_id()
            self._runs.create(WORKFLOW_ID, session_id, first_step, {"language": language})
            return ConnectionFlowResult(True, (GUIDE.render(first_step, language),))
        cleaned = message.strip().lower()
        language = active["state"].get("language", "en")
        if cleaned in {"cancel", "取消"}:
            self._pending.pop(active["id"], None)
            self._runs.update(active["id"], None, active["state"], status="cancelled")
            return ConnectionFlowResult(True, (("WhatsApp 设置已取消。" if language == "zh" else "WhatsApp connection cancelled."),))
        if not GUIDE.contains(active["current_step"]):
            return ConnectionFlowResult(True, ("Continue with the hidden setup inputs.",), request_secret=True)
        if cleaned in {"status", "help", "状态", "帮助", ""}:
            return ConnectionFlowResult(True, (GUIDE.render(active["current_step"], language),))
        if cleaned in {"back", "previous", "返回", "上一步"}:
            previous_step = GUIDE.previous_id(active["current_step"])
            if previous_step is not None:
                self._runs.update(active["id"], previous_step, active["state"])
                return ConnectionFlowResult(True, (GUIDE.render(previous_step, language),))
            return ConnectionFlowResult(True, (GUIDE.render(active["current_step"], language),))
        if cleaned in {"continue", "next", "done", "继续", "下一步", "完成"}:
            if active["current_step"] == CREDENTIAL_STEP:
                self._runs.update(active["id"], "awaiting_access_token", active["state"])
                message = "现在通过四次隐藏输入提供连接信息。" if language == "zh" else "Now provide the four connection values through hidden inputs."
                return ConnectionFlowResult(True, (message,), request_secret=True)
            next_step = GUIDE.next_id(active["current_step"])
            if next_step is None:
                self._runs.update(active["id"], None, active["state"], status="succeeded")
                message = "WhatsApp 端到端设置完成。请保持 Gateway 和 HTTPS tunnel 运行。" if language == "zh" else "WhatsApp end-to-end setup is complete. Keep the gateway and HTTPS tunnel running."
                return ConnectionFlowResult(True, (message,), completed=True)
            self._runs.update(active["id"], next_step, active["state"])
            return ConnectionFlowResult(True, (GUIDE.render(next_step, language),))
        reminder = "完成当前步骤后输入“继续”；也可以输入“返回”“状态”或“取消”。" if language == "zh" else "Finish the current step, then type “continue”; or use “back”, “status”, or “cancel”."
        return ConnectionFlowResult(True, (reminder,))

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
        state = {**active["state"], "credentials_verified": True}
        self._runs.update(active["id"], POST_CREDENTIAL_STEP, state)
        return ConnectionFlowResult(
            True,
            (
                f"WhatsApp credentials verified: {detail}.\n{GUIDE.render(POST_CREDENTIAL_STEP, active['state'].get('language', 'en'))}",
            ),
        )

    def _advance(self, active: dict, step: str, message: str) -> ConnectionFlowResult:
        self._runs.update(active["id"], step, active["state"])
        return ConnectionFlowResult(True, (message,), request_secret=True)


def _is_trigger(message: str) -> bool:
    lowered = message.lower()
    return "whatsapp" in lowered and any(
        phrase in lowered for phrase in ("connect", "setup", "set up", "连接", "配置", "设置")
    )

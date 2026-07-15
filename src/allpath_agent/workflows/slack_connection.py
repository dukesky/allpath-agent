from __future__ import annotations

from collections.abc import Callable

from allpath_agent.connectors import verify_slack_tokens
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import ConnectorConfigRepository, WorkflowRunRepository

from .provider_connection import ConnectionFlowResult


WORKFLOW_ID = "slack_connection"
BOT_TOKEN_KEY = "SLACK_BOT_TOKEN"
APP_TOKEN_KEY = "SLACK_APP_TOKEN"


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

    def secret_prompt(self, session_id: str) -> str:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        return "Slack App-Level Token xapp- (hidden)> " if active and active["current_step"] == "awaiting_app" else "Slack Bot Token xoxb- (hidden)> "

    def handle(self, session_id: str, message: str) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            if not _is_trigger(message):
                return ConnectionFlowResult(False)
            language = "zh" if any("\u4e00" <= char <= "\u9fff" for char in message) else "en"
            self._runs.create(WORKFLOW_ID, session_id, "awaiting_bot", {"language": language})
            return ConnectionFlowResult(True, (_setup_prompt(language),), request_secret=True)
        if message.strip().lower() in {"cancel", "取消"}:
            self._pending_bot_tokens.pop(active["id"], None)
            self._runs.update(active["id"], None, active["state"], status="cancelled")
            return ConnectionFlowResult(True, ("Slack connection cancelled.",))
        return ConnectionFlowResult(True, ("Continue with hidden token input.",), request_secret=True)

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


def _setup_prompt(language: str) -> str:
    return (
        "Connect Slack with Socket Mode: create an app at api.slack.com/apps; add bot scope chat:write; "
        "enable App Home messages and Event Subscriptions with message.im; enable Socket Mode; "
        "create an App-Level Token with connections:write; install the app to your workspace. "
        "You will enter the xoxb- Bot Token and xapp- App-Level Token through hidden inputs."
    )

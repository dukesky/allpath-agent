from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from allpath_agent.config import AgentConfig, AppConfig, ProviderConfig
from allpath_agent.models import (
    AuthType,
    ChatMessage,
    ChatRequest,
    ModelProfile,
    ProviderProtocol,
)
from allpath_agent.provider_runtime import build_provider_pool
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import WorkflowRunRepository


WORKFLOW_ID = "provider_connection"


@dataclass(frozen=True)
class ProviderChoice:
    id: str
    label: str
    protocol: ProviderProtocol
    auth: AuthType
    base_url: str = ""
    api_key_env: str = ""
    external_command: str = ""
    default_model: str = ""
    supports_tools: bool = True
    timeout_seconds: float = 60.0


CHOICES: tuple[ProviderChoice, ...] = (
    ProviderChoice(
        "openai",
        "OpenAI API",
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        AuthType.API_KEY,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    ),
    ProviderChoice(
        "anthropic",
        "Anthropic API",
        ProviderProtocol.ANTHROPIC_MESSAGES,
        AuthType.API_KEY,
        base_url="https://api.anthropic.com",
        api_key_env="ANTHROPIC_API_KEY",
    ),
    ProviderChoice(
        "openrouter",
        "OpenRouter",
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        AuthType.API_KEY,
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
    ),
    ProviderChoice(
        "ollama",
        "Ollama",
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        AuthType.NONE,
        base_url="http://127.0.0.1:11434/v1",
        default_model="llama3.2",
    ),
    ProviderChoice(
        "claude-code",
        "Claude Code account",
        ProviderProtocol.EXTERNAL_CLI,
        AuthType.EXTERNAL_CLI,
        external_command="claude",
        default_model="sonnet",
        supports_tools=False,
        timeout_seconds=300.0,
    ),
)


@dataclass(frozen=True)
class ConnectionFlowResult:
    handled: bool
    messages: tuple[str, ...] = ()
    request_secret: bool = False
    completed: bool = False


Verifier = Callable[[ProviderConfig, ModelProfile, str], None]


class ProviderConnectionWorkflow:
    def __init__(
        self,
        config_path: str | Path,
        runs: WorkflowRunRepository,
        secrets: SecretStore,
        verifier: Verifier | None = None,
    ):
        self._config_path = Path(config_path)
        self._runs = runs
        self._secrets = secrets
        self._verifier = verifier or verify_provider_connection

    def active(self, session_id: str) -> bool:
        return self._runs.get_active(session_id, WORKFLOW_ID) is not None

    def handle(self, session_id: str, message: str) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            if not _is_connection_request(message):
                return ConnectionFlowResult(False)
            language = "zh" if _contains_chinese(message) else "en"
            self._runs.create(
                WORKFLOW_ID,
                session_id,
                "choose_provider",
                {"language": language},
            )
            return ConnectionFlowResult(True, (_provider_prompt(language),))

        cleaned = message.strip()
        state = dict(active["state"])
        language = state.get("language", "en")
        if cleaned.lower() in {"cancel", "/cancel", "取消"}:
            self._runs.update(active["id"], None, state, status="cancelled")
            return ConnectionFlowResult(
                True,
                (_text(language, "已取消模型连接。", "Model connection cancelled."),),
            )

        if active["current_step"] == "choose_provider":
            choice = _resolve_choice(cleaned)
            if choice is None:
                return ConnectionFlowResult(
                    True,
                    (_text(language, "请选择 1–5，或输入“取消”。", "Choose 1–5, or type cancel."),),
                )
            state["provider"] = choice.id
            self._runs.update(active["id"], "choose_model", state)
            return ConnectionFlowResult(True, (_model_prompt(choice, language),))

        if active["current_step"] == "choose_model":
            choice = _choice_by_id(state["provider"])
            model = cleaned or choice.default_model
            if not model:
                return ConnectionFlowResult(
                    True,
                    (_text(language, "请输入 Provider 的模型 ID。", "Enter the provider model ID."),),
                )
            state["model"] = model
            if choice.auth == AuthType.API_KEY:
                self._runs.update(active["id"], "awaiting_secret", state)
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            "下一步请输入 API Key；输入内容不会显示或写入对话记录。",
                            "Next, enter the API key. It will be hidden and excluded "
                            "from conversation history.",
                        ),
                    ),
                    request_secret=True,
                )
            return self._finalize(active["id"], state, "")

        if active["current_step"] == "awaiting_secret":
            return ConnectionFlowResult(
                True,
                (_text(language, "请使用隐藏的 API Key 输入提示。", "Use the hidden API-key prompt."),),
                request_secret=True,
            )
        return ConnectionFlowResult(False)

    def submit_secret(self, session_id: str, secret: str) -> ConnectionFlowResult:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None or active["current_step"] != "awaiting_secret":
            return ConnectionFlowResult(False)
        if not secret:
            language = active["state"].get("language", "en")
            return ConnectionFlowResult(
                True,
                (_text(language, "API Key 不能为空。", "API key cannot be empty."),),
                request_secret=True,
            )
        return self._finalize(active["id"], dict(active["state"]), secret)

    def _finalize(
        self,
        run_id: str,
        state: dict[str, Any],
        secret: str,
    ) -> ConnectionFlowResult:
        choice = _choice_by_id(state["provider"])
        language = state.get("language", "en")
        provider = _provider_config(choice)
        profile = _model_profile(choice, state["model"])
        try:
            self._verifier(provider, profile, secret)
        except Exception as error:
            next_step = "awaiting_secret" if choice.auth == AuthType.API_KEY else "choose_model"
            self._runs.update(run_id, next_step, state)
            message = _text(
                language,
                f"连接验证失败：{type(error).__name__}: {str(error)[:240]}",
                f"Connection verification failed: {type(error).__name__}: {str(error)[:240]}",
            )
            return ConnectionFlowResult(
                True,
                (message,),
                request_secret=choice.auth == AuthType.API_KEY,
            )

        if choice.auth == AuthType.API_KEY:
            self._secrets.set(choice.api_key_env, secret)
        _write_config_atomic(self._config_path, provider, profile)
        self._runs.update(run_id, None, state, status="succeeded")
        return ConnectionFlowResult(
            True,
            (
                _text(
                    language,
                    f"{choice.label} 已连接并验证。现在切换到真实模型 {profile.model}。",
                    f"{choice.label} is connected and verified. Switching to live model {profile.model} now.",
                ),
            ),
            completed=True,
        )


def verify_provider_connection(
    provider: ProviderConfig,
    profile: ModelProfile,
    secret: str,
) -> None:
    environment = {provider.api_key_env: secret} if provider.api_key_env else {}
    config = AppConfig(
        providers={provider.id: provider},
        agent=AgentConfig("You are Allpath Agent.", 3, 6),
        models=(profile,),
    )
    pool = build_provider_pool(config, environment)
    response = pool.complete(
        provider.id,
        ChatRequest(
            profile.model,
            (ChatMessage("user", "Reply with OK to verify this connection."),),
        ),
    )
    if not response.content:
        raise ValueError("provider verification returned no text")


def _provider_config(choice: ProviderChoice) -> ProviderConfig:
    return ProviderConfig(
        id=choice.id,
        protocol=choice.protocol,
        auth=choice.auth,
        base_url=choice.base_url,
        api_key_env=choice.api_key_env,
        external_command=choice.external_command,
        timeout_seconds=choice.timeout_seconds,
    )


def _model_profile(choice: ProviderChoice, model: str) -> ModelProfile:
    return ModelProfile(
        name="default",
        model=model,
        quality=6,
        cost=3,
        supports_tools=choice.supports_tools,
        supports_vision=False,
        max_context_tokens=128_000,
        provider=choice.id,
    )


def _write_config_atomic(
    path: Path,
    provider: ProviderConfig,
    profile: ModelProfile,
) -> None:
    lines = [
        f"[providers.{provider.id}]",
        f"protocol = {_toml_string(provider.protocol.value)}",
        f"auth = {_toml_string(provider.auth.value)}",
    ]
    if provider.base_url:
        lines.append(f"base_url = {_toml_string(provider.base_url)}")
    if provider.api_key_env:
        lines.append(f"api_key_env = {_toml_string(provider.api_key_env)}")
    if provider.external_command:
        lines.append(f"external_command = {_toml_string(provider.external_command)}")
    lines.extend(
        [
            f"timeout_seconds = {provider.timeout_seconds}",
            "",
            "[agent]",
            'system_prompt = "You are Allpath Agent, a concise and helpful personal assistant."',
            "max_model_calls = 12",
            "max_task_tokens = 100000",
            "max_task_cost_usd = 0.0",
            "provider_max_attempts = 3",
            "retry_base_delay_seconds = 0.5",
            "retry_max_delay_seconds = 8.0",
            "advanced_threshold = 6",
            "",
            "[models.default]",
            f"provider = {_toml_string(profile.provider)}",
            f"model = {_toml_string(profile.model)}",
            f"quality = {profile.quality}",
            f"cost = {profile.cost}",
            f"supports_tools = {str(profile.supports_tools).lower()}",
            "supports_vision = false",
            f"max_context_tokens = {profile.max_context_tokens}",
            "input_cost_per_million = 0.0",
            "output_cost_per_million = 0.0",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _resolve_choice(value: str) -> ProviderChoice | None:
    normalized = value.strip().lower()
    aliases = {
        "1": "openai",
        "2": "anthropic",
        "3": "openrouter",
        "4": "ollama",
        "5": "claude-code",
        "claude": "claude-code",
        "claude code": "claude-code",
    }
    return next(
        (
            choice
            for choice in CHOICES
            if choice.id == aliases.get(normalized, normalized)
        ),
        None,
    )


def _choice_by_id(provider_id: str) -> ProviderChoice:
    choice = _resolve_choice(provider_id)
    if choice is None:
        raise ValueError(f"unknown provider choice: {provider_id}")
    return choice


def _provider_prompt(language: str) -> str:
    if language == "zh":
        return (
            "我们在当前对话中连接模型。请选择：\n"
            "1. OpenAI API\n2. Anthropic API\n3. OpenRouter\n"
            "4. Ollama（本地）\n5. Claude Code 账号\n输入“取消”可退出。"
        )
    return (
        "Let's connect a model in this conversation. Choose:\n"
        "1. OpenAI API\n2. Anthropic API\n3. OpenRouter\n"
        "4. Ollama (local)\n5. Claude Code account\nType cancel to stop."
    )


def _model_prompt(choice: ProviderChoice, language: str) -> str:
    default = f"（直接回车使用 {choice.default_model}）" if choice.default_model else ""
    default_en = f" (press Enter for {choice.default_model})" if choice.default_model else ""
    return _text(
        language,
        f"请输入 {choice.label} 的模型 ID{default}。",
        f"Enter the model ID for {choice.label}{default_en}.",
    )


def _is_connection_request(message: str) -> bool:
    lowered = message.lower()
    return any(
        phrase in lowered
        for phrase in (
            "connect a model",
            "connect model",
            "connect a provider",
            "model setup",
            "连接模型",
            "模型配置",
            "配置模型",
        )
    )


def _contains_chinese(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def _text(language: str, chinese: str, english: str) -> str:
    return chinese if language == "zh" else english

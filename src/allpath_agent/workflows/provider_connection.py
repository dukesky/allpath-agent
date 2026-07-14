from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from allpath_agent.config import AgentConfig, AppConfig, ProviderConfig, load_config
from allpath_agent.models import (
    AuthType,
    ChatMessage,
    ChatRequest,
    ModelProfile,
    ProviderProtocol,
    available_models,
    discover_provider_models,
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
        "openai-codex",
        "OpenAI Codex / ChatGPT account",
        ProviderProtocol.EXTERNAL_CLI,
        AuthType.EXTERNAL_CLI,
        external_command="codex",
        default_model="gpt-5.4",
        supports_tools=False,
        timeout_seconds=300.0,
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
        "xai",
        "xAI Grok API",
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        AuthType.API_KEY,
        base_url="https://api.x.ai/v1",
        api_key_env="XAI_API_KEY",
    ),
    ProviderChoice(
        "gemini",
        "Google Gemini API",
        ProviderProtocol.GEMINI_GENERATE_CONTENT,
        AuthType.API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GEMINI_API_KEY",
        supports_tools=False,
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
ModelDiscoverer = Callable[[str, str, str], tuple[str, ...]]


PROFILE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("fast", "Fast — cheapest eligible model for simple tasks"),
    ("standard", "Standard — balanced everyday model"),
    ("advanced", "Advanced — highest-quality model for complex tasks"),
)


class ProviderConnectionWorkflow:
    def __init__(
        self,
        config_path: str | Path,
        runs: WorkflowRunRepository,
        secrets: SecretStore,
        verifier: Verifier | None = None,
        model_discoverer: ModelDiscoverer | None = None,
    ):
        self._config_path = Path(config_path)
        self._runs = runs
        self._secrets = secrets
        self._verifier = verifier or verify_provider_connection
        self._model_discoverer = model_discoverer or discover_provider_models
        self._pending_secrets: dict[str, str] = {}

    def active(self, session_id: str) -> bool:
        return self._runs.get_active(session_id, WORKFLOW_ID) is not None

    def current_step(self, session_id: str) -> str | None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        return active["current_step"] if active else None

    def selected_provider(self, session_id: str) -> str | None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        return active["state"].get("provider") if active else None

    def provider_options(self) -> tuple[str, ...]:
        return tuple(choice.label for choice in CHOICES)

    def profile_options(self) -> tuple[str, ...]:
        return tuple(label for _, label in PROFILE_OPTIONS)

    def model_options(self, session_id: str) -> tuple[str, ...]:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            return ()
        options = active["state"].get("model_options")
        if isinstance(options, list) and all(isinstance(item, str) for item in options):
            return tuple(options)
        provider_id = active["state"].get("provider")
        return available_models(provider_id) if provider_id else ()

    def set_external_command(self, session_id: str, command: str) -> None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None or not command:
            return
        state = dict(active["state"])
        state["external_command"] = command
        self._runs.update(active["id"], active["current_step"], state)

    def input_hint(self, session_id: str) -> str | None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            return None
        language = active["state"].get("language", "en")
        if active["current_step"] == "choose_provider":
            return _text(
                language,
                f"输入 1–{len(CHOICES)} 选择模型服务，或输入“取消”",
                f"Type 1–{len(CHOICES)} to choose a provider, or type cancel",
            )
        if active["current_step"] == "choose_model":
            choice = _choice_by_id(active["state"]["provider"])
            if choice.default_model:
                return _text(
                    language,
                    f"输入模型 ID；直接回车使用 {choice.default_model}",
                    f"Enter a model ID; press Enter for {choice.default_model}",
                )
            return _text(language, "输入模型 ID", "Enter a model ID")
        if active["current_step"] == "choose_profile":
            return _text(
                language,
                "选择 fast、standard 或 advanced",
                "Choose fast, standard, or advanced",
            )
        if active["current_step"] == "awaiting_secret":
            return _text(language, "API Key 将隐藏输入", "API key input will be hidden")
        return None

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
                    (
                        _text(
                            language,
                            f"请选择 1–{len(CHOICES)}，或输入“取消”。",
                            f"Choose 1–{len(CHOICES)}, or type cancel.",
                        ),
                    ),
                )
            state["provider"] = choice.id
            if choice.auth == AuthType.API_KEY:
                self._runs.update(active["id"], "awaiting_secret", state)
                return ConnectionFlowResult(
                    True,
                    (_secret_prompt(language, discover_models=True),),
                    request_secret=True,
                )
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
            options = state.get("model_options")
            if isinstance(options, list) and model not in options:
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            "请选择列表中的模型，或重新连接以刷新目录。",
                            "Choose a model from the list, or reconnect to refresh the catalog.",
                        ),
                    ),
                )
            state["model"] = model
            self._runs.update(active["id"], "choose_profile", state)
            return ConnectionFlowResult(True, (_profile_prompt(language),))

        if active["current_step"] == "choose_profile":
            profile_name = _resolve_profile(cleaned)
            if profile_name is None:
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            "请选择 fast、standard 或 advanced。",
                            "Choose fast, standard, or advanced.",
                        ),
                    ),
                )
            state["profile"] = profile_name
            choice = _choice_by_id(state["provider"])
            if choice.auth == AuthType.API_KEY and active["id"] not in self._pending_secrets:
                self._runs.update(active["id"], "awaiting_secret", state)
                return ConnectionFlowResult(
                    True,
                    (_secret_prompt(language, discover_models=False),),
                    request_secret=True,
                )
            secret = self._pending_secrets.pop(active["id"], "")
            return self._finalize(active["id"], state, secret)

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
        state = dict(active["state"])
        if state.get("model") and state.get("profile"):
            return self._finalize(active["id"], state, secret)
        choice = _choice_by_id(state["provider"])
        models = self._model_discoverer(choice.id, choice.base_url, secret)
        state["model_options"] = list(models or available_models(choice.id))
        self._pending_secrets[active["id"]] = secret
        self._runs.update(active["id"], "choose_model", state)
        return ConnectionFlowResult(
            True,
            (
                _text(
                    state.get("language", "en"),
                    f"已加载 {len(state['model_options'])} 个可用模型，请选择。",
                    f"Loaded {len(state['model_options'])} available models. Choose one.",
                ),
            ),
        )

    def _finalize(
        self,
        run_id: str,
        state: dict[str, Any],
        secret: str,
    ) -> ConnectionFlowResult:
        choice = _choice_by_id(state["provider"])
        language = state.get("language", "en")
        provider = _provider_config(choice, state.get("external_command", ""))
        profile = _model_profile(choice, state["model"], state["profile"])
        try:
            self._verifier(provider, profile, secret)
        except Exception as error:
            self._pending_secrets.pop(run_id, None)
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
        self._pending_secrets.pop(run_id, None)
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


def _provider_config(choice: ProviderChoice, external_command: str = "") -> ProviderConfig:
    return ProviderConfig(
        id=choice.id,
        protocol=choice.protocol,
        auth=choice.auth,
        base_url=choice.base_url,
        api_key_env=choice.api_key_env,
        external_command=external_command or choice.external_command,
        timeout_seconds=choice.timeout_seconds,
    )


def _model_profile(choice: ProviderChoice, model: str, profile_name: str) -> ModelProfile:
    quality, cost = {
        "fast": (4, 1),
        "standard": (7, 4),
        "advanced": (10, 8),
    }[profile_name]
    return ModelProfile(
        name=profile_name,
        model=model,
        quality=quality,
        cost=cost,
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
    if path.is_file():
        existing = load_config(path)
        providers = dict(existing.providers)
        models = {item.name: item for item in existing.models}
        agent = existing.agent
    else:
        providers = {}
        models = {}
        agent = AgentConfig(
            "You are Allpath Agent, a concise and helpful personal assistant.",
            12,
            6,
        )
    providers[provider.id] = provider
    models[profile.name] = profile
    _write_app_config_atomic(
        path,
        AppConfig(providers=providers, agent=agent, models=tuple(models.values())),
    )


def reassign_model_role(path: Path, source_role: str, target_role: str) -> None:
    config = load_config(path)
    models = {item.name: item for item in config.models}
    if source_role not in models:
        raise ValueError(f"model role is not configured: {source_role}")
    if target_role not in {name for name, _ in PROFILE_OPTIONS}:
        raise ValueError(f"unsupported model role: {target_role}")
    if target_role in models and target_role != source_role:
        raise ValueError(f"target model role is already configured: {target_role}")
    source = models.pop(source_role)
    quality, cost = {
        "fast": (4, 1),
        "standard": (7, 4),
        "advanced": (10, 8),
    }[target_role]
    models[target_role] = ModelProfile(
        name=target_role,
        model=source.model,
        quality=quality,
        cost=cost,
        supports_tools=source.supports_tools,
        supports_vision=source.supports_vision,
        max_context_tokens=source.max_context_tokens,
        provider=source.provider,
        input_cost_per_million=source.input_cost_per_million,
        output_cost_per_million=source.output_cost_per_million,
    )
    _write_app_config_atomic(path, AppConfig(config.providers, config.agent, tuple(models.values())))


def remove_model_role(path: Path, role: str) -> str | None:
    config = load_config(path)
    models = {item.name: item for item in config.models}
    if role not in models:
        raise ValueError(f"model role is not configured: {role}")
    if len(models) == 1:
        raise ValueError("cannot remove the last configured model role")
    removed = models.pop(role)
    providers = dict(config.providers)
    removed_provider = None
    if removed.provider not in {item.provider for item in models.values()}:
        providers.pop(removed.provider, None)
        removed_provider = removed.provider
    _write_app_config_atomic(path, AppConfig(providers, config.agent, tuple(models.values())))
    return removed_provider


def _write_app_config_atomic(path: Path, config: AppConfig) -> None:
    lines: list[str] = []
    for provider_id, configured in sorted(config.providers.items()):
        lines.extend(_serialize_provider(provider_id, configured))
    lines.extend(_serialize_agent(config.agent))
    for configured in sorted(config.models, key=lambda item: item.name):
        lines.extend(_serialize_profile(configured.name, configured))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)


def _serialize_provider(provider_id: str, provider: ProviderConfig) -> list[str]:
    lines = [
        f"[providers.{provider_id}]",
        f"protocol = {_toml_string(provider.protocol.value)}",
        f"auth = {_toml_string(provider.auth.value)}",
    ]
    if provider.base_url:
        lines.append(f"base_url = {_toml_string(provider.base_url)}")
    if provider.api_key_env:
        lines.append(f"api_key_env = {_toml_string(provider.api_key_env)}")
    if provider.protocol == ProviderProtocol.ANTHROPIC_MESSAGES:
        lines.append(f"max_output_tokens = {provider.max_output_tokens}")
    if provider.external_command:
        lines.append(f"external_command = {_toml_string(provider.external_command)}")
    lines.extend([f"timeout_seconds = {provider.timeout_seconds}", ""])
    return lines


def _serialize_agent(agent: AgentConfig) -> list[str]:
    return [
        "[agent]",
        f"system_prompt = {_toml_string(agent.system_prompt)}",
        f"max_model_calls = {agent.max_model_calls}",
        f"max_task_tokens = {agent.max_task_tokens}",
        f"max_task_cost_usd = {agent.max_task_cost_usd}",
        f"provider_max_attempts = {agent.provider_max_attempts}",
        f"retry_base_delay_seconds = {agent.retry_base_delay_seconds}",
        f"retry_max_delay_seconds = {agent.retry_max_delay_seconds}",
        f"advanced_threshold = {agent.advanced_threshold}",
        "",
    ]


def _serialize_profile(profile_name: str, profile: ModelProfile) -> list[str]:
    return [
        f"[models.{profile_name}]",
        f"provider = {_toml_string(profile.provider)}",
        f"model = {_toml_string(profile.model)}",
        f"quality = {profile.quality}",
        f"cost = {profile.cost}",
        f"supports_tools = {str(profile.supports_tools).lower()}",
        f"supports_vision = {str(profile.supports_vision).lower()}",
        f"max_context_tokens = {profile.max_context_tokens}",
        f"input_cost_per_million = {profile.input_cost_per_million}",
        f"output_cost_per_million = {profile.output_cost_per_million}",
        "",
    ]


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _resolve_choice(value: str) -> ProviderChoice | None:
    normalized = value.strip().lower()
    aliases = {
        "1": "openai",
        "2": "openai-codex",
        "3": "anthropic",
        "4": "xai",
        "5": "gemini",
        "6": "openrouter",
        "7": "ollama",
        "8": "claude-code",
        "codex": "openai-codex",
        "chatgpt": "openai-codex",
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


def _resolve_profile(value: str) -> str | None:
    normalized = value.strip().lower()
    aliases = {"1": "fast", "2": "standard", "3": "advanced"}
    candidate = aliases.get(normalized, normalized)
    return candidate if candidate in {name for name, _ in PROFILE_OPTIONS} else None


def _choice_by_id(provider_id: str) -> ProviderChoice:
    choice = _resolve_choice(provider_id)
    if choice is None:
        raise ValueError(f"unknown provider choice: {provider_id}")
    return choice


def _provider_prompt(language: str) -> str:
    if language == "zh":
        return (
            "我们在当前对话中连接模型。请选择：\n"
            "1. OpenAI API\n2. OpenAI Codex / ChatGPT 账号\n3. Anthropic API\n"
            "4. xAI Grok API\n5. Google Gemini API\n6. OpenRouter\n"
            "7. Ollama（本地）\n8. Claude Code 账号\n"
            "Gemini/Grok 个人 App OAuth 不对第三方 Agent 开放，请使用 API。\n"
            "输入“取消”可退出。"
        )
    return (
        "Let's connect a model in this conversation. Choose:\n"
        "1. OpenAI API\n2. OpenAI Codex / ChatGPT account\n3. Anthropic API\n"
        "4. xAI Grok API\n5. Google Gemini API\n6. OpenRouter\n"
        "7. Ollama (local)\n8. Claude Code account\n"
        "Gemini/Grok personal app OAuth is not available to third-party agents; use their APIs.\n"
        "Type cancel to stop."
    )


def _model_prompt(choice: ProviderChoice, language: str) -> str:
    default = f"（直接回车使用 {choice.default_model}）" if choice.default_model else ""
    default_en = f" (press Enter for {choice.default_model})" if choice.default_model else ""
    return _text(
        language,
        f"请输入 {choice.label} 的模型 ID{default}。",
        f"Enter the model ID for {choice.label}{default_en}.",
    )


def _profile_prompt(language: str) -> str:
    return _text(
        language,
        "这个模型用于哪类任务？请选择：\n1. fast（便宜、简单任务）\n"
        "2. standard（日常平衡）\n3. advanced（复杂任务、最高质量）",
        "Which task role should use this model? Choose:\n"
        "1. fast (cheap, simple tasks)\n2. standard (balanced everyday tasks)\n"
        "3. advanced (complex, highest-quality tasks)",
    )


def _secret_prompt(language: str, *, discover_models: bool) -> str:
    if discover_models:
        return _text(
            language,
            "下一步请输入 API Key；它将用于加载可用模型，不会显示或写入对话记录。",
            "Next, enter the API key. It will load available models and remain hidden "
            "and excluded from conversation history.",
        )
    return _text(
        language,
        "请重新输入 API Key 以完成验证；Key 不会写入工作流状态。",
        "Re-enter the API key to finish verification. It is not stored in workflow state.",
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

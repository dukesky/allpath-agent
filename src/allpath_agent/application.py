from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from allpath_agent.agent import AgentLoop, AgentResult
from allpath_agent.curriculum import CapabilitySuggestion, CurriculumService
from allpath_agent.models import ModelProfile, ModelRouter, TaskSignals
from allpath_agent.storage import (
    RoutingDecisionRepository,
    ToolApprovalRepository,
    ToolExecutionRepository,
)


@dataclass(frozen=True)
class ApplicationResult:
    agent: AgentResult
    task_id: str
    routing_reason: str
    suggestion: CapabilitySuggestion | None


class AgentApplication:
    def __init__(
        self,
        loop: AgentLoop,
        router: ModelRouter,
        routing_decisions: RoutingDecisionRepository,
        tool_executions: ToolExecutionRepository,
        approvals: ToolApprovalRepository,
        curriculum: CurriculumService,
        system_prompt: str,
        live_provider: bool,
    ):
        self._loop = loop
        self._router = router
        self._routing_decisions = routing_decisions
        self._tool_executions = tool_executions
        self._approvals = approvals
        self._curriculum = curriculum
        self._system_prompt = system_prompt
        self._live_provider = live_provider

    def start_session(self, session_id: str) -> None:
        self._curriculum.start_session(session_id)

    def record_capability_success(self, capability_id: str) -> None:
        self._curriculum.record_success(capability_id)

    def dismiss_suggestion(self, session_id: str, capability_id: str | None = None) -> bool:
        return self._curriculum.dismiss(session_id, capability_id)

    def capability_progress(self) -> list[tuple[str, str, str]]:
        return self._curriculum.list_progress()

    def send(self, session_id: str, message: str) -> ApplicationResult:
        task_id = str(uuid4())
        signals = analyze_task(message)
        decision = self._router.route(signals)
        self._routing_decisions.record(
            session_id,
            task_id,
            decision.profile.name,
            decision.profile.model,
            decision.reason,
            signals.complexity(),
            provider=decision.profile.provider,
        )
        result = self._loop.run(
            session_id,
            task_id,
            message,
            _runtime_system_prompt(self._system_prompt, decision.profile),
            decision.profile,
        )
        evidence = self._task_evidence(session_id, task_id, decision.profile.name)
        suggestion = self._curriculum.after_task(
            session_id,
            detect_intents(message),
            evidence,
        )
        return ApplicationResult(result, task_id, decision.reason, suggestion)

    def _task_evidence(self, session_id: str, task_id: str, profile_name: str) -> set[str]:
        evidence = {"basic_chat"}
        if profile_name == "advanced":
            evidence.add("model_routing")
        if self._live_provider:
            evidence.add("live_provider")

        tool_capabilities = {
            "current_datetime": "current_time",
            "calculate": "calculator",
            "memory_get": "durable_memory",
            "memory_set": "durable_memory",
        }
        for execution in self._tool_executions.list_for_task(session_id, task_id):
            if execution["status"] == "succeeded" and execution["tool_name"] in tool_capabilities:
                evidence.add(tool_capabilities[execution["tool_name"]])
        if self._approvals.list_for_task(session_id, task_id):
            evidence.add("tool_approvals")
        return evidence


def analyze_task(message: str) -> TaskSignals:
    lowered = message.lower()
    deep_phrases = ("deep analysis", "analyze deeply", "深入分析", "详细分析", "不要遗漏")
    code_phrases = ("modify code", "edit file", "fix code", "修改代码", "修改文件", "修复代码")
    risk_phrases = ("delete", "send email", "payment", "删除", "发送邮件", "付款")
    tool_phrases = ("time", "calculate", "remember", "时间", "计算", "记住")
    return TaskSignals(
        estimated_tool_calls=1 if any(phrase in lowered for phrase in tool_phrases) else 0,
        context_tokens=max(1, len(message) // 3),
        requires_tools=any(phrase in lowered for phrase in tool_phrases),
        modifies_code_or_files=any(phrase in lowered for phrase in code_phrases),
        high_risk=any(phrase in lowered for phrase in risk_phrases),
        asks_for_deep_analysis=any(phrase in lowered for phrase in deep_phrases),
    )


def _runtime_system_prompt(system_prompt: str, profile: ModelProfile) -> str:
    tool_access = (
        "Allpath tool schemas may be available for this task."
        if profile.supports_tools
        else "This model connection does not receive Allpath tool schemas."
    )
    external_boundary = (
        " The Codex account provider runs through Codex CLI in a read-only sandbox."
        if profile.provider == "openai-codex"
        else ""
    )
    return (
        f"{system_prompt}\n\n"
        "Runtime identity (authoritative): "
        f"role={profile.name}, provider={profile.provider}, model={profile.model}. "
        f"{tool_access}{external_boundary} "
        "When asked which model or permissions are active, report these exact values and do not guess."
    )


def detect_intents(message: str) -> set[str]:
    lowered = message.lower()
    intents = {"chat"}
    mappings = {
        "time": ("time", "date", "几点", "时间", "日期"),
        "calculation": ("calculate", "math", "计算", "算一下"),
        "memory": ("remember", "preference", "记住", "偏好"),
        "session": ("session", "resume", "会话", "继续之前"),
        "deep_analysis": ("deep analysis", "analyze deeply", "深入分析", "详细分析"),
        "approval": ("approve", "permission", "批准", "权限"),
        "provider": (
            "provider",
            "api key",
            "connect a model",
            "connecting a model",
            "模型配置",
            "连接模型",
        ),
    }
    for intent, phrases in mappings.items():
        if any(phrase in lowered for phrase in phrases):
            intents.add(intent)
    return intents


def demo_profiles() -> tuple[ModelProfile, ...]:
    return (
        ModelProfile("fast", "demo-fast", quality=4, cost=1),
        ModelProfile("advanced", "demo-advanced", quality=10, cost=8, supports_vision=True),
    )

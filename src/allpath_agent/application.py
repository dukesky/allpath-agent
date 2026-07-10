from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from allpath_agent.agent import AgentLoop, AgentResult
from allpath_agent.models import ModelProfile, ModelRouter, TaskSignals
from allpath_agent.storage import RoutingDecisionRepository


@dataclass(frozen=True)
class ApplicationResult:
    agent: AgentResult
    task_id: str
    routing_reason: str


class AgentApplication:
    def __init__(
        self,
        loop: AgentLoop,
        router: ModelRouter,
        routing_decisions: RoutingDecisionRepository,
        system_prompt: str,
    ):
        self._loop = loop
        self._router = router
        self._routing_decisions = routing_decisions
        self._system_prompt = system_prompt

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
        )
        result = self._loop.run(
            session_id,
            task_id,
            message,
            self._system_prompt,
            decision.profile,
        )
        return ApplicationResult(result, task_id, decision.reason)


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


def demo_profiles() -> tuple[ModelProfile, ...]:
    return (
        ModelProfile("fast", "demo-fast", quality=4, cost=1),
        ModelProfile("advanced", "demo-advanced", quality=10, cost=8, supports_vision=True),
    )

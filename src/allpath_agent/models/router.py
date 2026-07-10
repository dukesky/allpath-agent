from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    name: str
    model: str
    quality: int
    cost: int
    supports_tools: bool = True
    supports_vision: bool = False
    max_context_tokens: int = 32_000


@dataclass(frozen=True)
class TaskSignals:
    estimated_tool_calls: int = 0
    context_tokens: int = 0
    requires_vision: bool = False
    requires_tools: bool = False
    modifies_code_or_files: bool = False
    high_risk: bool = False
    asks_for_deep_analysis: bool = False

    def complexity(self) -> int:
        score = min(self.estimated_tool_calls, 6)
        score += 3 if self.modifies_code_or_files else 0
        score += 4 if self.high_risk else 0
        score += 3 if self.asks_for_deep_analysis else 0
        score += 2 if self.context_tokens > 16_000 else 0
        return score


@dataclass(frozen=True)
class RoutingDecision:
    profile: ModelProfile
    reason: str


class ModelRouter:
    def __init__(self, profiles: list[ModelProfile], advanced_threshold: int = 6):
        if not profiles:
            raise ValueError("at least one model profile is required")
        self._profiles = tuple(profiles)
        self._advanced_threshold = advanced_threshold

    def route(self, signals: TaskSignals) -> RoutingDecision:
        eligible = [profile for profile in self._profiles if self._eligible(profile, signals)]
        if not eligible:
            raise ValueError("no configured model satisfies the task requirements")

        complexity = signals.complexity()
        if complexity >= self._advanced_threshold:
            profile = max(eligible, key=lambda item: (item.quality, -item.cost))
            return RoutingDecision(profile, f"advanced task complexity score: {complexity}")

        profile = min(eligible, key=lambda item: (item.cost, -item.quality))
        return RoutingDecision(profile, f"cost-efficient task complexity score: {complexity}")

    @staticmethod
    def _eligible(profile: ModelProfile, signals: TaskSignals) -> bool:
        if signals.requires_tools and not profile.supports_tools:
            return False
        if signals.requires_vision and not profile.supports_vision:
            return False
        return signals.context_tokens <= profile.max_context_tokens

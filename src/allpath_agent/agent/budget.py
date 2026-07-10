from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from allpath_agent.models.router import ModelProfile


class BudgetExceededError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskBudget:
    max_total_tokens: int = 100_000
    max_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.max_total_tokens < 0:
            raise ValueError("max_total_tokens cannot be negative")
        if self.max_cost_usd < 0:
            raise ValueError("max_cost_usd cannot be negative")


@dataclass(frozen=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    usage_reported: bool = False


class BudgetTracker:
    def __init__(self, budget: TaskBudget):
        self._budget = budget
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._estimated_cost_usd = 0.0
        self._usage_reported = False

    @property
    def totals(self) -> UsageTotals:
        return UsageTotals(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            total_tokens=self._total_tokens,
            estimated_cost_usd=self._estimated_cost_usd,
            usage_reported=self._usage_reported,
        )

    def record(self, usage: Mapping[str, int], profile: ModelProfile) -> UsageTotals:
        input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens")
        output_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
        reported_total = _usage_value(usage, "total_tokens")
        total_tokens = reported_total or input_tokens + output_tokens

        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._total_tokens += total_tokens
        self._estimated_cost_usd += (
            input_tokens * profile.input_cost_per_million
            + output_tokens * profile.output_cost_per_million
        ) / 1_000_000
        self._usage_reported = self._usage_reported or bool(usage)
        return self.totals

    def ensure_can_continue(self) -> None:
        if (
            self._budget.max_total_tokens
            and self._total_tokens >= self._budget.max_total_tokens
        ):
            raise BudgetExceededError(
                f"task reached the token budget of {self._budget.max_total_tokens} tokens"
            )
        if (
            self._budget.max_cost_usd
            and self._estimated_cost_usd >= self._budget.max_cost_usd
        ):
            raise BudgetExceededError(
                f"task reached the estimated cost budget of ${self._budget.max_cost_usd:.4f}"
            )


def _usage_value(usage: Mapping[str, int], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return 0

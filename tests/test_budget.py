from __future__ import annotations

import unittest

from allpath_agent.agent import BudgetExceededError, BudgetTracker, TaskBudget
from allpath_agent.models import ModelProfile


class BudgetTrackerTestCase(unittest.TestCase):
    def test_normalizes_provider_usage_and_estimates_cost(self) -> None:
        profile = ModelProfile(
            "priced",
            "model",
            quality=5,
            cost=2,
            input_cost_per_million=2.0,
            output_cost_per_million=8.0,
        )
        tracker = BudgetTracker(TaskBudget(max_total_tokens=1_000, max_cost_usd=1.0))

        tracker.record(
            {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125},
            profile,
        )
        totals = tracker.record({"input_tokens": 50, "output_tokens": 25}, profile)

        self.assertEqual(totals.input_tokens, 150)
        self.assertEqual(totals.output_tokens, 50)
        self.assertEqual(totals.total_tokens, 200)
        self.assertAlmostEqual(totals.estimated_cost_usd, 0.0007)
        self.assertTrue(totals.usage_reported)

    def test_token_budget_stops_continuation(self) -> None:
        tracker = BudgetTracker(TaskBudget(max_total_tokens=100))
        tracker.record({"input_tokens": 80, "output_tokens": 20}, ModelProfile("fast", "model", 4, 1))

        with self.assertRaisesRegex(BudgetExceededError, "100 tokens"):
            tracker.ensure_can_continue()

    def test_cost_budget_stops_continuation(self) -> None:
        profile = ModelProfile(
            "priced",
            "model",
            4,
            1,
            input_cost_per_million=1_000.0,
        )
        tracker = BudgetTracker(TaskBudget(max_cost_usd=0.01))
        tracker.record({"input_tokens": 10}, profile)

        with self.assertRaisesRegex(BudgetExceededError, "estimated cost budget"):
            tracker.ensure_can_continue()


if __name__ == "__main__":
    unittest.main()

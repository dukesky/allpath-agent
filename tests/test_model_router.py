from allpath_agent.models import ModelProfile, ModelRouter, TaskSignals


def profiles() -> list[ModelProfile]:
    return [
        ModelProfile(name="fast", model="fast-model", quality=4, cost=1),
        ModelProfile(name="advanced", model="advanced-model", quality=10, cost=8, supports_vision=True),
    ]


def test_simple_task_uses_cheapest_eligible_model() -> None:
    decision = ModelRouter(profiles()).route(TaskSignals(requires_tools=True))
    assert decision.profile.name == "fast"


def test_complex_task_uses_highest_quality_model() -> None:
    signals = TaskSignals(modifies_code_or_files=True, asks_for_deep_analysis=True)
    decision = ModelRouter(profiles()).route(signals)
    assert decision.profile.name == "advanced"


def test_hard_requirement_filters_models() -> None:
    decision = ModelRouter(profiles()).route(TaskSignals(requires_vision=True))
    assert decision.profile.name == "advanced"

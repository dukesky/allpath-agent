from allpath_agent.curriculum import Capability, CapabilityProgress, CurriculumEngine, LearningStatus


def test_recommends_relevant_eligible_capability() -> None:
    engine = CurriculumEngine(
        [
            Capability("memory", "Memory", 80, trigger_intents=frozenset({"remember"})),
            Capability("calendar", "Calendar", 70, trigger_intents=frozenset({"schedule"})),
        ]
    )

    recommendation = engine.recommend({"schedule"}, {})
    assert recommendation is not None
    assert recommendation.id == "calendar"


def test_prerequisite_blocks_advanced_capability() -> None:
    engine = CurriculumEngine(
        [Capability("daily_brief", "Daily brief", 90, prerequisite_ids=("calendar",))]
    )
    assert engine.recommend({"schedule"}, {}) is None


def test_dismissed_capability_is_not_recommended() -> None:
    engine = CurriculumEngine([Capability("memory", "Memory", 80)])
    progress = {
        "memory": CapabilityProgress("memory", LearningStatus.DISMISSED),
    }
    assert engine.recommend(set(), progress) is None

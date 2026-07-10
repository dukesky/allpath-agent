import unittest

from allpath_agent.curriculum import Capability, CapabilityProgress, CurriculumEngine, LearningStatus


class CurriculumEngineTestCase(unittest.TestCase):
    def test_recommends_relevant_eligible_capability(self) -> None:
        engine = CurriculumEngine(
            [
                Capability("memory", "Memory", 80, trigger_intents=frozenset({"remember"})),
                Capability("calendar", "Calendar", 70, trigger_intents=frozenset({"schedule"})),
            ]
        )

        recommendation = engine.recommend({"schedule"}, {})
        self.assertIsNotNone(recommendation)
        self.assertEqual(recommendation.id, "calendar")

    def test_prerequisite_blocks_advanced_capability(self) -> None:
        engine = CurriculumEngine(
            [Capability("daily_brief", "Daily brief", 90, prerequisite_ids=("calendar",))]
        )
        self.assertIsNone(engine.recommend({"schedule"}, {}))

    def test_dismissed_capability_is_not_recommended(self) -> None:
        engine = CurriculumEngine([Capability("memory", "Memory", 80)])
        progress = {
            "memory": CapabilityProgress("memory", LearningStatus.DISMISSED),
        }
        self.assertIsNone(engine.recommend(set(), progress))


if __name__ == "__main__":
    unittest.main()

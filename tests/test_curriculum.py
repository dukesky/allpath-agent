import unittest
import tempfile
from pathlib import Path

from allpath_agent.curriculum import (
    Capability,
    CapabilityProgress,
    CurriculumEngine,
    CurriculumService,
    LearningStatus,
    default_capabilities,
)
from allpath_agent.storage import (
    CapabilityProgressRepository,
    CapabilitySuggestionRepository,
    CurriculumSessionRepository,
    Database,
    SessionRepository,
)


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

    def test_explicit_intent_beats_unrelated_frequency_priority(self) -> None:
        engine = CurriculumEngine(
            [
                Capability("common", "Common", 100),
                Capability(
                    "provider",
                    "Provider",
                    20,
                    trigger_intents=frozenset({"provider"}),
                    setup_effort=10,
                ),
            ]
        )

        recommendation = engine.recommend({"provider"}, {})

        self.assertEqual(recommendation.id, "provider")

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

    def test_excluded_capability_is_not_recommended(self) -> None:
        engine = CurriculumEngine(
            [
                Capability(
                    "model_routing",
                    "Model routing",
                    100,
                    trigger_intents=frozenset({"deep"}),
                ),
                Capability("memory", "Memory", 50),
            ]
        )

        recommendation = engine.recommend(
            {"deep"},
            {},
            frozenset({"model_routing"}),
        )

        self.assertEqual(recommendation.id, "memory")


class CurriculumServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.sessions = SessionRepository(self.database)
        self.progress = CapabilityProgressRepository(self.database)
        self.suggestions = CapabilitySuggestionRepository(self.database)
        self.service = CurriculumService(
            CurriculumEngine(default_capabilities()),
            self.progress,
            self.suggestions,
            CurriculumSessionRepository(self.database),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_relevant_capability_is_offered_once_per_session(self) -> None:
        session = self.sessions.create()
        self.service.start_session(session.id)
        first = self.service.after_task(session.id, {"chat", "memory"}, {"basic_chat"})
        second = self.service.after_task(session.id, {"chat", "time"}, {"basic_chat"})

        self.assertEqual(first.capability_id, "durable_memory")
        self.assertIsNone(second)
        self.assertEqual(self.progress.get("basic_chat").status, "succeeded")

    def test_catalog_exposes_all_eight_capabilities(self) -> None:
        rows = self.service.list_progress()
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(status == "unseen" for _, _, status in rows))

    def test_success_evidence_prevents_reteaching_used_capability(self) -> None:
        session = self.sessions.create()
        suggestion = self.service.after_task(
            session.id,
            {"chat", "time"},
            {"basic_chat", "current_time"},
        )
        self.assertNotEqual(suggestion.capability_id, "current_time")
        self.assertEqual(self.progress.get("current_time").status, "succeeded")

    def test_recent_offer_has_cross_session_cooldown(self) -> None:
        first_session = self.sessions.create()
        first = self.service.after_task(
            first_session.id,
            {"chat", "memory"},
            {"basic_chat"},
        )
        second_session = self.sessions.create()
        second = self.service.after_task(
            second_session.id,
            {"chat", "memory"},
            {"basic_chat"},
        )

        self.assertEqual(first.capability_id, "durable_memory")
        self.assertNotEqual(second.capability_id, "durable_memory")

    def test_dismissed_capability_stays_suppressed(self) -> None:
        first_session = self.sessions.create()
        offered = self.service.after_task(
            first_session.id,
            {"chat", "memory"},
            {"basic_chat"},
        )
        self.assertTrue(self.service.dismiss(first_session.id))
        second_session = self.sessions.create()
        next_offer = self.service.after_task(
            second_session.id,
            {"chat", "memory"},
            {"basic_chat"},
        )

        self.assertEqual(offered.capability_id, "durable_memory")
        self.assertNotEqual(next_offer.capability_id, "durable_memory")
        self.assertEqual(self.progress.get("durable_memory").status, "dismissed")

    def test_unknown_capability_cannot_be_dismissed(self) -> None:
        session = self.sessions.create()
        self.assertFalse(self.service.dismiss(session.id, "missing"))

    def test_repeated_success_becomes_habitual(self) -> None:
        for _ in range(3):
            self.service.record_success("calculator")
        self.assertEqual(self.progress.get("calculator").status, "habitual")


if __name__ == "__main__":
    unittest.main()

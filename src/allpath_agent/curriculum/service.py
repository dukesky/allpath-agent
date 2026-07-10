from __future__ import annotations

from dataclasses import dataclass

from allpath_agent.storage import (
    CapabilityProgressRepository,
    CapabilitySuggestionRepository,
    CurriculumSessionRepository,
)

from .engine import CapabilityProgress, CurriculumEngine, LearningStatus


@dataclass(frozen=True)
class CapabilitySuggestion:
    capability_id: str
    title: str
    message: str


class CurriculumService:
    def __init__(
        self,
        engine: CurriculumEngine,
        progress: CapabilityProgressRepository,
        suggestions: CapabilitySuggestionRepository,
        sessions: CurriculumSessionRepository,
    ):
        self._engine = engine
        self._progress = progress
        self._suggestions = suggestions
        self._sessions = sessions

    def start_session(self, session_id: str) -> None:
        self._sessions.start_once(session_id)

    def after_task(
        self,
        session_id: str,
        intents: set[str],
        evidence: set[str],
    ) -> CapabilitySuggestion | None:
        self.start_session(session_id)
        for capability_id in sorted(evidence):
            self.record_success(capability_id)

        if self._suggestions.get_for_session(session_id):
            return None

        progress = {
            capability_id: CapabilityProgress(
                capability_id=record.capability_id,
                status=LearningStatus(record.status),
                offer_count=record.offer_count,
                success_count=record.success_count,
                sessions_since_offer=record.sessions_since_offer,
            )
            for capability_id, record in self._progress.list_all().items()
        }
        capability = self._engine.recommend(intents, progress)
        if capability is None:
            return None

        existing = self._progress.get(capability.id)
        self._progress.save(
            capability.id,
            LearningStatus.OFFERED.value,
            offer_count=(existing.offer_count if existing else 0) + 1,
            success_count=existing.success_count if existing else 0,
            sessions_since_offer=0,
        )
        self._suggestions.record(session_id, capability.id, capability.lesson)
        return CapabilitySuggestion(capability.id, capability.title, capability.lesson)

    def record_success(self, capability_id: str) -> None:
        if not self._engine.has_capability(capability_id):
            raise ValueError(f"unknown capability: {capability_id}")
        existing = self._progress.get(capability_id)
        success_count = (existing.success_count if existing else 0) + 1
        status = LearningStatus.HABITUAL if success_count >= 3 else LearningStatus.SUCCEEDED
        self._progress.save(
            capability_id,
            status.value,
            offer_count=existing.offer_count if existing else 0,
            success_count=success_count,
            sessions_since_offer=existing.sessions_since_offer if existing else None,
        )

    def dismiss(self, session_id: str, capability_id: str | None = None) -> bool:
        selected_id = capability_id
        if selected_id is None:
            suggestion = self._suggestions.get_for_session(session_id)
            selected_id = suggestion["capability_id"] if suggestion else None
        if not selected_id:
            return False
        if not self._engine.has_capability(selected_id):
            return False
        existing = self._progress.get(selected_id)
        self._progress.save(
            selected_id,
            LearningStatus.DISMISSED.value,
            offer_count=existing.offer_count if existing else 0,
            success_count=existing.success_count if existing else 0,
            sessions_since_offer=existing.sessions_since_offer if existing else None,
        )
        return True

    def list_progress(self) -> list[tuple[str, str, str]]:
        progress = self._progress.list_all()
        return [
            (
                capability.id,
                capability.title,
                progress[capability.id].status if capability.id in progress else "unseen",
            )
            for capability in self._engine.capabilities()
        ]

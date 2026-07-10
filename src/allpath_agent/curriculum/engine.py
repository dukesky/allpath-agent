from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class LearningStatus(StrEnum):
    LOCKED = "locked"
    ELIGIBLE = "eligible"
    OFFERED = "offered"
    TRIED = "tried"
    SUCCEEDED = "succeeded"
    HABITUAL = "habitual"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    base_priority: int
    prerequisite_ids: tuple[str, ...] = ()
    trigger_intents: frozenset[str] = field(default_factory=frozenset)
    setup_effort: int = 0


@dataclass(frozen=True)
class CapabilityProgress:
    capability_id: str
    status: LearningStatus
    offer_count: int = 0
    success_count: int = 0
    sessions_since_offer: int | None = None


class CurriculumEngine:
    def __init__(self, capabilities: list[Capability]):
        self._capabilities = {capability.id: capability for capability in capabilities}

    def recommend(
        self,
        intents: set[str],
        progress: dict[str, CapabilityProgress],
    ) -> Capability | None:
        completed = {
            capability_id
            for capability_id, state in progress.items()
            if state.status in {LearningStatus.SUCCEEDED, LearningStatus.HABITUAL}
        }
        candidates: list[tuple[int, Capability]] = []

        for capability in self._capabilities.values():
            state = progress.get(capability.id)
            if state and state.status in {
                LearningStatus.SUCCEEDED,
                LearningStatus.HABITUAL,
                LearningStatus.DISMISSED,
            }:
                continue
            if not set(capability.prerequisite_ids).issubset(completed):
                continue

            relevance = 30 if capability.trigger_intents.intersection(intents) else 0
            offer_penalty = (state.offer_count * 20) if state else 0
            fatigue_penalty = 25 if state and state.sessions_since_offer == 0 else 0
            score = capability.base_priority + relevance - capability.setup_effort - offer_penalty - fatigue_penalty
            candidates.append((score, capability))

        if not candidates:
            return None
        score, capability = max(candidates, key=lambda item: (item[0], item[1].id))
        return capability if score > 0 else None

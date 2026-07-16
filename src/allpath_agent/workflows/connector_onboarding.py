from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OnboardingStep:
    id: str
    title: str
    instructions: tuple[str, ...]
    title_zh: str
    instructions_zh: tuple[str, ...]


class ConnectorOnboardingGuide:
    def __init__(self, connector_name: str, steps: tuple[OnboardingStep, ...]):
        if not steps:
            raise ValueError("connector onboarding requires at least one step")
        if len({step.id for step in steps}) != len(steps):
            raise ValueError("connector onboarding step IDs must be unique")
        self.connector_name = connector_name
        self.steps = steps
        self._indexes = {step.id: index for index, step in enumerate(steps)}

    def contains(self, step_id: str | None) -> bool:
        return step_id in self._indexes

    def first_id(self) -> str:
        return self.steps[0].id

    def next_id(self, step_id: str) -> str | None:
        index = self._index(step_id)
        return self.steps[index + 1].id if index + 1 < len(self.steps) else None

    def previous_id(self, step_id: str) -> str | None:
        index = self._index(step_id)
        return self.steps[index - 1].id if index > 0 else None

    def input_hint(self, step_id: str, language: str) -> str:
        position = self._index(step_id) + 1
        if language == "zh":
            return f"{self.connector_name} 设置 {position}/{len(self.steps)} · 输入 继续、返回、状态 或 取消"
        return (
            f"{self.connector_name} setup {position}/{len(self.steps)} · "
            "type continue, back, status, or cancel"
        )

    def render(self, step_id: str, language: str) -> str:
        index = self._index(step_id)
        step = self.steps[index]
        title = step.title_zh if language == "zh" else step.title
        instructions = step.instructions_zh if language == "zh" else step.instructions
        progress = f"[{index + 1}/{len(self.steps)}]"
        next_action = (
            "完成后输入“继续”。你也可以输入“返回”“状态”或“取消”。"
            if language == "zh"
            else "When finished, type “continue”. You can also type “back”, “status”, or “cancel”."
        )
        return "\n".join((f"{self.connector_name} setup {progress} — {title}", *instructions, next_action))

    def _index(self, step_id: str) -> int:
        try:
            return self._indexes[step_id]
        except KeyError as error:
            raise ValueError(f"unknown onboarding step: {step_id}") from error

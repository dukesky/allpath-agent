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


_STATE_QUESTION_MARKERS = ("吗", "是否", "有没有", "了没")
_STATE_QUESTION_PREFIXES = (
    "have ", "has ", "did ", "is ", "are ", "was ", "were ", "am ",
)


def is_state_question(message: str) -> bool:
    stripped = message.strip()
    if any(marker in stripped for marker in _STATE_QUESTION_MARKERS):
        return True
    lowered = stripped.lower()
    if lowered.startswith(_STATE_QUESTION_PREFIXES):
        return True
    return "already" in lowered


def is_reconnect_request(message: str) -> bool:
    lowered = message.lower()
    if "reconnect" in lowered:
        return True
    return any(phrase in message for phrase in ("重新连接", "重新配置", "重连"))


def connection_status_reply(display_name: str, record: dict | None, language: str) -> str:
    connected = record is not None and record.get("status") == "active"
    if language == "zh":
        if connected:
            return (
                f"{display_name} 已连接（{record['detail']}）。"
                f"要重新配置请说“reconnect {display_name}”。"
            )
        return f"{display_name} 尚未连接。说“connect {display_name}”开始配置。"
    if connected:
        return (
            f"{display_name} is connected ({record['detail']}). "
            f"Say “reconnect {display_name}” to reconfigure."
        )
    return f"{display_name} is not connected yet. Say “connect {display_name}” to set it up."

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from allpath_agent.automations import AutomationService, parse_cron, parse_once
from allpath_agent.storage import WorkflowRunRepository

from .provider_connection import ConnectionFlowResult

WORKFLOW_ID = "automation_creation"
STEPS = ("name", "prompt", "schedule", "timezone", "destination", "confirm")

BindingsLister = Callable[[], list[dict[str, Any]]]

_TRIGGERS_EN = ("create automation", "new automation", "add automation")
_TRIGGERS_ZH = ("创建自动化", "新建自动化", "添加自动化", "创建定时任务", "新建定时任务")

_HINTS = {
    "name": {"en": "automation name · cancel", "zh": "自动化名称 · 取消"},
    "prompt": {"en": "task instruction · back · cancel", "zh": "任务指令 · 返回 · 取消"},
    "schedule": {
        "en": 'cron “0 8 * * 1-5” or ISO time · back · cancel',
        "zh": 'cron “0 8 * * 1-5” 或 ISO 时间 · 返回 · 取消',
    },
    "timezone": {"en": 'IANA timezone or “default” · back', "zh": 'IANA 时区或“默认” · 返回'},
    "destination": {"en": 'number, or “none” · back', "zh": '编号，或“无” · 返回'},
    "confirm": {"en": "confirm · back · cancel", "zh": "确认 · 返回 · 取消"},
}


class AutomationCreationWorkflow:
    def __init__(
        self,
        runs: WorkflowRunRepository,
        service: AutomationService,
        list_bindings: BindingsLister,
    ):
        self._runs = runs
        self._service = service
        self._list_bindings = list_bindings

    def active(self, session_id: str) -> bool:
        return self._runs.get_active(session_id, WORKFLOW_ID) is not None

    def input_hint(self, session_id: str) -> str | None:
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None or active["current_step"] not in _HINTS:
            return None
        language = active["state"].get("language", "en")
        return _HINTS[active["current_step"]][language]

    def handle(self, session_id: str, message: str) -> ConnectionFlowResult:
        cleaned = message.strip()
        active = self._runs.get_active(session_id, WORKFLOW_ID)
        if active is None:
            if not _is_trigger(cleaned):
                return ConnectionFlowResult(False)
            language = "zh" if _has_chinese(cleaned) else "en"
            self._runs.create(WORKFLOW_ID, session_id, "name", {"language": language})
            return ConnectionFlowResult(True, (self._prompt("name", {"language": language}),))
        state = dict(active["state"])
        language = state.get("language", "en")
        command = cleaned.lower()
        if command in {"cancel", "取消"}:
            self._runs.update(active["id"], None, state, status="cancelled")
            return ConnectionFlowResult(
                True,
                (_text(language, "Automation creation cancelled.", "已取消创建自动化。"),),
            )
        if command in {"status", "状态"}:
            return ConnectionFlowResult(True, (self._prompt(active["current_step"], state),))
        if command in {"back", "previous", "返回", "上一步"}:
            index = STEPS.index(active["current_step"])
            step = STEPS[max(index - 1, 0)]
            self._runs.update(active["id"], step, state)
            return ConnectionFlowResult(True, (self._prompt(step, state),))
        return self._advance(active, state, language, cleaned)

    def _advance(
        self,
        active: dict[str, Any],
        state: dict[str, Any],
        language: str,
        cleaned: str,
    ) -> ConnectionFlowResult:
        step = active["current_step"]
        if step == "name":
            if len(cleaned) > 60:
                return ConnectionFlowResult(
                    True,
                    (_text(language, "Keep the name under 60 characters.", "名称请控制在 60 个字符以内。"),),
                )
            state["name"] = cleaned
            return self._move(active, state, "prompt")
        if step == "prompt":
            state["prompt"] = cleaned
            return self._move(active, state, "schedule")
        if step == "schedule":
            kind = _schedule_kind(cleaned)
            if kind is None:
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            'Enter a five-field cron expression such as “0 8 * * 1-5”, or an ISO time such as “2026-12-01T08:00”.',
                            '请输入五段 cron 表达式（例如“0 8 * * 1-5”）或 ISO 时间（例如“2026-12-01T08:00”）。',
                        ),
                    ),
                )
            state["schedule_kind"] = kind
            state["schedule_expression"] = cleaned
            return self._move(active, state, "timezone")
        if step == "timezone":
            zone = "UTC" if cleaned.lower() in {"default", "utc", "默认"} else cleaned
            try:
                ZoneInfo(zone)
            except ZoneInfoNotFoundError:
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            f"Unknown IANA timezone: {zone}. Examples: UTC, America/Los_Angeles.",
                            f"未知的 IANA 时区：{zone}。示例：UTC、Asia/Shanghai。",
                        ),
                    ),
                )
            state["timezone"] = zone
            return self._move(active, state, "destination")
        if step == "destination":
            bindings = self._list_bindings()
            if cleaned.lower() in {"none", "no", "无", "不发送"}:
                state["destination_connector_id"] = None
                state["destination_conversation_id"] = None
                return self._move(active, state, "confirm")
            if cleaned.isdigit() and 1 <= int(cleaned) <= len(bindings):
                binding = bindings[int(cleaned) - 1]
                state["destination_connector_id"] = binding["connector_id"]
                state["destination_conversation_id"] = binding["conversation_id"]
                return self._move(active, state, "confirm")
            return ConnectionFlowResult(True, (self._prompt("destination", state),))
        if cleaned.lower() in {"confirm", "yes", "确认", "是"}:
            try:
                job = self._create(state)
            except ValueError as error:
                self._runs.update(active["id"], "schedule", state)
                return ConnectionFlowResult(
                    True,
                    (
                        _text(
                            language,
                            f"Could not save: {error}. Enter the schedule again.",
                            f"保存失败：{error}。请重新输入执行时间。",
                        ),
                    ),
                )
            self._runs.update(active["id"], None, state, status="succeeded")
            return ConnectionFlowResult(
                True,
                (
                    _text(
                        language,
                        f'Automation “{job["name"]}” saved. Next run: {job["next_run_at"]}. '
                        "It executes while `allpath-agent gateway` runs.",
                        f'自动化“{job["name"]}”已保存，下次执行：{job["next_run_at"]}。'
                        "它会在 `allpath-agent gateway` 运行期间自动执行。",
                    ),
                ),
                completed=True,
            )
        return ConnectionFlowResult(True, (self._prompt("confirm", state),))

    def _move(self, active: dict[str, Any], state: dict[str, Any], step: str) -> ConnectionFlowResult:
        self._runs.update(active["id"], step, state)
        return ConnectionFlowResult(True, (self._prompt(step, state),))

    def _create(self, state: dict[str, Any]) -> dict[str, Any]:
        kwargs = {
            "destination_connector_id": state.get("destination_connector_id"),
            "destination_conversation_id": state.get("destination_conversation_id"),
        }
        if state["schedule_kind"] == "cron":
            return self._service.create_cron(
                state["name"], state["prompt"], state["schedule_expression"], state["timezone"], **kwargs
            )
        return self._service.create_once(
            state["name"], state["prompt"], state["schedule_expression"], state["timezone"], **kwargs
        )

    def _prompt(self, step: str, state: dict[str, Any]) -> str:
        language = state.get("language", "en")
        if step == "name":
            return _text(language, 'What should this automation be called? (e.g. “Morning brief”)', '自动化名称？（例如“晨间简报”）')
        if step == "prompt":
            return _text(language, "What should Allpath do each time it runs? Describe the task in one message.", "每次执行时 Allpath 应该做什么？用一条消息描述任务。")
        if step == "schedule":
            return _text(
                language,
                'When should it run? Enter a five-field cron expression (“0 8 * * 1-5”) or a one-time ISO time (“2026-12-01T08:00”).',
                '什么时候执行？输入五段 cron 表达式（“0 8 * * 1-5”）或一次性 ISO 时间（“2026-12-01T08:00”）。',
            )
        if step == "timezone":
            return _text(
                language,
                'Which IANA timezone? Type “default” for UTC, or e.g. America/Los_Angeles.',
                '使用哪个 IANA 时区？输入“默认”使用 UTC，或例如 Asia/Shanghai。',
            )
        if step == "destination":
            bindings = self._list_bindings()
            if not bindings:
                return _text(
                    language,
                    'Where should results go? No connected conversations exist yet, so type “none” to keep results local. Message your bot once after connecting a channel to register a destination.',
                    '结果发送到哪里？当前还没有已连接的会话，输入“无”将结果保留在本地。连接消息渠道后先给机器人发一条消息即可注册投递目标。',
                )
            lines = [
                _text(
                    language,
                    'Where should results go? Type a number, or “none” to keep results local:',
                    '结果发送到哪里？输入编号，或输入“无”保留在本地：',
                )
            ]
            for index, binding in enumerate(bindings, start=1):
                lines.append(f"{index}. {binding['connector_id']} · {binding['conversation_id']}")
            return "\n".join(lines)
        summary = _text(
            language,
            "Please confirm this automation:\n"
            f"• Name: {state.get('name')}\n"
            f"• Task: {state.get('prompt')}\n"
            f"• Schedule ({state.get('schedule_kind')}): {state.get('schedule_expression')}\n"
            f"• Timezone: {state.get('timezone')}\n"
            f"• Destination: {_destination_text(state)}\n"
            'Type “confirm” to save, “back” to adjust, or “cancel”.',
            '请确认这个自动化：\n'
            f"• 名称：{state.get('name')}\n"
            f"• 任务：{state.get('prompt')}\n"
            f"• 计划（{state.get('schedule_kind')}）：{state.get('schedule_expression')}\n"
            f"• 时区：{state.get('timezone')}\n"
            f"• 投递目标：{_destination_text(state)}\n"
            '输入“确认”保存，“返回”修改，或“取消”。',
        )
        return summary


def _destination_text(state: dict[str, Any]) -> str:
    connector = state.get("destination_connector_id")
    if connector is None:
        return "local only / 仅本地"
    return f"{connector} · {state.get('destination_conversation_id')}"


def _schedule_kind(value: str) -> str | None:
    try:
        parse_cron(value, "UTC")
        return "cron"
    except ValueError:
        pass
    try:
        parse_once(value, "UTC")
        return "once"
    except ValueError:
        return None


def _text(language: str, english: str, chinese: str) -> str:
    return chinese if language == "zh" else english


def _has_chinese(value: str) -> bool:
    return any("一" <= character <= "鿿" for character in value)


def _is_trigger(message: str) -> bool:
    lowered = message.lower()
    if any(phrase in lowered for phrase in _TRIGGERS_EN):
        return True
    return any(phrase in message for phrase in _TRIGGERS_ZH)

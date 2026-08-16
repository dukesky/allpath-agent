from __future__ import annotations

from typing import TYPE_CHECKING

from allpath_agent.application import AgentApplication
from allpath_agent.hooks import HookBus
from allpath_agent.storage import ConnectorSessionRepository, SessionRepository

from .contracts import Connector, InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from allpath_agent.workflows.automation_creation import AutomationCreationWorkflow
    from allpath_agent.workflows.provider_connection import ConnectionFlowResult


_HELP_TEXT = (
    "Commands: `/automations` lists scheduled automations. `/automations add` "
    "starts a guided creation flow — results come back to this conversation. "
    "Saying “create automation” does the same thing. Model connections "
    "and channel setup are managed from the Allpath terminal."
)


class ConnectorRegistry:
    def __init__(self, connectors: tuple[Connector, ...] = ()):
        self._connectors: dict[str, Connector] = {}
        for connector in connectors:
            self.register(connector)

    def register(self, connector: Connector) -> None:
        if connector.id in self._connectors:
            raise ValueError(f"connector is already registered: {connector.id}")
        self._connectors[connector.id] = connector

    def get(self, connector_id: str) -> Connector:
        try:
            return self._connectors[connector_id]
        except KeyError as error:
            raise ValueError(f"connector is not registered: {connector_id}") from error

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._connectors))


class ConnectorRuntime:
    def __init__(
        self,
        application: AgentApplication,
        registry: ConnectorRegistry,
        sessions: SessionRepository,
        bindings: ConnectorSessionRepository,
        hooks: HookBus | None = None,
        automation_workflow: "AutomationCreationWorkflow | None" = None,
    ):
        self._application = application
        self._registry = registry
        self._sessions = sessions
        self._bindings = bindings
        self._hooks = hooks or getattr(application, "hooks", HookBus())
        self._automation_workflow = automation_workflow

    def poll_once(self, connector_id: str) -> int:
        connector = self._registry.get(connector_id)
        events = connector.poll()
        for event in events:
            self.dispatch(event)
        return len(events)

    def start_all(self) -> None:
        for connector_id in self._registry.ids():
            self._registry.get(connector_id).start()

    def stop_all(self) -> None:
        for connector_id in reversed(self._registry.ids()):
            self._registry.get(connector_id).stop()

    def dispatch(self, event: InboundMessage) -> str:
        if event.connector_id not in self._registry.ids():
            raise ValueError(f"connector is not registered: {event.connector_id}")
        self._hooks.emit(
            "connector_message_received",
            connector_id=event.connector_id,
            conversation_id=event.conversation_id,
            sender_id=event.sender_id,
            message_id=event.message_id,
        )
        session_id = self._bindings.session_for(
            event.connector_id,
            event.conversation_id,
        )
        if session_id is None:
            session = self._sessions.create(
                title=f"{event.connector_id}:{event.conversation_id}"
            )
            session_id = session.id
            self._bindings.bind(
                event.connector_id,
                event.conversation_id,
                session_id,
            )
        handled_reply, workflow_result = self._handle_channel_command(event, session_id)
        if handled_reply is not None:
            if workflow_result is not None:
                self._record_workflow_curriculum(workflow_result)
            self._registry.get(event.connector_id).send(
                OutboundMessage(
                    conversation_id=event.conversation_id,
                    text=handled_reply,
                    reply_to_message_id=event.message_id,
                    metadata=event.metadata,
                )
            )
            self._hooks.emit(
                "connector_reply_sent",
                connector_id=event.connector_id,
                conversation_id=event.conversation_id,
                source_message_id=event.message_id,
                session_id=session_id,
                task_id=None,
            )
            return session_id
        self._application.start_session(session_id)
        result = self._application.send(session_id, event.text)
        self._registry.get(event.connector_id).send(
            OutboundMessage(
                conversation_id=event.conversation_id,
                text=result.agent.content,
                reply_to_message_id=event.message_id,
                metadata=event.metadata,
            )
        )
        self._hooks.emit(
            "connector_reply_sent",
            connector_id=event.connector_id,
            conversation_id=event.conversation_id,
            source_message_id=event.message_id,
            session_id=session_id,
            task_id=result.task_id,
        )
        return session_id

    def _handle_channel_command(
        self, event: InboundMessage, session_id: str
    ) -> tuple[str | None, "ConnectionFlowResult | None"]:
        text = event.text.strip()
        lowered = _normalize_command(text.lower())
        if lowered == "/help":
            return _HELP_TEXT, None
        workflow = self._automation_workflow
        if workflow is None:
            return None, None
        if lowered == "/automations":
            return self._automation_list_text(), None
        if lowered == "/automations add":
            result = workflow.start(
                session_id,
                _language_of(text),
                None,
                default_destination=(event.connector_id, event.conversation_id),
            )
            return "\n\n".join(result.messages), result
        if workflow.active(session_id):
            result = workflow.handle(session_id, text)
            return ("\n\n".join(result.messages), result) if result.handled else (None, None)
        if workflow.is_trigger(text):
            result = workflow.start(
                session_id,
                _language_of(text),
                None,
                default_destination=(event.connector_id, event.conversation_id),
            )
            return "\n\n".join(result.messages), result
        return None, None

    def _record_workflow_curriculum(self, result: "ConnectionFlowResult") -> None:
        self._application.record_capability_tried("scheduled_automations")
        if not result.completed:
            return
        self._application.record_capability_success("scheduled_automations")
        jobs = self._automation_workflow.list_jobs()
        if jobs and _completed_daily_briefing(jobs):
            self._application.record_capability_success("daily_briefing")

    def _automation_list_text(self) -> str:
        jobs = self._automation_workflow.list_jobs()
        if not jobs:
            return "No automations yet. Send “/automations add” to create one."
        lines = ["Automations:"]
        for job in jobs:
            state = "on" if job["enabled"] else "off"
            lines.append(
                f"• {job['name']} — {job['schedule_kind']} {job['schedule_expression']} "
                f"({job['timezone']}) · {state} · next {job['next_run_at'] or '—'}"
            )
        return "\n".join(lines)


def _language_of(text: str) -> str:
    return "zh" if any("一" <= character <= "鿿" for character in text) else "en"


def _normalize_command(lowered: str) -> str:
    """Strip a Telegram group `@botname` suffix from the command token."""
    parts = lowered.split(" ", 1)
    command = parts[0]
    if "@" in command:
        command = command.split("@", 1)[0]
    return command if len(parts) == 1 else f"{command} {parts[1]}"


def _completed_daily_briefing(jobs: list[dict]) -> bool:
    newest = max(jobs, key=lambda job: job["created_at"])
    return bool(newest["schedule_kind"] == "cron" and newest["destination_connector_id"])

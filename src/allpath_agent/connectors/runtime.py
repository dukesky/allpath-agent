from __future__ import annotations

from typing import TYPE_CHECKING

from allpath_agent.application import AgentApplication
from allpath_agent.hooks import HookBus
from allpath_agent.storage import ConnectorSessionRepository, SessionRepository

from .contracts import Connector, InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from allpath_agent.workflows.automation_creation import AutomationCreationWorkflow


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
        handled_reply = self._handle_channel_command(event, session_id)
        if handled_reply is not None:
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

    def _handle_channel_command(self, event: InboundMessage, session_id: str) -> str | None:
        workflow = self._automation_workflow
        if workflow is None:
            return None
        text = event.text.strip()
        lowered = text.lower()
        if lowered == "/automations":
            return self._automation_list_text()
        if lowered == "/automations add":
            result = workflow.start(
                session_id,
                _language_of(text),
                None,
                default_destination=(event.connector_id, event.conversation_id),
            )
            return "\n\n".join(result.messages)
        if workflow.active(session_id):
            result = workflow.handle(session_id, text)
            return "\n\n".join(result.messages) if result.handled else None
        if workflow.is_trigger(text):
            result = workflow.start(
                session_id,
                _language_of(text),
                None,
                default_destination=(event.connector_id, event.conversation_id),
            )
            return "\n\n".join(result.messages)
        return None

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

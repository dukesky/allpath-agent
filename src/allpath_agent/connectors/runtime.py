from __future__ import annotations

from allpath_agent.application import AgentApplication
from allpath_agent.storage import ConnectorSessionRepository, SessionRepository

from .contracts import Connector, InboundMessage, OutboundMessage


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
    ):
        self._application = application
        self._registry = registry
        self._sessions = sessions
        self._bindings = bindings

    def poll_once(self, connector_id: str) -> int:
        connector = self._registry.get(connector_id)
        events = connector.poll()
        for event in events:
            self.dispatch(event)
        return len(events)

    def dispatch(self, event: InboundMessage) -> str:
        if event.connector_id not in self._registry.ids():
            raise ValueError(f"connector is not registered: {event.connector_id}")
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
        self._application.start_session(session_id)
        result = self._application.send(session_id, event.text)
        self._registry.get(event.connector_id).send(
            OutboundMessage(
                conversation_id=event.conversation_id,
                text=result.agent.content,
                reply_to_message_id=event.message_id,
            )
        )
        return session_id

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from allpath_agent.observability import EventLogger


@dataclass(frozen=True)
class HookEvent:
    name: str
    timestamp: str
    fields: Mapping[str, Any]


HookHandler = Callable[[HookEvent], None]


class HookBus:
    def __init__(self, loggers: tuple[EventLogger, ...] = ()):
        self._loggers = loggers
        self._handlers: dict[str, list[tuple[dict[str, Any], HookHandler]]] = defaultdict(list)
        self._lock = RLock()
        self.handler_errors: list[dict[str, str]] = []

    def subscribe(
        self,
        event_name: str,
        handler: HookHandler,
        *,
        conditions: dict[str, Any] | None = None,
    ) -> Callable[[], None]:
        entry = (dict(conditions or {}), handler)
        with self._lock:
            self._handlers[event_name].append(entry)

        def unsubscribe() -> None:
            with self._lock:
                if entry in self._handlers.get(event_name, []):
                    self._handlers[event_name].remove(entry)

        return unsubscribe

    def emit(self, event: str, **fields: Any) -> None:
        for logger in self._loggers:
            logger.emit(event, **fields)
        hook_event = HookEvent(event, datetime.now(UTC).isoformat(), dict(fields))
        with self._lock:
            handlers = tuple(self._handlers.get(event, ())) + tuple(self._handlers.get("*", ()))
        for conditions, handler in handlers:
            if any(fields.get(key) != value for key, value in conditions.items()):
                continue
            try:
                handler(hook_event)
            except Exception as error:
                self.handler_errors.append(
                    {
                        "event": event,
                        "error_type": type(error).__name__,
                        "message": str(error)[:200],
                    }
                )

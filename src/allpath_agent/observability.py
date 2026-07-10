from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol


class EventLogger(Protocol):
    def emit(self, event: str, **fields: Any) -> None: ...


class NullEventLogger:
    def emit(self, event: str, **fields: Any) -> None:
        return None


class JsonlEventLogger:
    def __init__(
        self,
        path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ):
        self.path = Path(path).expanduser()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = Lock()
        self.last_error: OSError | None = None

    def emit(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": self._clock().isoformat(),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(f"{line}\n")
        except OSError as error:
            self.last_error = error

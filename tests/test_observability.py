from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from allpath_agent.observability import JsonlEventLogger


class JsonlEventLoggerTestCase(unittest.TestCase):
    def test_writes_one_structured_record_without_unrequested_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logs" / "agent.jsonl"
            logger = JsonlEventLogger(
                path,
                clock=lambda: datetime(2026, 7, 9, tzinfo=UTC),
            )
            logger.emit("task_started", task_id="task-1", model="fast-model")
            record = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(record["event"], "task_started")
        self.assertEqual(record["task_id"], "task-1")
        self.assertNotIn("prompt", record)
        self.assertNotIn("api_key", record)

    def test_logging_failure_does_not_break_agent_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = JsonlEventLogger(Path(directory))
            logger.emit("task_started", task_id="task-1")

        self.assertIsInstance(logger.last_error, OSError)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from allpath_agent.hooks import HookBus


class RecordingLogger:
    def __init__(self):
        self.records = []

    def emit(self, event: str, **fields):
        self.records.append((event, fields))


class HookBusTestCase(unittest.TestCase):
    def test_dispatches_exact_and_wildcard_handlers(self) -> None:
        logger = RecordingLogger()
        bus = HookBus((logger,))
        received = []
        bus.subscribe("task_completed", lambda event: received.append(("exact", event)))
        bus.subscribe("*", lambda event: received.append(("wildcard", event)))

        bus.emit("task_completed", status="succeeded", task_id="task-1")

        self.assertEqual([kind for kind, _ in received], ["exact", "wildcard"])
        self.assertEqual(received[0][1].fields["task_id"], "task-1")
        self.assertEqual(logger.records[0][0], "task_completed")

    def test_conditions_filter_without_running_model_code(self) -> None:
        bus = HookBus()
        received = []
        bus.subscribe(
            "automation_run_completed",
            lambda event: received.append(event.fields["status"]),
            conditions={"status": "failed"},
        )
        bus.emit("automation_run_completed", status="succeeded")
        bus.emit("automation_run_completed", status="failed")
        self.assertEqual(received, ["failed"])

    def test_handler_failure_is_isolated(self) -> None:
        bus = HookBus()

        def broken(event):
            raise RuntimeError("hook failed")

        received = []
        bus.subscribe("event", broken)
        bus.subscribe("event", lambda event: received.append(event.name))
        bus.emit("event")

        self.assertEqual(received, ["event"])
        self.assertEqual(bus.handler_errors[0]["error_type"], "RuntimeError")

    def test_unsubscribe_removes_handler(self) -> None:
        bus = HookBus()
        received = []
        unsubscribe = bus.subscribe("event", lambda event: received.append(event.name))
        unsubscribe()
        bus.emit("event")
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()

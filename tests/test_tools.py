from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

from allpath_agent.storage import (
    Database,
    MemoryRepository,
    SessionRepository,
    ToolApprovalRepository,
)
from allpath_agent.tools import (
    ApprovalRequest,
    ToolApprovalDenied,
    ToolContext,
    ToolRuntime,
    ToolValidationError,
    WorkspaceAccessError,
    create_builtin_registry,
)


class StaticApprovalHandler:
    def __init__(self, allowed: bool):
        self.allowed = allowed
        self.requests: list[ApprovalRequest] = []

    def request(self, approval: ApprovalRequest) -> tuple[bool, str | None]:
        self.requests.append(approval)
        return self.allowed, "test decision"


class ToolRuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "state.db")
        self.database.initialize()
        self.session = SessionRepository(self.database).create(session_id="session-1")
        self.memories = MemoryRepository(self.database)
        self.approvals = ToolApprovalRepository(self.database)
        self.registry = create_builtin_registry(self.memories)
        self.context = ToolContext(self.session.id, "task-1")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_schemas_are_stable_and_sorted(self) -> None:
        names = [schema["function"]["name"] for schema in self.registry.schemas()]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names, ["calculate", "current_datetime", "memory_get", "memory_set"])

    def test_invalid_arguments_do_not_reach_handler(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        with self.assertRaises(ToolValidationError):
            runtime.execute("calculate", {"expression": "1 + 1", "unknown": True}, self.context)

    def test_unknown_tool_is_rejected(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        with self.assertRaisesRegex(KeyError, "unknown tool"):
            runtime.execute("missing_tool", {}, self.context)

    def test_read_only_calculator_executes_without_approval(self) -> None:
        handler = StaticApprovalHandler(False)
        runtime = ToolRuntime(self.registry, self.approvals, handler)
        result = runtime.execute("calculate", {"expression": "2 * (3 + 4)"}, self.context)

        self.assertEqual(result, {"result": 14})
        self.assertEqual(handler.requests, [])
        self.assertEqual(self.approvals.list_for_task(self.session.id, "task-1"), [])

    def test_current_datetime_uses_requested_timezone(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        result = runtime.execute("current_datetime", {"timezone": "UTC"}, self.context)
        self.assertEqual(result["timezone"], "UTC")
        self.assertIn("+00:00", result["iso"])

    def test_calculator_rejects_code_execution(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        with self.assertRaises(ValueError):
            runtime.execute(
                "calculate",
                {"expression": "__import__('os').system('echo unsafe')"},
                self.context,
            )

    def test_side_effect_is_denied_and_persisted_by_default(self) -> None:
        runtime = ToolRuntime(self.registry, self.approvals)
        with self.assertRaises(ToolApprovalDenied):
            runtime.execute(
                "memory_set",
                {"key": "style", "content": "concise"},
                self.context,
            )

        self.assertIsNone(self.memories.get("style"))
        decisions = self.approvals.list_for_task(self.session.id, "task-1")
        self.assertEqual(decisions[0]["decision"], "denied")

    def test_approved_side_effect_writes_memory(self) -> None:
        handler = StaticApprovalHandler(True)
        runtime = ToolRuntime(self.registry, self.approvals, handler)
        result = runtime.execute(
            "memory_set",
            {"key": "style", "content": "concise"},
            self.context,
        )

        self.assertEqual(result["content"], "concise")
        self.assertEqual(self.memories.get("style").content, "concise")
        decisions = self.approvals.list_for_task(self.session.id, "task-1")
        self.assertEqual(decisions[0]["decision"], "allowed")


class WorkspaceToolTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "workspace"
        self.root.mkdir()
        (self.root / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        source = self.root / "src"
        source.mkdir()
        (source / "app.py").write_text("def hello():\n    return 'beta'\n", encoding="utf-8")
        database = Database(Path(self.temporary_directory.name) / "state.db")
        database.initialize()
        SessionRepository(database).create(session_id="session-1")
        self.approvals = ToolApprovalRepository(database)
        self.registry = create_builtin_registry(
            MemoryRepository(database),
            (self.root,),
        )
        self.runtime = ToolRuntime(self.registry, self.approvals)
        self.context = ToolContext("session-1", "task-1")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_workspace_tools_are_registered_when_root_is_explicit(self) -> None:
        names = [schema["function"]["name"] for schema in self.registry.schemas()]
        self.assertIn("read_file", names)
        self.assertIn("search_files", names)

    def test_read_file_returns_bounded_line_range(self) -> None:
        result = self.runtime.execute(
            "read_file",
            {"path": "notes.txt", "start_line": 2, "max_lines": 1},
            self.context,
        )
        self.assertEqual(result["content"], "beta")
        self.assertEqual(result["start_line"], 2)
        self.assertEqual(result["end_line"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_search_files_returns_relative_path_and_line(self) -> None:
        result = self.runtime.execute(
            "search_files",
            {"query": "beta"},
            self.context,
        )
        matches = {(match["path"], match["line"]) for match in result["matches"]}
        self.assertEqual(matches, {("notes.txt", 2), ("src/app.py", 2)})
        self.assertFalse(result["truncated"])

    def test_search_files_respects_glob(self) -> None:
        result = self.runtime.execute(
            "search_files",
            {"query": "beta", "glob": "*.txt"},
            self.context,
        )
        self.assertEqual([match["path"] for match in result["matches"]], ["notes.txt"])

    def test_absolute_and_traversal_paths_are_rejected(self) -> None:
        for path in (str(self.root / "notes.txt"), "../notes.txt"):
            with self.subTest(path=path), self.assertRaises(WorkspaceAccessError):
                self.runtime.execute("read_file", {"path": path}, self.context)

    def test_symlink_is_rejected_even_when_target_is_inside_workspace(self) -> None:
        (self.root / "linked.txt").symlink_to(self.root / "notes.txt")
        with self.assertRaises(WorkspaceAccessError):
            self.runtime.execute("read_file", {"path": "linked.txt"}, self.context)

    def test_binary_and_oversized_files_are_rejected(self) -> None:
        (self.root / "binary.dat").write_bytes(b"abc\x00def")
        (self.root / "large.txt").write_text("x" * 100_001, encoding="utf-8")
        for path in ("binary.dat", "large.txt"):
            with self.subTest(path=path), self.assertRaises(WorkspaceAccessError):
                self.runtime.execute("read_file", {"path": path}, self.context)

    def test_sensitive_credentials_are_not_read_or_searched(self) -> None:
        (self.root / ".env").write_text("API_KEY=secret", encoding="utf-8")
        with self.assertRaises(WorkspaceAccessError):
            self.runtime.execute("read_file", {"path": ".env"}, self.context)

        result = self.runtime.execute(
            "search_files",
            {"query": "secret"},
            self.context,
        )
        self.assertEqual(result["matches"], [])
        self.assertGreaterEqual(result["skipped_files"], 1)

    def test_write_file_requires_approval(self) -> None:
        runtime = ToolRuntime(
            self.registry,
            self.approvals,
            StaticApprovalHandler(False),
        )
        with self.assertRaises(ToolApprovalDenied):
            runtime.execute(
                "write_file",
                {"path": "created.txt", "content": "new content"},
                self.context,
            )
        self.assertFalse((self.root / "created.txt").exists())

    def test_approved_write_creates_file_atomically(self) -> None:
        runtime = ToolRuntime(
            self.registry,
            self.approvals,
            StaticApprovalHandler(True),
        )
        result = runtime.execute(
            "write_file",
            {"path": "created.txt", "content": "new content"},
            self.context,
        )
        self.assertTrue(result["created"])
        self.assertEqual((self.root / "created.txt").read_text(encoding="utf-8"), "new content")
        self.assertEqual(list(self.root.glob(".*.allpath-tmp")), [])

    def test_overwrite_requires_matching_read_hash(self) -> None:
        runtime = ToolRuntime(
            self.registry,
            self.approvals,
            StaticApprovalHandler(True),
        )
        with self.assertRaises(WorkspaceAccessError):
            runtime.execute(
                "write_file",
                {"path": "notes.txt", "content": "replacement"},
                self.context,
            )
        read_result = runtime.execute("read_file", {"path": "notes.txt"}, self.context)
        (self.root / "notes.txt").write_text("changed elsewhere", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceAccessError, "changed since it was read"):
            runtime.execute(
                "write_file",
                {
                    "path": "notes.txt",
                    "content": "replacement",
                    "expected_sha256": read_result["sha256"],
                },
                self.context,
            )
        self.assertEqual(
            (self.root / "notes.txt").read_text(encoding="utf-8"),
            "changed elsewhere",
        )

    def test_patch_replaces_exact_expected_occurrence(self) -> None:
        runtime = ToolRuntime(
            self.registry,
            self.approvals,
            StaticApprovalHandler(True),
        )
        read_result = runtime.execute("read_file", {"path": "notes.txt"}, self.context)
        result = runtime.execute(
            "patch",
            {
                "path": "notes.txt",
                "old_text": "beta",
                "new_text": "delta",
                "expected_sha256": read_result["sha256"],
            },
            self.context,
        )
        self.assertEqual(result["replacements"], 1)
        self.assertEqual(
            (self.root / "notes.txt").read_text(encoding="utf-8"),
            "alpha\ndelta\ngamma\n",
        )

    def test_patch_rejects_ambiguous_occurrence_count(self) -> None:
        (self.root / "notes.txt").write_text("same\nsame\n", encoding="utf-8")
        runtime = ToolRuntime(
            self.registry,
            self.approvals,
            StaticApprovalHandler(True),
        )
        read_result = runtime.execute("read_file", {"path": "notes.txt"}, self.context)
        with self.assertRaisesRegex(WorkspaceAccessError, "occurrence mismatch"):
            runtime.execute(
                "patch",
                {
                    "path": "notes.txt",
                    "old_text": "same",
                    "new_text": "different",
                    "expected_sha256": read_result["sha256"],
                },
                self.context,
            )

    def test_terminal_requires_approval_and_runs_in_workspace(self) -> None:
        denied = ToolRuntime(self.registry, self.approvals, StaticApprovalHandler(False))
        with self.assertRaises(ToolApprovalDenied):
            denied.execute("terminal", {"command": ["pwd"]}, self.context)

        allowed = ToolRuntime(self.registry, self.approvals, StaticApprovalHandler(True))
        result = allowed.execute("terminal", {"command": ["pwd"]}, self.context)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(Path(result["stdout"].strip()).resolve(), self.root.resolve())
        self.assertFalse(result["timed_out"])

    def test_terminal_rejects_shell_and_destructive_git_actions(self) -> None:
        allowed = ToolRuntime(self.registry, self.approvals, StaticApprovalHandler(True))
        for command in (["bash", "-lc", "echo unsafe"], ["git", "reset", "--hard"]):
            with self.subTest(command=command), self.assertRaises(WorkspaceAccessError):
                allowed.execute("terminal", {"command": command}, self.context)

    def test_terminal_cwd_cannot_escape_or_use_symlink(self) -> None:
        (self.root / "linked-dir").symlink_to(self.root / "src", target_is_directory=True)
        allowed = ToolRuntime(self.registry, self.approvals, StaticApprovalHandler(True))
        for cwd in ("..", "linked-dir"):
            with self.subTest(cwd=cwd), self.assertRaises(WorkspaceAccessError):
                allowed.execute("terminal", {"command": ["pwd"], "cwd": cwd}, self.context)

    def test_terminal_strips_secret_environment_and_bounds_output(self) -> None:
        previous = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "must-not-leak"
        try:
            allowed = ToolRuntime(self.registry, self.approvals, StaticApprovalHandler(True))
            environment_result = allowed.execute(
                "terminal",
                {"command": ["python3", "-c", "import os; print(os.getenv('OPENAI_API_KEY'))"]},
                self.context,
            )
            output_result = allowed.execute(
                "terminal",
                {"command": ["python3", "-c", "print('x' * 21000)"]},
                self.context,
            )
        finally:
            if previous is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = previous
        self.assertEqual(environment_result["stdout"].strip(), "None")
        self.assertTrue(output_result["stdout_truncated"])
        self.assertLessEqual(len(output_result["stdout"]), 20_100)

    def test_terminal_timeout_terminates_process_group(self) -> None:
        allowed = ToolRuntime(self.registry, self.approvals, StaticApprovalHandler(True))
        result = allowed.execute(
            "terminal",
            {
                "command": ["python3", "-c", "import time; time.sleep(10)"],
                "timeout_seconds": 1,
            },
            self.context,
        )
        self.assertTrue(result["timed_out"])


if __name__ == "__main__":
    unittest.main()

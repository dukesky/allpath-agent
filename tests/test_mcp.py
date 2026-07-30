from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from allpath_agent.tools import MCPToolDescriptor, ToolRegistry, ToolRisk
from allpath_agent.tools.mcp_client import (
    load_mcp_config,
    mcp_tool_name,
    register_mcp_descriptors,
)


class MCPIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_loads_bounded_stdio_configuration(self) -> None:
        path = self.root / "mcp.json"
        path.write_text(
            json.dumps(
                {
                    "servers": {
                        "local": {
                            "command": "python3",
                            "args": ["server.py"],
                            "cwd": ".",
                            "env_vars": ["TOKEN"],
                            "timeout_seconds": 15,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        server = load_mcp_config(path, self.workspace)[0]
        self.assertEqual(server.name, "local")
        self.assertEqual(server.args, ("server.py",))
        self.assertEqual(server.env_vars, ("TOKEN",))
        self.assertEqual(server.cwd, self.workspace.resolve())

    def test_config_rejects_cwd_outside_workspace(self) -> None:
        path = self.root / "mcp.json"
        path.write_text(
            json.dumps({"servers": {"bad": {"command": "x", "cwd": ".."}}}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "cwd must stay inside"):
            load_mcp_config(path, self.workspace)

    def test_descriptor_registers_namespaced_approved_tool(self) -> None:
        registry = ToolRegistry()
        calls = []
        register_mcp_descriptors(
            registry,
            "Demo Server",
            [
                MCPToolDescriptor(
                    "create-item",
                    "Create an item",
                    {
                        "properties": {"title": {"type": "string"}},
                        "required": ["title", "missing"],
                    },
                )
            ],
            lambda name, arguments: calls.append((name, arguments)) or {"created": True},
        )
        name = "mcp__demo_server__create_item"
        definition = registry.get(name)
        result = definition.handler({"title": "Example"})
        self.assertEqual(definition.risk, ToolRisk.SIDE_EFFECT)
        self.assertEqual(definition.parameters["type"], "object")
        self.assertEqual(definition.parameters["required"], ["title"])
        self.assertEqual(result, {"created": True})
        self.assertEqual(calls, [("create-item", {"title": "Example"})])

    def test_long_tool_names_are_stable_and_registry_safe(self) -> None:
        first = mcp_tool_name("server", "very-long-name-" * 10)
        second = mcp_tool_name("server", "very-long-name-" * 10)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 64)
        self.assertRegex(first, r"^[a-z][a-z0-9_]+$")


if __name__ == "__main__":
    unittest.main()

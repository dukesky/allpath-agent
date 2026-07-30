from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .registry import ToolDefinition, ToolRegistry, ToolRisk


try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ImportError:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    MCP_AVAILABLE = False


MCP_NAME_COMPONENT = re.compile(r"[^a-zA-Z0-9_]+")
MAX_MCP_SERVERS = 20
MAX_MCP_TOOLS = 200


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: tuple[str, ...]
    cwd: Path
    env_vars: tuple[str, ...] = ()
    timeout_seconds: int = 30
    enabled: bool = True


@dataclass(frozen=True)
class MCPToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]


def load_mcp_config(path: Path, workspace: Path) -> tuple[MCPServerConfig, ...]:
    if not path.is_file():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read MCP configuration: {error}") from error
    servers_raw = raw.get("servers", {})
    if not isinstance(servers_raw, dict) or len(servers_raw) > MAX_MCP_SERVERS:
        raise ValueError("MCP configuration has an invalid servers object")
    servers: list[MCPServerConfig] = []
    for name, value in sorted(servers_raw.items()):
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ValueError("MCP server entries must be named objects")
        command = value.get("command")
        args = value.get("args", [])
        env_vars = value.get("env_vars", [])
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"MCP server {name} requires command")
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError(f"MCP server {name} args must be strings")
        if not isinstance(env_vars, list) or not all(isinstance(item, str) for item in env_vars):
            raise ValueError(f"MCP server {name} env_vars must be strings")
        raw_cwd = value.get("cwd", ".")
        if not isinstance(raw_cwd, str):
            raise ValueError(f"MCP server {name} cwd must be a string")
        cwd = (workspace / raw_cwd).resolve(strict=True)
        resolved_workspace = workspace.resolve(strict=True)
        if not cwd.is_relative_to(resolved_workspace) or not cwd.is_dir():
            raise ValueError(f"MCP server {name} cwd must stay inside the workspace")
        timeout = value.get("timeout_seconds", 30)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
            raise ValueError(f"MCP server {name} timeout_seconds must be between 1 and 120")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"MCP server {name} enabled must be boolean")
        servers.append(
            MCPServerConfig(
                name=name,
                command=command.strip(),
                args=tuple(args),
                cwd=cwd,
                env_vars=tuple(env_vars),
                timeout_seconds=timeout,
                enabled=enabled,
            )
        )
    return tuple(servers)


def discover_and_register_mcp_tools(
    registry: ToolRegistry,
    config_path: Path,
    workspace: Path,
    environment: dict[str, str],
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for server in load_mcp_config(config_path, workspace):
        if not server.enabled:
            statuses.append({"server": server.name, "status": "disabled", "tools": 0})
            continue
        if not MCP_AVAILABLE:
            statuses.append({"server": server.name, "status": "sdk_missing", "tools": 0})
            continue
        try:
            descriptors = _run_with_timeout(
                _list_tools(server, environment),
                server.timeout_seconds,
            )
            register_mcp_descriptors(
                registry,
                server.name,
                descriptors[:MAX_MCP_TOOLS],
                lambda tool_name, arguments, selected=server: _run_with_timeout(
                    _call_tool(selected, tool_name, arguments, environment),
                    selected.timeout_seconds,
                ),
            )
            statuses.append(
                {"server": server.name, "status": "connected", "tools": len(descriptors)}
            )
        except Exception as error:
            statuses.append(
                {
                    "server": server.name,
                    "status": "error",
                    "tools": 0,
                    "detail": f"{type(error).__name__}: {str(error)[:200]}",
                }
            )
    return statuses


def register_mcp_descriptors(
    registry: ToolRegistry,
    server_name: str,
    descriptors: list[MCPToolDescriptor],
    caller: Callable[[str, dict[str, Any]], Any],
) -> None:
    for descriptor in descriptors:
        registered_name = mcp_tool_name(server_name, descriptor.name)
        schema = _normalize_schema(descriptor.input_schema)
        registry.register(
            ToolDefinition(
                name=registered_name,
                description=descriptor.description or f"MCP tool {descriptor.name}",
                parameters=schema,
                handler=lambda arguments, tool_name=descriptor.name: caller(tool_name, arguments),
                risk=ToolRisk.SIDE_EFFECT,
            )
        )


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    server = _safe_component(server_name)
    tool = _safe_component(tool_name)
    candidate = f"mcp__{server}__{tool}".lower()
    if len(candidate) <= 64:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:10]
    return f"{candidate[:53]}_{digest}"


async def _list_tools(
    server: MCPServerConfig,
    environment: dict[str, str],
) -> list[MCPToolDescriptor]:
    parameters = _stdio_parameters(server, environment)
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.list_tools()
            return [
                MCPToolDescriptor(
                    tool.name,
                    tool.description or "",
                    dict(tool.inputSchema or {"type": "object", "properties": {}}),
                )
                for tool in response.tools
            ]


async def _call_tool(
    server: MCPServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
    environment: dict[str, str],
) -> dict[str, Any]:
    parameters = _stdio_parameters(server, environment)
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            structured = getattr(result, "structuredContent", None)
            if structured is None:
                structured = getattr(result, "structured_content", None)
            content = []
            for block in getattr(result, "content", ()):
                if hasattr(block, "model_dump"):
                    content.append(block.model_dump(mode="json"))
                elif hasattr(block, "text"):
                    content.append({"type": "text", "text": block.text})
                else:
                    content.append({"type": "unknown", "value": str(block)})
            return {
                "is_error": bool(getattr(result, "isError", False)),
                "structured_content": structured,
                "content": content,
            }


def _stdio_parameters(server: MCPServerConfig, environment: dict[str, str]):
    safe_environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "LANG", "PATH", "SHELL", "TERM", "TMPDIR"} or key.startswith("LC_")
    }
    for name in server.env_vars:
        if name not in environment:
            raise ValueError(f"MCP server {server.name} requires missing secret: {name}")
        safe_environment[name] = environment[name]
    return StdioServerParameters(
        command=server.command,
        args=list(server.args),
        cwd=str(server.cwd),
        env=safe_environment,
    )


def _run_with_timeout(coroutine, timeout_seconds: int):
    async def runner():
        return await asyncio.wait_for(coroutine, timeout=timeout_seconds)

    return asyncio.run(runner())


def _safe_component(value: str) -> str:
    cleaned = MCP_NAME_COMPONENT.sub("_", value).strip("_")
    return cleaned or "unnamed"


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(schema)
    normalized["type"] = "object"
    properties = normalized.get("properties")
    normalized["properties"] = properties if isinstance(properties, dict) else {}
    required = normalized.get("required")
    if isinstance(required, list):
        normalized["required"] = [
            name for name in required if isinstance(name, str) and name in normalized["properties"]
        ]
    normalized.setdefault("additionalProperties", True)
    return normalized

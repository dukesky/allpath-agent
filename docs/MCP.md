# MCP Integration

Allpath supports MCP stdio servers through the official Python SDK. MCP tools are converted into normal Allpath tools, namespaced as `mcp__server__tool`, validated by the same JSON-schema layer, and treated as side-effecting until a future permission model can prove otherwise.

## Configuration

Create `~/.allpath-agent/mcp.json`:

```json
{
  "servers": {
    "example": {
      "command": "python3",
      "args": ["tools/example_server.py"],
      "cwd": ".",
      "env_vars": ["EXAMPLE_TOKEN"],
      "timeout_seconds": 30,
      "enabled": true
    }
  }
}
```

`cwd` is relative to the workspace and cannot escape it. Only explicitly named `env_vars` are copied from Allpath's merged secret environment; normal provider and Connector credentials are not inherited automatically.

Use `/mcp` to inspect configured servers and SDK availability.

## Lifecycle

The MVP starts a short-lived stdio session for discovery and a new short-lived session for each call. This is simpler and failure-isolated, but slower than Hermes's long-lived background event loop.

The next MCP hardening step is persistent connections, health-gated schemas, reconnect backoff, `tools/list_changed`, HTTP transport, OAuth, resources, and prompts.

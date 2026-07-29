"""Shared MCP server instance.

All tool modules import `mcp` from here so they register with the same
server. Mirrors the proxmox-mcp pattern: one singleton, decorator-based
tool registration. This is the only module that touches the SDK's server
class, so it is also the single place that knows which SDK major is installed.
"""
from __future__ import annotations

try:  # mcp >= 2.0: FastMCP renamed to MCPServer (spec revision 2026-07-28)
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x maintenance line -- old name, same decorator API
    from mcp.server.fastmcp import FastMCP as _Server

mcp = _Server("pbs-mcp")

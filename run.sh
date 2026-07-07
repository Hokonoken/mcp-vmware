#!/usr/bin/env bash
# MCP server launcher on the jump host (invoked by Claude Code via ssh).
# stdio = MCP protocol; logs go to stderr.
exec "$HOME/VMware/venv/bin/python" -m mcp_vmware

#!/usr/bin/env bash
# Lanceur du serveur MCP sur la machine rebond (invoque par Claude Code via ssh).
# stdio = protocole MCP ; les logs partent sur stderr.
exec "$HOME/VMware/venv/bin/python" -m mcp_vmware

# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Entry point of the VMware MCP server (stdio transport).

Runs on the jumphost; Claude Code connects to it via `ssh jumphost ...`.
Never write to stdout outside the MCP protocol (logs go to stderr).
"""

import sys

# Importing registers the tools (filtered by role) on the shared FastMCP instance.
from . import (
    tools_cluster,  # noqa: F401
    tools_host,  # noqa: F401
    tools_host_config,  # noqa: F401
    tools_read,  # noqa: F401
    tools_write,  # noqa: F401
)
from .app import mcp
from .roles import allowed_groups, current_role


def main() -> None:
    role = current_role()
    groups = ", ".join(sorted(allowed_groups()))
    print(f"mcp-vmware started, role={role} groups=[{groups}]", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()

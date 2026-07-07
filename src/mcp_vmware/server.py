# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Point d'entree du serveur MCP VMware (transport stdio).

Lance sur la machine rebond ; Claude Code s'y connecte via `ssh jumphost ...`.
Ne jamais ecrire sur stdout en dehors du protocole MCP (les logs vont sur stderr).
"""

import sys

# L'import enregistre les outils (filtres par role) sur l'instance FastMCP partagee.
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
    print(f"mcp-vmware demarre, role={role} groupes=[{groups}]", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()

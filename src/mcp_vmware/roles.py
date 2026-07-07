# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Permission groups and access roles of the MCP server.

The current role is set by MCP_VMWARE_ROLE in the env file (default: viewer).
A tool whose group is not covered by the role is not registered at all
(invisible in tools/list); a check at call time doubles the protection.

The matching vSphere privilege templates (to create aligned vCenter service
accounts) are in docs/roles.md.
"""

import os

from .connection import load_env

GROUPS: dict[str, str] = {
    "read": "read-only access to the whole inventory (VMs, hosts, clusters, storage, network)",
    "vm.power": "VM power operations (on/off/reset/suspend/shutdown)",
    "vm.snapshot": "VM snapshots (create/revert/delete)",
    "vm.config": "VM CPU/RAM reconfiguration",
    "vm.lifecycle": "VM lifecycle (clone, deletion, migration)",
    "cluster.ops": "cluster configuration (HA, DRS, affinity rules)",
    "host.ops": "ESXi host operations (maintenance, reboot, reconnect)",
    "host.config": "fine-grained ESXi host configuration (services, firewall, "
    "advanced settings, storage rescan — esxcli equivalent)",
}

ROLES: dict[str, frozenset[str]] = {
    "viewer": frozenset({"read"}),
    "operator": frozenset({"read", "vm.power", "vm.snapshot"}),
    "vm_admin": frozenset({"read", "vm.power", "vm.snapshot", "vm.config", "vm.lifecycle"}),
    "infra_admin": frozenset(GROUPS),
}


def current_role() -> str:
    load_env()
    role = os.environ.get("MCP_VMWARE_ROLE", "").strip().lower()
    if role in ROLES:
        return role
    # Compat with the old binary safety switch.
    if os.environ.get("MCP_VMWARE_ALLOW_WRITE", "0").lower() in ("1", "true", "yes"):
        return "vm_admin"
    return "viewer"


def allowed_groups() -> frozenset[str]:
    return ROLES[current_role()]


def group_allowed(group: str) -> bool:
    return group in allowed_groups()


def deny_message(group: str) -> str:
    roles = sorted(r for r, groups in ROLES.items() if group in groups)
    return (
        f"Error: the current role '{current_role()}' does not allow the group "
        f"'{group}' ({GROUPS.get(group, '?')}). Roles that allow it: {', '.join(roles)}. "
        "Change MCP_VMWARE_ROLE in ~/VMware/.vcenter.env on the jumphost, "
        "then restart the MCP session."
    )

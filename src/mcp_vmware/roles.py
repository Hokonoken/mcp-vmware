# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Groupes de droits et roles d'acces du serveur MCP.

Le role courant est defini par MCP_VMWARE_ROLE dans le fichier env (defaut: viewer).
Un outil dont le groupe n'est pas couvert par le role n'est pas enregistre du tout
(invisible dans tools/list) ; une verification a l'appel double la protection.

Les templates de privileges vSphere correspondants (pour creer des comptes de
service vCenter alignes) sont dans docs/roles.md.
"""

import os

from .connection import load_env

GROUPS: dict[str, str] = {
    "read": "lecture seule de tout l'inventaire (VMs, hotes, clusters, stockage, reseau)",
    "vm.power": "alimentation des VMs (on/off/reset/suspend/shutdown)",
    "vm.snapshot": "snapshots des VMs (create/revert/delete)",
    "vm.config": "reconfiguration CPU/RAM des VMs",
    "vm.lifecycle": "cycle de vie des VMs (clone, suppression, migration)",
    "cluster.ops": "configuration des clusters (HA, DRS, regles d'affinite)",
    "host.ops": "operations sur les hotes ESXi (maintenance, reboot, reconnexion)",
    "host.config": "configuration fine des hotes ESXi (services, firewall, "
    "parametres avances, rescan stockage — equivalent esxcli)",
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
    # Compat avec l'ancien garde-fou binaire.
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
        f"Erreur: le role courant '{current_role()}' n'autorise pas le groupe "
        f"'{group}' ({GROUPS.get(group, '?')}). Roles qui l'autorisent: {', '.join(roles)}. "
        "Modifier MCP_VMWARE_ROLE dans ~/VMware/.vcenter.env sur la machine rebond, "
        "puis relancer la session MCP."
    )

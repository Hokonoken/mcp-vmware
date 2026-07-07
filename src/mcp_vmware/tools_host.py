"""Outils hotes ESXi : detail (groupe read) et operations (groupe host.ops).

Les operations d'hote sont les plus sensibles du serveur : maintenance et
reboot/shutdown exigent confirm=true.
"""

from typing import Annotated

from pydantic import Field

from .app import tool
from .helpers import error_text, find_host, fmt_bytes, to_json, wait_for_task
from .roles import deny_message, group_allowed


def _gate(group: str) -> str | None:
    return None if group_allowed(group) else deny_message(group)


@tool("vmware_get_host", "Detail d'un hote ESXi", group="read", read=True, idempotent=True)
def vmware_get_host(
    host: Annotated[str, Field(description="Nom de l'hote (cf. vmware_list_hosts)")],
) -> str:
    """Detail d'un hote ESXi : etat, uptime, hardware, VMs hebergees, datastores montes.

    Retourne un JSON {name, moid, connection_state, power_state, in_maintenance,
    in_quarantine, boot_time, uptime_hours, version, model, cpu, memory, vms:[...],
    datastores:[...], networks:[...]}.
    """
    try:
        h = find_host(host)
        s = h.summary
        hw, rt = s.hardware, s.runtime
        uptime_h = None
        if rt.bootTime:
            from datetime import UTC, datetime

            uptime_h = round((datetime.now(UTC) - rt.bootTime).total_seconds() / 3600, 1)
        return to_json(
            {
                "name": h.name,
                "moid": h._moId,
                "connection_state": str(rt.connectionState),
                "power_state": str(rt.powerState),
                "in_maintenance": rt.inMaintenanceMode,
                "in_quarantine": getattr(rt, "inQuarantineMode", None),
                "boot_time": rt.bootTime,
                "uptime_hours": uptime_h,
                "version": s.config.product.fullName if s.config.product else None,
                "model": f"{hw.vendor} {hw.model}" if hw else None,
                "cpu": {
                    "model": hw.cpuModel if hw else None,
                    "sockets": hw.numCpuPkgs if hw else None,
                    "cores": hw.numCpuCores if hw else None,
                    "threads": hw.numCpuThreads if hw else None,
                    "mhz": hw.cpuMhz if hw else None,
                },
                "memory_total": fmt_bytes(hw.memorySize) if hw else None,
                "vms": sorted(v.name for v in h.vm),
                "datastores": sorted(d.name for d in h.datastore),
                "networks": sorted(n.name for n in h.network),
            }
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_maintenance", "Mode maintenance d'un hote", group="host.ops", destructive=True)
def vmware_host_maintenance(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    action: Annotated[str, Field(description="enter ou exit")],
    confirm: Annotated[
        bool, Field(description="Doit etre true pour enter (peut evacuer des VMs via DRS)")
    ] = False,
    timeout_s: Annotated[
        int, Field(ge=60, le=7200, description="Timeout vCenter de l'operation")
    ] = 1800,
) -> str:
    """Fait entrer ou sortir un hote ESXi du mode maintenance.

    L'entree en maintenance attend l'evacuation des VMs (DRS). Exige confirm=true pour
    enter. Retourne un JSON {action, status, host, in_maintenance}.
    """
    if msg := _gate("host.ops"):
        return msg
    if action not in ("enter", "exit"):
        return "Erreur: action invalide, choisir enter ou exit."
    try:
        h = find_host(host)
        if action == "enter":
            if not confirm:
                return (
                    f"Refus: entree en maintenance de '{h.name}' non confirmee "
                    f"({len(h.vm)} VMs presentes, evacuation DRS possible). Rappeler "
                    "avec confirm=true apres validation explicite de l'utilisateur."
                )
            if h.summary.runtime.inMaintenanceMode:
                return f"'{h.name}' est deja en maintenance."
            wait_for_task(h.EnterMaintenanceMode_Task(timeout=timeout_s), timeout_s=timeout_s)
        else:
            if not h.summary.runtime.inMaintenanceMode:
                return f"'{h.name}' n'est pas en maintenance."
            wait_for_task(h.ExitMaintenanceMode_Task(timeout=timeout_s), timeout_s=timeout_s)
        return to_json(
            {
                "action": f"maintenance_{action}",
                "status": "success",
                "host": h.name,
                "in_maintenance": h.summary.runtime.inMaintenanceMode,
            }
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_power", "Reboot/arret d'un hote", group="host.ops", destructive=True)
def vmware_host_power(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    action: Annotated[str, Field(description="reboot ou shutdown")],
    confirm: Annotated[
        bool, Field(description="Doit etre true pour executer. Sans cela l'outil refuse.")
    ] = False,
    force: Annotated[
        bool,
        Field(description="Forcer meme hors maintenance (DANGEREUX: VMs coupees brutalement)"),
    ] = False,
) -> str:
    """Redemarre ou eteint un hote ESXi. Refuse hors mode maintenance sauf force=true.

    Operation la plus sensible du serveur : exige confirm=true. Retourne un JSON
    {action, status, host}.
    """
    if msg := _gate("host.ops"):
        return msg
    if action not in ("reboot", "shutdown"):
        return "Erreur: action invalide, choisir reboot ou shutdown."
    try:
        h = find_host(host)
        if not confirm:
            return (
                f"Refus: {action} de l'hote '{h.name}' non confirme. Rappeler avec "
                "confirm=true apres validation explicite de l'utilisateur."
            )
        if not h.summary.runtime.inMaintenanceMode and not force:
            return (
                f"Erreur: '{h.name}' n'est pas en maintenance. Passer par "
                "vmware_host_maintenance d'abord, ou force=true en toute connaissance "
                "de cause."
            )
        if action == "reboot":
            wait_for_task(h.RebootHost_Task(force=force))
        else:
            wait_for_task(h.ShutdownHost_Task(force=force))
        return to_json({"action": f"host_{action}", "status": "success", "host": h.name})
    except Exception as e:
        return error_text(e)


@tool("vmware_host_connection", "Connexion d'un hote au vCenter", group="host.ops")
def vmware_host_connection(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    action: Annotated[str, Field(description="reconnect ou disconnect")],
) -> str:
    """Reconnecte ou deconnecte un hote ESXi du vCenter (gestion, pas d'impact VMs).

    Retourne un JSON {action, status, host, connection_state}.
    """
    if msg := _gate("host.ops"):
        return msg
    if action not in ("reconnect", "disconnect"):
        return "Erreur: action invalide, choisir reconnect ou disconnect."
    try:
        h = find_host(host)
        if action == "reconnect":
            wait_for_task(h.ReconnectHost_Task())
        else:
            wait_for_task(h.DisconnectHost_Task())
        return to_json(
            {
                "action": f"host_{action}",
                "status": "success",
                "host": h.name,
                "connection_state": str(h.summary.runtime.connectionState),
            }
        )
    except Exception as e:
        return error_text(e)

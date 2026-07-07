"""Utilitaires partages : resolution d'objets, vues d'inventaire, taches, serialisation."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from pyVmomi import vim

from .connection import get_si


@contextmanager
def container_view(obj_type: type) -> Iterator[list[Any]]:
    """Vue d'inventaire sur tout le vCenter pour un type de managed object."""
    si = get_si()
    view_manager = si.content.viewManager
    if view_manager is None:
        raise RuntimeError("viewManager indisponible sur ce vCenter.")
    view = view_manager.CreateContainerView(si.content.rootFolder, [obj_type], True)
    try:
        yield list(view.view)
    finally:
        view.Destroy()


def find_vm(name_or_moid: str) -> vim.VirtualMachine:
    """Resout une VM par MoID (vm-123) ou par nom exact (insensible a la casse).

    Leve ValueError avec suggestions si introuvable ou ambigu.
    """
    with container_view(vim.VirtualMachine) as vms:
        if name_or_moid.startswith("vm-"):
            for vm in vms:
                if vm._moId == name_or_moid:
                    return vm
            raise ValueError(f"Aucune VM avec le MoID '{name_or_moid}'.")
        exact = [vm for vm in vms if vm.name.lower() == name_or_moid.lower()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            moids = ", ".join(f"{vm.name} ({vm._moId})" for vm in exact)
            raise ValueError(f"Plusieurs VMs nommees '{name_or_moid}': {moids}. Utiliser le MoID.")
        partial = [vm.name for vm in vms if name_or_moid.lower() in vm.name.lower()][:10]
        hint = f" VMs proches: {', '.join(partial)}." if partial else ""
        raise ValueError(f"VM '{name_or_moid}' introuvable.{hint}")


def _find_entity(obj_type: type, kind: str, name: str) -> Any:
    """Resout un objet d'inventaire par nom exact (insensible a la casse)."""
    with container_view(obj_type) as objs:
        exact = [o for o in objs if o.name.lower() == name.lower()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            moids = ", ".join(f"{o.name} ({o._moId})" for o in exact)
            raise ValueError(f"Plusieurs {kind}s nommes '{name}': {moids}.")
        known = ", ".join(sorted(o.name for o in objs)[:15])
        raise ValueError(f"{kind} '{name}' introuvable. Disponibles: {known}")


def find_cluster(name: str) -> vim.ClusterComputeResource:
    return _find_entity(vim.ClusterComputeResource, "cluster", name)


def find_host(name: str) -> vim.HostSystem:
    return _find_entity(vim.HostSystem, "hote ESXi", name)


def wait_for_task(task: vim.Task, timeout_s: int = 600) -> Any:
    """Attend la fin d'une tache vCenter, retourne son resultat ou leve RuntimeError."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = task.info.state
        if state == vim.TaskInfo.State.success:
            return task.info.result
        if state == vim.TaskInfo.State.error:
            msg = getattr(task.info.error, "msg", None) or "erreur inconnue"
            raise RuntimeError(f"Tache vCenter en echec: {msg}")
        time.sleep(1)
    raise RuntimeError(
        f"Tache vCenter non terminee apres {timeout_s}s (elle continue cote vCenter)."
    )


def to_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=_json_default)


def _json_default(o: Any) -> str:
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


def fmt_bytes(n: int | None) -> str | None:
    if n is None:
        return None
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if value < 1024 or unit == "PiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return None


def error_text(e: Exception) -> str:
    if isinstance(e, ValueError | RuntimeError):
        return f"Erreur: {e}"
    if isinstance(e, vim.fault.NoPermission):
        return "Erreur: permission vCenter insuffisante pour cette operation."
    if isinstance(e, vim.fault.InvalidPowerState):
        return (
            "Erreur: etat d'alimentation incompatible avec cette operation "
            "(verifier avec vmware_get_vm)."
        )
    return f"Erreur inattendue ({type(e).__name__}): {e}"


# ------------------------------------------------------------------ serialisation


def vm_summary(vm: vim.VirtualMachine) -> dict[str, Any]:
    s = vm.summary
    return {
        "name": vm.name,
        "moid": vm._moId,
        "power_state": str(s.runtime.powerState),
        "guest_os": s.config.guestFullName if s.config else None,
        "ip": s.guest.ipAddress if s.guest else None,
        "hostname": s.guest.hostName if s.guest else None,
        "cpu": s.config.numCpu if s.config else None,
        "memory_mb": s.config.memorySizeMB if s.config else None,
        "host": s.runtime.host.name if s.runtime.host else None,
        "vmware_tools": str(s.guest.toolsStatus) if s.guest and s.guest.toolsStatus else None,
    }


def snapshot_tree(nodes: list[Any]) -> list[dict[str, Any]]:
    out = []
    for n in nodes or []:
        out.append(
            {
                "name": n.name,
                "description": n.description or "",
                "created": n.createTime,
                "state": str(n.state),
                "snapshot_moid": n.snapshot._moId,
                "children": snapshot_tree(n.childSnapshotList),
            }
        )
    return out


def vm_detail(vm: vim.VirtualMachine) -> dict[str, Any]:
    detail = vm_summary(vm)
    cfg = vm.config
    disks, nics = [], []
    if cfg:
        for dev in cfg.hardware.device:
            if isinstance(dev, vim.vm.device.VirtualDisk):
                backing = dev.backing
                disks.append(
                    {
                        "label": dev.deviceInfo.label if dev.deviceInfo else None,
                        "capacity": fmt_bytes(dev.capacityInBytes),
                        "datastore_file": getattr(backing, "fileName", None),
                        "thin": getattr(backing, "thinProvisioned", None),
                    }
                )
            elif isinstance(dev, vim.vm.device.VirtualEthernetCard):
                nics.append(
                    {
                        "label": dev.deviceInfo.label if dev.deviceInfo else None,
                        "mac": dev.macAddress,
                        "network": dev.deviceInfo.summary if dev.deviceInfo else None,
                        "connected": dev.connectable.connected if dev.connectable else None,
                    }
                )
    detail.update(
        {
            "uuid": cfg.uuid if cfg else None,
            "annotation": cfg.annotation if cfg else None,
            "path": cfg.files.vmPathName if cfg else None,
            "hardware_version": cfg.version if cfg else None,
            "cpu_hot_add": cfg.cpuHotAddEnabled if cfg else None,
            "memory_hot_add": cfg.memoryHotAddEnabled if cfg else None,
            "disks": disks,
            "nics": nics,
            "guest_ips": [ip for n in (vm.guest.net or []) for ip in (n.ipAddress or [])]
            if vm.guest
            else [],
            "snapshots": snapshot_tree(vm.snapshot.rootSnapshotList) if vm.snapshot else [],
            "resource_pool": vm.resourcePool.name if vm.resourcePool else None,
            "folder": vm.parent.name if vm.parent else None,
        }
    )
    return detail

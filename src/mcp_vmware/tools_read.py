"""Outils MCP en lecture seule — toujours actifs."""

from typing import Annotated, Any

from pydantic import Field
from pyVmomi import vim

from .app import tool
from .connection import get_si
from .helpers import (
    container_view,
    error_text,
    find_vm,
    fmt_bytes,
    snapshot_tree,
    to_json,
    vm_detail,
    vm_summary,
)


@tool("vmware_list_vms", "Lister les VMs", group="read", read=True, idempotent=True)
def vmware_list_vms(
    name_filter: Annotated[
        str | None, Field(description="Sous-chaine a chercher dans le nom (insensible a la casse)")
    ] = None,
    power_state: Annotated[
        str | None,
        Field(description="Filtre d'etat: poweredOn, poweredOff ou suspended"),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=500, description="Nombre max de resultats")] = 50,
    offset: Annotated[int, Field(ge=0, description="Decalage de pagination")] = 0,
) -> str:
    """Liste les VMs du vCenter avec filtres et pagination.

    Retourne un JSON {total, count, offset, has_more, next_offset, vms:[{name, moid,
    power_state, guest_os, ip, hostname, cpu, memory_mb, host, vmware_tools}]}.
    """
    try:
        with container_view(vim.VirtualMachine) as vms:
            if name_filter:
                vms = [v for v in vms if name_filter.lower() in v.name.lower()]
            if power_state:
                vms = [v for v in vms if str(v.summary.runtime.powerState) == power_state]
            vms.sort(key=lambda v: v.name.lower())
            total = len(vms)
            page = vms[offset : offset + limit]
            return to_json(
                {
                    "total": total,
                    "count": len(page),
                    "offset": offset,
                    "has_more": offset + len(page) < total,
                    "next_offset": offset + len(page) if offset + len(page) < total else None,
                    "vms": [vm_summary(v) for v in page],
                }
            )
    except Exception as e:
        return error_text(e)


@tool("vmware_get_vm", "Detail d'une VM", group="read", read=True, idempotent=True)
def vmware_get_vm(
    vm: Annotated[str, Field(description="Nom exact ou MoID (ex: vm-123) de la VM")],
) -> str:
    """Detail complet d'une VM : config, CPU/RAM, disques, NICs, IPs guest, snapshots.

    Retourne un JSON avec uuid, path, hardware_version, disks[], nics[], guest_ips[],
    snapshots[] (arbre), resource_pool, folder, en plus du resume standard.
    """
    try:
        return to_json(vm_detail(find_vm(vm)))
    except Exception as e:
        return error_text(e)


@tool("vmware_list_hosts", "Lister les hotes ESXi", group="read", read=True, idempotent=True)
def vmware_list_hosts() -> str:
    """Liste les hotes ESXi : etat, version, modele, charge CPU/RAM, nombre de VMs.

    Retourne un JSON {count, hosts:[{name, moid, connection_state, power_state, in_maintenance,
    version, model, cpu_cores, cpu_usage_mhz, cpu_total_mhz, memory_total, memory_usage, vms}]}.
    """
    try:
        with container_view(vim.HostSystem) as hosts:
            out = []
            for h in sorted(hosts, key=lambda x: x.name):
                s = h.summary
                hw, qs = s.hardware, s.quickStats
                out.append(
                    {
                        "name": h.name,
                        "moid": h._moId,
                        "connection_state": str(s.runtime.connectionState),
                        "power_state": str(s.runtime.powerState),
                        "in_maintenance": s.runtime.inMaintenanceMode,
                        "version": s.config.product.fullName if s.config.product else None,
                        "model": f"{hw.vendor} {hw.model}" if hw else None,
                        "cpu_cores": hw.numCpuCores if hw else None,
                        "cpu_usage_mhz": qs.overallCpuUsage,
                        "cpu_total_mhz": (hw.cpuMhz * hw.numCpuCores) if hw else None,
                        "memory_total": fmt_bytes(hw.memorySize) if hw else None,
                        "memory_usage": fmt_bytes(qs.overallMemoryUsage * 1024 * 1024)
                        if qs.overallMemoryUsage
                        else None,
                        "vms": len(h.vm),
                    }
                )
            return to_json({"count": len(out), "hosts": out})
    except Exception as e:
        return error_text(e)


@tool("vmware_list_clusters", "Lister les clusters", group="read", read=True, idempotent=True)
def vmware_list_clusters() -> str:
    """Liste les clusters : HA/DRS, hotes, capacite CPU/RAM agregee.

    Retourne un JSON {count, clusters:[{name, moid, hosts, ha_enabled, drs_enabled,
    drs_behavior, total_cpu_mhz, total_memory, num_vms}]}.
    """
    try:
        with container_view(vim.ClusterComputeResource) as clusters:
            out = []
            for c in sorted(clusters, key=lambda x: x.name):
                cfg = c.configurationEx
                out.append(
                    {
                        "name": c.name,
                        "moid": c._moId,
                        "hosts": len(c.host),
                        "ha_enabled": cfg.dasConfig.enabled if cfg.dasConfig else None,
                        "drs_enabled": cfg.drsConfig.enabled if cfg.drsConfig else None,
                        "drs_behavior": str(cfg.drsConfig.defaultVmBehavior)
                        if cfg.drsConfig
                        else None,
                        "total_cpu_mhz": c.summary.totalCpu,
                        "total_memory": fmt_bytes(c.summary.totalMemory),
                        "effective_hosts": c.summary.numEffectiveHosts,
                    }
                )
            return to_json({"count": len(out), "clusters": out})
    except Exception as e:
        return error_text(e)


@tool("vmware_list_datastores", "Lister les datastores", group="read", read=True, idempotent=True)
def vmware_list_datastores() -> str:
    """Liste les datastores : type, capacite, espace libre, accessibilite.

    Retourne un JSON {count, datastores:[{name, moid, type, capacity, free, free_pct,
    accessible, hosts, vms}]}.
    """
    try:
        with container_view(vim.Datastore) as stores:
            out = []
            for d in sorted(stores, key=lambda x: x.name):
                s = d.summary
                free_pct = round(100 * s.freeSpace / s.capacity, 1) if s.capacity else None
                out.append(
                    {
                        "name": d.name,
                        "moid": d._moId,
                        "type": s.type,
                        "capacity": fmt_bytes(s.capacity),
                        "free": fmt_bytes(s.freeSpace),
                        "free_pct": free_pct,
                        "accessible": s.accessible,
                        "hosts": len(d.host),
                        "vms": len(d.vm),
                    }
                )
            return to_json({"count": len(out), "datastores": out})
    except Exception as e:
        return error_text(e)


@tool("vmware_list_networks", "Lister les reseaux", group="read", read=True, idempotent=True)
def vmware_list_networks() -> str:
    """Liste les reseaux (portgroups standards et distribues).

    Retourne un JSON {count, networks:[{name, moid, type, accessible, vms, vlan}]}.
    vlan n'est renseigne que pour les portgroups distribues.
    """
    try:
        with container_view(vim.Network) as nets:
            out = []
            for n in sorted(nets, key=lambda x: x.name):
                vlan: int | str | None = None
                if isinstance(n, vim.dvs.DistributedVirtualPortgroup):
                    port_config = n.config.defaultPortConfig
                    vlan_cfg = port_config.vlan if port_config else None
                    vlan_id = getattr(vlan_cfg, "vlanId", None)
                    if isinstance(vlan_id, int):
                        vlan = vlan_id
                    elif isinstance(vlan_id, list):
                        vlan = ", ".join(f"{r.start}-{r.end}" for r in vlan_id)
                out.append(
                    {
                        "name": n.name,
                        "moid": n._moId,
                        "type": type(n).__name__.rsplit(".", 1)[-1],
                        "accessible": n.summary.accessible,
                        "vms": len(n.vm),
                        "vlan": vlan,
                    }
                )
            return to_json({"count": len(out), "networks": out})
    except Exception as e:
        return error_text(e)


@tool("vmware_list_snapshots", "Snapshots d'une VM", group="read", read=True, idempotent=True)
def vmware_list_snapshots(
    vm: Annotated[str, Field(description="Nom exact ou MoID de la VM")],
) -> str:
    """Arbre des snapshots d'une VM (nom, description, date, enfants).

    Retourne un JSON {vm, count, current_snapshot, snapshots:[...arbre...]} ou un message
    si la VM n'a aucun snapshot.
    """
    try:
        obj = find_vm(vm)
        if not obj.snapshot:
            return to_json({"vm": obj.name, "count": 0, "snapshots": []})
        tree = snapshot_tree(obj.snapshot.rootSnapshotList)

        def count(nodes: list[dict[str, Any]]) -> int:
            return sum(1 + count(n["children"]) for n in nodes)

        current = obj.snapshot.currentSnapshot._moId if obj.snapshot.currentSnapshot else None
        return to_json(
            {
                "vm": obj.name,
                "count": count(tree),
                "current_snapshot_moid": current,
                "snapshots": tree,
            }
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_recent_tasks", "Taches recentes", group="read", read=True, idempotent=True)
def vmware_recent_tasks(
    limit: Annotated[int, Field(ge=1, le=200, description="Nombre max de taches")] = 30,
) -> str:
    """Dernieres taches vCenter (operations en cours ou recentes) avec etat et cible.

    Retourne un JSON {count, tasks:[{key, description, target, state, progress_pct, user,
    queued, started, completed, error}]}.
    """
    try:
        si = get_si()
        task_manager = si.content.taskManager
        if task_manager is None:
            return "Erreur: taskManager indisponible sur ce vCenter."
        tasks = list(task_manager.recentTask)[-limit:]
        out = []
        for t in reversed(tasks):
            i = t.info
            out.append(
                {
                    "key": i.key,
                    "description": i.descriptionId,
                    "target": i.entityName,
                    "state": str(i.state),
                    "progress_pct": i.progress,
                    "user": getattr(i.reason, "userName", None),
                    "queued": i.queueTime,
                    "started": i.startTime,
                    "completed": i.completeTime,
                    "error": getattr(i.error, "msg", None) if i.error else None,
                }
            )
        return to_json({"count": len(out), "tasks": out})
    except Exception as e:
        return error_text(e)


@tool("vmware_list_events", "Evenements recents", group="read", read=True, idempotent=True)
def vmware_list_events(
    vm: Annotated[
        str | None, Field(description="Limiter aux evenements de cette VM (nom ou MoID)")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="Nombre max d'evenements")] = 30,
) -> str:
    """Evenements vCenter recents, globaux ou filtres sur une VM.

    Retourne un JSON {count, events:[{time, type, user, target, message}]}, du plus recent
    au plus ancien.
    """
    try:
        si = get_si()
        spec = vim.event.EventFilterSpec()
        if vm:
            obj = find_vm(vm)
            spec.entity = vim.event.EventFilterSpec.ByEntity(
                entity=obj, recursion=vim.event.EventFilterSpec.RecursionOption.self
            )
        event_manager = si.content.eventManager
        if event_manager is None:
            return "Erreur: eventManager indisponible sur ce vCenter."
        collector = event_manager.CreateCollectorForEvents(spec)
        try:
            events = collector.latestPage[:limit]
        finally:
            collector.DestroyCollector()
        out = [
            {
                "time": e.createdTime,
                "type": type(e).__name__.rsplit(".", 1)[-1],
                "user": e.userName or None,
                "target": e.vm.name if getattr(e, "vm", None) else None,
                "message": (e.fullFormattedMessage or "").strip(),
            }
            for e in events
        ]
        return to_json({"count": len(out), "events": out})
    except Exception as e:
        return error_text(e)

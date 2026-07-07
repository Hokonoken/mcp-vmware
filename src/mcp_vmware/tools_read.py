# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Read-only MCP tools — always active.

Listings accept response_format (markdown by default, json for the full
structure) and are paginated. Detail tools return a structured object.
"""

from typing import Annotated, Any

from pydantic import Field
from pyVmomi import vim

from .app import tool
from .connection import get_si
from .helpers import (
    ResponseFormat,
    container_view,
    error_text,
    find_vm,
    fmt_bytes,
    paginate,
    render_listing,
    snapshot_tree,
    vm_detail,
    vm_summary,
)

FORMAT_FIELD = Field(description="markdown (default, compact table) or json (full structure)")


@tool("vmware_list_vms", "List VMs", group="read", read=True, idempotent=True)
def vmware_list_vms(
    name_filter: Annotated[
        str | None, Field(description="Substring to search for in the name (case-insensitive)")
    ] = None,
    power_state: Annotated[
        str | None,
        Field(description="State filter: poweredOn, poweredOff or suspended"),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum number of results")] = 50,
    offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Lists the vCenter VMs with filters and pagination.

    In json: {total, count, offset, has_more, next_offset, vms:[{name, moid, power_state,
    guest_os, ip, hostname, cpu, memory_mb, host, vmware_tools}]}. In markdown: table.
    """
    try:
        with container_view(vim.VirtualMachine) as vms:
            if name_filter:
                vms = [v for v in vms if name_filter.lower() in v.name.lower()]
            if power_state:
                vms = [v for v in vms if str(v.summary.runtime.powerState) == power_state]
            vms.sort(key=lambda v: v.name.lower())
            page, meta = paginate(vms, limit, offset)
            rows = [vm_summary(v) for v in page]
        return render_listing("VMs", "vms", rows, response_format, meta)
    except Exception as e:
        return error_text(e)


@tool("vmware_get_vm", "Details of a VM", group="read", read=True, idempotent=True)
def vmware_get_vm(
    vm: Annotated[str, Field(description="Exact name or MoID (e.g. vm-123) of the VM")],
) -> dict[str, Any] | str:
    """Full details of a VM: config, CPU/RAM, disks, NICs, guest IPs, snapshots.

    Returns a structured object with uuid, path, hardware_version, disks[], nics[],
    guest_ips[], snapshots[] (tree), resource_pool, folder, on top of the standard summary.
    """
    try:
        return vm_detail(find_vm(vm))
    except Exception as e:
        return error_text(e)


@tool("vmware_list_hosts", "List ESXi hosts", group="read", read=True, idempotent=True)
def vmware_list_hosts(
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum number of results")] = 50,
    offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Lists the ESXi hosts: state, version, model, CPU/RAM load, VM count.

    In json: {total, count, ..., hosts:[{name, moid, connection_state, power_state,
    in_maintenance, version, model, cpu_cores, cpu_usage_mhz, cpu_total_mhz, memory_total,
    memory_usage, vms}]}. In markdown: table.
    """
    try:
        with container_view(vim.HostSystem) as hosts:
            hosts.sort(key=lambda h: h.name)
            page, meta = paginate(hosts, limit, offset)
            rows = []
            for h in page:
                s = h.summary
                hw, qs = s.hardware, s.quickStats
                rows.append(
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
        return render_listing("ESXi hosts", "hosts", rows, response_format, meta)
    except Exception as e:
        return error_text(e)


@tool("vmware_list_clusters", "List clusters", group="read", read=True, idempotent=True)
def vmware_list_clusters(
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Lists the clusters: HA/DRS, hosts, aggregated CPU/RAM capacity.

    In json: {count, clusters:[{name, moid, hosts, ha_enabled, drs_enabled, drs_behavior,
    total_cpu_mhz, total_memory, effective_hosts}]}. In markdown: table.
    """
    try:
        with container_view(vim.ClusterComputeResource) as clusters:
            rows = []
            for c in sorted(clusters, key=lambda x: x.name):
                cfg = c.configurationEx
                rows.append(
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
        return render_listing("Clusters", "clusters", rows, response_format)
    except Exception as e:
        return error_text(e)


@tool("vmware_list_datastores", "List datastores", group="read", read=True, idempotent=True)
def vmware_list_datastores(
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum number of results")] = 100,
    offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Lists the datastores: type, capacity, free space, accessibility.

    In json: {total, count, ..., datastores:[{name, moid, type, capacity, free, free_pct,
    accessible, hosts, vms}]}. In markdown: table.
    """
    try:
        with container_view(vim.Datastore) as stores:
            stores.sort(key=lambda d: d.name)
            page, meta = paginate(stores, limit, offset)
            rows = []
            for d in page:
                s = d.summary
                free_pct = round(100 * s.freeSpace / s.capacity, 1) if s.capacity else None
                rows.append(
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
        return render_listing("Datastores", "datastores", rows, response_format, meta)
    except Exception as e:
        return error_text(e)


@tool("vmware_list_networks", "List networks", group="read", read=True, idempotent=True)
def vmware_list_networks(
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum number of results")] = 100,
    offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Lists the networks (standard and distributed portgroups).

    In json: {total, count, ..., networks:[{name, moid, type, accessible, vms, vlan}]}.
    vlan is only filled in for distributed portgroups. In markdown: table.
    """
    try:
        with container_view(vim.Network) as nets:
            nets.sort(key=lambda n: n.name)
            page, meta = paginate(nets, limit, offset)
            rows = []
            for n in page:
                vlan: int | str | None = None
                if isinstance(n, vim.dvs.DistributedVirtualPortgroup):
                    port_config = n.config.defaultPortConfig
                    vlan_cfg = port_config.vlan if port_config else None
                    vlan_id = getattr(vlan_cfg, "vlanId", None)
                    if isinstance(vlan_id, int):
                        vlan = vlan_id
                    elif isinstance(vlan_id, list):
                        vlan = ", ".join(f"{r.start}-{r.end}" for r in vlan_id)
                rows.append(
                    {
                        "name": n.name,
                        "moid": n._moId,
                        "type": type(n).__name__.rsplit(".", 1)[-1],
                        "accessible": n.summary.accessible,
                        "vms": len(n.vm),
                        "vlan": vlan,
                    }
                )
        return render_listing("Networks", "networks", rows, response_format, meta)
    except Exception as e:
        return error_text(e)


@tool("vmware_list_snapshots", "Snapshots of a VM", group="read", read=True, idempotent=True)
def vmware_list_snapshots(
    vm: Annotated[str, Field(description="Exact name or MoID of the VM")],
) -> dict[str, Any] | str:
    """Snapshot tree of a VM (name, description, date, children).

    Returns a structured object {vm, count, current_snapshot_moid, snapshots:[...tree...]}.
    """
    try:
        obj = find_vm(vm)
        if not obj.snapshot:
            return {"vm": obj.name, "count": 0, "snapshots": []}
        tree = snapshot_tree(obj.snapshot.rootSnapshotList)

        def count(nodes: list[dict[str, Any]]) -> int:
            return sum(1 + count(n["children"]) for n in nodes)

        current = obj.snapshot.currentSnapshot._moId if obj.snapshot.currentSnapshot else None
        return {
            "vm": obj.name,
            "count": count(tree),
            "current_snapshot_moid": current,
            "snapshots": tree,
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_recent_tasks", "Recent tasks", group="read", read=True)
def vmware_recent_tasks(
    limit: Annotated[int, Field(ge=1, le=200, description="Maximum number of tasks")] = 30,
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Latest vCenter tasks (running or recent operations) with state and target.

    In json: {count, tasks:[{key, description, target, state, progress_pct, user, queued,
    started, completed, error}]}. In markdown: table, most recent first.
    """
    try:
        si = get_si()
        task_manager = si.content.taskManager
        if task_manager is None:
            return "Error: taskManager unavailable on this vCenter."
        tasks = list(task_manager.recentTask)[-limit:]
        rows = []
        for t in reversed(tasks):
            i = t.info
            rows.append(
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
        return render_listing("Recent tasks", "tasks", rows, response_format)
    except Exception as e:
        return error_text(e)


@tool("vmware_list_events", "Recent events", group="read", read=True)
def vmware_list_events(
    vm: Annotated[
        str | None, Field(description="Limit to events for this VM (name or MoID)")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="Maximum number of events")] = 30,
    offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Recent vCenter events, global or filtered on a VM.

    In json: {total, count, offset, has_more, next_offset, events:[{time, type, user,
    target, message}]}, most recent first. In markdown: table.
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
            return "Error: eventManager unavailable on this vCenter."
        collector = event_manager.CreateCollectorForEvents(spec)
        try:
            events = list(collector.latestPage)
        finally:
            collector.DestroyCollector()
        page, meta = paginate(events, limit, offset)
        rows = [
            {
                "time": e.createdTime,
                "type": type(e).__name__.rsplit(".", 1)[-1],
                "user": e.userName or None,
                "target": e.vm.name if getattr(e, "vm", None) else None,
                "message": (e.fullFormattedMessage or "").strip(),
            }
            for e in page
        ]
        return render_listing("Events", "events", rows, response_format, meta)
    except Exception as e:
        return error_text(e)

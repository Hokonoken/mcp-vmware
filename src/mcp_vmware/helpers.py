# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Shared utilities: object resolution, inventory views, tasks, serialization."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from typing import Any

from pyVmomi import vim

from .connection import get_si


class ResponseFormat(StrEnum):
    """Output format of the listing tools."""

    MARKDOWN = "markdown"
    JSON = "json"


@contextmanager
def container_view(obj_type: type) -> Iterator[list[Any]]:
    """Inventory view over the whole vCenter for one managed object type."""
    si = get_si()
    view_manager = si.content.viewManager
    if view_manager is None:
        raise RuntimeError("viewManager unavailable on this vCenter.")
    view = view_manager.CreateContainerView(si.content.rootFolder, [obj_type], True)
    try:
        yield list(view.view)
    finally:
        view.Destroy()


def find_vm(name_or_moid: str) -> vim.VirtualMachine:
    """Resolve a VM by MoID (vm-123) or by exact name (case-insensitive).

    Raises ValueError with suggestions when not found or ambiguous.
    """
    with container_view(vim.VirtualMachine) as vms:
        if name_or_moid.startswith("vm-"):
            for vm in vms:
                if vm._moId == name_or_moid:
                    return vm
            raise ValueError(f"No VM with MoID '{name_or_moid}'.")
        exact = [vm for vm in vms if vm.name.lower() == name_or_moid.lower()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            moids = ", ".join(f"{vm.name} ({vm._moId})" for vm in exact)
            raise ValueError(f"Multiple VMs named '{name_or_moid}': {moids}. Use the MoID.")
        partial = [vm.name for vm in vms if name_or_moid.lower() in vm.name.lower()][:10]
        hint = f" Close matches: {', '.join(partial)}." if partial else ""
        raise ValueError(f"VM '{name_or_moid}' not found.{hint}")


def _find_entity(obj_type: type, kind: str, name: str) -> Any:
    """Resolve an inventory object by exact name (case-insensitive)."""
    with container_view(obj_type) as objs:
        exact = [o for o in objs if o.name.lower() == name.lower()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            moids = ", ".join(f"{o.name} ({o._moId})" for o in exact)
            raise ValueError(f"Multiple {kind}s named '{name}': {moids}.")
        known = ", ".join(sorted(o.name for o in objs)[:15])
        raise ValueError(f"{kind} '{name}' not found. Available: {known}")


def find_cluster(name: str) -> vim.ClusterComputeResource:
    return _find_entity(vim.ClusterComputeResource, "cluster", name)


def find_host(name: str) -> vim.HostSystem:
    return _find_entity(vim.HostSystem, "ESXi host", name)


def wait_for_task(task: vim.Task, timeout_s: int = 600) -> Any:
    """Wait for a vCenter task to finish, return its result or raise RuntimeError."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = task.info.state
        if state == vim.TaskInfo.State.success:
            return task.info.result
        if state == vim.TaskInfo.State.error:
            msg = getattr(task.info.error, "msg", None) or "unknown error"
            raise RuntimeError(f"vCenter task failed: {msg}")
        time.sleep(1)
    raise RuntimeError(
        f"vCenter task not finished after {timeout_s}s (it keeps running on the vCenter side)."
    )


async def wait_for_task_async(
    task: vim.Task,
    timeout_s: int = 600,
    progress: Callable[..., Any] | None = None,
    label: str = "",
) -> Any:
    """Async version of wait_for_task with progress reporting.

    `progress` is a coroutine (typically ctx.report_progress) called with
    (progress, total=100, message) on every percentage change.
    """
    import time

    import anyio

    deadline = time.monotonic() + timeout_s
    last: float | None = None
    while time.monotonic() < deadline:
        info = await anyio.to_thread.run_sync(lambda: task.info)
        if info.state == vim.TaskInfo.State.success:
            if progress is not None:
                await progress(100.0, 100.0, f"{label} finished" if label else None)
            return info.result
        if info.state == vim.TaskInfo.State.error:
            msg = getattr(info.error, "msg", None) or "unknown error"
            raise RuntimeError(f"vCenter task failed: {msg}")
        if progress is not None and info.progress is not None and info.progress != last:
            last = info.progress
            await progress(float(info.progress), 100.0, label or None)
        await anyio.sleep(1)
    raise RuntimeError(
        f"vCenter task not finished after {timeout_s}s (it keeps running on the vCenter side)."
    )


def paginate(items: list[Any], limit: int, offset: int) -> tuple[list[Any], dict[str, Any]]:
    """Slice a list and return (page, pagination metadata)."""
    total = len(items)
    page = items[offset : offset + limit]
    end = offset + len(page)
    return page, {
        "total": total,
        "count": len(page),
        "offset": offset,
        "has_more": end < total,
        "next_offset": end if end < total else None,
    }


def _md_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def md_table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    """Render a list of flat dicts as a markdown table."""
    if not rows:
        return "(no items)"
    cols = columns or list(rows[0].keys())
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    lines.extend("| " + " | ".join(_md_cell(r.get(c)) for c in cols) + " |" for r in rows)
    return "\n".join(lines)


def render_listing(
    title: str,
    key: str,
    rows: list[dict[str, Any]],
    fmt: ResponseFormat,
    meta: dict[str, Any] | None = None,
    columns: list[str] | None = None,
) -> dict[str, Any] | str:
    """Uniform listing output: dict (structured JSON) or markdown table."""
    meta = meta if meta is not None else {"count": len(rows)}
    if fmt == ResponseFormat.JSON:
        return {**meta, key: rows}
    parts = [f"# {title}", ""]
    if "total" in meta:
        shown = f"{meta['count']} shown out of {meta['total']}"
        if meta.get("has_more"):
            shown += f" — continue with offset={meta['next_offset']}"
        parts.append(shown)
    else:
        parts.append(f"{meta.get('count', len(rows))} item(s)")
    parts.extend(["", md_table(rows, columns)])
    return "\n".join(parts)


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
        return f"Error: {e}"
    if isinstance(e, vim.fault.NoPermission):
        return "Error: insufficient vCenter permission for this operation."
    if isinstance(e, vim.fault.InvalidPowerState):
        return "Error: power state incompatible with this operation (check with vmware_get_vm)."
    return f"Unexpected error ({type(e).__name__}): {e}"


# ------------------------------------------------------------------ serialization


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

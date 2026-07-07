# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""ESXi host tools: detail (read group) and operations (host.ops group).

Host operations are the most sensitive of the server: maintenance and
reboot/shutdown require confirm=true.
"""

from typing import Annotated, Any

import anyio
from mcp.server.fastmcp import Context
from pydantic import Field

from .app import tool
from .helpers import error_text, find_host, fmt_bytes, wait_for_task, wait_for_task_async
from .roles import deny_message, group_allowed


def _gate(group: str) -> str | None:
    return None if group_allowed(group) else deny_message(group)


@tool("vmware_get_host", "Details of an ESXi host", group="read", read=True, idempotent=True)
def vmware_get_host(
    host: Annotated[str, Field(description="Host name (see vmware_list_hosts)")],
) -> dict[str, Any] | str:
    """Details of an ESXi host: state, uptime, hardware, hosted VMs, mounted datastores.

    Returns a JSON {name, moid, connection_state, power_state, in_maintenance,
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
        return {
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
    except Exception as e:
        return error_text(e)


@tool("vmware_host_maintenance", "Maintenance mode of a host", group="host.ops", destructive=True)
async def vmware_host_maintenance(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    action: Annotated[str, Field(description="enter or exit")],
    ctx: Context,
    confirm: Annotated[
        bool, Field(description="Must be true for enter (may evacuate VMs via DRS)")
    ] = False,
    timeout_s: Annotated[
        int, Field(ge=60, le=7200, description="vCenter timeout for the operation")
    ] = 1800,
) -> dict[str, Any] | str:
    """Puts an ESXi host into or takes it out of maintenance mode, with progress.

    Entering maintenance waits for VM evacuation (DRS). Requires confirm=true for
    enter. Returns a JSON {action, status, host, in_maintenance}.
    """
    if msg := _gate("host.ops"):
        return msg
    if action not in ("enter", "exit"):
        return "Error: invalid action, choose enter or exit."
    try:

        def _prepare() -> Any:
            h = find_host(host)
            in_maintenance = h.summary.runtime.inMaintenanceMode
            if action == "enter":
                if not confirm:
                    raise ValueError(
                        f"Refused: entering maintenance on '{h.name}' not confirmed "
                        f"({len(h.vm)} VMs present, DRS evacuation possible). Call again "
                        "with confirm=true after explicit user validation."
                    )
                if in_maintenance:
                    raise ValueError(f"'{h.name}' is already in maintenance mode.")
                return h, h.EnterMaintenanceMode_Task(timeout=timeout_s)
            if not in_maintenance:
                raise ValueError(f"'{h.name}' is not in maintenance mode.")
            return h, h.ExitMaintenanceMode_Task(timeout=timeout_s)

        h, task = await anyio.to_thread.run_sync(_prepare)
        await wait_for_task_async(
            task,
            timeout_s=timeout_s,
            progress=ctx.report_progress,
            label=f"maintenance {action} {host}",
        )
        return {
            "action": f"maintenance_{action}",
            "status": "success",
            "host": h.name,
            "in_maintenance": h.summary.runtime.inMaintenanceMode,
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_host_power", "Reboot/shutdown of a host", group="host.ops", destructive=True)
def vmware_host_power(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    action: Annotated[str, Field(description="reboot or shutdown")],
    confirm: Annotated[
        bool, Field(description="Must be true to execute. Otherwise the tool refuses.")
    ] = False,
    force: Annotated[
        bool,
        Field(description="Force even outside maintenance mode (DANGEROUS: VMs cut abruptly)"),
    ] = False,
) -> dict[str, Any] | str:
    """Reboots or shuts down an ESXi host. Refuses outside maintenance mode unless force=true.

    Most sensitive operation of the server: requires confirm=true. Returns a JSON
    {action, status, host}.
    """
    if msg := _gate("host.ops"):
        return msg
    if action not in ("reboot", "shutdown"):
        return "Error: invalid action, choose reboot or shutdown."
    try:
        h = find_host(host)
        if not confirm:
            return (
                f"Refused: {action} of host '{h.name}' not confirmed. Call again with "
                "confirm=true after explicit user validation."
            )
        if not h.summary.runtime.inMaintenanceMode and not force:
            return (
                f"Error: '{h.name}' is not in maintenance mode. Go through "
                "vmware_host_maintenance first, or use force=true fully aware of the "
                "consequences."
            )
        if action == "reboot":
            wait_for_task(h.RebootHost_Task(force=force))
        else:
            wait_for_task(h.ShutdownHost_Task(force=force))
        return {"action": f"host_{action}", "status": "success", "host": h.name}
    except Exception as e:
        return error_text(e)


@tool("vmware_host_connection", "Host connection to vCenter", group="host.ops")
def vmware_host_connection(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    action: Annotated[str, Field(description="reconnect or disconnect")],
) -> dict[str, Any] | str:
    """Reconnects or disconnects an ESXi host from vCenter (management only, no VM impact).

    Returns a JSON {action, status, host, connection_state}.
    """
    if msg := _gate("host.ops"):
        return msg
    if action not in ("reconnect", "disconnect"):
        return "Error: invalid action, choose reconnect or disconnect."
    try:
        h = find_host(host)
        if action == "reconnect":
            wait_for_task(h.ReconnectHost_Task())
        else:
            wait_for_task(h.DisconnectHost_Task())
        return {
            "action": f"host_{action}",
            "status": "success",
            "host": h.name,
            "connection_state": str(h.summary.runtime.connectionState),
        }
    except Exception as e:
        return error_text(e)

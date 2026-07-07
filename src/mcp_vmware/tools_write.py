# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""VM write MCP tools — exposed according to the role (see roles.py).

Destructive operations (delete) additionally require confirm=True.
"""

from typing import Annotated, Any

import anyio
from mcp.server.fastmcp import Context
from pydantic import Field
from pyVmomi import vim

from .app import tool
from .helpers import error_text, find_vm, vm_summary, wait_for_task, wait_for_task_async
from .roles import deny_message, group_allowed

POWER_ACTIONS = ("on", "off", "reset", "suspend", "shutdown_guest", "reboot_guest")


def _gate(group: str) -> str | None:
    return None if group_allowed(group) else deny_message(group)


def _find_snapshot(node_list: list[Any], name: str) -> vim.vm.Snapshot | None:
    for n in node_list or []:
        if n.name == name:
            return n.snapshot
        found = _find_snapshot(n.childSnapshotList, name)
        if found:
            return found
    return None


def _done(
    action: str, vm_obj: vim.VirtualMachine, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {"action": action, "status": "success", "vm": vm_summary(vm_obj)}
    if extra:
        result.update(extra)
    return result


@tool("vmware_power_vm", "Power control of a VM", group="vm.power", destructive=True)
def vmware_power_vm(
    vm: Annotated[str, Field(description="Exact name or MoID of the VM")],
    action: Annotated[
        str,
        Field(
            description=f"Action among: {', '.join(POWER_ACTIONS)}. The _guest variants "
            "go through VMware Tools (clean shutdown/reboot)."
        ),
    ],
) -> dict[str, Any] | str:
    """Changes the power state of a VM: on, off, reset, suspend, shutdown_guest,
    reboot_guest.

    off/reset are brutal (equivalent to the power button); prefer shutdown_guest/reboot_guest
    when VMware Tools is running. Returns a JSON {action, status, vm:{...}}.
    """
    if msg := _gate("vm.power"):
        return msg
    if action not in POWER_ACTIONS:
        return f"Error: invalid action '{action}'. Choose from: {', '.join(POWER_ACTIONS)}."
    try:
        obj = find_vm(vm)
        if action == "on":
            wait_for_task(obj.PowerOnVM_Task())
        elif action == "off":
            wait_for_task(obj.PowerOffVM_Task())
        elif action == "reset":
            wait_for_task(obj.ResetVM_Task())
        elif action == "suspend":
            wait_for_task(obj.SuspendVM_Task())
        elif action == "shutdown_guest":
            obj.ShutdownGuest()
        elif action == "reboot_guest":
            obj.RebootGuest()
        return _done(f"power_{action}", obj)
    except Exception as e:
        return error_text(e)


@tool("vmware_snapshot_create", "Create a snapshot", group="vm.snapshot")
def vmware_snapshot_create(
    vm: Annotated[str, Field(description="Exact name or MoID of the VM")],
    name: Annotated[str, Field(min_length=1, max_length=80, description="Snapshot name")],
    description: Annotated[str, Field(description="Free-form description")] = "",
    memory: Annotated[
        bool, Field(description="Include RAM (snapshot of a running VM, restorable live)")
    ] = False,
    quiesce: Annotated[
        bool, Field(description="Quiesce the filesystem via VMware Tools (running VM only)")
    ] = False,
) -> dict[str, Any] | str:
    """Creates a snapshot of the VM. Returns a JSON {action, status, snapshot, vm:{...}}."""
    if msg := _gate("vm.snapshot"):
        return msg
    try:
        obj = find_vm(vm)
        wait_for_task(
            obj.CreateSnapshot_Task(
                name=name, description=description, memory=memory, quiesce=quiesce
            )
        )
        return _done("snapshot_create", obj, {"snapshot": name})
    except Exception as e:
        return error_text(e)


@tool("vmware_snapshot_revert", "Revert to a snapshot", group="vm.snapshot", destructive=True)
def vmware_snapshot_revert(
    vm: Annotated[str, Field(description="Exact name or MoID of the VM")],
    snapshot_name: Annotated[str, Field(description="Exact name of the target snapshot")],
) -> dict[str, Any] | str:
    """Restores the VM to the state of a snapshot. The current (unsnapshotted) disk state
    is lost.

    Returns a JSON {action, status, snapshot, vm:{...}}.
    """
    if msg := _gate("vm.snapshot"):
        return msg
    try:
        obj = find_vm(vm)
        if not obj.snapshot:
            return f"Error: VM '{obj.name}' has no snapshot."
        snap = _find_snapshot(obj.snapshot.rootSnapshotList, snapshot_name)
        if not snap:
            return (
                f"Error: snapshot '{snapshot_name}' not found on '{obj.name}'. "
                "List with vmware_list_snapshots."
            )
        wait_for_task(snap.RevertToSnapshot_Task())
        return _done("snapshot_revert", obj, {"snapshot": snapshot_name})
    except Exception as e:
        return error_text(e)


@tool("vmware_snapshot_delete", "Delete a snapshot", group="vm.snapshot", destructive=True)
def vmware_snapshot_delete(
    vm: Annotated[str, Field(description="Exact name or MoID of the VM")],
    snapshot_name: Annotated[str, Field(description="Exact name of the snapshot to delete")],
    remove_children: Annotated[bool, Field(description="Also delete child snapshots")] = False,
) -> dict[str, Any] | str:
    """Deletes a snapshot (consolidates disks). Returns a JSON {action, status, ...}."""
    if msg := _gate("vm.snapshot"):
        return msg
    try:
        obj = find_vm(vm)
        if not obj.snapshot:
            return f"Error: VM '{obj.name}' has no snapshot."
        snap = _find_snapshot(obj.snapshot.rootSnapshotList, snapshot_name)
        if not snap:
            return (
                f"Error: snapshot '{snapshot_name}' not found on '{obj.name}'. "
                "List with vmware_list_snapshots."
            )
        wait_for_task(snap.RemoveSnapshot_Task(removeChildren=remove_children))
        return _done("snapshot_delete", obj, {"snapshot": snapshot_name})
    except Exception as e:
        return error_text(e)


@tool("vmware_reconfigure_vm", "Reconfigure CPU/RAM", group="vm.config")
def vmware_reconfigure_vm(
    vm: Annotated[str, Field(description="Exact name or MoID of the VM")],
    cpu: Annotated[int | None, Field(ge=1, le=128, description="New vCPU count")] = None,
    memory_mb: Annotated[int | None, Field(ge=128, le=4194304, description="New RAM in MB")] = None,
) -> dict[str, Any] | str:
    """Changes the vCPU count and/or RAM of a VM.

    If hot-add is not enabled, the VM must be powered off (check with vmware_get_vm).
    Returns a JSON {action, status, changes, vm:{...}}.
    """
    if msg := _gate("vm.config"):
        return msg
    if cpu is None and memory_mb is None:
        return "Error: provide at least cpu or memory_mb."
    try:
        obj = find_vm(vm)
        spec = vim.vm.ConfigSpec()
        changes = {}
        if cpu is not None:
            spec.numCPUs = cpu
            changes["cpu"] = cpu
        if memory_mb is not None:
            spec.memoryMB = memory_mb
            changes["memory_mb"] = memory_mb
        wait_for_task(obj.ReconfigVM_Task(spec=spec))
        return _done("reconfigure", obj, {"changes": changes})
    except Exception as e:
        return error_text(e)


@tool("vmware_clone_vm", "Clone a VM", group="vm.lifecycle")
async def vmware_clone_vm(
    vm: Annotated[str, Field(description="Source VM or template (exact name or MoID)")],
    new_name: Annotated[str, Field(min_length=1, max_length=80, description="Clone name")],
    ctx: Context,
    power_on: Annotated[bool, Field(description="Power on the clone after creation")] = False,
    datastore: Annotated[
        str | None, Field(description="Target datastore (default: same as the source)")
    ] = None,
) -> dict[str, Any] | str:
    """Clones a VM or deploys a VM from a template, in the same folder as the source.

    Potentially long operation (disk copy). Returns a JSON
    {action, status, vm:{...}} describing the clone.
    """
    if msg := _gate("vm.lifecycle"):
        return msg
    try:

        def _prepare() -> Any:
            src = find_vm(vm)
            relocate = vim.vm.RelocateSpec()
            if datastore:
                from .helpers import container_view

                with container_view(vim.Datastore) as stores:
                    match = [d for d in stores if d.name.lower() == datastore.lower()]
                if not match:
                    raise ValueError(f"datastore '{datastore}' not found (vmware_list_datastores).")
                relocate.datastore = match[0]
            spec = vim.vm.CloneSpec(location=relocate, powerOn=power_on, template=False)
            return src.CloneVM_Task(folder=src.parent, name=new_name, spec=spec)

        task = await anyio.to_thread.run_sync(_prepare)
        clone = await wait_for_task_async(
            task, timeout_s=3600, progress=ctx.report_progress, label=f"clone {new_name}"
        )
        return _done("clone", clone)
    except Exception as e:
        return error_text(e)


@tool("vmware_delete_vm", "Destroy a VM", group="vm.lifecycle", destructive=True)
def vmware_delete_vm(
    vm: Annotated[str, Field(description="Exact name or MoID of the VM to DESTROY")],
    confirm: Annotated[
        bool, Field(description="Must be true to execute. Otherwise the tool refuses.")
    ] = False,
) -> dict[str, Any] | str:
    """DESTROYS a VM: permanent deletion of the VM and its disks from the datastore.

    Irreversible. Requires confirm=true and a powered-off VM. Returns a JSON {action, status,
    deleted_vm}.
    """
    if msg := _gate("vm.lifecycle"):
        return msg
    try:
        obj = find_vm(vm)
        name, moid = obj.name, obj._moId
        if not confirm:
            return (
                f"Refused: destruction of '{name}' ({moid}) not confirmed. Call again with "
                "confirm=true after explicit user validation."
            )
        if str(obj.summary.runtime.powerState) != "poweredOff":
            return (
                f"Error: '{name}' is powered on. Power it off first "
                "(vmware_power_vm action=off), then retry."
            )
        wait_for_task(obj.Destroy_Task())
        return {
            "action": "delete",
            "status": "success",
            "deleted_vm": {"name": name, "moid": moid},
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_migrate_vm", "Migrate a VM (vMotion)", group="vm.lifecycle")
async def vmware_migrate_vm(
    vm: Annotated[str, Field(description="Exact name or MoID of the VM")],
    ctx: Context,
    target_host: Annotated[
        str | None, Field(description="Target ESXi host (name, see vmware_list_hosts)")
    ] = None,
    target_datastore: Annotated[
        str | None, Field(description="Target datastore (storage vMotion)")
    ] = None,
) -> dict[str, Any] | str:
    """Live-migrates a VM: to another host (vMotion), another datastore
    (storage vMotion), or both. Provide at least one target.

    Returns a JSON {action, status, vm:{...}}.
    """
    if msg := _gate("vm.lifecycle"):
        return msg
    if not target_host and not target_datastore:
        return "Error: provide target_host and/or target_datastore."
    try:

        def _prepare() -> tuple[Any, Any]:
            from .helpers import container_view

            obj = find_vm(vm)
            relocate = vim.vm.RelocateSpec()
            if target_host:
                with container_view(vim.HostSystem) as hosts:
                    match = [h for h in hosts if h.name.lower() == target_host.lower()]
                if not match:
                    raise ValueError(f"host '{target_host}' not found (vmware_list_hosts).")
                relocate.host = match[0]
                relocate.pool = match[0].parent.resourcePool
            if target_datastore:
                with container_view(vim.Datastore) as stores:
                    match = [d for d in stores if d.name.lower() == target_datastore.lower()]
                if not match:
                    raise ValueError(f"datastore '{target_datastore}' not found.")
                relocate.datastore = match[0]
            return obj, obj.RelocateVM_Task(spec=relocate)

        obj, task = await anyio.to_thread.run_sync(_prepare)
        await wait_for_task_async(
            task, timeout_s=3600, progress=ctx.report_progress, label=f"migration {vm}"
        )
        return _done("migrate", obj)
    except Exception as e:
        return error_text(e)

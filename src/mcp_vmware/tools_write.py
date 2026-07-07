"""Outils MCP d'ecriture sur les VMs — exposes selon le role (cf. roles.py).

Les operations destructrices (delete) exigent en plus confirm=True.
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


@tool("vmware_power_vm", "Alimentation d'une VM", group="vm.power", destructive=True)
def vmware_power_vm(
    vm: Annotated[str, Field(description="Nom exact ou MoID de la VM")],
    action: Annotated[
        str,
        Field(
            description=f"Action parmi: {', '.join(POWER_ACTIONS)}. Les variantes _guest "
            "passent par VMware Tools (arret/redemarrage propre)."
        ),
    ],
) -> dict[str, Any] | str:
    """Change l'etat d'alimentation d'une VM: on, off, reset, suspend, shutdown_guest,
    reboot_guest.

    off/reset sont brutaux (equivalent bouton power) ; preferer shutdown_guest/reboot_guest
    si VMware Tools est actif. Retourne un JSON {action, status, vm:{...}}.
    """
    if msg := _gate("vm.power"):
        return msg
    if action not in POWER_ACTIONS:
        return f"Erreur: action '{action}' invalide. Choisir parmi: {', '.join(POWER_ACTIONS)}."
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


@tool("vmware_snapshot_create", "Creer un snapshot", group="vm.snapshot")
def vmware_snapshot_create(
    vm: Annotated[str, Field(description="Nom exact ou MoID de la VM")],
    name: Annotated[str, Field(min_length=1, max_length=80, description="Nom du snapshot")],
    description: Annotated[str, Field(description="Description libre")] = "",
    memory: Annotated[
        bool, Field(description="Inclure la RAM (snapshot d'une VM allumee restaurable a chaud)")
    ] = False,
    quiesce: Annotated[
        bool, Field(description="Geler le filesystem via VMware Tools (VM allumee uniquement)")
    ] = False,
) -> dict[str, Any] | str:
    """Cree un snapshot de la VM. Retourne un JSON {action, status, snapshot, vm:{...}}."""
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


@tool("vmware_snapshot_revert", "Revenir a un snapshot", group="vm.snapshot", destructive=True)
def vmware_snapshot_revert(
    vm: Annotated[str, Field(description="Nom exact ou MoID de la VM")],
    snapshot_name: Annotated[str, Field(description="Nom exact du snapshot cible")],
) -> dict[str, Any] | str:
    """Restaure la VM a l'etat d'un snapshot. L'etat disque actuel (non snapshotte) est perdu.

    Retourne un JSON {action, status, snapshot, vm:{...}}.
    """
    if msg := _gate("vm.snapshot"):
        return msg
    try:
        obj = find_vm(vm)
        if not obj.snapshot:
            return f"Erreur: la VM '{obj.name}' n'a aucun snapshot."
        snap = _find_snapshot(obj.snapshot.rootSnapshotList, snapshot_name)
        if not snap:
            return (
                f"Erreur: snapshot '{snapshot_name}' introuvable sur '{obj.name}'. "
                "Lister avec vmware_list_snapshots."
            )
        wait_for_task(snap.RevertToSnapshot_Task())
        return _done("snapshot_revert", obj, {"snapshot": snapshot_name})
    except Exception as e:
        return error_text(e)


@tool("vmware_snapshot_delete", "Supprimer un snapshot", group="vm.snapshot", destructive=True)
def vmware_snapshot_delete(
    vm: Annotated[str, Field(description="Nom exact ou MoID de la VM")],
    snapshot_name: Annotated[str, Field(description="Nom exact du snapshot a supprimer")],
    remove_children: Annotated[
        bool, Field(description="Supprimer aussi les snapshots enfants")
    ] = False,
) -> dict[str, Any] | str:
    """Supprime un snapshot (consolide les disques). Retourne un JSON {action, status, ...}."""
    if msg := _gate("vm.snapshot"):
        return msg
    try:
        obj = find_vm(vm)
        if not obj.snapshot:
            return f"Erreur: la VM '{obj.name}' n'a aucun snapshot."
        snap = _find_snapshot(obj.snapshot.rootSnapshotList, snapshot_name)
        if not snap:
            return (
                f"Erreur: snapshot '{snapshot_name}' introuvable sur '{obj.name}'. "
                "Lister avec vmware_list_snapshots."
            )
        wait_for_task(snap.RemoveSnapshot_Task(removeChildren=remove_children))
        return _done("snapshot_delete", obj, {"snapshot": snapshot_name})
    except Exception as e:
        return error_text(e)


@tool("vmware_reconfigure_vm", "Reconfigurer CPU/RAM", group="vm.config")
def vmware_reconfigure_vm(
    vm: Annotated[str, Field(description="Nom exact ou MoID de la VM")],
    cpu: Annotated[int | None, Field(ge=1, le=128, description="Nouveau nombre de vCPU")] = None,
    memory_mb: Annotated[
        int | None, Field(ge=128, le=4194304, description="Nouvelle RAM en MB")
    ] = None,
) -> dict[str, Any] | str:
    """Change le nombre de vCPU et/ou la RAM d'une VM.

    Si le hot-add n'est pas active, la VM doit etre eteinte (verifier avec vmware_get_vm).
    Retourne un JSON {action, status, changes, vm:{...}}.
    """
    if msg := _gate("vm.config"):
        return msg
    if cpu is None and memory_mb is None:
        return "Erreur: fournir au moins cpu ou memory_mb."
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


@tool("vmware_clone_vm", "Cloner une VM", group="vm.lifecycle")
async def vmware_clone_vm(
    vm: Annotated[str, Field(description="VM ou template source (nom exact ou MoID)")],
    new_name: Annotated[str, Field(min_length=1, max_length=80, description="Nom du clone")],
    ctx: Context,
    power_on: Annotated[bool, Field(description="Demarrer le clone apres creation")] = False,
    datastore: Annotated[
        str | None, Field(description="Datastore cible (defaut: celui de la source)")
    ] = None,
) -> dict[str, Any] | str:
    """Clone une VM ou deploie une VM depuis un template, dans le meme dossier que la source.

    Operation potentiellement longue (copie des disques). Retourne un JSON
    {action, status, vm:{...}} decrivant le clone.
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
                    raise ValueError(
                        f"datastore '{datastore}' introuvable (vmware_list_datastores)."
                    )
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


@tool("vmware_delete_vm", "Detruire une VM", group="vm.lifecycle", destructive=True)
def vmware_delete_vm(
    vm: Annotated[str, Field(description="Nom exact ou MoID de la VM a DETRUIRE")],
    confirm: Annotated[
        bool, Field(description="Doit etre true pour executer. Sans cela l'outil refuse.")
    ] = False,
) -> dict[str, Any] | str:
    """DETRUIT une VM : suppression definitive de la VM et de ses disques du datastore.

    Irreversible. Exige confirm=true et une VM eteinte. Retourne un JSON {action, status,
    deleted_vm}.
    """
    if msg := _gate("vm.lifecycle"):
        return msg
    try:
        obj = find_vm(vm)
        name, moid = obj.name, obj._moId
        if not confirm:
            return (
                f"Refus: destruction de '{name}' ({moid}) non confirmee. Rappeler avec "
                "confirm=true apres validation explicite de l'utilisateur."
            )
        if str(obj.summary.runtime.powerState) != "poweredOff":
            return (
                f"Erreur: '{name}' est allumee. L'eteindre d'abord "
                "(vmware_power_vm action=off), puis reessayer."
            )
        wait_for_task(obj.Destroy_Task())
        return {
            "action": "delete",
            "status": "success",
            "deleted_vm": {"name": name, "moid": moid},
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_migrate_vm", "Migrer une VM (vMotion)", group="vm.lifecycle")
async def vmware_migrate_vm(
    vm: Annotated[str, Field(description="Nom exact ou MoID de la VM")],
    ctx: Context,
    target_host: Annotated[
        str | None, Field(description="Hote ESXi cible (nom, cf. vmware_list_hosts)")
    ] = None,
    target_datastore: Annotated[
        str | None, Field(description="Datastore cible (storage vMotion)")
    ] = None,
) -> dict[str, Any] | str:
    """Migre une VM a chaud : vers un autre hote (vMotion), un autre datastore
    (storage vMotion), ou les deux. Fournir au moins une cible.

    Retourne un JSON {action, status, vm:{...}}.
    """
    if msg := _gate("vm.lifecycle"):
        return msg
    if not target_host and not target_datastore:
        return "Erreur: fournir target_host et/ou target_datastore."
    try:

        def _prepare() -> tuple[Any, Any]:
            from .helpers import container_view

            obj = find_vm(vm)
            relocate = vim.vm.RelocateSpec()
            if target_host:
                with container_view(vim.HostSystem) as hosts:
                    match = [h for h in hosts if h.name.lower() == target_host.lower()]
                if not match:
                    raise ValueError(f"hote '{target_host}' introuvable (vmware_list_hosts).")
                relocate.host = match[0]
                relocate.pool = match[0].parent.resourcePool
            if target_datastore:
                with container_view(vim.Datastore) as stores:
                    match = [d for d in stores if d.name.lower() == target_datastore.lower()]
                if not match:
                    raise ValueError(f"datastore '{target_datastore}' introuvable.")
                relocate.datastore = match[0]
            return obj, obj.RelocateVM_Task(spec=relocate)

        obj, task = await anyio.to_thread.run_sync(_prepare)
        await wait_for_task_async(
            task, timeout_s=3600, progress=ctx.report_progress, label=f"migration {vm}"
        )
        return _done("migrate", obj)
    except Exception as e:
        return error_text(e)

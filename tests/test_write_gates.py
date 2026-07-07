# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Gates d'ecriture : refus par role, validations d'entree, confirmations destructives."""

import asyncio

import mcp_vmware.tools_cluster as tc
import mcp_vmware.tools_host as th
import mcp_vmware.tools_host_config as thc
import mcp_vmware.tools_write as tw

from .conftest import fake_host, fake_vm

# ------------------------------------------------------- refus par role (viewer)


def test_power_refuse_en_viewer():
    msg = tw.vmware_power_vm("une-vm", "on")
    assert "vm.power" in msg
    assert "viewer" in msg


def test_set_drs_refuse_en_viewer():
    msg = tc.vmware_set_drs("cluster", enabled=True)
    assert "cluster.ops" in msg


def test_host_power_refuse_en_viewer():
    msg = th.vmware_host_power("hote", "reboot", confirm=True, force=True)
    assert "host.ops" in msg


def test_service_action_refuse_en_viewer():
    msg = thc.vmware_host_service_action("hote", "ntpd", action="restart")
    assert "host.config" in msg


def test_le_refus_ne_touche_jamais_au_vcenter(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("le vCenter ne doit pas etre contacte quand le role refuse")

    monkeypatch.setattr(tw, "find_vm", boom)
    assert "vm.lifecycle" in tw.vmware_delete_vm("prod", confirm=True)


# ------------------------------------------------------------ validations d'entree


def test_power_action_invalide(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    msg = tw.vmware_power_vm("une-vm", "explode")
    assert "invalide" in msg


def test_reconfigure_sans_parametre(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    assert "au moins" in tw.vmware_reconfigure_vm("une-vm")


def test_migrate_sans_cible(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    msg = asyncio.run(tw.vmware_migrate_vm("une-vm", None))
    assert "target_host" in msg


def test_set_drs_behavior_invalide(monkeypatch):
    monkeypatch.setattr(tc, "group_allowed", lambda g: True)
    assert "invalide" in tc.vmware_set_drs("cluster", behavior="turbo")


def test_maintenance_action_invalide(monkeypatch):
    monkeypatch.setattr(th, "group_allowed", lambda g: True)
    msg = asyncio.run(th.vmware_host_maintenance("hote", "pause", None))
    assert "invalide" in msg


# --------------------------------------------------------- confirmations destructives


def test_delete_sans_confirm_refuse(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: fake_vm("victime", power="poweredOff"))
    msg = tw.vmware_delete_vm("victime")
    assert "Refus" in msg
    assert "confirm=true" in msg


def test_delete_vm_allumee_refuse(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: fake_vm("victime", power="poweredOn"))
    assert "allumee" in tw.vmware_delete_vm("victime", confirm=True)


def test_delete_confirme_et_eteinte_detruit(monkeypatch):
    detruite = []
    vm = fake_vm("victime", moid="vm-9", power="poweredOff", Destroy_Task=lambda: "task")
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: vm)
    monkeypatch.setattr(tw, "wait_for_task", lambda t, **k: detruite.append(t))
    out = tw.vmware_delete_vm("victime", confirm=True)
    assert out == {
        "action": "delete",
        "status": "success",
        "deleted_vm": {"name": "victime", "moid": "vm-9"},
    }
    assert detruite == ["task"]


def test_snapshot_revert_sans_snapshot(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: fake_vm("nue", snapshot=None))
    assert "aucun snapshot" in tw.vmware_snapshot_revert("nue", "avant-maj")


def test_host_power_sans_confirm_refuse(monkeypatch):
    monkeypatch.setattr(th, "group_allowed", lambda g: True)
    monkeypatch.setattr(th, "find_host", lambda h: fake_host("esx1"))
    msg = th.vmware_host_power("esx1", "reboot")
    assert "Refus" in msg


def test_host_power_hors_maintenance_refuse(monkeypatch):
    monkeypatch.setattr(th, "group_allowed", lambda g: True)
    monkeypatch.setattr(th, "find_host", lambda h: fake_host("esx1", in_maintenance=False))
    msg = th.vmware_host_power("esx1", "reboot", confirm=True)
    assert "maintenance" in msg


def test_maintenance_enter_sans_confirm_refuse(monkeypatch):
    monkeypatch.setattr(th, "group_allowed", lambda g: True)
    monkeypatch.setattr(th, "find_host", lambda h: fake_host("esx1", vms=[1, 2, 3]))
    msg = asyncio.run(th.vmware_host_maintenance("esx1", "enter", None))
    assert "Refus" in msg
    assert "3 VMs" in msg


def test_power_on_reussit_avec_vm_factice(monkeypatch):
    vm = fake_vm("ok-vm", PowerOnVM_Task=lambda: "task")
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: vm)
    monkeypatch.setattr(tw, "wait_for_task", lambda t, **k: None)
    out = tw.vmware_power_vm("ok-vm", "on")
    assert out["status"] == "success"
    assert out["action"] == "power_on"
    assert out["vm"]["name"] == "ok-vm"

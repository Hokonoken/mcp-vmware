# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Write gates: role-based denials, input validation, destructive confirmations.

Expected strings ("Refused", "invalid", "powered on", ...) are matched verbatim
against messages produced by the server source code.
"""

import asyncio

import mcp_vmware.tools_cluster as tc
import mcp_vmware.tools_host as th
import mcp_vmware.tools_host_config as thc
import mcp_vmware.tools_write as tw

from .conftest import fake_host, fake_vm

# ---------------------------------------------------- role denials (as viewer)


def test_power_denied_as_viewer():
    msg = tw.vmware_power_vm("some-vm", "on")
    assert "vm.power" in msg
    assert "viewer" in msg


def test_set_drs_denied_as_viewer():
    msg = tc.vmware_set_drs("cluster", enabled=True)
    assert "cluster.ops" in msg


def test_host_power_denied_as_viewer():
    msg = th.vmware_host_power("host1", "reboot", confirm=True, force=True)
    assert "host.ops" in msg


def test_service_action_denied_as_viewer():
    msg = thc.vmware_host_service_action("host1", "ntpd", action="restart")
    assert "host.config" in msg


def test_denial_never_touches_vcenter(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("vCenter must not be contacted when the role denies")

    monkeypatch.setattr(tw, "find_vm", boom)
    assert "vm.lifecycle" in tw.vmware_delete_vm("prod", confirm=True)


# -------------------------------------------------------------- input validation


def test_power_invalid_action(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    msg = tw.vmware_power_vm("some-vm", "explode")
    assert "invalid" in msg


def test_reconfigure_without_parameters(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    assert "at least" in tw.vmware_reconfigure_vm("some-vm")


def test_migrate_without_target(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    msg = asyncio.run(tw.vmware_migrate_vm("some-vm", None))
    assert "target_host" in msg


def test_set_drs_invalid_behavior(monkeypatch):
    monkeypatch.setattr(tc, "group_allowed", lambda g: True)
    assert "invalid" in tc.vmware_set_drs("cluster", behavior="turbo")


def test_maintenance_invalid_action(monkeypatch):
    monkeypatch.setattr(th, "group_allowed", lambda g: True)
    msg = asyncio.run(th.vmware_host_maintenance("host1", "pause", None))
    assert "invalid" in msg


# ------------------------------------------------------ destructive confirmations


def test_delete_without_confirm_denied(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: fake_vm("victim", power="poweredOff"))
    msg = tw.vmware_delete_vm("victim")
    assert "Refused" in msg
    assert "confirm=true" in msg


def test_delete_powered_on_vm_denied(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: fake_vm("victim", power="poweredOn"))
    assert "powered on" in tw.vmware_delete_vm("victim", confirm=True)


def test_delete_confirmed_and_powered_off_destroys(monkeypatch):
    destroyed = []
    vm = fake_vm("victim", moid="vm-9", power="poweredOff", Destroy_Task=lambda: "task")
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: vm)
    monkeypatch.setattr(tw, "wait_for_task", lambda t, **k: destroyed.append(t))
    out = tw.vmware_delete_vm("victim", confirm=True)
    assert out == {
        "action": "delete",
        "status": "success",
        "deleted_vm": {"name": "victim", "moid": "vm-9"},
    }
    assert destroyed == ["task"]


def test_snapshot_revert_without_snapshot(monkeypatch):
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: fake_vm("bare", snapshot=None))
    assert "no snapshot" in tw.vmware_snapshot_revert("bare", "pre-update")


def test_host_power_without_confirm_denied(monkeypatch):
    monkeypatch.setattr(th, "group_allowed", lambda g: True)
    monkeypatch.setattr(th, "find_host", lambda h: fake_host("esx1"))
    msg = th.vmware_host_power("esx1", "reboot")
    assert "Refused" in msg


def test_host_power_outside_maintenance_denied(monkeypatch):
    monkeypatch.setattr(th, "group_allowed", lambda g: True)
    monkeypatch.setattr(th, "find_host", lambda h: fake_host("esx1", in_maintenance=False))
    msg = th.vmware_host_power("esx1", "reboot", confirm=True)
    assert "maintenance" in msg


def test_maintenance_enter_without_confirm_denied(monkeypatch):
    monkeypatch.setattr(th, "group_allowed", lambda g: True)
    monkeypatch.setattr(th, "find_host", lambda h: fake_host("esx1", vms=[1, 2, 3]))
    msg = asyncio.run(th.vmware_host_maintenance("esx1", "enter", None))
    assert "Refused" in msg
    assert "3 VMs" in msg


def test_power_on_succeeds_with_fake_vm(monkeypatch):
    vm = fake_vm("ok-vm", PowerOnVM_Task=lambda: "task")
    monkeypatch.setattr(tw, "group_allowed", lambda g: True)
    monkeypatch.setattr(tw, "find_vm", lambda v: vm)
    monkeypatch.setattr(tw, "wait_for_task", lambda t, **k: None)
    out = tw.vmware_power_vm("ok-vm", "on")
    assert out["status"] == "success"
    assert out["action"] == "power_on"
    assert out["vm"]["name"] == "ok-vm"

# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Roles, permission groups and denial messages."""

import mcp_vmware.roles as roles


def test_default_role_is_viewer():
    assert roles.current_role() == "viewer"


def test_explicit_role(monkeypatch):
    for role in roles.ROLES:
        monkeypatch.setenv("MCP_VMWARE_ROLE", role)
        assert roles.current_role() == role


def test_unknown_role_falls_back_to_viewer(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ROLE", "superadmin")
    assert roles.current_role() == "viewer"


def test_role_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ROLE", "  Infra_Admin ")
    assert roles.current_role() == "infra_admin"


def test_allow_write_compat_gives_vm_admin(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ALLOW_WRITE", "1")
    assert roles.current_role() == "vm_admin"


def test_explicit_role_overrides_allow_write(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ALLOW_WRITE", "1")
    monkeypatch.setenv("MCP_VMWARE_ROLE", "viewer")
    assert roles.current_role() == "viewer"


def test_role_hierarchy_is_increasing():
    order = ["viewer", "operator", "vm_admin", "infra_admin"]
    for lower, higher in zip(order, order[1:], strict=False):
        assert roles.ROLES[lower] < roles.ROLES[higher]


def test_infra_admin_covers_all_groups():
    assert roles.ROLES["infra_admin"] == frozenset(roles.GROUPS)


def test_group_allowed_matrix(monkeypatch):
    cases = [
        ("viewer", "read", True),
        ("viewer", "vm.power", False),
        ("operator", "vm.power", True),
        ("operator", "vm.lifecycle", False),
        ("vm_admin", "vm.lifecycle", True),
        ("vm_admin", "cluster.ops", False),
        ("infra_admin", "host.config", True),
    ]
    for role, group, expected in cases:
        monkeypatch.setenv("MCP_VMWARE_ROLE", role)
        assert roles.group_allowed(group) is expected, (role, group)


def test_deny_message_is_actionable(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ROLE", "viewer")
    msg = roles.deny_message("host.ops")
    assert "viewer" in msg
    assert "host.ops" in msg
    assert "infra_admin" in msg
    assert "MCP_VMWARE_ROLE" in msg


def test_all_groups_are_reachable():
    covered = set()
    for groups in roles.ROLES.values():
        covered |= groups
    assert covered == set(roles.GROUPS)

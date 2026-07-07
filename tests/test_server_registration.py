# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Tool exposure per role: the server only shows what the role covers.

These tests reload the package to replay tool registration with each
role - without any vCenter connection.
"""

import asyncio
import importlib
import sys

import pytest

EXPECTED = {
    "viewer": 20,
    "operator": 24,
    "vm_admin": 28,
    "infra_admin": 39,
}


def load_server(role, monkeypatch):
    if role:
        monkeypatch.setenv("MCP_VMWARE_ROLE", role)
    for mod in [m for m in sys.modules if m.startswith("mcp_vmware")]:
        del sys.modules[mod]
    return importlib.import_module("mcp_vmware.server")


@pytest.fixture(autouse=True)
def restore_modules():
    yield
    # Reimport cleanly so the other test files are not polluted.
    for mod in [m for m in sys.modules if m.startswith("mcp_vmware")]:
        del sys.modules[mod]


@pytest.mark.parametrize("role,expected", sorted(EXPECTED.items()))
def test_tool_count_per_role(role, expected, monkeypatch):
    server = load_server(role, monkeypatch)
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) == expected


def test_viewer_is_strictly_read_only(monkeypatch):
    server = load_server("viewer", monkeypatch)
    tools = asyncio.run(server.mcp.list_tools())
    assert all(t.annotations.readOnlyHint for t in tools)


def test_default_role_exposes_as_viewer(monkeypatch):
    server = load_server(None, monkeypatch)
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) == EXPECTED["viewer"]


def test_write_tools_invisible_as_operator(monkeypatch):
    server = load_server("operator", monkeypatch)
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert "vmware_power_vm" in names
    assert "vmware_snapshot_create" in names
    assert "vmware_delete_vm" not in names
    assert "vmware_host_power" not in names
    assert "vmware_set_ha" not in names


def test_destructive_annotations_present(monkeypatch):
    server = load_server("infra_admin", monkeypatch)
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert tools["vmware_delete_vm"].annotations.destructiveHint is True
    assert tools["vmware_host_power"].annotations.destructiveHint is True
    assert tools["vmware_list_vms"].annotations.destructiveHint is False


def test_listings_declare_an_output_schema(monkeypatch):
    server = load_server("viewer", monkeypatch)
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert tools["vmware_list_vms"].outputSchema is not None
    assert tools["vmware_get_vm"].outputSchema is not None

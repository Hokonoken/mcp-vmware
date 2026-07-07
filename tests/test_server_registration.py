# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Exposition des outils par role : le serveur ne montre que ce que le role couvre.

Ces tests rechargent le package pour rejouer l'enregistrement des outils avec
chaque role — sans aucune connexion vCenter.
"""

import asyncio
import importlib
import sys

import pytest

ATTENDU = {
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
    # Reimporte proprement pour ne pas polluer les autres fichiers de test.
    for mod in [m for m in sys.modules if m.startswith("mcp_vmware")]:
        del sys.modules[mod]


@pytest.mark.parametrize("role,attendu", sorted(ATTENDU.items()))
def test_nombre_d_outils_par_role(role, attendu, monkeypatch):
    server = load_server(role, monkeypatch)
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) == attendu


def test_viewer_est_strictement_read_only(monkeypatch):
    server = load_server("viewer", monkeypatch)
    tools = asyncio.run(server.mcp.list_tools())
    assert all(t.annotations.readOnlyHint for t in tools)


def test_role_par_defaut_expose_comme_viewer(monkeypatch):
    server = load_server(None, monkeypatch)
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) == ATTENDU["viewer"]


def test_outils_write_invisibles_en_operator(monkeypatch):
    server = load_server("operator", monkeypatch)
    noms = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert "vmware_power_vm" in noms
    assert "vmware_snapshot_create" in noms
    assert "vmware_delete_vm" not in noms
    assert "vmware_host_power" not in noms
    assert "vmware_set_ha" not in noms


def test_annotations_destructives_presentes(monkeypatch):
    server = load_server("infra_admin", monkeypatch)
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert tools["vmware_delete_vm"].annotations.destructiveHint is True
    assert tools["vmware_host_power"].annotations.destructiveHint is True
    assert tools["vmware_list_vms"].annotations.destructiveHint is False


def test_listings_declarent_un_output_schema(monkeypatch):
    server = load_server("viewer", monkeypatch)
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert tools["vmware_list_vms"].outputSchema is not None
    assert tools["vmware_get_vm"].outputSchema is not None

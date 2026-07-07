# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Fixtures communes : environnement isole et fabriques d'objets pyvmomi factices."""

from types import SimpleNamespace

import pytest

import mcp_vmware.connection as connection


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Aucun test ne doit dependre du fichier env reel ni de variables residuelles."""
    monkeypatch.setattr(connection, "ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("MCP_VMWARE_ENV_FILE", str(tmp_path / "absent.env"))
    for var in ("MCP_VMWARE_ROLE", "MCP_VMWARE_ALLOW_WRITE", "VC_HOST", "VC_USER", "VC_PASS"):
        monkeypatch.delenv(var, raising=False)


def fake_vm(name, moid="vm-1", power="poweredOn", snapshot=None, **extra):
    """VM pyvmomi factice, suffisante pour vm_summary et les gates."""
    vm = SimpleNamespace(
        name=name,
        _moId=moid,
        snapshot=snapshot,
        summary=SimpleNamespace(
            runtime=SimpleNamespace(powerState=power, host=None),
            config=None,
            guest=None,
        ),
    )
    for k, v in extra.items():
        setattr(vm, k, v)
    return vm


def fake_host(name, moid="host-1", in_maintenance=False, vms=(), **extra):
    host = SimpleNamespace(
        name=name,
        _moId=moid,
        vm=list(vms),
        summary=SimpleNamespace(
            runtime=SimpleNamespace(
                inMaintenanceMode=in_maintenance,
                connectionState="connected",
                powerState="poweredOn",
            ),
        ),
    )
    for k, v in extra.items():
        setattr(host, k, v)
    return host


def fake_task(state="success", result=None, error_msg=None, progress=None):
    """Tache vCenter factice dans un etat fixe."""
    error = SimpleNamespace(msg=error_msg) if error_msg else None
    return SimpleNamespace(
        info=SimpleNamespace(state=state, result=result, error=error, progress=progress)
    )

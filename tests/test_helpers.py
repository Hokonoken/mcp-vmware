"""Helpers : formatage, pagination, resolution d'objets, taches."""

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from pyVmomi import vim

import mcp_vmware.helpers as helpers
from mcp_vmware.helpers import ResponseFormat

from .conftest import fake_task, fake_vm


def patch_inventory(monkeypatch, objs):
    @contextmanager
    def _view(obj_type):
        yield list(objs)

    monkeypatch.setattr(helpers, "container_view", _view)


# ------------------------------------------------------------------- formatage


def test_fmt_bytes():
    assert helpers.fmt_bytes(None) is None
    assert helpers.fmt_bytes(512) == "512.0 B"
    assert helpers.fmt_bytes(1024) == "1.0 KiB"
    assert helpers.fmt_bytes(2 * 1024**4) == "2.0 TiB"


def test_to_json_serialise_les_dates():
    quand = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    assert "2026-07-07T12:00:00+00:00" in helpers.to_json({"t": quand})


def test_md_table_vide():
    assert helpers.md_table([]) == "(aucun element)"


def test_md_table_echappe_et_joint():
    rows = [{"a": "x|y", "b": [1, 2], "c": None}]
    table = helpers.md_table(rows)
    assert "x\\|y" in table
    assert "1, 2" in table
    assert table.count("\n") == 2  # entete + separateur + 1 ligne


def test_paginate():
    items = list(range(10))
    page, meta = helpers.paginate(items, limit=3, offset=6)
    assert page == [6, 7, 8]
    assert meta == {"total": 10, "count": 3, "offset": 6, "has_more": True, "next_offset": 9}
    page, meta = helpers.paginate(items, limit=5, offset=8)
    assert page == [8, 9]
    assert meta["has_more"] is False
    assert meta["next_offset"] is None
    page, meta = helpers.paginate(items, limit=5, offset=50)
    assert page == []


def test_render_listing_json_et_markdown():
    rows = [{"name": "a", "cpu": 2}]
    meta = {"total": 5, "count": 1, "offset": 0, "has_more": True, "next_offset": 1}
    out = helpers.render_listing("Titre", "vms", rows, ResponseFormat.JSON, meta)
    assert isinstance(out, dict)
    assert out["vms"] == rows
    assert out["has_more"] is True
    md = helpers.render_listing("Titre", "vms", rows, ResponseFormat.MARKDOWN, meta)
    assert isinstance(md, str)
    assert md.startswith("# Titre")
    assert "1 affiche(s) sur 5" in md
    assert "offset=1" in md
    assert "| name | cpu |" in md


# ------------------------------------------------------------------ resolution


def test_find_vm_par_nom_exact_insensible_casse(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("Web-01"), fake_vm("db-01", moid="vm-2")])
    assert helpers.find_vm("web-01").name == "Web-01"


def test_find_vm_par_moid(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("a", moid="vm-42")])
    assert helpers.find_vm("vm-42")._moId == "vm-42"


def test_find_vm_moid_introuvable(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("a", moid="vm-1")])
    with pytest.raises(ValueError, match="MoID 'vm-99'"):
        helpers.find_vm("vm-99")


def test_find_vm_ambigue_liste_les_moids(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("dup", moid="vm-1"), fake_vm("dup", moid="vm-2")])
    with pytest.raises(ValueError, match="vm-1.*vm-2"):
        helpers.find_vm("dup")


def test_find_vm_introuvable_suggere(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("centreon-prod"), fake_vm("centreon-dev")])
    with pytest.raises(ValueError, match="centreon-prod"):
        helpers.find_vm("centreon")  # pas de match exact -> suggestions


def test_find_entity_introuvable_liste_les_candidats(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("CLUSTER_A"), fake_vm("CLUSTER_B")])
    with pytest.raises(ValueError, match="CLUSTER_A"):
        helpers._find_entity(object, "cluster", "inexistant")


# ---------------------------------------------------------------------- taches


def test_wait_for_task_succes():
    assert helpers.wait_for_task(fake_task("success", result="fini")) == "fini"


def test_wait_for_task_echec():
    with pytest.raises(RuntimeError, match="disque plein"):
        helpers.wait_for_task(fake_task("error", error_msg="disque plein"))


def test_wait_for_task_timeout():
    with pytest.raises(RuntimeError, match="non terminee"):
        helpers.wait_for_task(fake_task("running"), timeout_s=0)


def test_wait_for_task_async_remonte_la_progression():
    appels = []

    async def progress(pct, total, message):
        appels.append((pct, total, message))

    async def scenario():
        return await helpers.wait_for_task_async(
            fake_task("success", result="ok"), progress=progress, label="clone"
        )

    assert asyncio.run(scenario()) == "ok"
    assert appels == [(100.0, 100.0, "clone termine")]


def test_wait_for_task_async_echec():
    async def scenario():
        await helpers.wait_for_task_async(fake_task("error", error_msg="boum"))

    with pytest.raises(RuntimeError, match="boum"):
        asyncio.run(scenario())


# ---------------------------------------------------------------------- erreurs


def test_error_text():
    assert helpers.error_text(ValueError("VM 'x' introuvable.")) == "Erreur: VM 'x' introuvable."
    assert "Erreur:" in helpers.error_text(RuntimeError("boum"))
    assert "TypeError" in helpers.error_text(TypeError("mauvais type"))
    assert "permission" in helpers.error_text(vim.fault.NoPermission()).lower()

# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Helpers: formatting, pagination, object resolution, tasks."""

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from pyVmomi import vim

import mcp_vmware.helpers as helpers

from .conftest import fake_task, fake_vm


def patch_inventory(monkeypatch, objs):
    @contextmanager
    def _view(obj_type):
        yield list(objs)

    monkeypatch.setattr(helpers, "container_view", _view)


# ------------------------------------------------------------------ formatting


def test_fmt_bytes():
    assert helpers.fmt_bytes(None) is None
    assert helpers.fmt_bytes(512) == "512.0 B"
    assert helpers.fmt_bytes(1024) == "1.0 KiB"
    assert helpers.fmt_bytes(2 * 1024**4) == "2.0 TiB"


def test_to_json_serializes_dates():
    when = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    assert "2026-07-07T12:00:00+00:00" in helpers.to_json({"t": when})


def test_md_table_empty():
    assert helpers.md_table([]) == "(no items)"


def test_md_table_escapes_and_joins():
    rows = [{"a": "x|y", "b": [1, 2], "c": None}]
    table = helpers.md_table(rows)
    assert "x\\|y" in table
    assert "1, 2" in table
    assert table.count("\n") == 2  # header + separator + 1 row


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


def test_render_listing_json_and_markdown():
    rows = [{"name": "a", "cpu": 2}]
    meta = {"total": 5, "count": 1, "offset": 0, "has_more": True, "next_offset": 1}
    out = helpers.render_listing("Title", "vms", rows, helpers.ResponseFormat.JSON, meta)
    assert isinstance(out, dict)
    assert out["vms"] == rows
    assert out["has_more"] is True
    md = helpers.render_listing("Title", "vms", rows, helpers.ResponseFormat.MARKDOWN, meta)
    assert isinstance(md, str)
    assert md.startswith("# Title")
    assert "1 shown out of 5" in md
    assert "offset=1" in md
    assert "| name | cpu |" in md


# ------------------------------------------------------------------ resolution


def test_find_vm_exact_name_case_insensitive(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("Web-01"), fake_vm("db-01", moid="vm-2")])
    assert helpers.find_vm("web-01").name == "Web-01"


def test_find_vm_by_moid(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("a", moid="vm-42")])
    assert helpers.find_vm("vm-42")._moId == "vm-42"


def test_find_vm_moid_not_found(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("a", moid="vm-1")])
    with pytest.raises(ValueError, match="MoID 'vm-99'"):
        helpers.find_vm("vm-99")


def test_find_vm_ambiguous_lists_moids(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("dup", moid="vm-1"), fake_vm("dup", moid="vm-2")])
    with pytest.raises(ValueError, match="vm-1.*vm-2"):
        helpers.find_vm("dup")


def test_find_vm_not_found_suggests(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("centreon-prod"), fake_vm("centreon-dev")])
    with pytest.raises(ValueError, match="centreon-prod"):
        helpers.find_vm("centreon")  # no exact match -> suggestions


def test_find_entity_not_found_lists_candidates(monkeypatch):
    patch_inventory(monkeypatch, [fake_vm("CLUSTER_A"), fake_vm("CLUSTER_B")])
    with pytest.raises(ValueError, match="CLUSTER_A"):
        helpers._find_entity(object, "cluster", "nonexistent")


# ----------------------------------------------------------------------- tasks


def test_wait_for_task_success():
    assert helpers.wait_for_task(fake_task("success", result="done")) == "done"


def test_wait_for_task_failure():
    with pytest.raises(RuntimeError, match="disk full"):
        helpers.wait_for_task(fake_task("error", error_msg="disk full"))


def test_wait_for_task_timeout():
    with pytest.raises(RuntimeError, match="not finished"):
        helpers.wait_for_task(fake_task("running"), timeout_s=0)


def test_wait_for_task_async_reports_progress():
    calls = []

    async def progress(pct, total, message):
        calls.append((pct, total, message))

    async def scenario():
        return await helpers.wait_for_task_async(
            fake_task("success", result="ok"), progress=progress, label="clone"
        )

    assert asyncio.run(scenario()) == "ok"
    assert calls == [(100.0, 100.0, "clone finished")]


def test_wait_for_task_async_failure():
    async def scenario():
        await helpers.wait_for_task_async(fake_task("error", error_msg="boom"))

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(scenario())


# ---------------------------------------------------------------------- errors


def test_error_text():
    assert helpers.error_text(ValueError("VM 'x' not found.")) == "Error: VM 'x' not found."
    assert "Error:" in helpers.error_text(RuntimeError("boom"))
    assert "TypeError" in helpers.error_text(TypeError("wrong type"))
    assert "permission" in helpers.error_text(vim.fault.NoPermission()).lower()

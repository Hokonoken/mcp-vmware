# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Property-based tests (Hypothesis) for the pure helpers.

These fuzz the formatting/pagination layer with arbitrary inputs and check
invariants rather than fixed examples.
"""

import json
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from mcp_vmware import helpers

# Cell values md_table must never break on: text with pipes/newlines,
# numbers, None, lists.
cells = st.one_of(
    st.text(max_size=30),
    st.integers(),
    st.none(),
    st.lists(st.text(max_size=10), max_size=3),
)
rows_strategy = st.lists(
    st.dictionaries(st.sampled_from(["name", "status", "notes"]), cells, min_size=1),
    max_size=20,
)


@given(items=st.lists(st.integers(), max_size=200), limit=st.integers(1, 50))
def test_paginate_walk_reconstructs_everything(items, limit):
    """Following next_offset from 0 yields every item exactly once, in order."""
    collected = []
    offset = 0
    while True:
        page, meta = helpers.paginate(items, limit, offset)
        collected.extend(page)
        assert meta["total"] == len(items)
        assert meta["count"] == len(page) <= limit
        assert meta["offset"] == offset
        if not meta["has_more"]:
            assert meta["next_offset"] is None
            break
        assert meta["next_offset"] == offset + meta["count"]
        offset = meta["next_offset"]
    assert collected == items


@given(
    items=st.lists(st.integers(), max_size=100),
    limit=st.integers(1, 50),
    offset=st.integers(0, 150),
)
def test_paginate_matches_slice(items, limit, offset):
    page, meta = helpers.paginate(items, limit, offset)
    assert page == items[offset : offset + limit]
    assert meta["has_more"] == (offset + len(page) < len(items))


@given(rows=rows_strategy)
def test_md_table_structure_survives_any_cell_content(rows):
    out = helpers.md_table(rows)
    if not rows:
        assert out == "(no items)"
        return
    lines = out.split("\n")
    assert len(lines) == len(rows) + 2  # header + separator + one line per row
    n_cols = lines[0].count("|")  # header has no escaped pipes
    for line in lines:
        assert line.startswith("| ") and line.endswith(" |")
        # Escaped pipes must not create phantom columns.
        assert line.count("|") - line.count("\\|") == n_cols


@given(rows=rows_strategy)
def test_render_listing_json_carries_meta_and_rows(rows):
    out = helpers.render_listing("T", "items", rows, helpers.ResponseFormat.JSON)
    assert isinstance(out, dict)
    assert out["items"] == rows
    assert out["count"] == len(rows)


@given(n=st.integers(0, 2**70))
def test_fmt_bytes_always_formats(n):
    out = helpers.fmt_bytes(n)
    assert isinstance(out, str)
    value, unit = out.split(" ")
    assert unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    assert float(value) >= 0.0
    if unit != "PiB":
        assert float(value) < 1024.0


@given(
    data=st.recursive(
        st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=20)),
        lambda children: st.one_of(
            st.lists(children, max_size=5),
            st.dictionaries(st.text(max_size=10), children, max_size=5),
        ),
        max_leaves=20,
    )
)
def test_to_json_roundtrips_json_safe_data(data):
    assert json.loads(helpers.to_json(data)) == data


def test_to_json_serializes_datetimes():
    out = helpers.to_json({"when": datetime(2026, 7, 7, tzinfo=UTC)})
    assert "2026-07-07" in out

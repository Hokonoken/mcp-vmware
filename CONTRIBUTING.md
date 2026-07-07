# Contributing

Thanks for your interest in mcp-vmware.

## Prerequisites

- Python 3.12+
- A test vCenter is a plus but is **not required**: the test suite fully mocks
  pyvmomi.

## Setup

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

## Before opening a PR

```bash
./.venv/bin/ruff check src tools tests
./.venv/bin/ruff format src tools tests
./.venv/bin/mypy src
./.venv/bin/pytest
```

CI replays exactly these checks, plus the container image build and a stdio
smoke test of the containerized server.

## Project rules

- **Every new MCP tool** goes through the `tool(name, title, group=...)`
  decorator from `app.py` (never `mcp.tool` directly): it enforces the roles.
- Write tools call `_gate("<group>")` at the top of the function, and
  destructive operations require `confirm=true`.
- Listings support `response_format` (markdown/json) and uniform pagination via
  `paginate()` + `render_listing()`.
- Update `api-map/coverage.yaml` in the same commit as the tool.
- No emojis in code or output. Actionable error messages.
- No secrets in the repo: credentials live in an env file outside the tree
  (`.vcenter.env`, chmod 600).

## Reporting a security issue

Do not open a public issue: see [SECURITY.md](SECURITY.md).

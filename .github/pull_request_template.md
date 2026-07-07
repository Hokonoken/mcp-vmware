## Description

<!-- What and why. -->

## Checklist

- [ ] `ruff check` + `ruff format` + `mypy src` + `pytest` pass locally
- [ ] New tool: `tool(..., group=...)` decorator, `_gate()` if write,
      `confirm=true` if destructive
- [ ] `api-map/coverage.yaml` updated in the same commit
- [ ] Tests added/adapted (pyvmomi mocks, no dependency on a live vCenter)
- [ ] No secrets, internal hostnames or instance data in the diff

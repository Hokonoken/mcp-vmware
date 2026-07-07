# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[SemVer](https://semver.org/).

## [0.1.0] - 2026-07-07

First public release.

### Added

- Stdio MCP server for vCenter (vSphere 7/8) via pyvmomi, 39 tools:
  - VMs: inventory, detail, power, snapshots, CPU/RAM reconfiguration, clone,
    delete, vMotion migration.
  - Clusters: HA/DRS config, DRS recommendations, affinity rules (read and
    write).
  - ESXi hosts: detail, maintenance, reboot/shutdown, connection, and esxcli
    equivalent through the official API (services, network, storage, firewall,
    advanced settings, VIBs, health sensors).
- 4 roles with permission groups (`MCP_VMWARE_ROLE`): viewer (20 tools),
  operator (24), vm_admin (28), infra_admin (39). Tools outside the active role
  are not exposed to the LLM; vCenter privilege templates in `docs/roles.md`.
- Destructive confirmations (`confirm=true`) on VM delete, host maintenance and
  host reboot/shutdown; host reboot refused outside maintenance unless
  `force=true`.
- Two deployment modes: direct (Docker/pip) and SSH jump host (stdio over SSH).
- LLM ergonomics: `response_format` markdown/json, structuredContent +
  outputSchema, uniform pagination, real-time progress for long operations
  (`ctx.report_progress`).
- API map versioned to the vCenter build (`api-map/`) and coverage matrix
  (`coverage.yaml`).
- Local pytest suite (56 tests, mocked pyvmomi, no vCenter required) and GitHub
  Actions CI (ruff, mypy, pytest, image build + smoke test).

[0.1.0]: https://github.com/Hokonoken/mcp-vmware/releases/tag/v0.1.0

# mcp-vmware

[![CI](https://github.com/Hokonoken/mcp-vmware/actions/workflows/ci.yml/badge.svg)](https://github.com/Hokonoken/mcp-vmware/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/protocol-MCP-8A2BE2)](https://modelcontextprotocol.io)

MCP server to pilot a VMware vCenter (vSphere 7/8) from Claude Code or any MCP
client, with **two deployment modes** depending on your network topology:

- **Direct**: the machine running the MCP client has a route to vCenter
  (homelab, admin workstation). Up and running in 2 minutes via Docker or pip.
- **Jump host**: the workstation has no access to the management network (a
  common enterprise setup). The server runs on a bastion machine and the client
  talks to it over SSH stdio — vCenter credentials never leave the secured
  zone.

Highlights:

- **39 tools** covering VMs (inventory, power, snapshots, clone, migration),
  clusters (HA, DRS, affinity rules) and ESXi hosts (maintenance, services,
  firewall, storage, advanced settings — esxcli equivalent through the official
  API, no SSH to the hosts).
- **4 roles with permission groups** (viewer/operator/vm_admin/infra_admin):
  tools outside the active role are not even exposed to the LLM.
- **LLM ergonomics**: compact markdown or structured JSON listings
  (structuredContent), uniform pagination, real-time progress for long
  operations.
- **API map versioned to the vCenter build**: the full API surface
  (1409 SOAP methods, 1064 REST operations) is mapped and versioned; the
  coverage matrix drives the server's evolution.

## Quick start (direct access to vCenter)

```bash
cp .vcenter.env.example .vcenter.env && chmod 600 .vcenter.env && vi .vcenter.env

# Docker / Podman (nothing else to install):
docker build -t mcp-vmware -f Containerfile .
docker run -i --rm --env-file .vcenter.env mcp-vmware

# or with Python (>= 3.12):
pip install . && MCP_VMWARE_ENV_FILE=./.vcenter.env python -m mcp_vmware
```

Declaration in `.mcp.json` (the MCP client talks stdio to the container):

```json
{
  "mcpServers": {
    "vmware": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", "/path/.vcenter.env", "mcp-vmware"]
    }
  }
}
```

Building behind a corporate proxy (TLS interception included):

```bash
docker build --network=host \
  --build-arg http_proxy --build-arg https_proxy --build-arg no_proxy \
  --build-arg PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org" \
  -t mcp-vmware -f Containerfile .
```

## Jump host mode (segmented enterprise networks)

When vCenter lives in a management network unreachable from workstations, the
server installs on the official jump host. MCP speaks stdio over SSH natively:
no tunnel, no exposed port.

```
Workstation (Claude Code / MCP client)
   |  spawn: ssh jumphost VMware/mcp-vmware/run.sh   (stdio = MCP protocol)
   v
jumphost (Linux, Python 3.12 venv)
   |  pyvmomi (SOAP vim25)
   v
vcenter.example.com (vSphere 8)
```

Benefits: network segmentation respected, credentials confined to the jump host
(`~/VMware/.vcenter.env`, chmod 600, never in the repo nor on the workstation),
single audit point.

```bash
# 1. Jump host: venv (once)
ssh jumphost 'mkdir -p ~/VMware && python3.12 -m venv ~/VMware/venv'

# 2. Credentials on the jump host
scp .vcenter.env.example jumphost:VMware/.vcenter.env
ssh jumphost 'chmod 600 ~/VMware/.vcenter.env && vi ~/VMware/.vcenter.env'

# 3. Deploy the server (rsync + pip install -e)
./deploy.sh

# 4. Adjust .mcp.json:
#    {"mcpServers": {"vmware": {"command": "ssh",
#                               "args": ["jumphost", "VMware/mcp-vmware/run.sh"]}}}
```

Quick check outside any MCP client:

```bash
ssh jumphost 'VMware/mcp-vmware/run.sh' <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}
EOF
```

## Roles and permission groups

Access is driven by `MCP_VMWARE_ROLE` in `.vcenter.env` (see `docs/roles.md`
for details and the matching vCenter privilege templates):

| Role | Exposed tools | Scope |
|---|---|---|
| `viewer` (default) | 20 | read-only over everything (inventory + host config) |
| `operator` | 24 | + VM power and snapshots |
| `vm_admin` | 28 | + VM reconfiguration, clone, delete, migration |
| `infra_admin` | 39 | + cluster HA/DRS/rules, host operations and fine-grained host config (esxcli equivalent) |

Tools outside the role are not registered: the LLM never sees them in
tools/list. Additional protections: `vmware_delete_vm`,
`vmware_host_maintenance` (enter) and `vmware_host_power` require
`confirm=true`; host reboot/shutdown is refused outside maintenance mode unless
`force=true`.

Defense in depth: use a vCenter service account whose vSphere role matches the
ceiling of the MCP role (templates in `docs/roles.md`), one env file per
account (`MCP_VMWARE_ENV_FILE`).

## Versioned API map (drives the evolution)

The server's evolution is driven by a complete map of the API, versioned to the
vCenter build:

- `tools/build_api_map.py` (run wherever vCenter is reachable) generates
  `api-map/<version>-<build>/`: the full vim25 SOAP surface (pyvmomi
  introspection) and the REST vAPI surface (live vCenter metamodel).
- `api-map/coverage.yaml` links each API area to an MCP tool with a status
  (todo / in_progress / done / wontdo) and carries the v2 backlog.
- On every vCenter upgrade: rerun the script, commit the new snapshot, and the
  git diff shows how the API evolved.

## Development

```bash
./.venv/bin/ruff check src tools tests && ./.venv/bin/ruff format src tools tests
./.venv/bin/mypy src
./.venv/bin/pytest          # local suite, mocked pyvmomi, no vCenter required
```

Adding a tool: implement it in the relevant `tools_*.py` module with the
`tool(name, title, group=...)` decorator (write tools call `_gate()` first),
update `api-map/coverage.yaml` in the same commit, deploy, smoke test.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Warning

This server gives an LLM the ability to act on virtualization infrastructure.
Start with the `viewer` role, use a vCenter service account with privileges
aligned to the chosen role (`docs/roles.md`), and only raise privileges after
validating the write tools on a test scope.

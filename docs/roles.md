# MCP server access roles and vCenter templates

## Principle: two layers of permissions

1. **MCP side** — `MCP_VMWARE_ROLE` in the env file (`.vcenter.env`). Tools
   outside the active role are not exposed to the LLM (absent from tools/list).
2. **vCenter side** — the service account used in `.vcenter.env` must carry a
   vSphere role *aligned with the same ceiling*. This is the real security
   boundary: even if the MCP layer were bypassed, vCenter would refuse.

Rule: **one service account per role**, never an Administrator account behind a
`viewer` MCP role.

## The 4 MCP roles

| MCP role | Groups | Exposed tools |
|---|---|---|
| `viewer` (default) | read | 20 read-only tools (inventory + host config) |
| `operator` | + vm.power, vm.snapshot | + power_vm, snapshot_create/revert/delete |
| `vm_admin` | + vm.config, vm.lifecycle | + reconfigure, clone, delete, migrate |
| `infra_admin` | + cluster.ops, host.ops, host.config | + HA/DRS/rules, host maintenance/reboot/connection, services/firewall/advanced settings/rescan (esxcli equivalent) |

Compatibility: `MCP_VMWARE_ALLOW_WRITE=1` without a role set is equivalent to
`vm_admin`.

## vSphere privilege templates per role

Create them in vCenter (Administration > Access Control > Roles), then assign
to the service account on the root object (or the datacenter) with propagation.
Check the exact labels in your vSphere version.

### viewer — use the built-in "Read-Only" role

Nothing to create: assign the built-in **Read-Only** role.

### operator — "MCP-Operator" role

Start from Read-Only and add:

- Virtual machine > Interaction: Power on, Power off, Suspend, Reset
- Virtual machine > Snapshot management: Create snapshot, Revert to snapshot,
  Remove snapshot, Rename snapshot

(Close to the built-in sample role "Virtual Machine Power User".)

### vm_admin — "MCP-VMAdmin" role

Start from MCP-Operator and add:

- Virtual machine > Configuration: Change CPU count, Change memory,
  Advanced configuration
- Virtual machine > Provisioning: Clone virtual machine, Deploy template
- Virtual machine > Inventory: Create from existing, Remove
- Datastore: Allocate space
- Network: Assign network
- Resource: Assign virtual machine to resource pool, Migrate powered on
  virtual machine, Migrate powered off virtual machine

### infra_admin — "MCP-InfraAdmin" role

Start from MCP-VMAdmin and add:

- Host > Configuration: Maintenance, Network configuration, Storage partition
  configuration, Advanced settings, Security profile and firewall,
  Change settings
- Host > Inventory: Add host to cluster, Remove host, Modify cluster
- Global: Diagnostics
- Resource: all remaining entries (DRS recommendations)

For host reboot/shutdown: Host > Configuration > Power (or leave it out of the
vCenter role to physically forbid it even under the infra_admin MCP role).

## Typical setup

```bash
# On the machine running the server, one env file per account/role if needed:
#   ~/VMware/.vcenter.env            (default viewer, read-only account)
#   ~/VMware/.vcenter-admin.env      (infra_admin, MCP-InfraAdmin account)
# The server reads MCP_VMWARE_ENV_FILE to pick the file:
ssh jumphost 'MCP_VMWARE_ENV_FILE=~/VMware/.vcenter-admin.env VMware/mcp-vmware/run.sh'
```

In `.mcp.json`, declare one MCP server per role if both are needed in parallel
(e.g. `vmware` as viewer and `vmware-admin` as infra_admin).

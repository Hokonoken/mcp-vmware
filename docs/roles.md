# Roles d'acces du serveur MCP et templates vCenter

## Principe : deux couches de droits

1. **Cote MCP** — `MCP_VMWARE_ROLE` dans `~/VMware/.vcenter.env` sur la machine rebond.
   Les outils hors role ne sont pas exposes au LLM (absents de tools/list).
2. **Cote vCenter** — le compte de service utilise dans `.vcenter.env` doit porter un
   role vSphere *aligne sur le meme plafond*. C'est la vraie barriere de securite :
   meme si la couche MCP etait contournee, le vCenter refuserait.

Regle : **un compte de service par role**, jamais un compte Administrator derriere un
role MCP `viewer`.

## Les 4 roles MCP

| Role MCP | Groupes | Outils exposes |
|---|---|---|
| `viewer` (defaut) | read | 20 outils de lecture (inventaire + config hotes) |
| `operator` | + vm.power, vm.snapshot | + power_vm, snapshot_create/revert/delete |
| `vm_admin` | + vm.config, vm.lifecycle | + reconfigure, clone, delete, migrate |
| `infra_admin` | + cluster.ops, host.ops, host.config | + HA/DRS/regles, maintenance/reboot/connexion hotes, services/firewall/parametres avances/rescan (equivalent esxcli) |

Compat : `MCP_VMWARE_ALLOW_WRITE=1` sans role defini equivaut a `vm_admin`.

## Templates de privileges vSphere par role

A creer dans vCenter (Administration > Access Control > Roles), puis assigner au compte
de service sur l'objet racine (ou le datacenter) avec propagation. Verifier les
libelles exacts dans votre version de vSphere.

### viewer — utiliser le role integre "Read-Only"

Aucun role a creer : assigner **Read-Only** (integre).

### operator — role "MCP-Operator"

Partir de Read-Only et ajouter :

- Virtual machine > Interaction : Power on, Power off, Suspend, Reset
- Virtual machine > Snapshot management : Create snapshot, Revert to snapshot,
  Remove snapshot, Rename snapshot

(Equivalent proche du sample role integre "Virtual Machine Power User".)

### vm_admin — role "MCP-VMAdmin"

Partir de MCP-Operator et ajouter :

- Virtual machine > Configuration : Change CPU count, Change memory,
  Advanced configuration
- Virtual machine > Provisioning : Clone virtual machine, Deploy template
- Virtual machine > Inventory : Create from existing, Remove
- Virtual machine > Edit inventory : Remove (selon version)
- Datastore : Allocate space
- Network : Assign network
- Resource : Assign virtual machine to resource pool, Migrate powered on virtual
  machine, Migrate powered off virtual machine

### infra_admin — role "MCP-InfraAdmin"

Partir de MCP-VMAdmin et ajouter :

- Host > Configuration : Maintenance, Network configuration, Storage partition
  configuration, Advanced settings, Security profile and firewall, Change settings
- Host > Inventory : Add host to cluster, Remove host, Modify cluster
- Global : Diagnostics (lecture des taches/evenements etendue)
- Resource : toutes les entrees restantes (recommendations DRS)

Pour reboot/shutdown d'hote : Host > Configuration > Power (sinon laisser hors du
role vCenter pour l'interdire physiquement meme en role MCP infra_admin).

## Mise en place type

```bash
# Sur la machine rebond, un fichier env par compte/role si besoin :
#   ~/VMware/.vcenter.env            (viewer par defaut, compte read-only)
#   ~/VMware/.vcenter-admin.env      (infra_admin, compte MCP-InfraAdmin)
# Le serveur lit MCP_VMWARE_ENV_FILE pour choisir le fichier :
ssh jumphost 'MCP_VMWARE_ENV_FILE=~/VMware/.vcenter-admin.env VMware/mcp-vmware/run.sh'
```

Dans `.mcp.json`, declarer un serveur MCP par role si l'on veut les deux en parallele
(ex. `vmware` en viewer et `vmware-admin` en infra_admin).

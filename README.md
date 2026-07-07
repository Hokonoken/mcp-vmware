# mcp-vmware

Serveur MCP pour piloter un vCenter VMware (vSphere 7/8) depuis Claude Code ou tout
client MCP, concu pour le cas frequent en entreprise ou le poste de travail n'a
**pas d'acces direct au vCenter** : le serveur tourne sur une machine rebond
(jump host) et le client s'y connecte en stdio a travers SSH. Aucun credential ne
quitte la machine rebond.

Points cles :

- **39 outils** couvrant VMs (inventaire, power, snapshots, clone, migration),
  clusters (HA, DRS, regles d'affinite) et hotes ESXi (maintenance, services,
  firewall, stockage, parametres avances — equivalent esxcli via l'API officielle,
  sans SSH vers les hotes).
- **4 roles a groupes de droits** (viewer/operator/vm_admin/infra_admin) : les
  outils hors role ne sont meme pas exposes au LLM.
- **Carte d'API versionnee au build vCenter** : la surface complete de l'API
  (1409 methodes SOAP, 1064 operations REST) est cartographiee et versionnee, la
  matrice de couverture pilote l'evolution du serveur.

## Architecture

```
Poste de travail (Claude Code / client MCP)
   |  spawn: ssh jumphost VMware/mcp-vmware/run.sh   (stdio = protocole MCP)
   v
jumphost (Linux, venv Python 3.12)
   |  pyvmomi (SOAP vim25)
   v
vcenter.example.com (vSphere 8)
```

- Le code vit dans ce repo (poste de travail) et est deploye sur la machine rebond
  par `./deploy.sh` (rsync + `pip install -e` dans `~/VMware/venv`).
- Les identifiants vCenter restent sur la machine rebond, dans `~/VMware/.vcenter.env`
  (chmod 600, modele dans `.vcenter.env.example`), jamais dans le repo.

## Installation

```bash
# 1. Machine rebond : venv + dependances (une fois)
ssh jumphost 'mkdir -p ~/VMware && python3.12 -m venv ~/VMware/venv'

# 2. Identifiants sur la machine rebond (jamais dans le repo)
scp .vcenter.env.example jumphost:VMware/.vcenter.env
ssh jumphost 'chmod 600 ~/VMware/.vcenter.env && vi ~/VMware/.vcenter.env'

# 3. Deployer le serveur
./deploy.sh

# 4. Adapter .mcp.json (nom d'hote SSH) — Claude Code detecte le fichier
#    a la racine du repo et se connecte tout seul.
```

## Roles et groupes de droits

L'acces est pilote par `MCP_VMWARE_ROLE` dans `.vcenter.env` (voir `docs/roles.md`
pour le detail et les templates de privileges vCenter correspondants) :

| Role | Outils exposes | Contenu |
|---|---|---|
| `viewer` (defaut) | 20 | lecture seule de tout (inventaire + config hotes) |
| `operator` | 24 | + power et snapshots des VMs |
| `vm_admin` | 28 | + reconfiguration, clone, delete, migration des VMs |
| `infra_admin` | 39 | + HA/DRS/regles cluster, operations et config fine des hotes (equivalent esxcli) |

Les outils hors role ne sont pas enregistres : le LLM ne les voit pas dans
tools/list. Protections supplementaires : `vmware_delete_vm`,
`vmware_host_maintenance` (enter) et `vmware_host_power` exigent `confirm=true` ;
reboot/shutdown d'hote refuse hors maintenance sauf `force=true`.

Defense en profondeur : utiliser un compte de service vCenter dont le role vSphere
correspond au plafond du role MCP (templates dans `docs/roles.md`), un fichier env
par compte (`MCP_VMWARE_ENV_FILE`).

## Carte d'API versionnee (pilotage de l'evolution)

L'evolution du serveur est pilotee par une cartographie complete de l'API,
versionnee au build du vCenter :

- `tools/build_api_map.py` (execute sur la machine rebond) genere
  `api-map/<version>-<build>/` : surface SOAP vim25 complete (introspection pyvmomi)
  et surface REST vAPI (metamodel du vCenter live).
- `api-map/coverage.yaml` relie chaque zone d'API a un outil MCP avec un statut
  (todo / in_progress / done / wontdo) et porte le backlog v2.
- A chaque upgrade du vCenter : relancer le script, committer le nouveau snapshot,
  le diff git montre l'evolution de l'API.

## Utilisation

```bash
./deploy.sh                      # deployer sur la machine rebond
# Claude Code detecte .mcp.json a la racine du repo et se connecte tout seul.
```

Verification rapide hors Claude Code :

```bash
ssh jumphost 'VMware/mcp-vmware/run.sh' <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}
EOF
```

## Developpement

```bash
./.venv/bin/ruff check src tools && ./.venv/bin/ruff format src tools
./.venv/bin/mypy src
```

Ajout d'un outil : implementer dans le module `tools_*.py` adequat avec le
decorateur `tool(name, title, group=...)` (les outils write appellent `_gate()` en
tete), mettre a jour `api-map/coverage.yaml` dans le meme commit, `./deploy.sh`,
smoke test.

## Avertissement

Ce serveur donne a un LLM la capacite d'agir sur une infrastructure de
virtualisation. Commencer en role `viewer`, utiliser un compte de service vCenter
aux privileges alignes sur le role choisi (`docs/roles.md`), et ne monter en
privileges qu'apres avoir valide les outils d'ecriture sur un perimetre de test.

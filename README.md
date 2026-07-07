# mcp-vmware

Serveur MCP pour piloter un vCenter VMware (vSphere 7/8) depuis Claude Code ou tout
client MCP, avec **deux modes de deploiement** selon votre topologie reseau :

- **Direct** : la machine qui execute le client MCP a une route vers le vCenter
  (homelab, poste d'admin). Demarrage en 2 minutes via Docker ou pip.
- **Jump host** : le poste de travail n'a pas d'acces au reseau de management
  (cas frequent en entreprise). Le serveur tourne sur une machine rebond et le
  client s'y connecte en stdio a travers SSH — les credentials vCenter ne
  quittent jamais la zone securisee.

Points cles :

- **39 outils** couvrant VMs (inventaire, power, snapshots, clone, migration),
  clusters (HA, DRS, regles d'affinite) et hotes ESXi (maintenance, services,
  firewall, stockage, parametres avances — equivalent esxcli via l'API officielle,
  sans SSH vers les hotes).
- **4 roles a groupes de droits** (viewer/operator/vm_admin/infra_admin) : les
  outils hors role ne sont meme pas exposes au LLM.
- **Ergonomie LLM** : listings en markdown compact ou JSON structure
  (structuredContent), pagination uniforme, progression en temps reel des
  operations longues.
- **Carte d'API versionnee au build vCenter** : la surface complete de l'API
  (1409 methodes SOAP, 1064 operations REST) est cartographiee et versionnee, la
  matrice de couverture pilote l'evolution du serveur.

## Demarrage rapide (acces direct au vCenter)

```bash
cp .vcenter.env.example .vcenter.env && chmod 600 .vcenter.env && vi .vcenter.env

# Docker / Podman (rien d'autre a installer) :
docker build -t mcp-vmware -f Containerfile .
docker run -i --rm --env-file .vcenter.env mcp-vmware

# ou en Python (>= 3.12) :
pip install . && MCP_VMWARE_ENV_FILE=./.vcenter.env python -m mcp_vmware
```

Declaration dans `.mcp.json` (le client MCP parle stdio au conteneur) :

```json
{
  "mcpServers": {
    "vmware": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", "/chemin/.vcenter.env", "mcp-vmware"]
    }
  }
}
```

Build derriere un proxy d'entreprise (interception TLS comprise) :

```bash
docker build --network=host \
  --build-arg http_proxy --build-arg https_proxy --build-arg no_proxy \
  --build-arg PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org" \
  -t mcp-vmware -f Containerfile .
```

## Mode jump host (reseaux d'entreprise cloisonnes)

Quand le vCenter vit dans un reseau de management inaccessible depuis les postes
de travail, le serveur s'installe sur la machine rebond officielle. MCP parle
stdio a travers SSH nativement : pas de tunnel, pas de port expose.

```
Poste de travail (Claude Code / client MCP)
   |  spawn: ssh jumphost VMware/mcp-vmware/run.sh   (stdio = protocole MCP)
   v
jumphost (Linux, venv Python 3.12)
   |  pyvmomi (SOAP vim25)
   v
vcenter.example.com (vSphere 8)
```

Avantages : cloisonnement reseau respecte, credentials confines a la machine
rebond (`~/VMware/.vcenter.env`, chmod 600, jamais dans le repo ni sur le poste),
point d'audit unique.

```bash
# 1. Machine rebond : venv (une fois)
ssh jumphost 'mkdir -p ~/VMware && python3.12 -m venv ~/VMware/venv'

# 2. Identifiants sur la machine rebond
scp .vcenter.env.example jumphost:VMware/.vcenter.env
ssh jumphost 'chmod 600 ~/VMware/.vcenter.env && vi ~/VMware/.vcenter.env'

# 3. Deployer le serveur (rsync + pip install -e)
./deploy.sh

# 4. Adapter .mcp.json :
#    {"mcpServers": {"vmware": {"command": "ssh",
#                               "args": ["jumphost", "VMware/mcp-vmware/run.sh"]}}}
```

Verification rapide hors client MCP :

```bash
ssh jumphost 'VMware/mcp-vmware/run.sh' <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}
EOF
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

- `tools/build_api_map.py` (execute la ou le vCenter est joignable) genere
  `api-map/<version>-<build>/` : surface SOAP vim25 complete (introspection pyvmomi)
  et surface REST vAPI (metamodel du vCenter live).
- `api-map/coverage.yaml` relie chaque zone d'API a un outil MCP avec un statut
  (todo / in_progress / done / wontdo) et porte le backlog v2.
- A chaque upgrade du vCenter : relancer le script, committer le nouveau snapshot,
  le diff git montre l'evolution de l'API.

## Developpement

```bash
./.venv/bin/ruff check src tools tests && ./.venv/bin/ruff format src tools tests
./.venv/bin/mypy src
./.venv/bin/pytest          # suite locale, pyvmomi mocke, aucun vCenter requis
```

Ajout d'un outil : implementer dans le module `tools_*.py` adequat avec le
decorateur `tool(name, title, group=...)` (les outils write appellent `_gate()` en
tete), mettre a jour `api-map/coverage.yaml` dans le meme commit, deployer,
smoke test.

## Avertissement

Ce serveur donne a un LLM la capacite d'agir sur une infrastructure de
virtualisation. Commencer en role `viewer`, utiliser un compte de service vCenter
aux privileges alignes sur le role choisi (`docs/roles.md`), et ne monter en
privileges qu'apres avoir valide les outils d'ecriture sur un perimetre de test.

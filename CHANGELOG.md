# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
versionnage [SemVer](https://semver.org/lang/fr/).

## [0.1.0] - 2026-07-07

Premiere version publique.

### Ajoute

- Serveur MCP stdio pour vCenter (vSphere 7/8) via pyvmomi, 39 outils :
  - VMs : inventaire, detail, power, snapshots, reconfiguration CPU/RAM,
    clone, suppression, migration vMotion.
  - Clusters : config HA/DRS, recommandations DRS, regles d'affinite
    (lecture et ecriture).
  - Hotes ESXi : detail, maintenance, reboot/arret, connexion, et equivalent
    esxcli via l'API officielle (services, reseau, stockage, firewall,
    parametres avances, VIBs, capteurs sante).
- 4 roles a groupes de droits (`MCP_VMWARE_ROLE`) : viewer (20 outils),
  operator (24), vm_admin (28), infra_admin (39). Les outils hors role ne sont
  pas exposes au LLM ; templates de privileges vCenter dans `docs/roles.md`.
- Confirmations destructives (`confirm=true`) sur delete VM, maintenance et
  reboot/arret d'hote ; reboot refuse hors maintenance sauf `force=true`.
- Deux modes de deploiement : direct (Docker/pip) et jump host (stdio via SSH).
- Ergonomie LLM : `response_format` markdown/json, structuredContent +
  outputSchema, pagination uniforme, progression temps reel des operations
  longues (`ctx.report_progress`).
- Carte d'API versionnee au build vCenter (`api-map/`) et matrice de
  couverture (`coverage.yaml`).
- Suite pytest locale (56 tests, pyvmomi mocke, aucun vCenter requis) et CI
  GitHub Actions (ruff, mypy, pytest, build + smoke test de l'image).

[0.1.0]: https://github.com/Hokonoken/mcp-vmware/releases/tag/v0.1.0

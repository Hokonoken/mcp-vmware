# Contribuer

Merci de votre interet pour mcp-vmware.

## Prerequis

- Python 3.12+
- Un vCenter de test est un plus mais n'est **pas requis** : la suite de tests
  mocke pyvmomi entierement.

## Mise en place

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

## Avant d'ouvrir une PR

```bash
./.venv/bin/ruff check src tools tests
./.venv/bin/ruff format src tools tests
./.venv/bin/mypy src
./.venv/bin/pytest
```

La CI rejoue exactement ces verifications, plus le build de l'image et un smoke
test stdio du serveur conteneurise.

## Regles du projet

- **Tout nouvel outil MCP** passe par le decorateur `tool(name, title, group=...)`
  de `app.py` (jamais `mcp.tool` direct) : c'est lui qui applique les roles.
- Les outils d'ecriture appellent `_gate("<groupe>")` en tete de fonction et les
  operations destructrices exigent `confirm=true`.
- Les listings supportent `response_format` (markdown/json) et la pagination
  uniforme via `paginate()` + `render_listing()`.
- Mettre a jour `api-map/coverage.yaml` dans le meme commit que l'outil.
- Pas d'emojis dans le code ni les sorties. Messages d'erreur actionnables.
- Aucun secret dans le repo : les identifiants vivent dans un fichier env hors
  depot (`.vcenter.env`, chmod 600).

## Signaler un bug de securite

Ne pas ouvrir d'issue publique : voir [SECURITY.md](SECURITY.md).

## Description

<!-- Quoi et pourquoi. -->

## Checklist

- [ ] `ruff check` + `ruff format` + `mypy src` + `pytest` passent en local
- [ ] Nouvel outil : decorateur `tool(..., group=...)`, gate `_gate()` si write,
      `confirm=true` si destructif
- [ ] `api-map/coverage.yaml` mis a jour dans le meme commit
- [ ] Tests ajoutes/adaptes (mocks pyvmomi, pas de dependance a un vCenter)
- [ ] Aucun secret, hostname interne ou donnee d'instance dans le diff

# Politique de securite

## Versions supportees

| Version | Supportee |
|---|---|
| 0.1.x | Oui |

## Signaler une vulnerabilite

Ce serveur donne a un LLM la capacite d'agir sur une infrastructure de
virtualisation : les questions de securite sont prises au serieux.

- **Ne pas ouvrir d'issue publique** pour une vulnerabilite.
- Utiliser les [GitHub Security Advisories](../../security/advisories/new)
  (signalement prive).
- Decrire l'impact, les etapes de reproduction et la version concernee.

Reponse initiale sous 7 jours.

## Perimetre

Sont notamment considerees comme vulnerabilites :

- Contournement du systeme de roles (execution d'un outil hors role).
- Contournement des confirmations destructives (`confirm=true`).
- Fuite d'identifiants vCenter via les sorties d'outils ou les logs.
- Injection dans les parametres transmis a l'API vCenter.

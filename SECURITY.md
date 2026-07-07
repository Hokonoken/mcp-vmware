# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

This server gives an LLM the ability to act on virtualization infrastructure:
security reports are taken seriously.

- **Do not open a public issue** for a vulnerability.
- Use [GitHub Security Advisories](../../security/advisories/new) (private
  reporting).
- Describe the impact, reproduction steps and the affected version.

Initial response within 7 days.

## Scope

The following are considered vulnerabilities, among others:

- Bypassing the role system (executing a tool outside the active role).
- Bypassing destructive confirmations (`confirm=true`).
- Leaking vCenter credentials through tool output or logs.
- Injection through parameters passed to the vCenter API.

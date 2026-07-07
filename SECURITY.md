# Security Policy

This is a personal, best-effort open-source project with no support commitment
or SLA (see the Disclaimer in the README). Security reports are still taken
seriously and handled as fast as I reasonably can.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

This server gives an LLM the ability to act on virtualization infrastructure:
security reports are taken seriously.

- **Do not open a public issue** for a vulnerability.
- Use [GitHub Security Advisories](https://github.com/Hokonoken/mcp-vmware/security/advisories/new)
  (private reporting).
- Describe the impact, reproduction steps and the affected version.

Initial response within 7 days.

## Scope

The following are considered vulnerabilities, among others:

- Bypassing the role system (executing a tool outside the active role).
- Bypassing destructive confirmations (`confirm=true`).
- Leaking vCenter credentials through tool output or logs.
- Injection through parameters passed to the vCenter API.

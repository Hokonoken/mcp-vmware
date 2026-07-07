# Governance

## Model

This project currently follows a **single-maintainer (BDFL)** model. The
repository owner is the maintainer and has final say on the roadmap, design
decisions, and what gets merged.

This is deliberate and honest about the project's size: it is a personal
project (see the Disclaimer in the [README](README.md)), not a foundation-backed
effort.

## Decision making

- Changes go through pull requests and must pass CI (lint, types, tests,
  container build) before merge.
- Design discussions happen in issues and pull requests, in the open.
- The maintainer may accept, request changes to, or decline any contribution,
  with a stated reason.

## Becoming a maintainer

If the project grows and someone contributes consistently and with quality,
they may be invited as a co-maintainer. This would be reflected by an update to
[CODEOWNERS](.github/CODEOWNERS) and this document.

## Releases

Releases follow [Semantic Versioning](https://semver.org/) and are documented in
[CHANGELOG.md](CHANGELOG.md). Each release is tagged `vX.Y.Z`.

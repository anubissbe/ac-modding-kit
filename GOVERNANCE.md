# Governance

The Ancient Cities Modding Kit is maintained in public for the benefit of its modding
community. This document describes how decisions and access are managed.

## Roles

- **Contributors** report problems, improve documentation, write code, and review work.
- **Reviewers** are trusted contributors who consistently provide accurate, respectful
  review; they may triage issues but do not merge by default.
- **Maintainers** set project direction, merge changes, manage releases and automation,
  and enforce community and security policies.

The repository owner is the initial maintainer. Maintainers may appoint reviewers or
new maintainers based on sustained, constructive contributions, sound judgment,
licensing awareness, and safe handling of compatibility claims. Access follows least
privilege and may be removed after prolonged inactivity or a policy breach.

## Decisions

Routine changes use pull-request review and lazy consensus. Significant changes—such
as supported formats, trust boundaries, release policy, or compatibility promises—must
start with a public issue or discussion and allow reasonable community review.
Maintainers seek consensus; when consensus is not possible, the maintainer responsible
for the affected area makes and records the decision and rationale.

No vote or approval can authorize redistribution of game assets, third-party Workshop
content, binary reverse engineering, unsafe credential handling, or misleading claims
of current-build compatibility.

## Merging and releases

At least one maintainer approval and passing required checks are expected before merge.
Maintainers must not approve their own high-risk changes without another reviewer when
one is available. Releases are tagged from `main`, summarized in `CHANGELOG.md`, and
follow semantic versioning where practical. Compatibility notes identify the Ancient
Cities build and validation date; absence of a note means compatibility is unverified.

## Security and conduct

Security reports follow [SECURITY.md](SECURITY.md). Conduct reports follow
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). A maintainer named in a report must recuse
themselves. The remaining maintainers may appoint a neutral reviewer when needed.

## Continuity

An inactive maintainer should hand over credentials and responsibilities to another
trusted maintainer. If no active maintainer remains, established contributors may
document a succession proposal publicly; control should transfer only after identity,
provenance, and repository security are verified.

# Security Policy

## Supported versions

Security fixes are made on `main` and included in the next release. Only the latest
release is supported after a fix ships.

| Version | Supported |
| --- | --- |
| `main` / latest release | Yes |
| Older releases | No |

## Reporting a vulnerability

Use **Security > Report a vulnerability** in this GitHub repository to open a private
report. Do not disclose exploitable details in a public issue, discussion, Steam post,
or pull request. If private vulnerability reporting is unavailable, open a public
issue containing only a request for a maintainer to enable a private channel.

Include, when safe:

- the affected version or commit;
- impact and realistic attack scenario;
- minimal reproduction steps or proof of concept;
- suggested mitigation, if known;
- whether Steam credentials, local files, saves, or Workshop publishing are involved.

Maintainers aim to acknowledge a report within five business days and provide an
initial assessment within ten. Timing depends on severity and maintainer availability.
We coordinate disclosure after a fix or mitigation is available and credit reporters
who want attribution.

## Scope

In scope are vulnerabilities in this repository's code, release artifacts, automation,
and documented installation flow—including crashes, resource exhaustion, path escape,
or code execution in this toolkit when it processes a hostile mod or archive. The
third-party mod's own in-game behavior, game vulnerabilities, Steam platform issues,
pirated copies, and unsupported binary reverse engineering are outside this project's
authority; report those to the relevant vendor or author.

Never attach proprietary game files, Workshop content, access tokens, personal saves,
or other people's personal information to a report.

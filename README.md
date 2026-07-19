# Ancient Cities Modding Kit

[![CI](https://github.com/anubissbe/ac-modding-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/anubissbe/ac-modding-kit/actions/workflows/ci.yml)
[![CodeQL](https://github.com/anubissbe/ac-modding-kit/actions/workflows/codeql.yml/badge.svg)](https://github.com/anubissbe/ac-modding-kit/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An unofficial, community-maintained toolkit for creating and validating mods for
*Ancient Cities* (Steam app `667610`). It turns the community's documented modding
knowledge into repeatable checks and small, auditable tools.

> [!IMPORTANT]
> This project is not affiliated with, endorsed by, or supported by Uncasual Games or
> Steam. Modding is at your own risk.

## Safety and legal boundaries

- The repository contains **no game files, proprietary assets, or redistributed Steam
  Workshop content**. Examples and test fixtures must be original or synthetic.
- Do not decompile, disassemble, bypass protections, or otherwise reverse engineer game
  binaries for this project. Use public documentation, user-authored material, and
  observable mod interfaces only.
- Treat every mod as build-specific until it has been tested against the current Steam
  build. Record the game build and test date with compatibility reports.
- Work with a new, disposable save and keep backups outside the game's save directory.
  Mods can break saves, change simulation state, and affect or disable achievements.
- Textual `.art` and `.loc` files for the audited v1.9.3 build require **UTF-16 little-
  endian (UTF-16LE) with a byte-order marker**. Repository source and documentation
  stay UTF-8; preserve the game encoding when exporting and validate it before use.

## What is included

- a Codex skill with a conservative Ancient Cities modding workflow;
- a small `acmk` command-line interface for inspection and validation;
- reference material derived from public community documentation;
- automated tests and GitHub checks for supported Python versions.

Repository layout:

```text
skills/ancient-cities-modding/  Skill, scripts, audited references, and safety guidance
tests/                          Automated tests with synthetic fixtures
.github/                        Contribution templates and automation
```

## Quick start

Requirements: Python 3.11 or newer and a legally obtained Steam installation of
*Ancient Cities*.

Windows PowerShell:

```powershell
git clone https://github.com/anubissbe/ac-modding-kit.git
cd ac-modding-kit
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
acmk --help
```

POSIX shell (static inspection/validation on Linux or macOS):

```bash
git clone https://github.com/anubissbe/ac-modding-kit.git
cd ac-modding-kit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
acmk --help
```

The static validators are cross-platform and CI-tested. Automatic discovery of Steam,
the redirected Windows Documents folder, and the live in-game workflow are currently
Windows-focused.

For Codex, ask the standard `skill-installer` to install path
`skills/ancient-cities-modding` from `anubissbe/ac-modding-kit`, then restart Codex so
the skill is discovered. Invoke it as `$ancient-cities-modding`. Start each task with:

```powershell
acmk --json discover
```

The tools do not install or publish Workshop items automatically: review generated
output before copying it into a local mod directory or uploading it through Steam.

## Validation checklist

Before sharing a mod:

1. Verify provenance for every file; exclude game and third-party Workshop assets.
2. Validate paths, expected structure, and UTF-16LE game-facing text.
3. Test on a disposable save with the current Steam build.
4. Restart the game and repeat the test from a clean launch.
5. Document the build, test date, dependencies, known conflicts, save impact, and
   achievement impact.

Passing toolkit checks is not proof of in-game compatibility. The running game is the
final validator.

## Community

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change.
- Ask usage questions through [GitHub Discussions](https://github.com/anubissbe/ac-modding-kit/discussions)
  or the [Ancient Cities Workshop discussions](https://steamcommunity.com/workshop/discussions/18446744073709551615/?appid=667610).
- Report security concerns according to [SECURITY.md](SECURITY.md).
- Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Code and original project documentation are available under the [MIT License](LICENSE).
That license does not grant rights to *Ancient Cities*, Steam, or third-party content.

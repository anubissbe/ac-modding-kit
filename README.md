# Ancient Cities Modding Kit

[![CI](https://github.com/anubissbe/ac-modding-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/anubissbe/ac-modding-kit/actions/workflows/ci.yml)
[![CodeQL](https://github.com/anubissbe/ac-modding-kit/actions/workflows/codeql.yml/badge.svg)](https://github.com/anubissbe/ac-modding-kit/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An unofficial, community-maintained Python SDK and toolkit for creating and validating
mods for *Ancient Cities* (Steam app `667610`). It turns audited community knowledge and
the game's observable data interface into typed, repeatable, and auditable workflows.

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
- a typed, standard-library-only `acmk` Python package;
- a backwards-compatible CLI for discovery, inspection, validation, conflicts, logs,
  deterministic packages, and safe metadata changes;
- a structured `acmk.toml` authoring project with separate runtime, authoring, state, and
  Workshop-staging directories;
- atomic import of current game-generated skeletons and dry-run-first release staging;
- lossless UTF-16LE ART/LOC documents, validated value objects, and immutable reports;
- a searchable offline knowledge base derived from audited public documentation;
- three original Blender/FBX authoring examples for a building, plant, and resource;
- JSON schemas, examples, strict typing, synthetic security and model tests, and GitHub
  checks for supported Python and Blender versions.

Repository layout:

```text
skills/ancient-cities-modding/  Skill, scripts, audited references, and safety guidance
src/acmk/                       Typed public Python SDK
docs/                           Tutorials, reference, and compatibility policy
schemas/                        Versioned SDK-owned contracts
examples/                       Read-only and dry-run-first Python examples
modeling/                       Original model sources, exports, metadata, and provenance
tools/blender/                  Scripted model generator and semantic Blender validator
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
acmk sdk-info
acmk doctor
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

The static validators run in Windows and Linux CI. macOS is best-effort rather than part
of the current test matrix. Automatic Steam discovery, redirected Windows Documents,
Blender discovery, and the live in-game workflow are Windows-focused.

For Codex, ask the standard `skill-installer` to install path
`skills/ancient-cities-modding` from `anubissbe/ac-modding-kit`, then restart Codex so
the skill is discovered. Invoke it as `$ancient-cities-modding`. Start each task with:

```powershell
acmk --json discover
```

The tools do not install or publish Workshop items automatically: review generated
output before copying it into a local mod directory or uploading it through Steam.

## Python SDK

```python
from acmk import AncientCitiesSDK, ValidationProfile

sdk = AncientCitiesSDK()
current = sdk.discover()
print(current.game_semver, current.steam_build_id, current.game_version)

project = sdk.open_project(r"C:\mods\my-project")
report = project.validate(ValidationProfile.AUTHORING)
print(report.to_dict())
```

The public API includes typed game/version identifiers, lossless UTF-16 documents,
manifest scans/specifications, exact `AncientPath` values, project configuration,
discovery, doctor checks, authoring/release profiles, skeleton import, runtime-test
records, deterministic staging, and offline knowledge search. `acmk/py.typed` enables
editor and type-checker support.

Read the [SDK guide](docs/sdk.md), [first safe mod tutorial](docs/tutorials/first-safe-mod.md),
[support matrix](docs/reference/support-matrix.md), and
[compatibility policy](docs/compatibility-policy.md). Maintainers also have a
[release checklist](docs/releasing.md).

## Structured projects

```text
my-project/
  acmk.toml
  src/                    # Index.art, Thumbnail.jpg, Ancient/... runtime files
  assets-src/             # Blender and other authoring sources; never packaged
  .acmk/                  # local fingerprints and sanitized reports
  dist/workshop/          # isolated Index.art, Thumbnail.jpg, Mod.zip
```

Import a skeleton produced by the current game. This previews without writing:

```powershell
acmk project import "<Documents>\Uncasual Games\Ancient Cities\Mod\MySkeleton" `
  "C:\mods\my-project" --id my-project
```

Add `--apply` only after reviewing the plan. Use `acmk project configure` to record the
version, license, contact, and provenance review. `configure`, `record-test`, and `stage`
all preserve the same preview-first rule. Staging never deploys to the game and never
publishes to Steam; changing runtime source after a recorded test invalidates release
readiness. Configuration rewrites return a backup path and use a canonical layout, so keep
custom notes in documentation rather than unsupported `acmk.toml` keys or comments.

Release checks require the chosen license identifier and contact details to appear in the
manifest Description or Content as well as the project metadata. These fields and a
`reviewed` provenance status are author attestations; verify the underlying rights yourself
and repeat the information in the manual Workshop listing.

## Starter models

The [modeling guide](modeling/README.md) defines the source, export, texture, provenance,
and validation contract for the original starter shelter, plant, and resource. Their
reference toolchain is Blender 5.2.0 LTS, pinned to an official portable archive and
SHA-256 digest.

The pack includes a scripted generator plus a Blender-side validator that reopens all
source files and round-trips every FBX export. The dedicated model workflow downloads only
the exact pinned official archive after verifying its digest.

Model binaries are repository-source content and are intentionally not installed by the
lightweight Python package; clone or download the repository when authoring models.

These assets are intentionally marked `runtime_tested = false`. They contain no game or
Workshop material and are not complete gameplay mods. Static checks can verify file shape,
metadata, and integrity, but only an explicitly authorized test in the current game can
establish runtime compatibility.

## Validation checklist

Before sharing a mod:

1. Verify provenance for every file; exclude game and third-party Workshop assets.
2. Validate paths, expected structure, and UTF-16LE game-facing text.
3. Test on a disposable save with the current Steam build.
4. Restart the game and repeat the test from a clean launch.
5. Document the build, test date, dependencies, known conflicts, save impact, and
   achievement impact.

For model contributions, also update the asset manifest, semantic report, preview, and
SHA-256 manifest. Keep Blender and FBX files compact; this repository does not currently
use Git LFS.

Passing toolkit checks is not proof of in-game compatibility. Only a clean launch on the
recorded build, a disposable save, and a relevant log review can establish runtime
compatibility.

## Community

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change.
- Ask usage questions through [GitHub Discussions](https://github.com/anubissbe/ac-modding-kit/discussions)
  or the [Ancient Cities Workshop discussions](https://steamcommunity.com/workshop/discussions/18446744073709551615/?appid=667610).
- Report security concerns according to [SECURITY.md](SECURITY.md).
- Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Code and original project documentation are available under the [MIT License](LICENSE).
That license does not grant rights to *Ancient Cities*, Steam, or third-party content.

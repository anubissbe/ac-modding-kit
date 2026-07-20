# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) where
practical.

## Unreleased

### Added

- Typed `acmk` Python SDK with an explicit public API and PEP 561 marker.
- Versioned `acmk.toml` project model and JSON schemas for SDK-owned contracts.
- Atomic import of current, game-generated loose mod skeletons.
- Evidence-backed `observed-consensus` reconciliation for the audited Ancient Cities
  1.9.3 / Steam build 23915225 / GameVersion 22 Generic root layout, without copying or
  mislabelling Workshop content.
- Separate runtime source, authoring asset, local state, and Workshop staging paths.
- Authoring and release validation profiles with compatibility, provenance, contact,
  runtime-test, and authoring-file checks.
- Manual runtime-test recording that stores only a log hash, sanitized summary, and
  deterministic runtime-source fingerprint.
- Optional pre-candidate warning baselines for `project record-test`; exact recurring base
  warnings may be discounted while new warnings and all errors remain release blockers.
- Dry-run-first, backed-up project configuration updates and provenance review metadata.
- Atomic, deterministic Workshop staging without game deployment or Steam publication.
- Offline typed knowledge-base reading and deterministic search.
- `doctor`, `sdk-info`, `knowledge`, and structured `project` CLI commands.
- Python API guide, first-safe-mod tutorial, support matrix, schemas, and examples.
- Strict mypy checks and isolated wheel/resource/CLI smoke tests.
- Original Blender/FBX starter-model contracts for a building, plant, and resource.
- Typed standalone building specifications and atomic, dry-run-first scaffolds with ART/LOC,
  manifest, model, icon, location-mask, dependency, and current-base reference validation.
- Explicit standalone location-mask binding, case-unambiguous asset contracts, bounded TGA
  packet validation, and distinct engine-reference versus mod-relation result fields.
- Per-asset rights, provenance, compatibility, output, and runtime-test metadata.
- Static model-asset integrity tests, Blender/FBX semantic validation, and a path-filtered
  GitHub workflow using a checksum-pinned official Blender archive.

### Changed

- Package version advances to `0.2.0a1`; existing CLI commands and JSON remain available.
- New SDK CLI commands emit a versioned JSON envelope in explicit `--json` mode.
- Document Blender binary handling, backup exclusions, and the initial no-LFS policy.
- Render a default Generic manifest `Content` node without a `Value` line, matching every
  audited current Generic exemplar; explicit content values remain supported.

### Security

- Enforce exactly one UTF-16LE BOM and ASCII-only numeric game/Steam identifiers.
- Reject ambiguous manifest mutation, unsafe root casing, engine-reference confusion,
  payload-root symlinks, build-output collisions, and non-empty initialization targets.
- Bind observed-consensus evidence to the exact root manifest, provide a backed-up refresh
  path after canonical metadata changes, and reject linked or escaping state-backup paths.

### Fixed

- Generate standalone building `Index.en.loc` files with the Ancient Cities 1.9.3
  runtime-proven UTF-16LE BOM, LF-only line endings, and no terminal newline.
- Keep default SDK CLI errors as unwrapped pretty JSON; reserve versioned envelopes for
  explicit `--json` output.

## 0.1.0 - 2026-07-19

### Added

- Initial community-ready project structure.
- Ancient Cities modding skill, validation tools, and synthetic tests.
- Contribution, security, governance, support, and automation policies.

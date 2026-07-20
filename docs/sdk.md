# Python community SDK

Status: **alpha**. SDK API, report-envelope, and project schema versions are `1`.
The latest runtime-test evidence schema is `2`; release validation continues to accept
existing version `1` records.

ACMK is an unofficial, standard-library-only Python SDK around Ancient Cities' publicly
observable data and asset mod interface. It is not an engine SDK and does not invent a
DLL, C#, BepInEx, Harmony, or arbitrary-code plug-in interface.

## Design boundary

The installed game, a skeleton created through **Mods > Create**, and `Log.txt` remain
the runtime specification. The SDK deliberately avoids a universal `.art` schema: it
preserves unknown structures and exposes targeted manifest operations instead.

The six independent version axes are:

1. Python package version, such as `0.2.0a1`;
2. SDK API version;
3. machine-readable report-envelope schema version;
4. `acmk.toml` project schema version;
5. sanitized runtime-test evidence schema version; and
6. game semantic version, Steam build, content hash, and internal `GameVersion`.

## Quick start

```python
from acmk import AncientCitiesSDK, ValidationProfile

sdk = AncientCitiesSDK()
snapshot = sdk.discover()
print(snapshot.game_semver, snapshot.steam_build_id, snapshot.game_version)

project = sdk.open_project(r"C:\mods\my-project")
report = project.validate(ValidationProfile.AUTHORING)
for issue in report.issues:
    print(issue.severity, issue.code, issue.message)
```

All write-capable operations discover protected game, Workshop, and user-cache paths.
They default to a plan or dry run and reject symlinks, traversal, case collisions, and
unexpected overwrites.

## Structured project

```text
my-project/
  acmk.toml
  src/
    Index.art
    Thumbnail.jpg
    Ancient/...
  assets-src/          # Blender and other authoring sources; never packaged
  .acmk/               # local fingerprints and reports; Git-ignored
  dist/workshop/       # isolated Index.art, Thumbnail.jpg, Mod.zip
```

`acmk.toml` records licensing/contact status, skeleton origin, runtime-test status,
save/achievement impact, provenance review notes, relationships, and the exact game
compatibility fingerprint.
The JSON representation of its parsed structure is versioned in
`schemas/acmk-project-v1.schema.json`.
The SDK owns this file: unknown keys are rejected so they cannot disappear during a
rewrite. Write operations serialize the canonical layout and may remove comments; their
results expose the backup path so the exact previous file remains recoverable.

## Standalone building authoring

`BuildingSpec`, typed model/stage bindings, and `standalone_building_builder` provide a
dry-run-first scaffold for a new building directory. The preflight covers the root manifest,
UTF-16LE ART/LOC output, the distinct ART and runtime-proven building-LOC newline layouts,
exact local file references, current base-reference anchors, FBX headers, localization
markers, the 128x128 RGBA icon, the grayscale location mask, and mod relations. Read the
[standalone building guide](standalone-buildings.md) for the complete contract and example.

The typed result reports `engine_references`, `mod_dependencies`, and `mod_conflicts`
separately; `BuildingSpec.index_path` is the exact generated ART definition path.

This workflow is an experimental `community-draft`, not a complete engine SDK. It never
deploys or launches the game, and it cannot replace Blender validation or a disposable-save
runtime test.

## Import the canonical skeleton

Create an empty generic or language mod in the current game's Mods menu. Import that
non-numeric loose folder instead of starting from an old sample:

```powershell
acmk project import "<Documents>\Uncasual Games\Ancient Cities\Mod\MySkeleton" `
  "C:\mods\my-project" --id my-project
```

This only previews. Add `--apply` after reviewing the paths. The importer validates the
skeleton, records hashes without storing its private absolute source path, and copies it
atomically into a new authoring project.

If the current Generic creator does not produce a usable folder, ACMK has a narrower,
honestly labelled fallback for exact builds whose Generic root layout has been independently
audited:

```powershell
acmk project reconcile-consensus C:\mods\my-project
acmk project reconcile-consensus C:\mods\my-project --apply
```

The first command is a write-free preview. The applied operation changes
`community-draft` to `observed-consensus`, normalizes only `src/Index.art`, stores a
sanitized profile record in `.acmk/import.json`, and resets runtime status to `untested`.
It never copies Workshop content and never claims that the game generated the skeleton.
Release validation requires the exact supported compatibility fingerprint, profile record,
Generic manifest structure, and a fresh passing runtime test. A game update makes the
profile unsupported until a new audit is added.

The evidence record binds the complete current root manifest. If a reconciled project later
changes canonical Description, Changelog, Content, or Steam ID metadata, release validation
will stop until `reconcile-consensus` is previewed and applied again. That refresh preserves
the canonical metadata, backs up the configuration and manifest under `.acmk/backups`,
updates the evidence hash, resets runtime status, and therefore requires a new runtime test.
Legacy Date and Version nodes are outside the audited seven-field profile and are rejected
before an observed-consensus manifest is changed.

## Draft builder

The typed `DraftProjectBuilder` can create synthetic or experimental projects while a
game-generated skeleton is unavailable. Such projects begin as `community-draft`; release
validation refuses them until they are either rebased onto a current game-generated
skeleton or reconciled through one supported exact-build observed-consensus profile.

`AncientPath`, `GameVersion`, `SteamModId`, `ManifestSpec`, `Utf16TextDocument`, and
`ManifestDocument` provide validated value objects. ART/LOC generation always uses exactly
one UTF-16LE BOM. Engine references such as `~/`, `/System/`, and `../` remain opaque and
are never resolved as files.

## Validation and staging

```powershell
acmk project check C:\mods\my-project --profile authoring
acmk project configure C:\mods\my-project --license MIT `
  --contact "https://github.com/example" --provenance reviewed `
  --provenance-notes "All runtime assets are original and covered by MIT." --apply
acmk project record-test C:\mods\my-project --log "<user-root>\Log.txt" `
  --result passed --save-impact new-save-recommended --achievement-impact disabled `
  --save-type new-disposable --clean-launch --apply
acmk project check C:\mods\my-project --profile release
acmk project stage C:\mods\my-project
```

Every write-capable SDK command remains a preview until `--apply` is supplied. The runtime
record stores only a hash and summary of the selected log, never its raw contents or private
absolute path. The selected log must remain outside the project tree. The record binds the
test to the operating system, toolkit and exact game build plus a deterministic fingerprint
of every runtime source file, so later edits invalidate release readiness. Claiming
`none-observed` save impact requires a test with an existing disposable save.

If the unmodded game emits a reproducible warning, save a separate clean-launch log before
enabling the candidate and pass it with `--baseline-log`. ACMK removes timestamps, compares
warning lines as an exact occurrence-counted set, and records both hashes plus the sanitized
differential. The baseline must identify the same game version and must not enable the tested
mod. New warning text, excess duplicate warnings, and every runtime error or failure remain
blocking. Raw logs and private absolute paths are still excluded from the project. Warning-free
records keep the v1 evidence format; supplying a baseline selects v2.

Staging creates an isolated Workshop directory; it never deploys to the game and never
uploads to Steam. Release validation additionally requires resolved license/contact data in
both `acmk.toml` and the manifest's distributed Description or Content, a game-generated
skeleton or valid observed-consensus evidence, a current build fingerprint, no authoring
files in `src/`, reviewed provenance notes, and a recorded successful runtime test.
`--license` and `--provenance reviewed` are human attestations, not automated proof of
rights. Repeat the contact and license in the manual Workshop listing before publication.

## Offline knowledge base

The audited Markdown knowledge ships inside the wheel and is available without network
access:

```python
from acmk import read_knowledge, search_knowledge

print(read_knowledge("format-and-layout").text)
for hit in search_knowledge("UTF-16LE"):
    print(hit.topic.id, hit.line_number, hit.excerpt)
```

CLI equivalents are `acmk knowledge list`, `read`, and `search`.

## Compatibility promise

See [compatibility-policy.md](compatibility-policy.md). The original commands and JSON
fields remain available. New SDK commands use a versioned envelope when `--json` is passed;
their default pretty output is the unwrapped command payload. Static validation proves tool
contracts only; only an authorized clean game launch, disposable save, and relevant log
review can establish runtime compatibility.

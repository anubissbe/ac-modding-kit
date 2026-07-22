# Python community SDK

Status: **alpha**. SDK API, report-envelope, and project schema versions are `1`.
The latest runtime-test evidence schema is `3`. Versions `1` and `2` remain readable as
legacy evidence, but cannot satisfy release validation until the test is explicitly re-recorded
as v3; ACMK never silently upgrades evidence.

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
  --tested-source "<Documents>\Uncasual Games\Ancient Cities\Mod\MyLooseMod" `
  --result passed --save-impact new-save-recommended --achievement-impact disabled `
  --save-type new-disposable --save-persistence manual-save-reload-passed `
  --clean-launch --apply
acmk project check C:\mods\my-project --profile release
acmk project stage C:\mods\my-project
```

Every write-capable SDK command remains a preview until `--apply` is supplied. `--tested-source`
must name the loose mod root that was actually enabled; it is never inferred from project `src`.
The v3 fingerprint covers exact `Index.art`, `Thumbnail.jpg`, and every file below `Ancient/`.
The only excluded entry is an empty root `Mod.hms`, which the game may manage; a non-empty
`Mod.hms`, another root entry, wrong case, link, or non-regular file is rejected. The evidence
record stores the fingerprint but not the tested root's private absolute path. Release validation
recomputes the same scoped fingerprint for canonical `src` and blocks staging when it differs
from the tested loose root.

The record stores only a hash and summary of the selected log, never its raw contents or private
absolute path. The selected log must remain outside the project tree. Evidence also binds the test
to the operating system, toolkit, exact game build, save type, and explicit save-persistence
attestation. Passing `new-disposable` and `existing-disposable` evidence requires
`manual-save-reload-passed`; `no-save` requires `not-applicable`. `failed` and `not-tested` can
describe unsuccessful/incomplete save persistence in a failed runtime record. Claiming
`none-observed` save impact still requires a test with an existing disposable save.

For a warning differential, pass a distinct clean-launch or pre-save/reload log with
`--baseline-log`. The same tested mod or combined enabled-mod set may already be present in that
baseline; this supports one canonical launch followed by manual save, full exit, restart, and
reload evidence. ACMK removes timestamps and the engine's leading `Warning - [n]` occurrence
ordinal, then compares normalized warning-signature membership and records both hashes plus the
sanitized differential. Repeated occurrences of an allowed baseline signature do not block a
passing test. The baseline must identify the same game version. New warning signatures and every
runtime error or failure in the candidate log remain blocking—baseline errors are never
subtracted. Raw logs and private absolute paths are still excluded from the project.

All new records use v3, with or without a warning baseline. Existing v1/v2 files and the legacy
v2 occurrence-counted algorithm remain parseable for diagnostics, but release validation emits
`RELEASE_RUNTIME_EVIDENCE_MIGRATION_REQUIRED`; explicitly run `record-test` with
`--tested-source` and `--save-persistence` to replace them.

When `--achievement-impact disabled` is selected and the tested mod is enabled, ACMK also
discounts Ancient Cities' exact normal notification
`Warning - This enabled Mod has *.art files that disables Achievements: [<id>] (<project name>)`.
The project name must match exactly. The original log remains bound by its hash, while this one
expected notification is excluded from the actionable warning count. A different title, altered
message, any other new warning, and every error or failure still block a passing record; the same
rule is applied before an optional baseline differential.

Staging creates an isolated Workshop directory; it never deploys to the game and never
uploads to Steam. Release validation additionally requires resolved license/contact data in
both `acmk.toml` and the manifest's distributed Description or Content, a game-generated
skeleton or valid observed-consensus evidence, a current build fingerprint, no authoring
files in `src/`, reviewed provenance notes, and a recorded successful runtime test.
`--license` and `--provenance reviewed` are human attestations, not automated proof of
rights. Repeat the contact and license in the manual Workshop listing before publication.

## In-game publisher and Workshop identity boundary

The SDK's deterministic staged `Mod.zip` is an inspection artifact, not a promise about the
game's packer. In the audited 1.9.3 client, the in-game flow selected the non-numeric loose
`Index.art`, `Thumbnail.jpg`, and `Ancient/**`, then generated `%TEMP%\ACZipMod\Index.art`,
`Thumbnail.jpg`, and `Mod.zip`. The temporary directory persisted after a run and the generated
ZIP was not byte-identical to the deterministic SDK ZIP. Treat it as potentially stale: before
the final action, compare its time, identity, thumbnail, complete ZIP entry inventory, and
per-entry hashes to the selected loose root. Never copy it or the SDK ZIP into canonical `src`.

The audited green upload arrow opened a **Yes/No** modal without a details or visibility editor.
Before **Yes**, confirm the active Steam account is the intended publisher and present a
time-limited, single-use packet for one action on one mod. It must identify the loose input and
fresh generated package hashes, app/item identity, and UI visibility state; if no selector is
shown, record that fact and the intended result. There is no batch authorization. The SDK does
not inspect account credentials and does not click or upload anything.

Use `project publish-packet` immediately before that modal is confirmed:

```powershell
acmk project publish-packet C:\mods\my-project `
  --candidate-root "<user-root>\Mod\MyLooseMod" --candidate-kind loose `
  --action publish --visibility public --visibility-control not-exposed `
  --account-preflight-passed --generated-package-root "$env:TEMP\ACZipMod" `
  --valid-minutes 15
```

It requires release-ready canonical source, checks persistent `.acmk/workshop.json`, accepts
only exact canonical manifest bytes or the exact first-publish removal of both complete
`GameVersion` and `SteamModId` blocks, inventories every loose input, and optionally proves each
uncompressed member of the game ZIP. The packet records `single_use=true` and
`authorization_recorded=false`; it has no upload path. Rerun the CLI immediately before the
confirmation. Python callers holding the packet can call `PublishPacket.assert_active()` to
check time and re-hash every candidate/generated-package input.
For `--action update`, also supply `--target-ownership-verified` after confirming in Steam that
the item still exists and belongs to the active account. No account name or identifier is stored.

When a PublishedFileId belongs to another account or no longer exists, do not mutate the old
project back to `0,0`. Preserve it as an immutable predecessor. After current Steam ownership,
existence, and log checks establish the condition, make a separately named sibling successor
with a new project id, non-numeric loose folder, `SteamModId 0,0`, and fresh provenance,
runtime/save/reload, release, stage, and publication evidence. In the dated 2026-07-22 incident,
in-game Error 9 corresponded first to the exact log result
`Failed to initialize build on server (Access Denied)` for a wrong-owned item and later to
`Getting Workshop info ... failed : File Not Found` after deletion. These are not universal
Error 9 definitions.

After a new Publish succeeds, fully exit the game and read the same live root manifest. Verify
that the game restored the current `GameVersion` and wrote the assigned nonzero `SteamModId`,
then match it to successful content, preview, and final-completion log lines and the remote item.
Synchronize only those verified fields into the matching successor's canonical manifest and
Workshop state. Do not copy the complete live or temporary manifest: changing canonical
`Index.art` invalidates its observed-consensus evidence, runtime-source fingerprint, and staged
output until the documented reconcile, retest, release-check, and restage sequence is completed.

After those checks, preview and then apply the narrow identity reconciliation:

```powershell
acmk project sync-workshop-id C:\mods\my-project `
  --from-live "<user-root>\Mod\MyLooseMod" --visibility public `
  --predecessor-id 1234567890,0
# Review the dry run, then repeat with --apply.
```

The SDK never replaces a different nonzero ID or resurrects a deleted predecessor. It snapshots
canonical and live bytes, rechecks them immediately before writing, stores backups below
`.acmk/backups`, writes `.acmk/workshop.json`, and invalidates runtime readiness only for an
actual identity change.

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

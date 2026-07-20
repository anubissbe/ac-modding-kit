# Standalone building scaffolds

`BuildingSpec` provides a typed, deliberately narrow authoring contract for a building
that receives its own `Ancient/Entity/Local/Building/<Identifier>` directory. The current
base loader discovers such a directory without editing a central building list. This is
an observed v1.9.3 behavior, not a universal engine schema.

The scaffold is always labelled `community-draft`. It is suitable for isolated authoring
and static validation, but release validation will reject it until it has either been
rebased onto a current **Mods > Create > New generic** skeleton or passed the SDK's
evidence-backed `reconcile-consensus` route for an explicitly supported exact build. A
fresh clean runtime test is required after either route. The builder never deploys,
launches the game, or uploads to Steam.

## Minimal typed example

```python
from pathlib import Path

from acmk import (
    AncientCitiesSDK,
    BuildingAssetPath,
    BuildingModel,
    BuildingSpec,
    ConstructionStage,
    DecayStage,
    EngineReference,
    GameVersion,
    ManifestSpec,
)

sdk = AncientCitiesSDK()
current = sdk.discover()
if current.game_version is None:
    raise RuntimeError("The installed game's internal GameVersion was not discovered")

stick_material = EngineReference(
    "~/Entity/Local/Resource/List/Stick/Asset/AsMaterial/Material"
)
stick_resource = EngineReference("~/Entity/Local/Resource/List/Stick/Entity")

spec = BuildingSpec(
    identifier="AuthorBranchHut",
    display_name="branch hut",
    plural_name="branch huts",
    description="A compact dwelling made from original branch-work models.",
    preview_model=BuildingAssetPath("Blueprint.fbx"),
    default_models=(
        BuildingModel(
            "Struct", BuildingAssetPath("Struct_Default.fbx"), stick_material
        ),
    ),
    construction_stages=(
        ConstructionStage(
            "00-Labour",
            None,
            10,
            (
                BuildingModel(
                    "Struct", BuildingAssetPath("Struct_Build_00.fbx"), stick_material
                ),
            ),
        ),
        ConstructionStage(
            "01-Stick",
            stick_resource,
            24,
            (
                BuildingModel(
                    "Struct", BuildingAssetPath("Struct_Build_01.fbx"), stick_material
                ),
            ),
        ),
    ),
    decay_stages=(
        DecayStage(
            "00-Light",
            (
                BuildingModel(
                    "Struct", BuildingAssetPath("Struct_Decay_00.fbx"), stick_material
                ),
            ),
        ),
    ),
)

manifest = ManifestSpec(
    title="Author Branch Hut",
    description="Original assets. License and current author contact belong here.",
    changelog="Initial authoring draft",
    game_version=GameVersion(current.game_version),
)

builder = sdk.standalone_building_builder(
    Path("work") / "author-branch-hut",
    project_identifier="author-branch-hut",
    manifest=manifest,
    building=spec,
)
for filename in (
    "Blueprint.fbx",
    "Struct_Default.fbx",
    "Struct_Build_00.fbx",
    "Struct_Build_01.fbx",
    "Struct_Decay_00.fbx",
    "Icon.tga",
    "LocationMask.tga",
):
    builder.add_asset_file(filename, Path("original-assets") / filename)
builder.set_thumbnail_file(Path("original-assets") / "Thumbnail.jpg")

report = builder.validate()
report.raise_for_errors()
plan = builder.plan()
print(plan.preview().to_dict())  # no files are written
# result = plan.apply()          # explicit authoring write, still no game deployment
```

Construction and decay entries are complete visual snapshots, not inferred deltas. A
construction resource of `None` renders the empty resource entry used by current labor or
excavation exemplars. Resource counts, ordering, models, capacity, bounds, door placement,
and knowledge requirements still need an isolated in-game test. ACMK accepts construction
counts from 1 through 1,000,000 as a defensive serialization limit; that range is not an
engine guarantee.

`spec.index_path` identifies the generated `Ancient/.../Index.art` definition. Scaffold
results keep load-order relations distinct from engine-node references: use
`mod_dependencies`, `mod_conflicts`, and `engine_references` respectively.

## Checks performed before planning

| Area | Static check | Boundary |
| --- | --- | --- |
| Root manifest | `Generic`, `SteamModId` `0,0`, live `GameVersion`, and a valueless `Content` node matching current Generic layout | Release contact, license, and provenance remain author attestations |
| Entity identity | Safe ASCII identifier and no case-insensitive base-building collision | Loader behavior must still be tested after game updates |
| ART | Deterministic CRLF with a terminal CRLF, exactly one UTF-16LE BOM, required entity/location-mask blocks, and the exact literal file set | ACMK does not claim a complete ART grammar |
| Building LOC | Runtime-proven v1.9.3 layout: LF-only, no terminal newline, exactly one UTF-16LE BOM, and the required localization markers | Re-test this byte contract after a game update |
| Engine references | Typed external-reference syntax plus an exact-case current base-file anchor when available | Nodes inside that file remain engine-defined and runtime-verified |
| Models | Every role has an exact-case, case-insensitively unambiguous FBX path and a binary or ASCII FBX signature | Blender import, axes, materials, animation, and rendering need specialist and runtime tests |
| Icon | Valid 128x128, 32-bit true-color TGA; raw or RLE with dimensions bounded before packet validation | Visual quality is a human review |
| Location mask | Exact `LocationMask.tga`, explicit ART binding, valid 8-bit grayscale TGA, dimensions equal `location_size`, with dimensions bounded before packet validation | Placement and pathfinding require a disposable save |
| Mod relations | Case-insensitive uniqueness and no dependency/conflict overlap; values enter `acmk.toml` | Installed load-order resolution is a separate conflict check |

Unknown extra assets are reported as notices. Missing files, wrong case, malformed TGA/FBX
headers, manifest mismatches, and identifier collisions block planning. A successful plan
still reports `BUILDING_MODEL_RUNTIME_UNVERIFIED` because static checks cannot prove that
the game can construct, render, enter, use, decay, or remove the building.

Only original or appropriately licensed assets belong in the scaffold. Never copy base-game
or Workshop models, icons, masks, ART, LOC, or other content into a distributed mod.

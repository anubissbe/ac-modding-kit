# Original starter models

This directory contains three small, original authoring examples for Blender and
Ancient Cities: a building, a plant, and a resource. They demonstrate a conservative
asset workflow without copying files from the game or Steam Workshop.

The assets are repository content and are not bundled into Python package artifacts. Clone
or download the repository when model files are needed.

> [!IMPORTANT]
> These are authoring examples, not finished gameplay mods. Their manifests deliberately
> set `runtime_tested = false`. A valid Blender file, FBX header, or static test does not
> prove that Ancient Cities can render or simulate an asset. Runtime compatibility may be
> claimed only after a clean launch against the recorded game build, a disposable save,
> and a relevant `Log.txt` review.

## Toolchain

The reference authoring tool is **Blender 5.2.0 LTS**. The plain version marker is in
[`BLENDER_VERSION`](BLENDER_VERSION), while [`toolchain.lock.json`](toolchain.lock.json)
pins the official Windows x64 portable archive and its SHA-256 digest. Do not replace the
lock with a floating `latest` download or bypass checksum verification.

Blender is not vendored by this repository. Local users may use a verified Blender 5.2.0
installation. Automation that downloads Blender must use the exact official URL and digest
from the lock file.

## Regeneration

From the repository root, run the reviewed generator with the pinned Blender version:

```text
blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tools/blender/generate_all.py
```

The command regenerates all three source files, exports, textures, previews, semantic
reports, and checksum manifests in place. Review every resulting binary size, preview,
report, and checksum change before committing. The generator uses original primitives and
does not read the Ancient Cities installation or Workshop cache.

## Asset layout

Each asset follows the same contract:

```text
<category>/<asset-id>/
  README.md
  asset.toml
  source/*.blend
  exports/*.fbx
  textures/C.tga
  textures/N.tga
  textures/T.tga
  textures/O.tga
  preview.png
  report.json
  checksums.sha256
```

- `source/` contains the editable Blender source. It is intentionally stored uncompressed
  so normal repository checks can scan it for private paths and unexpected provenance.
- `exports/` contains binary FBX exports; filenames and internal mesh names must match the
  eventual `.art` references exactly, including case.
- `textures/` uses the Ancient Cities channel convention: colour/mask (`C`), OpenGL-style
  normal/gloss (`N`), thickness (`T`), and ambient occlusion (`O`).
- `report.json` is a machine-readable semantic inspection report.
- `checksums.sha256` covers every generated source, export, texture, preview, and report.

Generated outputs may temporarily be absent while a generator is being developed. Static
tests skip an entirely absent output set, fail a partially present set, and fully validate a
complete set. Release validation must set `ACMK_REQUIRE_MODEL_OUTPUTS=1` so missing outputs
are failures.

## Authoring contract

- Work in metres at final size, with the origin on ground level.
- Apply location, rotation, and scale before export.
- Export meshes only, triangulated, with smoothing and explicit UVs.
- Blender source scenes are Z-up. Export binary FBX with an explicit Y-up conversion.
  Forward-axis behaviour remains subject to an in-game test and must not be inferred from
  inconsistent legacy exporter metadata.
- Keep textures external; do not embed them in FBX files.
- Use only original geometry and textures. Never trace, convert, bundle, or modify game or
  Workshop assets for these examples.
- Do not add scripts, drivers, linked libraries, or private absolute paths to `.blend` files.

The public modelling guides provide the conceptual baseline for
[general models](https://ancient-cities.com/docs/13%20-%20How%20to%20model.html),
[buildings](https://ancient-cities.com/docs/04%20-%20How%20to%20model%20a%20building.html),
[plants](https://ancient-cities.com/docs/12%20-%20How%20to%20model%20a%20plant.html), and
[resources](https://ancient-cities.com/docs/01%20-%20How%20to%20model%20resources.html).
The installed v1.9.3 data remains the authority when older documentation differs.

## Licensing and provenance

All three starter assets are original project work licensed under the repository's
[MIT License](../LICENSE). Every `asset.toml` records the author, public contact route,
creation method, toolchain, compatibility baseline, AI-assistance disclosure, and explicit
absence of game and Workshop content. Contributors must update that metadata and the
checksums whenever an asset changes.

The repository intentionally does not use Git LFS for these compact starter assets. Keep
each committed binary small and generated from reviewable source. Reconsider LFS or GitHub
release assets before adding high-resolution or frequently changing binaries that would
materially increase clone size.

## Validation

Run the repository's static model checks with:

```powershell
python -m pytest tests/test_model_assets.py
```

Regenerate and semantically reopen every `.blend` and FBX with the pinned Blender build:

```powershell
blender --background --factory-startup --disable-autoexec --python-exit-code 1 `
  --python tools/blender/generate_all.py
blender --background --factory-startup --disable-autoexec --python-exit-code 1 `
  --python tools/blender/validate_models.py
```

The generator strips Blender path and timestamp metadata from previews before checksums are
written. It also disables backup copies, saves inspectable uncompressed sources, and
overwrites Blender's startup file-browser directory before saving. Manual GUI saves can
serialize a contributor's local path or enable compression, so regenerate these starter
assets before committing and never bypass the privacy tests. The validator rejects
unexpected objects, embedded scripts, linked libraries, unapplied source transforms,
invalid LOD relationships, degenerate UV triangles, and incorrect vertex-RGBA semantics.
It also imports every FBX back into a clean Blender scene.

Geometry and metadata generation are repeatable with the pinned toolchain, but Blender adds
an FBX creation timestamp and file identifier. Regenerated FBX and checksum bytes are
therefore not promised to be identical. Regenerate intentionally and review semantic reports
and previews alongside binary changes.

For a release candidate, require every output:

```powershell
$env:ACMK_REQUIRE_MODEL_OUTPUTS = "1"
python -m pytest tests/test_model_assets.py
```

After static and Blender-side checks pass, integration into an isolated mod still needs
strict `acmk` validation and an explicitly authorized in-game test. Do not deploy, launch,
or publish automatically.

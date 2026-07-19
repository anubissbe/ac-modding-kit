# Starter Plant

`starter_plant` is an original, small foliage-only authoring example. It uses the live
v1.9.3 naming pattern `LOD0` and `LOD1`, keeps its origin on the soil line, and is modelled at
real small-plant scale.

Only the alive foliage state is in scope. The public guide permits small plants to disappear
when they die, so dead, chopped, rotten, flower, and fruit meshes are intentionally absent.
The metadata records `WindNone`, which is the mode used by the current installed Nettle
example. Any more advanced wind, AO, seasonal masking, or vertex-split behaviour must be
introduced and runtime-tested separately.

Expected generated files are declared in [`asset.toml`](asset.toml): an editable Blender
source, one or more binary FBX exports, `C/N/T/O` starter textures, a preview, semantic
report, and SHA-256 manifest.

This is not a complete plant mod. Distribution, entity, instancer, localization, and other
`.art` definitions must be authored from current legal exemplars and tested independently.

License: MIT. The asset contains no Ancient Cities or Workshop geometry, textures, code, or
other content. Runtime status: **not tested**.

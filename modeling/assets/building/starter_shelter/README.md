# Starter Shelter

`starter_shelter` is an original, static building-authoring example. It is deliberately
small and symmetrical so scale, pivot, construction state, decay state, collider, and FBX
orientation problems are easy to see.

The intended source contains roles for a blueprint, collider, dark/interior volume, an
intermediate build state, an intermediate decay state, and a complete default state. The
complete form should be reused as the final representation on both progress paths. Complex
or final visual states should provide a lower-detail representation when the eventual game
definition requires it.

This directory is not a complete building mod. Current buildings also need `.art`
components, construction resources, slots, instancing, localization, and other gameplay
definitions. Those must be created from a current game-generated skeleton or current base
exemplar without redistributing proprietary files.

Expected generated files are declared in [`asset.toml`](asset.toml): one or more editable
sources in `source/`, one or more binary FBX files in `exports/`, the four standard starter
textures, a preview, semantic report, and SHA-256 manifest.

License: MIT. The asset contains no Ancient Cities or Workshop geometry, textures, code, or
other content. Runtime status: **not tested**.

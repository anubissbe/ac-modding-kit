# Starter Resource

`starter_resource` is an original resource-authoring example covering a loose item, natural
heap, ground pile, and simple carried load. It does not attempt to introduce a pack, tool,
rig, or animation set.

Every disconnected element receives one uniform split-alpha value. Multi-item roles spread
those values evenly from `254` to `0`; the three-item carried load therefore demonstrates
`254`, `127`, and `0`, while the denser heap uses intermediate values too. This follows the
documented `SPLIT` convention while keeping the behaviour easy to inspect. RGB remains a
neutral authoring colour, and the intended game-side mode is `ColorVSplit`.

Expected generated files are declared in [`asset.toml`](asset.toml): an editable Blender
source, one or more binary FBX exports, `C/N/T/O` starter textures, a preview, semantic
report, and SHA-256 manifest.

This is not a complete resource mod. Resource properties, gathering, storage, localization,
heap/pile/load instancers, recipes, and cultural availability require current `.art`
definitions and an isolated runtime test.

License: MIT. The asset contains no Ancient Cities or Workshop geometry, textures, code, or
other content. Runtime status: **not tested**.

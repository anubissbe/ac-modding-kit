# Format and layout

## Paths and lifecycle

Use these roles, discovered dynamically:

- Base content: `<game>\Ancient\Data\Ancient\...`
- Built-in examples: `<game>\Ancient\Data\Ancient\Mod\...`
- Steam source/cache: `<steamapps>\workshop\content\667610\<item-id>`
- User mods/log: `<Windows Documents>\Uncasual Games\Ancient Cities\Mod` and `Log.txt`
- Project source: a dedicated Codex workspace directory

Never work directly in the Steam cache or numeric extracted user folders. Steam/game regeneration can overwrite them.

Modern Workshop item layout:

```text
<item>/
  Index.art
  Thumbnail.jpg
  Mod.zip
    Ancient/...
```

Loose local development uses the same root metadata/preview plus an `Ancient\...` payload. The game may add an empty `Mod.hms`; treat it as game-managed and undocumented.

## Root metadata

Current manifests use UTF-16LE with BOM and normally contain:

- `Changelog` (`String`)
- `Content` (`String`, often empty; language mods point at their language node)
- `Description` (`String`)
- `GameVersion` (`String`; internal revision such as `22`, not semantic version `1.9.3`)
- `SteamModId` (`U32x2`; use `0,0` before first publication)
- `Title` (`String`)
- `Type` (`String`)

Legacy manifests may also contain `Date`, `Enabled`, or `Version`. Preserve unknown valid nodes. Observed type values are `Generic`, `Language`, `Landmark`, `Plant`, `Cheat`, and `Texture`; prefer `Generic` unless a current game-generated skeleton specifies another type.

The game explicitly validates presence of Title, Description, Changelog, and GameVersion. Keep all standard nodes and give Title, Description, GameVersion, and Type non-empty values. Use a meaningful Changelog even though some older published examples left its value empty.

## `.art` and `.loc`

- Encode textual `.art` and `.loc` as UTF-16 little-endian with `FF FE` BOM.
- Preserve the original newline convention and byte round-trip.
- Do not globally reformat `.art`; some files contain very large inline payloads or engine-specific data.
- Mirror the exact base path and filename to override a definition. Use a new exact-case path to add a new entity.
- Treat `~/`, `/System/...`, and `../` as engine node references, not filesystem paths.
- Resolve literal `File:"...ext"` references relative to the containing definition unless a current exemplar proves otherwise.
- Match case exactly even on Windows. ZIP and the engine's virtual namespace can expose case mistakes.

Localization files use `#<node-path>` markers followed by their value or script. Use exactly one leading `#`, no invisible prefix, and no accidental whitespace in the path. Retain UTF-16LE BOM. Use ASCII folder/identifier names unless a current working example proves a wider character set safe.

## Assets

Locally proven formats include TGA, PNG, JPG, DDS, FBX, and WAV. Installed Workshop mods empirically demonstrate original FBX/TGA plants and more complex building assets, but no general binary plugin API.

- Create original assets or use assets with documented redistribution rights.
- Follow the dimensions, channels, filenames, material nodes, scale, orientation, and case of a current same-category exemplar.
- Use a square JPEG preview; 512 x 512 is the safest locally observed default. Do not hard-fail other square sizes without a current game error.
- Validate PNG/JPEG/WAV/FBX signatures. Treat DDS/TGA semantic validation as exemplar-driven unless a specialist tool is available.
- Discover and verify an FBX authoring tool before promising model creation. The modding-kit
  model pack pins Blender 5.2.0 LTS and includes Blender-side source/FBX validation when the
  repository checkout is available; simple headers remain insufficient.

## Load semantics

The UI states that mods at the top have preference. Any two enabled mods that provide the same `Ancient/...` path conflict; the higher item wins the whole file/path. A full old `.art` override can silently erase fields added by a game update or another mod. Prefer new entities and the smallest necessary override surface.

Any payload with `.art` disables achievements. A full restart is required. Adding, removing, changing, or reordering mods can break saves.

# Local baseline (audited 2026-07-19)

Use this only as a drift baseline. Run live discovery before every task.

## Installed build

- Steam app ID: `667610`
- Depot: `667611`, manifest `5654499374290634821`
- Build ID: `23915225`
- Game version: `1.9.3`
- Content hash: `D9BF481D195671BF9CB98274B4CFF604`
- Internal mod compatibility revision: `GameVersion:"22"`
- Common default install: `C:\Program Files (x86)\Steam\steamapps\common\Ancient Cities`
- Effective Documents folder: the Windows known-folder value; discover it dynamically
  because folder redirection and additional Steam libraries are common
- User root: `<Documents>\Uncasual Games\Ancient Cities`

Never derive Documents blindly from `%USERPROFILE%\Documents`; use the Windows known
folder so redirection is respected.

## Engine and content evidence

Treat the engine as proprietary, native, and data-driven. It is not a standard Unity, Unreal, .NET, BepInEx, Harmony, or C# plugin installation. The build contains approximately 2,109 `.art`, 4,616 `.loc`, 2,117 `.tga`, 614 `.dds`, 455 `.FBX`, 1,004 `.wav`, and GLSL-related shader files. TinyCC runtime files exist, but no public custom SDK headers or supported binary plugin interface were found.

Do not inspect executable/DLL internals. The distributed textual data, the in-game empty-mod generator, and loader logs are sufficient and contract-aligned evidence.

## Public Workshop examples reviewed

The following public items were reviewed as read-only structural examples during the
audit; this list does not disclose or define any user's current subscriptions:

- `2175125663` Landmark: StarCarr: small clean added-content example.
- `2312940890` Plant: Phyllitis Scolopendrium: educational FBX/TGA/plant example.
- `3298397416` FOODCRAFT Nuts: complex added building/resources/assets example without a compatibility warning in the audited log.
- `2326098134` Landmark: Heuneburg: an audited load produced an image error; do not treat as clean.
- `3320012613` CERAMIC Trade: has missing Mesh/Render references; use only to learn intended structure.

Several reviewed older mods are stale full overrides; some still use loose pre-ZIP
payloads. Rebase every override on the current game file.

The live configuration remains authoritative; do not publish a user's enabled-mod set
or other machine telemetry in compatibility reports without consent.

## External-tool boundary

Configuration, localization, balance, and many texture tasks need only the bundled
Python tool plus suitable user-authored assets. Creation or reliable revision of
original FBX models/animations requires Blender or an equivalent FBX authoring tool;
discover that capability live rather than assuming it is installed. A Codex skill
does not replace a 3D authoring tool.

# Steam Workshop article audit

Audited on 2026-07-19 from the complete three-page index supplied by the user:

https://steamcommunity.com/workshop/discussions/18446744073709551615/?appid=667610

Exactly 41 active topics were present: 14 official pinned guides by UncasualGames and
27 community discussions. All opening posts, visible replies, linked official HTML
guides, and reachable sample downloads were reviewed. Prefer the current installed
build, an in-game generated empty mod, and `Log.txt` whenever an older guide conflicts.

## Contents

- [Findings that govern current work](#findings-that-govern-current-work)
- [Fourteen official pinned guides](#fourteen-official-pinned-guides)
- [Official sample downloads](#official-sample-downloads)
- [Twenty-seven community discussions](#twenty-seven-community-discussions)
- [Evidence boundary](#evidence-boundary)

## Findings that govern current work

- The documented local root remains
  `Documents\Uncasual Games\Ancient Cities\Mod\<ModName>\`.
- A loose mod uses root `Index.art`, `Thumbnail.jpg`, and an `Ancient/...` payload that
  mirrors the relative path below the game's `Ancient\Data\Ancient` tree.
- Publishing/updating is performed through the green-arrow action in the Mods menu.
- Current local Workshop items use internal `GameVersion:"22"`; this is distinct from
  semantic game version `1.9.3` and Steam build ID `23915225`.
- Current textual `.art` and `.loc` files use UTF-16LE with `FF FE` BOM. Old wording
  such as “UCS-2 Little Endian with BOM” should be interpreted in that light.
- On update failures, the developer directs mod authors to the user `Log.txt`, which
  identifies mirrored files that need updating.
- Official example ZIPs are learning material, not canonical v1.9.3 templates. Rebuild
  from a current same-category base exemplar and never redistribute proprietary assets.
- The forum documents data/assets only; it provides no evidence of a supported DLL,
  C#, BepInEx, Harmony, or other binary plugin API.

## Fourteen official pinned guides

All links below are Workshop topics by UncasualGames. “Current” means the core workflow
was corroborated against the local v1.9.3 data; it does not remove the need to test.

| Guide | What it establishes | v1.9.3 assessment |
| --- | --- | --- |
| [Modify a Workshop mod](https://steamcommunity.com/workshop/discussions/18446744073709551615/3110274289481711194/?appid=667610) | Copy an item by Workshop ID and remove `GameVersion`/`SteamModId` to fork it | Core workflow current; do not copy third-party assets without rights |
| [Create a language mod](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648960165/?appid=667610) | In-game language skeleton, UTF-16 localization, `##` to `#`, preview and upload | Current; use the live skeleton and BOM |
| [TransLoc Tool v0.12](https://steamcommunity.com/workshop/discussions/18446744073709551615/3827540930024149119/?appid=667610) | Compare changed English strings between game releases | Usable; configure a fresh v1.9.3 baseline and review its PowerShell source |
| [Create a font mod](https://steamcommunity.com/workshop/discussions/18446744073709551615/3765608728350832207/?appid=667610) | BMFont `.fnt`/`_0.tga`, distance field, `Font.art`, Unicode ranges | Largely current; validate against a live font exemplar |
| [Add a river](https://steamcommunity.com/workshop/discussions/18446744073709551615/3082124889506849850/?appid=667610) | Geographic path, `Point`, `Width`, and localization | Partly stale: current river definitions also contain `Area` |
| [Plant from FBX](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258649005704/?appid=667610) | FBX export, mesh/material/texture, distribution, entity, and LOD concepts | Conceptual only; Nettle references and encoding have drifted |
| [Height-map mod](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258649000572/?appid=667610) | 16-bit uncompressed GeoTIFF, `Area`, `Bathymetry`, overlay priority | Current concept; the engine may add `Baked` |
| [Model resources](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648996311/?appid=667610) | Heap/pile/load/pack/tool states, vertex channels, textures, and LODs | Current design guidance |
| [Model a plant](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648993298/?appid=667610) | Alive/dead/chopped/rotten states, foliage/flowers/fruit, growth, LODs | Current design guidance |
| [General modelling](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648990516/?appid=667610) | Metres, local transforms, normals, vertex channels, C/N/T/O textures, binary FBX/Y-up | Current conceptual baseline |
| [Model a building](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648986645/?appid=667610) | Construction/decay steps, LODs, optional skinning/animation | Current design guidance |
| [Duplicate/replace an asset](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648977750/?appid=667610) | Mirror an effective path to override a definition/texture | Loader concept current; PurpleFern files are stale and distribution is rights-sensitive |
| [Create a landmark](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648972176/?appid=667610) | `Point`, `Year`, localized name/description, optional image | Format current; sample misspells `Landmark` as `Lanmark` in root metadata |
| [Create a mod by hand](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648954452/?appid=667610) | Root manifest/thumbnail, mirrored payload, upload action | Core layout current; old root fields are superseded by the game creator |

Official HTML mirrors exist for guide numbers `00` through `07` and `09` through
`13`; there is no linked current guide numbered `08`:

- [00 — Mod by hand](https://ancient-cities.com/docs/00%20-%20How%20to%20create%20a%20Mod%20by%20hand.html)
- [01 — Model resources](https://ancient-cities.com/docs/01%20-%20How%20to%20model%20resources.html)
- [02 — Modify Workshop mod](https://ancient-cities.com/docs/02%20-%20How%20to%20modify%20a%20mod%20from%20Steam%20Workshop.html)
- [03 — River](https://ancient-cities.com/docs/03%20-%20How%20to%20make%20a%20Mod%20to%20add%20a%20river%20to%20the%20world.html)
- [04 — Building](https://ancient-cities.com/docs/04%20-%20How%20to%20model%20a%20building.html)
- [05 — Font](https://ancient-cities.com/docs/05%20-%20How%20to%20create%20a%20Font%20Mod.html)
- [06 — Asset override](https://ancient-cities.com/docs/06%20-%20How%20to%20duplicate%20(replace)%20a%20game%20asset.html)
- [07 — Language](https://ancient-cities.com/docs/07%20-%20How%20to%20create%20a%20language%20mod.html)
- [09 — FBX plant](https://ancient-cities.com/docs/09%20-%20How%20to%20create%20a%20Mod%20plant%20from%20a%20FBX%20file.html)
- [10 — Landmark](https://ancient-cities.com/docs/10%20-%20How%20to%20create%20a%20new%20LandMark.html)
- [11 — Height map](https://ancient-cities.com/docs/11%20-%20How%20to%20create%20a%20Height%20Map%20Mod.html)
- [12 — Plant modelling](https://ancient-cities.com/docs/12%20-%20How%20to%20model%20a%20plant.html)
- [13 — General modelling](https://ancient-cities.com/docs/13%20-%20How%20to%20model.html)

## Official sample downloads

These returned HTTP 200 on the audit date. Do not vendor them in this repository.

- [BMFont configuration](https://ancient-cities.com/docs/bmfont.zip)
- [PurpleFern example](https://ancient-cities.com/docs/PurpleFern.zip)
- [Nettle example](https://ancient-cities.com/docs/Nettle.zip)
- [Cova Remigia landmark](https://ancient-cities.com/docs/CovaRemigia.zip)
- [TransLoc v0.12](https://uncasualgames.com/UG_TransLoc.zip)

Known drift: PurpleFern and Nettle include `.loc` files without the current BOM and
old entity/terrain references; CovaRemigia contains `Lanmark` typos; the river guide
omits the current `Area` field. TransLoc is a Windows PowerShell/WinForms helper whose
`MasterDir` must be configured; its license/provenance must be checked before reuse.

## Twenty-seven community discussions

| Topic | Useful evidence | Assessment |
| --- | --- | --- |
| [Authors not updating mods](https://steamcommunity.com/workshop/discussions/18446744073709551615/840628660304124416/?appid=667610) | Request to purge abandoned items | Current concern; no technical solution |
| [Assign people work](https://steamcommunity.com/workshop/discussions/18446744073709551615/764059330564765782/?appid=667610) | Gameplay request | No modding evidence |
| [Language upload very slow](https://steamcommunity.com/workshop/discussions/18446744073709551615/684116072957259940/?appid=667610) | Developer says upload uses Steam resources; retry later | Current publishing advice |
| [Adjusting pregnancy](https://steamcommunity.com/workshop/discussions/18446744073709551615/685238975203459622/?appid=667610) | Parameter question | Unanswered/undocumented |
| [Remove storage icons](https://steamcommunity.com/workshop/discussions/18446744073709551615/555745444093852967/?appid=667610) | UI request | Unanswered/undocumented |
| [Change local map size](https://steamcommunity.com/workshop/discussions/18446744073709551615/604153636037073739/?appid=667610) | Map-size question | Unanswered/undocumented |
| [Unable to update mods](https://steamcommunity.com/workshop/discussions/18446744073709551615/4634861089657539234/?appid=667610) | Developer directs authors to `Log.txt` for outdated mirrored files | Important/current |
| [Replace character model](https://steamcommunity.com/workshop/discussions/18446744073709551615/3880471364307919715/?appid=667610) | TGA override, texture-only F5 reload, normalized RGB `[0,1]` culture colour | Partly current; full model replacement unanswered; F5 is not a general mod reload |
| [More stones](https://steamcommunity.com/workshop/discussions/18446744073709551615/4293690852333414287/?appid=667610) | Old item crashed and was blocked | Superseded by a local `GameVersion=22` replacement |
| [Stonehenge](https://steamcommunity.com/workshop/discussions/18446744073709551615/4201364982094923511/?appid=667610) | Landmark request | Fulfilled by a current local v22 item |
| [Time progression and aging](https://steamcommunity.com/workshop/discussions/18446744073709551615/3820781817412814788/?appid=667610) | `Human.art` `AgeMultiplier`; `State\Game.art` `YearHistoryFactor` | Both fields exist in v1.9.3; test a new save and performance |
| [Structure decay](https://steamcommunity.com/workshop/discussions/18446744073709551615/4131556193370692686/?appid=667610) | Building `Constitution`; `ConstitutionReady` repair threshold | Fields current; old values/items still require rebasing |
| [Animal domestication](https://steamcommunity.com/workshop/discussions/18446744073709551615/4032475099158139805/?appid=667610) | Gameplay question | No modding evidence |
| [Leave starting region](https://steamcommunity.com/workshop/discussions/18446744073709551615/4032475099155426070/?appid=667610) | Gameplay question | No modding evidence |
| [More grains](https://steamcommunity.com/workshop/discussions/18446744073709551615/6266251726402411753/?appid=667610) | Production parameter question | Unanswered |
| [Create a music mod](https://steamcommunity.com/workshop/discussions/18446744073709551615/3820796859478048640/?appid=667610) | Developer says to replace mirrored `.wav` files | Likely current; take exact path/format from v1.9.3 |
| [Hungarian](https://steamcommunity.com/workshop/discussions/18446744073709551615/3436829654706397043/?appid=667610) | Links an older translation tool | Superseded by TransLoc v0.12 |
| [More gathering groups](https://steamcommunity.com/workshop/discussions/18446744073709551615/5371100420926141741/?appid=667610) | Suggests obsolete `CountLimit:"16"` | Stale: v1.9.3 uses `JobLimit`, not `CountLimit` |
| [Chinese translation failure](https://steamcommunity.com/workshop/discussions/18446744073709551615/4578439633205937492/?appid=667610) | Historical missing font support | Stale; use current language/font workflow |
| [More Food](https://steamcommunity.com/workshop/discussions/18446744073709551615/3015689818914553906/?appid=667610) | Old calorie mod | Linked item unavailable/stale |
| [Italian](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002178258648783160/?appid=667610) | Old forum/upload error | Stale; use current language guide |
| [Updates needed](https://steamcommunity.com/workshop/discussions/18446744073709551615/3002177675802810604/?appid=667610) | Early Access feature requests | No current modding evidence |
| [Temperature monitoring](https://steamcommunity.com/workshop/discussions/18446744073709551615/4149469212601964056/?appid=667610) | Hardware-overlay request | Unsupported/undocumented |
| [Farming, animals, pottery](https://steamcommunity.com/workshop/discussions/18446744073709551615/4149469212597111654/?appid=667610) | Early Access feature request | No modding evidence |
| [Resource menu separation](https://steamcommunity.com/workshop/discussions/18446744073709551615/4149469212598295169/?appid=667610) | UI request | Unanswered/undocumented |
| [French](https://steamcommunity.com/workshop/discussions/18446744073709551615/4149469212593106708/?appid=667610) | Selecting built-in French | No modding evidence |
| [Medieval-era content](https://steamcommunity.com/workshop/discussions/18446744073709551615/2971776551526025603/?appid=667610) | Developer confirms FBX/new-building support | Core capability still locally demonstrated |

## Evidence boundary

The audited forum supports `.art` balance/data, `.loc` languages, fonts, textures,
FBX plants/buildings/resources, rivers, 16-bit GeoTIFF height maps, landmarks, mirrored
WAV replacement, and some human texture/colour variants. It does not establish safe
support for arbitrary code plugins, general UI replacement, full character-model
replacement, local map-size changes, pregnancy tuning, or every production formula.

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

## Standalone-building runtime case (audited 2026-07-22)

On the same 1.9.3 / build 23915225 / `GameVersion 22` baseline, isolated loose-mod tests
established these narrow boundaries:

- building availability was observed through Culture progression plus Knowledge references and
  their XP thresholds; no direct building gate through `Year` or `HistoryRangeYear` was proven;
- a zero `ConstitutionCount` disabled the tested building's catalogue entry; a matching positive
  ones-vector was useful only as a minimal discovery smoke probe, not as release balance; and
- omitting `Requirement` and `RequirementPercent` together could isolate a suspected gate, but
  the omission was confined to a backed-up live non-numeric loose diagnostic copy. Neither field
  was removed from canonical `src` or release content.

The diagnostic bytes were not treated as the tested release candidate. Valid evidence required
restoring the live file exactly from canonical `src`, verifying its hash, and completing a final
clean launch, explicit manual save, full exit, restart, and save reload. These observations do
not prove a universal ART schema or a calendar-year availability mechanism.

## Workshop publication case (audited 2026-07-21)

Public item `3768682609`, **Mesolithic Branch Hut**, retained the same PublishedFileId through
initial publication and later updates. Its public page is
<https://steamcommunity.com/sharedfiles/filedetails/?id=3768682609>.

- Initial content uploads succeeded, but the primary preview failed with in-game Error 15 and
  Steam's exact log message `Failed to upload workshop preview file ... (Access Denied)`.
- Live app `667610` info then exposed `ufs.quota=0` and `ufs.maxnumfiles=0`. Updating content
  without the preview made the mod public and downloadable but left the square Workshop tile on
  Steam's generic placeholder. A separately added gallery image did not fill that field.
- On 2026-07-21 the publisher configuration changed to `ufs.quota=1000000000` and
  `ufs.maxnumfiles=1000`.
- The first in-game retry returned Error 2; `workshop_log.txt` identified the actual cause as
  `Failed to initialize build on server (No Connection)`. The local manifest still contained
  `SteamModId` value `3768682609,0`.
- After fully restarting Steam and using the in-game **Update** action, the user confirmed that
  the primary preview appeared on the existing public item.

This case establishes a diagnostic sequence, not universal definitions for Steam error numbers.
Always match the error to the current log, verify live `ufs` values, and preserve an existing
nonzero Workshop identity.

## Wrong-account recovery and successor publications (audited 2026-07-22)

Nine items were initially created under an unintended Steam account. Attempts to update a
still-existing item from the maintained account produced in-game Error 9 while
`workshop_log.txt` said exactly
`Upload workshop item <id> failed (Failed to initialize build on server (Access Denied) )`.
After deletion of the remote predecessor, another Error 9 attempt instead said exactly
`Getting Workshop info for item <id> failed : File Not Found`. The current log therefore
distinguished an ownership failure from a deleted/unresolvable PublishedFileId even though the
dialog number did not. These meanings are evidence for this dated incident only.

The predecessor projects, manifests, and nonzero ids were preserved unchanged. Each replacement
was built as a separately named sibling successor with a unique project identity, a non-numeric
loose folder, and `SteamModId 0,0`; it received fresh provenance, exact-source runtime/save/reload
evidence, release validation, staging, and publication state. The resulting verified mapping is:

| Mod | Immutable deleted predecessor | New public successor |
|---|---:|---:|
| Mesolithic Roasting Hearth | `3769249469` | [`3769474322`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769474322) |
| Howick Sunken-Floor House | `3769249957` | [`3769474267`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769474267) |
| Huseby Klev Birch-Pitch Hearth | `3769250418` | [`3769474212`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769474212) |
| Antrea Netmaker's Rack | `3769250934` | [`3769474151`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769474151) |
| Lepenski Vir Trapezoidal House | `3769452595` | [`3769473846`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769473846) |
| Tybrind Vig Paddle Workshop | `3769452717` | [`3769473919`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769473919) |
| La Draga Basketry Shelter | `3769452860` | [`3769473979`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769473979) |
| Franchthi Shell-Ornament Place | `3769452949` | [`3769474016`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769474016) |
| Star Carr Frontlet-Working Place | `3769453122` | [`3769474067`](https://steamcommunity.com/sharedfiles/filedetails/?id=3769474067) |

For all nine new ids, the Steam log recorded item creation, content upload, primary-preview
upload, and final `OK`. After publication, each live root manifest again contained
`GameVersion 22` plus its assigned nonzero `SteamModId`. The official Steam API returned result
`1`, visibility `0` (Public), `banned=0`, creator/consumer app `667610`, a positive content size
and manifest, and a non-empty primary preview. Unauthenticated detail pages returned HTTP 200
with the correct title and **Subscribe to download**; every remote primary JPEG byte-matched its
local `Thumbnail.jpg`; all nine appeared in the unfiltered **Most Recent** view. The user also
confirmed the publications worked. This is a 2026-07-22 verification snapshot, not a guarantee
that owners cannot later update, hide, or delete an item.

The same run showed that the game used each selected loose root to create its own temporary
`%TEMP%\ACZipMod` package. That directory persisted after publication and could therefore be
stale on a later attempt. Its game-generated `Mod.zip` was not byte-identical to ACMK's
deterministic staged ZIP even when both represented the reviewed payload. Treat the loose source
inventory as the publisher input, the fresh temporary package as ephemeral evidence, and the SDK
ZIP as an inspection artifact only.

## External-tool boundary

Configuration, localization, balance, and many texture tasks need only the bundled
Python tool plus suitable user-authored assets. Creation or reliable revision of
original FBX models/animations requires Blender or an equivalent FBX authoring tool;
discover that capability live rather than assuming it is installed. During this audit,
the official portable Blender `5.2.0 LTS` Windows x64 archive was installed and verified
against SHA-256 `2d184b626c001692c362291911293b6a297179d618d95e9e9192c3a80318adc4`.
Its executable location is environment-specific and must still be discovered. A Codex
skill does not replace a 3D authoring tool.

# Task workflows

## Balance or gameplay override

1. Discover the current build and enabled order.
2. Use `catalog --query <term>` for structural mod examples, then locate the exact
   current definition with a read-only search under the discovered `base_data_root`.
3. Record why a new entity cannot achieve the change.
4. Copy the current textual definition into the isolated project only when the modding agreement permits the intended distribution.
5. Change the smallest possible set of properties while preserving encoding and unknown nodes.
6. Run strict validation and conflict reporting.
7. Assume achievements are disabled and an existing save may be unsafe. Test in a new save after a full restart.

After any game update, rebuild the override from the new base version and reapply the semantic change. Never carry an old entire file forward automatically.

## New entity, plant, landmark, building, or resource

1. Select a current base exemplar of the same category plus a locally clean Workshop concept example.
2. Create a unique ASCII identifier and a new `Ancient/Entity/.../<Identifier>` path.
3. Recreate only the required node structure. Use original assets and localization.
4. Check every literal file reference and every node reference against the candidate-plus-base union.
5. Validate and test first with only this mod enabled.

Use installed StarCarr (`2175125663`) for a small landmark concept, Phyllitis (`2312940890`) for a plant/FBX concept, and FOODCRAFT Nuts (`3298397416`) for a complex added-content concept. Do not copy their assets or assume all values remain current.

### Standalone-building availability and catalogue diagnosis

For the audited build, building availability is evidenced through Culture progression plus
Knowledge references and their XP thresholds. No direct building gate through `Year` or
`HistoryRangeYear` has been proven. Do not add or promise calendar-year availability unless a
current same-category exemplar and an isolated runtime test establish it.

Keep canonical `src` construction counts content-correct and positive. A zero
`ConstitutionCount` disabled the tested building's catalogue entry. If a count gate must be
isolated, use only a minimal positive ones-vector of the same length as
`ConstitutionResource`, and only as a smoke probe; it does not establish balanced release data.

An empty requirement pair is also diagnostic, not a supported release layout. Never omit just
one field, and never remove either from canonical `src` or a staged release. To isolate a
suspected availability gate:

1. Fully exit the game. Back up the deployed non-numeric loose mod and record SHA-256 for its
   canonical `Index.art` and the corresponding file under project `src`.
2. Change only the backed-up live loose diagnostic copy. Remove `Requirement` and
   `RequirementPercent` together, or substitute the positive ones-vector, but do not combine
   probes in one run.
3. Start from a clean launch with only the candidate enabled, use a disposable/new game, make an
   explicit manual save, fully exit, restart, and reload that save. Capture the relevant log and
   the observed Culture/Knowledge state.
4. Restore the live deployment byte-for-byte from canonical `src` and verify its hash. Repeat a
   final clean launch, manual save, full exit, restart, and reload before recording compatibility
   or staging a release.

The diagnostic copy is disposable evidence. Never publish it, synchronize it back into `src`,
or treat catalogue visibility alone as proof that construction, persistence, or progression is
correct.

## Localization

1. Create a language skeleton with the in-game New language action.
2. Keep the language node, ISO identifier, `Content` target, and folder names aligned.
3. Encode every `.loc` and `.art` as UTF-16LE with BOM.
4. Require exactly one `#` on each localization path marker and reject invisible leading characters.
5. Compare key coverage with the current English files, but do not distribute original English text unnecessarily.
6. Test menus, dynamic scripted strings, diacritics, line wrapping, and fallback behavior after restart.

## Textures, models, and audio

1. Confirm rights/provenance for every source asset.
2. Inspect a current same-category exemplar for names, dimensions, channels, materials, scale, animation, and references.
3. Keep source authoring files outside `Ancient/`; package only runtime assets.
4. Use image generation only for original visual bases and record that provenance. Do not imitate or reconstruct proprietary game art.
5. For FBX creation or animation, require Blender/equivalent or a user-supplied validated model. Header checks alone do not prove that the game can render it.
6. When an `ac-modding-kit` checkout contains `modeling/toolchain.lock.json`, use that exact
   checksum-pinned Blender build and treat `modeling/assets/` only as original authoring
   examples. Run both the static model tests and `tools/blender/validate_models.py`.
7. Keep source scenes Z-up and metres-based with applied transforms; export binary,
   triangulated FBX with explicit Y-up conversion, usable UVs, and the documented vertex
   RGBA mode. Record source and export axes separately.
8. Keep model claims at authoring-only/runtime-unverified until an explicitly authorized
   isolated game test and relevant `Log.txt` review succeed.

## Validation and test deployment

Run:

```text
acmk validate <project> --strict
acmk conflicts <enabled-paths-in-effective-order> <project>
```

Then explain the save and achievement impact. With explicit confirmation, back up any destination and deploy to the discovered user Mod directory. Do not overwrite a numeric extracted cache. Restart the game fully, enable the mod at the intended position, test a separate/new save, and parse the log:

```text
acmk log
```

Treat `ERROR`, `Warning`, `failed to load`, `needs to be updated`, obsolete packaging, missing Type, image failures, and unresolved Mesh/Render references as failures relevant to the affected mod.

## Conflict diagnosis

1. Capture enabled order and intersect effective payload paths.
2. Explain which higher mod wins each overlap.
3. Disable all unrelated mods, restart, and reproduce.
4. Re-enable one at a time. Never diagnose from subscription state alone; only enabled order is effective.

## Workshop preparation

Prefer the game's Publish/Update action. Before confirmation:

- validate against the live build;
- use a meaningful Changelog and square JPEG thumbnail;
- include accurate owner/author contact details as required by the installed agreement;
- verify every asset/code license and remove authoring/source clutter;
- test with a new save and a clean relevant log;
- confirm in the Steam client that the currently active account is the intended publisher; for
  an Update, also confirm that the remote item still exists and that this account owns it; and
- warn that upload/update is an external public action.

Record the account preflight as a sanitized pass/fail statement. Do not put an account name,
Steam ID, cached credential, token, or Steam Guard data in a public project record.

Use `build --apply` only to create a deterministic staging package for inspection. The audited
in-game publisher read the selected non-numeric loose root (`Index.art`, `Thumbnail.jpg`, and
loose `Ancient/**`) and generated its own temporary package. The SDK's deterministic
`dist/workshop/Mod.zip` was not that publisher input and was not byte-identical to the game's
generated ZIP. Never copy the SDK ZIP into the live loose folder or cite only its hash as proof
of the bytes selected by the in-game publisher.

On the audited client, preparing a publication could leave `%TEMP%\ACZipMod` behind with an
`Index.art`, `Thumbnail.jpg`, and game-generated `Mod.zip` from the last candidate or attempt.
Treat that directory as ephemeral and potentially stale. A matching title alone is insufficient:
compare its modification time, identity, thumbnail hash, ZIP entry inventory, and per-entry
hashes with the currently selected loose root. If it does not match, choose **No**, fully exit the
game, preserve any needed diagnostic evidence, and restart preparation. Do not delete or reuse
the directory as canonical project state.

Immediately before the final Publish/Update control, present one confirmation packet containing:

- the exact action (`Publish` or `Update`) and current timestamp plus the agreed immediate
  validity window;
- the exact selected loose folder, an exhaustive inventory and SHA-256 for every publisher input,
  and, when the game has freshly generated it, the matching temporary `Index.art`,
  `Thumbnail.jpg`, and `Mod.zip` hashes;
- Steam app `667610` and either **new item** with manifest `SteamModId 0,0`, or the exact existing
  PublishedFileId/`SteamModId` selected for Update; and
- the exact visibility control/value shown by the UI, or an explicit statement that this client
  shows no visibility selector, plus the intended result that will be verified afterward.

Obtain explicit, single-use confirmation for exactly one action on exactly one mod. Batch consent
for multiple mods or items is invalid. Approval to inspect, build, deploy, test, publish a
different candidate, or perform an earlier retry is not upload authorization. Re-hash and ask
again if the window expires or any bytes, item list, action, target ID, selected UI item, account,
or visibility state changes.

For an ACMK project, `acmk project publish-packet` implements the bounded inventory step without
uploading or storing authorization. Require `--account-preflight-passed`; for Update also require
`--target-ownership-verified`. Use `--generated-package-root "%TEMP%\ACZipMod"` only after the
game freshly generated that exact package. Rerun the CLI immediately before confirmation;
Python callers may instead call `PublishPacket.assert_active()` on the in-memory packet so
changed bytes or expiry are rejected.

### First-publish visibility adapter

Keep the authoring project at `SteamModId 0,0` before its first publication. On the audited
1.9.3 / build 23915225 client, however, a valid loose mod could load at runtime yet remain
absent from **Mods > List** while the deployed root manifest contained both `GameVersion 22`
and `SteamModId 0,0`. The working in-game route, also described by Uncasual Games for a new
upload/fork, was:

1. Fully exit the game and back up the deployed root `Index.art`.
2. In the non-numeric loose deployment only, remove the complete `GameVersion` and
   `SteamModId` blocks while preserving UTF-16LE/BOM and every other byte. Do not change the
   project manifest, copy `Mod.zip` into the live folder, rename the folder, or use a numeric
   Workshop-cache directory.
3. Restart fully and open **Mods > List**. On the audited client, the green upward arrow for the
   loose mod opened only a **Yes/No** publication modal; it did not open a title, description,
   details, or visibility editor. Select the intended arrow, verify that any freshly generated
   `%TEMP%\ACZipMod` matches this loose mod, and stop before **Yes**. Present the current
   confirmation packet above and choose **Yes** only after the user confirms it.
4. After success, fully exit and verify that the game restored the current `GameVersion` and
   wrote a nonzero `SteamModId` in the same live root manifest. Confirm the corresponding Steam
   log has successful content, preview, and final completion lines. Synchronize only the verified
   compatibility value and exact id into the matching canonical successor project and persistent
   Workshop state; do not copy the whole live or temporary manifest blindly. Reconcile the
   canonical manifest, invalidate or refresh fingerprints/runtime evidence and staged output as
   required, then use Update thereafter.

   For a matching ACMK successor, preview `acmk project sync-workshop-id <project>` with
   `--from-live <loose-root> --visibility <verified-value>`, and add each immutable deleted id
   with `--predecessor-id`. Add `--apply` only after reviewing the plan. The command rejects identity
   replacement/reuse, rechecks canonical and live bytes, writes `.acmk/workshop.json`, and keeps
   backups below `.acmk/backups`; it never contacts Steam.

Apply this adapter only when the first-publish item is otherwise valid and the current client
reproduces the visibility problem. A nonzero `SteamModId` is permanent identity and must never
be removed or reset to recover from an upload error.

### Publish/Update troubleshooting

Treat a numeric Steam error as a symptom, not a diagnosis. Stop repeated retries and capture
the exact operation and time, the current root `Index.art`, the game's `Log.txt`, and Steam's
recent `workshop_log.txt` and connection-related log lines. Verify the public item metadata and
the live app configuration; never assume a previously observed quota or error meaning is still
current. Do not expose cached credentials, login tokens, or Steam Guard data while inspecting
logs.

Every retry is a new external action. Recompute the confirmation packet and obtain a fresh
action-, candidate-, target-, visibility-, hash-, and time-scoped confirmation immediately
before clicking Publish/Update again.

- If `SteamModId` is nonzero, preserve it and use **Update**. Never reset it to `0,0` or choose
  a new Publish action merely to recover from an upload failure.
- In the audited 2026-07-22 wrong-account incident, the in-game dialog reported **Error 9**
  while a still-existing item belonged to another account. `workshop_log.txt` distinguished that
  phase with the exact operation result
  `Upload workshop item <id> failed (Failed to initialize build on server (Access Denied) )`.
  After that remote item was deleted, the same dialog number accompanied the distinct log result
  `Getting Workshop info for item <id> failed : File Not Found`. The former was an ownership
  failure in this case; the latter meant the recorded PublishedFileId no longer resolved. These
  are dated observations, not universal definitions of Error 9.
- A deleted or wrong-owned identity is not repaired by resetting its manifest. Preserve the
  predecessor project and its nonzero id unchanged as historical evidence. If a replacement is
  intended, create a separately named sibling successor from reviewed canonical content, give it
  a new ACMK project identity and non-numeric loose folder, keep its manifest at `SteamModId 0,0`,
  and obtain fresh provenance, runtime, staging, account-preflight, and one-mod publication
  evidence. Use this recovery only after remote existence and ownership are established from the
  current Steam state and logs.
- Determine which stage failed. Content upload, primary-preview upload, visibility, indexing,
  and client connectivity are independent. Confirm the final item directly and in the public
  browse index; a gallery image is not proof that the square primary preview exists.
- In the audited 2026-07-21 incident, in-game **Error 15** corresponded to
  `Failed to upload workshop preview file ... (Access Denied)` after the content manifest had
  already uploaded. Live app info then showed `ufs.quota=0` and `ufs.maxnumfiles=0`. Valve stores
  Workshop preview images in Steam Cloud, so a content-only update was a temporary payload
  workaround but could not populate the primary preview. Re-check live app info before applying
  this diagnosis because the publisher can change those values.
- In the same incident, in-game **Error 2** corresponded to
  `Failed to initialize build on server (No Connection)`. No upload had begun. Fully exit the
  game and Steam client, reopen Steam online, verify that a Community/Workshop page loads, and
  retry the in-game **Update**. Administrator rights, deleting other mods, or creating another
  Workshop item are not remedies for that log-confirmed condition.
- After the publisher raised app `667610` to `ufs.quota=1000000000` and
  `ufs.maxnumfiles=1000`, the canonical in-game Update succeeded and attached the primary preview
  to the existing item. Treat these figures as dated evidence, not permanent guarantees.

After a reported success, verify that the item retains the intended PublishedFileId, has the
intended visibility, remains downloadable, exposes a non-empty primary preview, and appears under
an unfiltered **Most Recent** view. Also verify the public API result, creator/consumer app ids,
ban flag, content size/manifest, unauthenticated item page/title, and primary-preview bytes when
those checks are available. Preserve the upload log and a short sanitized outcome in the project
docs. Every such result is dated evidence, not a permanent guarantee.

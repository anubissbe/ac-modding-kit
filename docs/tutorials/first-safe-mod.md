# First safe mod: complete authoring path

Status: supported workflow; last audited against Ancient Cities 1.9.3, Steam build
23915225, internal `GameVersion` 22 on 2026-07-19. Always run live discovery because these
values can change.

1. Run `acmk doctor` and resolve failed checks.
2. Read the installed `Modding Agreement.txt` and confirm rights for every planned asset.
3. In Ancient Cities, use **Mods > Create > New generic** or **New language**.
4. Exit the game and import the new non-numeric skeleton with `acmk project import`.
5. Keep runtime files under `src/Ancient/`; keep `.blend` and other sources in
   `assets-src/`.
6. Make the smallest possible change. Preserve exact paths, case, unknown ART nodes, and
   UTF-16LE BOM encoding.
7. Run the authoring profile and conflict report. Treat warnings as work items.
8. With explicit approval, back up saves, deploy a copy, restart fully, enable only the
   candidate, and test a disposable/new save.
9. Review the relevant `Log.txt`. Do not mark the project runtime-tested while relevant
   errors, warnings, missing references, or update notices remain.
10. Complete license/contact/provenance metadata. Put the license identifier and contact in
    the manifest Description or Content too; treat `reviewed` as your attestation, not proof.
    Then run the release profile.
11. Stage the Workshop directory. Inspect `Index.art`, `Thumbnail.jpg`, and deterministic
    `Mod.zip`, but do not copy that ZIP into the live loose folder or assume it is the ZIP the
    game will generate.
12. In Steam's UI, confirm the active account is the intended publisher; for Update, also confirm
    that the PublishedFileId exists and belongs to it. Keep only a sanitized pass/fail record.
13. Inventory and hash every file in the selected loose publisher input (`Index.art`,
    `Thumbnail.jpg`, and `Ancient/**`). On the audited client, the green upload arrow opens a
    **Yes/No** modal with no title/details or visibility selector. After selecting the intended
    arrow, verify that a freshly generated `%TEMP%\ACZipMod` matches this loose root; reject a
    stale package and stop before **Yes**.
14. Immediately before **Yes**, obtain single-use confirmation for exactly one action on exactly
    one mod. Include the candidate and complete hashes, app/item IDs, current time window, and
    exact visibility state; when no selector is shown, say so and name the intended result to
    verify afterward. Batch consent is invalid.
15. After success, fully exit. Verify that the game restored the current `GameVersion` and wrote
    the new nonzero `SteamModId` in the same live manifest. Match it to successful Steam content,
    preview, and final-completion logs and verify the remote page. Synchronize only that verified
    id and compatibility metadata into the canonical project, then deliberately refresh any
    invalidated evidence and staging.

For a standalone-building catalogue diagnosis, never change canonical `src`. Omit
`Requirement` and `RequirementPercent` only together and only in a backed-up live non-numeric
loose copy. A zero `ConstitutionCount` disables the tested catalogue entry; use a matching
positive ones-vector only as a minimal smoke probe, never as release balance. Restore the exact
canonical bytes and finish with a clean launch, explicit manual save, full exit, restart, and
reload. Building availability is currently evidenced through Culture plus Knowledge/XP; no
direct `Year`/`HistoryRangeYear` gate has been proven.

For every later release, keep the nonzero `SteamModId` and choose **Update**, never a new
Publish action. Earlier build, deploy, test, or retry approval is not upload authorization. If
Steam returns a numeric error, stop retrying and inspect the current
`workshop_log.txt`: a logged `No Connection` requires a full Steam-client reconnect, while a
preview `Access Denied` requires live verification of app `667610`'s Steam Cloud quota. See
[Publish/Update troubleshooting](../../skills/ancient-cities-modding/references/workflows.md#publishupdate-troubleshooting).

Do not confuse that preview-specific Access Denied case with the dated 2026-07-22 Error 9
account incident. There, a still-existing wrong-owned item logged
`Failed to initialize build on server (Access Denied)`, while its deleted predecessor later
logged `Getting Workshop info ... failed : File Not Found`. Preserve the predecessor and its id;
after confirming remote state, use a fresh, separately named `SteamModId 0,0` sibling successor
with new test/release evidence. Error numbers alone do not establish this recovery.

Never edit the Steam installation, Workshop cache, or numeric extracted mod directories.
Never upload game files, third-party Workshop content, authoring clutter, or private paths.

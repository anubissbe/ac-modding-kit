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
11. Stage the Workshop directory. Inspect `Index.art`, `Thumbnail.jpg`, and `Mod.zip`.
12. Publish manually through the game's current Publish/Update action only after a final
    rights and visibility review.

Never edit the Steam installation, Workshop cache, or numeric extracted mod directories.
Never upload game files, third-party Workshop content, authoring clutter, or private paths.

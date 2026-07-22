---
name: ancient-cities-modding
description: Build, inspect, update, validate, test, package, and publish Steam Workshop mods for Ancient Cities (Steam app 667610) on Windows. Use for .art/.loc editing, balance changes, buildings, resources, plants, landmarks, languages, textures, FBX models, audio, installed or Workshop mod inspection, conflict resolution, rebasing after game updates, local test deployment, Log.txt diagnosis, Workshop publishing, preview images, and upload-error troubleshooting.
---

# Ancient Cities Modding

Create mods against the user's installed build and the game's own data-driven overlay system. Treat the current installation, an in-game generated empty mod, and the local runtime log as the primary specification.

## Non-negotiable rules

1. Run `python scripts/ancient_cities_mod.py --json discover` before planning or editing. Never assume the Steam library, Documents folder, game build, or internal `GameVersion`.
2. Read the installed `Modding Agreement.txt` completely before the first creation, packaging, or publishing action in a task. Re-read it when its hash changes. Do not decompile or disassemble binaries, bypass DRM, or infer a DLL/plugin API.
3. Work in a dedicated project under the current Codex workspace. Never edit `Program Files`, Steam Workshop cache, or a numeric game-extracted mod folder. Treat those locations as read-only evidence.
4. Use the game's **Mods > Create > New generic/New language** output as the preferred canonical skeleton for the installed build. Use `init-project` only for an isolated draft when a game-generated skeleton is unavailable. A Generic draft may use `acmk project reconcile-consensus` only when the installed SDK supports the exact discovered build; retain its honest `observed-consensus` label and fresh evidence/runtime requirements.
5. Preserve UTF-16LE with BOM for every textual `.art` and `.loc` file. Do not use `apply_patch`, ordinary UTF-8 writers, or formatters on them. Use the bundled metadata editor or a byte-preserving script. Refuse files that do not round-trip exactly.
6. Do not redistribute unmodified game or Workshop assets/code. Create original assets, retain provenance, and keep overrides minimal. If the loader appears to require a full proprietary base file, flag the licensing uncertainty before distribution.
7. Never deploy, launch the game, delete/replace a local mod, or publish/update a Workshop item without explicit user confirmation. Immediately before every Publish/Update action, obtain single-use confirmation for exactly one mod, scoped to the exact action, active-account preflight, candidate, target/item IDs, UI visibility state (including when no selector is exposed), complete publisher-input inventory and SHA-256 hashes, and a stated current time window. Never accept batch consent. Publishing also requires current author/contact details and a rights/provenance check.

## Core workflow

1. **Discover and snapshot.** Record app ID, semantic version, build ID, content hash, internal mod revision, user mod path, enabled order, and log path. Read [local-baseline.md](references/local-baseline.md) only to compare with the dated audit; prefer live discovery.
2. **Define scope.** State whether the mod adds content or overrides a base path, whether it changes `.art`, whether a new save is needed, and which other enabled mods may conflict.
3. **Select current exemplars.** Run `catalog --query <term>` to locate installed,
   user-cache, Workshop, or built-in mod examples. Search the discovered
   `base_data_root` read-only (prefer `rg --files <base_data_root> | rg <term>`) for the
   exact current base definition. Mod examples provide concepts; the current base file
   provides the schema. Never copy third-party assets or trust stale values blindly.
4. **Create/import a skeleton.** Prefer the in-game creator. Copy the resulting non-numeric local skeleton into the workspace. If the Generic creator demonstrably fails, use only an SDK-supported exact-build `reconcile-consensus` fallback; never relabel that output as game-generated and never copy Workshop content. Keep the project `SteamModId` as `0,0` until Steam assigns an id. For the build-specific first-publish live-manifest adapter, follow [workflows.md](references/workflows.md); never remove an assigned nonzero id. When an id belongs to another account or a deleted item, preserve that predecessor unchanged and create a separately named `0,0` sibling successor only after current log and ownership checks establish that recovery path.
5. **Implement minimally.** Mirror payload paths under `Ancient/...`. Add only intentional files. Use original visuals/audio and exact-case references. For format and layout rules, read [format-and-layout.md](references/format-and-layout.md).
6. **Validate before deployment.** Run `validate <project> --strict`. Run `conflicts`
   for the discovered enabled set and verify its scanned count against the resolved
   enabled entries. Then run `conflicts <enabled-paths-in-effective-order> <project>`
   with the candidate in its intended winning position. Resolve encoding, metadata,
   unsafe ZIP paths, missing references, stale base overrides, and load-order collisions.
7. **Test safely.** Back up affected saves; deploy only after confirmation; fully restart the game; use a separate/new save; check the achievements warning; then run `log`. Repeat with only the candidate enabled when diagnosing. For standalone-building catalogue diagnosis, never alter canonical `src`: omit `Requirement` and `RequirementPercent` only as a pair in a backed-up live non-numeric loose copy, and use a minimal positive `ConstitutionCount` ones-vector only as a smoke probe. Restore the exact canonical bytes, then finish with a clean launch, explicit manual save, full exit, restart, and reload.
8. **Rebase after updates.** Re-run discovery. Rebuild each override from the new base exemplar instead of laying an old full file over it. Revalidate and retest.
9. **Prepare publishing.** Read [legal-and-publishing.md](references/legal-and-publishing.md) and [workflows.md](references/workflows.md). Prefer the game's Publish/Update UI; use `build` only to create a deterministic inspection/staging package. The audited publisher consumed a loose live root and generated its own potentially stale `%TEMP%\ACZipMod`; the SDK ZIP is not evidence of the exact publisher bytes. Re-hash and re-confirm immediately before the final UI action; earlier approval to build, deploy, test, or retry does not carry over. For every upload failure, stop repeated retries and follow the Publish/Update troubleshooting procedure in `workflows.md`; never diagnose from the numeric Steam error alone.

## Route by task

- For manifest, `.art`, `.loc`, virtual paths, assets, or ZIP layout, read [format-and-layout.md](references/format-and-layout.md).
- For balance overrides, new entities, standalone-building availability/catalogue diagnosis, localization, textures/models/audio, testing, rebasing, and publishing, read the matching section of [workflows.md](references/workflows.md).
- For licensing, contact details, provenance, privacy, monetization, Steam publication, or external sharing, read [legal-and-publishing.md](references/legal-and-publishing.md).
- For Workshop Publish/Update, preview failures, missing listings, or Steam error codes, read the Workshop preparation and troubleshooting sections in [workflows.md](references/workflows.md), then verify the live Steam configuration and logs.
- For claims derived from the user-supplied Steam Workshop article index, read [forum-articles.md](references/forum-articles.md). Prefer newer official statements and the live local build when sources conflict.

## Bundled tool

Use `python scripts/ancient_cities_mod.py --help` for the complete command surface:

- `discover`: locate the live install, user data, build, compatibility revision, and enabled order.
- `catalog`: inventory and filter installed/built-in mod examples without bundling their content.
- `inspect`: summarize a loose or packaged mod.
- `validate`: lint metadata, UTF-16LE, payload/ZIP safety, assets, overrides, and local references.
- `conflicts`: report overlapping effective paths and top-wins load order.
- `metadata`: preview and safely update root `Index.art`; dry-run unless `--apply`.
- `init-project`: create a noncanonical isolated draft; dry-run unless `--apply`.
- `build`: create a deterministic `Mod.zip` beside the separately maintained root
  `Index.art` and `Thumbnail.jpg`; dry-run unless `--apply`.
- `log`: decode BOM-less UTF-16LE logs and classify loader problems.
- `self-test`: run the full synthetic repository suite when it is present; an installed
  skill without repository tests runs a smaller UTF-16LE/manifest smoke test.

Treat warnings as work items, not decoration. Do not claim a mod is compatible until the installed build loads it without relevant errors after a full restart.

## Repository SDK

When a checkout or installed Python package exposes `acmk` version `0.2.0a1` or newer,
prefer its typed project workflow for new work while retaining the safety rules above:

- `acmk doctor` checks the live installation, compatibility fingerprint, user paths, and
  Blender without changing them.
- `acmk knowledge list|read|search` exposes the audited reference set offline.
- `acmk project import` copies a current non-numeric in-game skeleton into a structured
  authoring project; it is dry-run unless `--apply` is explicitly supplied.
- `acmk project reconcile-consensus` is the narrower Generic fallback for a supported exact
  build. It records sanitized origin evidence, uses the separate `observed-consensus` label,
  resets runtime status, and is also dry-run unless `--apply` is supplied. Repeat its
  preview/apply sequence after an intentional canonical root-manifest metadata change; this
  refreshes the bound evidence and requires a fresh runtime test.
- Keep runtime files in `src/`, authoring sources in `assets-src/`, local reports in
  `.acmk/`, and isolated upload candidates in `dist/workshop/`.
- Use `project check --profile authoring` while editing and `--profile release` only after
  licensing/contact, current-build, provenance, save/achievement, and runtime evidence are
  complete.
- `project record-test` records a user-performed test and sanitized log summary; it never
  launches the game. `project stage` builds an isolated candidate; it never deploys or
  uploads it.
- `project publish-packet` verifies one expiring, content-addressed in-game action after the
  sanitized account/ownership preflight; it never records authorization or uploads. For the
  audited loose flow, include and verify the freshly generated `ACZipMod` package.
- After a verified success, preview `project sync-workshop-id` to reconcile the assigned id and
  immutable predecessors into canonical state. Apply only after review; it stores backups below
  `.acmk/backups`, rejects deleted/replaced ids, and resets runtime readiness on identity change.

`acmk.toml` and SDK JSON schemas describe ACMK-owned project/report contracts only. They
must never be presented as a complete schema for the game's open-ended `.art` format.

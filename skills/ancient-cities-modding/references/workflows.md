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
- warn that upload/update is an external public action.

Use `build --apply` only to create a deterministic staging package for inspection. Do not substitute it for the game's current Steam publisher unless the user explicitly requests a manual package and understands that the in-game flow is canonical.

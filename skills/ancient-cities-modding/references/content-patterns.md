# Content authoring patterns

These patterns summarize evidence from the audited Ancient Cities 1.9.3 / GameVersion 22 /
Steam build 23915225 data interface. They are authoring and test guidance, not a complete engine
schema. Re-check current base exemplars and repeat isolated runtime tests after every game update.

## Evolving culture distributions

Keep research layers separate from runtime cultures. A research layer may describe an
archaeological region or phase for source attribution, map authoring, and visual review. Its
authoring identifier is **not** a valid `~/Entity/Culture/List/.../Entity` reference unless the
current base or candidate actually defines a matching runtime Culture entity. Compile research
layers into culture identifiers proven by the current installation; on the audited build the
built-in Mesolithic and Neolithic entities are the conservative targets.

Treat the playable map as a chronological sequence of frames rather than a set of unrelated
images. For pixel `p` in frame `t`, define combined availability as the maximum intensity across
all runtime culture masks:

```text
A[t, p] = max(M[c, t, p] for every runtime culture c)
```

If settlement evidence is intended to expand over time, assert `A[t, p] >= A[t-1, p]` for every
pixel. A culture transition may reduce a predecessor mask only after its successor holds that
same availability. Assert that the combined predecessor/successor value remains `A[t, p]` at
every handoff frame. This lets cultures evolve without making previously available land vanish.

Recommended generator checks are:

- exact current-exemplar dimensions, orientation, image format, filenames, and ART ordering;
- a reliable exact-255 plateau in every playable dated frame, not merely a bright
  feathered glow; Ancient Cities 1.9.5 was observed rendering a 252-valued glow while
  rejecting every start region inside it;
- an explicit, source-documented first frame rather than an invented full-map start;
- a declared final authored envelope and the frame by which it must be reached;
- bytewise non-retreat of combined availability through every consecutive frame;
- gap-free predecessor-to-successor handoffs at every pixel;
- no use of research-layer identifiers as engine Culture references; and
- review atlases for source layers, each runtime culture, and their combined availability.

Require at least four exact-255 pixels as a conservative generator guard, then test the actual
start-location UI at representative early, transition, and late dates. These checks prove
generator invariants only: loader interpretation, map projection, UI filtering, and whether an
authored core contains a selectable game-region centre remain runtime concerns.

Treat a new-game culture start as two checkpoints. First select a valid global-map culture
region. After the local map loads, explicitly choose the settlement start point and wait for
residents and ordinary settlement controls to appear. Reaching the local map alone is not proof
that settlement initialization completed.

## Culture-specific wonders

Standalone-building availability on the audited build is evidenced through a proven runtime
Culture reference plus Knowledge references and their XP thresholds. No direct calendar-year or
geographic building gate has been verified. Therefore:

- do not use research-layer names as building Culture requirements;
- use only current runtime Culture IDs and current Knowledge IDs;
- describe Knowledge XP as an approximation of historical progression, not an exact date;
- do not promise regional exclusivity unless a same-category exemplar and isolated test prove a
  geographic gate; and
- use a current, tested uniqueness field such as `CountLimit` only after checking the exact
  building exemplar, then verify the limit in game.

For monument-scale visuals, a strong authoring review set is one blueprint, five cumulative
construction snapshots, one completed Default snapshot, and two complete decay snapshots. Each
construction snapshot must contain everything visible at that point, not only the newly consumed
resource. Keep persistent finished materials in the Default model set. Scaffolds, ropes, ramps,
or lifting timbers may appear during construction but should be absent from Default when they are
not part of the intended completed monument. Decay snapshots likewise represent complete damaged
states rather than mesh deltas.

Five construction and two decay snapshots are a review pattern, not a universal engine minimum.
Model references, material separation, ordering, repair behavior, footprint, entrances, service
slots, and decay transitions still require an isolated runtime test.

Each model's `Tx/Render.Render` field must resolve to a Render node, not directly to a Material
node. The audited MudWall and MudWallDecay materials therefore require local `Render/Full`
wrappers. Reference those wrappers through the additive building's absolute engine namespace:
`/Ancient/Entity/Local/Building/List/<EntityId>/Asset/<RenderName>`. The `/List/` segment is
required even though it is absent from the payload directory. See
[format-and-layout.md](format-and-layout.md) for the exact boundary.

## Generic Fish tools

A resource using the current generic Fish-tool component is a reusable hand-held tool. It does
not become a passive net, water trap, or persistent placed object merely because its model and
localization call it a net. A passive fishing installation needs a separately evidenced building,
service, or task pattern.

Workers choose among available tools according to engine behavior and tool scores. Audit every
current competitor under the same Culture/Knowledge conditions and give the intended upgrade a
strictly higher Fish score; a tie is not evidence that workers will prefer it. On the dated
audited build, a score of `2.25` was selected to exceed the built-in bone harpoon's observed
`2.0`, but both values must be re-checked after an update.

Static ART validation cannot establish tool use. A functional test must craft the tool, make it
available to a fishing workgroup, assign a valid water task, observe a worker performing the
fishing activity, inspect the worker's equipped tool, and confirm that fish inventory increases.
Record separately whether crafting, equipping, activity, production, and save/reload persistence
passed; do not infer one result from another.

## Fail-closed evidence sessions and mod-list capture

Treat the enabled-mod UI as an active control, not a passive details view. On Ancient Cities
1.9.5, clicking the body of a row in **Mods > List** toggled that mod even when the pointer was
outside its checkbox. To capture an isolation screenshot, open the list, scroll from inside the
list, and take the screenshot without clicking a row or checkbox.

Bind every evidence run to the pre-launch configuration hash, candidate hash, and exact game
fingerprint. If an unintended toggle occurs:

1. stop using that process session for runtime evidence;
2. return the checkbox to its intended state only to recover the user's configuration;
3. exit Ancient Cities normally and verify the configuration byte-for-byte against the frozen
   pre-launch hash; and
4. start a completely new process before recapturing both screenshots and log phases.

Turning the checkbox back off can restore the exact configuration bytes, but it cannot remove the
enable/disable event from the current `Log.txt`. Therefore do not combine a pre-toggle screenshot
with a post-toggle log or present that session as a clean isolated launch. If any frozen binding
changed, abandon the evidence run, restore the exact backed-up configuration while the game is
closed, and initialize a new run. Never edit an immutable run's bindings after observations have
started.

Treat an opened entity panel as another active control surface. In Ancient Cities 1.9.5 the
bottom-right red `X` on a completed housing entity starts demolition instead of closing the panel;
it can remove the dwelling and make its residents leave the tribe. On a building site, the
equivalent red `X` cancels the site. Do not use either icon for navigation. Use the panel's
top-left back chevron or a harmless selection change, and refresh the observation before the next
input. If demolition or cancellation was triggered in a disposable runtime world, stop recording,
discard the changed world state, and reload the frozen pre-action save. Never claim later
construction, production, population, or persistence evidence from the contaminated continuation.

To recover a stable local view without touching a destructive panel control, select the tribe flag
in the top HUD and press `F`. In the observed 1.9.5 client this focused the settlement. Do not use
`Home`/`End` as camera controls: they traverse selection history and can relocate the camera to a
remote prior selection. The tribe-panel magnifier can open a global/map-focused view; return with
the documented local/global control. Read the tribe People tab for the population total. The small
number adjacent to the year in the observed HUD is the day, not the tribe population.

If runtime progress is accelerated, keep every ultra-fast interval short, pause immediately after
the interval, and capture the resulting tasks, tools, resources, population, and food state. Such
an interval can prove that the ordinary scheduler advanced a task, but it cannot prove normal
duration, stage timing, costs, or unattended stability.

## Isolated runtime test

Use the reusable [isolated runtime test record](isolated-runtime-test.md)
and keep one candidate active at a time:

1. Run discovery, record the exact build fingerprint and enabled order, and hash canonical
   `src`, the active configuration, and any live file that will be changed.
2. Fully exit the game. With explicit authorization, deploy only to a new non-numeric loose-mod
   folder. Never overwrite a numeric cache, Workshop source, or the game installation.
3. Enable only the candidate and start a new disposable save. Record any developer or instant-
   build aid; cheats can accelerate a test but do not prove normal progression or unlock timing.
4. Exercise the feature-specific checks below and capture observations rather than intentions.
5. Make an explicit manual save, fully exit, restart from a clean launch, reload that save, and
   repeat the essential visibility/use check.
6. Review the complete relevant log for new warnings, errors, missing references, and image/model
   failures. Catalogue visibility or a clean load line alone is not end-to-end proof.
7. Fully exit, restore the previous enabled configuration byte-for-byte, and verify its hash.
   Keep sanitized evidence outside the live mod and save directories.

Feature-specific minimums:

| Feature | Required observations |
| --- | --- |
| Culture timeline | Early, transition, and late start maps; intended expansion; no handoff holes; expected runtime culture labels |
| Wonder | Locked and unlocked catalogue state; placement; all construction snapshots; Default; uniqueness; service behavior if any; both decay states; repair; save/reload |
| Fish tool | Recipe visible; inputs consumed; item created; fishing worker equips it; fishing activity occurs; fish stock rises; save/reload |

If a required observation cannot be produced, record it as unverified. Do not upgrade a static
or clean-load result into a functional runtime claim.

For a building that appears stalled, first select its construction site. A valid site may be
clearing trees or vegetation before construction tasks appear. Raise the site's own priority
when appropriate and observe its task count. Compare the same terrain and worker context with a
built-in building before attributing a shared clearing delay to custom ART. Catalogue presence,
placement, terrain clearing, construction, completed visuals, function, decay, and persistence
are separate claims. In the observed 1.9.5 case, the custom Hellenic house completed after the
site and Builders were prioritized, Woodchoppers were active, and a competing Gatherers group
was temporarily paused; restore any group and speed changes after the diagnostic run. Its
persistence check used an explicit manual save, a full process exit, a clean restart, and an
exact-entity reinspection after reload. The reloaded panel preserved the custom name, completed
state, constitution, and material totals. Treat that as proof for the tested instance only, not
for the rest of a building catalogue.

Placement itself can also have more than one interaction contract. The observed fixed-footprint
house accepted one left click, whereas an orientation-sensitive yard kept moving its green
preview after loose clicks and created the real site only after a short left drag set its facing.
Record which gesture the tested building required and confirm success from a toast or selectable
site. Do not count a green preview as a placed building.

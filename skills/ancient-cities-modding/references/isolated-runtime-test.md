# Isolated runtime test record

Copy this record into the mod project's documentation and complete it during a manual,
explicitly authorized in-game test. It is an evidence record, not authorization to deploy or
publish.

## Candidate and environment

- Project:
- Candidate version:
- Canonical `src` SHA-256 or deterministic inventory hash:
- Loose non-numeric test folder:
- Ancient Cities semantic version:
- Steam build ID:
- Internal GameVersion:
- Installed content hash:
- Test date/time and timezone:
- Tester:
- Enabled mods in effective order (candidate only unless the test says otherwise):
- Pre-test configuration SHA-256:
- Disposable save identifier:
- Developer/instant-build aids used:

## Preflight

- [ ] Game fully exited before deployment or configuration change.
- [ ] Existing saves backed up outside the live save directory when needed.
- [ ] Destination is a new non-numeric loose-mod folder.
- [ ] Numeric cache, Workshop source, and game installation remain untouched.
- [ ] Static strict validation passed.
- [ ] Enabled-set and candidate-last conflict scans passed or are explained below.
- [ ] Only the intended candidate is enabled for the isolated run.

## Functional observations

Record observed results, screenshots/log timestamps, and failures. Do not mark a row passed from
catalogue visibility or a clean load line alone.

| Check | Pass / fail / unverified | Evidence and notes |
| --- | --- | --- |
| Candidate loads on a clean launch |  |  |
| Intended lock and unlock conditions |  |  |
| Creation/construction/crafting |  |  |
| Completed visuals and behavior |  |  |
| Worker routing, equipment, or service use |  |  |
| Decay/damage and repair when applicable |  |  |
| Manual save created |  |  |
| Full exit, clean restart, and reload |  |  |
| Essential behavior repeated after reload |  |  |
| Exact tested entity reselected after reload; identity and state match |  |  |
| Relevant log contains no candidate errors/new warnings |  |  |

### Culture timeline extension

- [ ] Every playable dated mask has a reliable exact-255 core; no sub-255 glow is treated as proof.
- [ ] Early start frame shows only the intended evidence-backed seed.
- [ ] Transition frames expand combined availability without holes.
- [ ] Late frame reaches the declared authored envelope.
- [ ] Predecessor-to-successor culture handoffs do not remove playable land.
- [ ] UI shows only runtime culture entities, not authoring/research-layer IDs.
- [ ] Global culture region and local settlement start point were both selected.

### Wonder extension

- [ ] Correct runtime Culture and Knowledge XP gate observed below and above threshold.
- [ ] Blueprint plus five cumulative construction snapshots observed in order.
- [ ] Default state contains only intended persistent materials/aids.
- [ ] Uniqueness/count limit observed.
- [ ] Two decay states and repair observed.
- [ ] Footprint, entrance, collision, routing, and optional service slots behave correctly.

### Building-site diagnosis

- [ ] Placement was confirmed once and produced the intended named construction site.
- [ ] Terrain clearing and construction were recorded as separate states.
- [ ] Site priority, tools, available workers, and paused workgroups were inspected.
- [ ] A built-in comparison site was tested in the same runtime context before blaming custom ART.
- [ ] After reload, the same instance still has the expected name, completion/constitution state,
  and material totals; no catalogue-wide persistence claim is inferred from one instance.

### Production-workgroup routing

- [ ] The completed map entity was assigned through the destination workgroup's **Assign** action.
- [ ] The workgroup building tab changed to the expected count and showed the intended thumbnail.
- [ ] Right click exited assignment mode without changing the assignment.
- [ ] Building count, open positions, current members, and active worker behavior were recorded as
  separate observations.
- [ ] A nonzero current-member count and the worker's Load/Process/Unload behavior were observed;
  `Production <n>` or an open vacancy alone was not treated as production proof.
- [ ] Any competing workgroup paused for diagnosis was restored, and the before/after member
  counters were recorded.
- [ ] Exact recipe inputs decreased and one isolated output increased before function was marked
  passed.
- [ ] “Exact” means one completed batch whose isolated before/after quantities equal the declared
  full-batch input vector and expected output count. Partial batches or items touched by a
  concurrent producer/consumer remain unverified.

### Generic Fish-tool extension

- [ ] Recipe visible and resource inputs consumed.
- [ ] Tool created and stored.
- [ ] Fishing worker equips this tool instead of an available competitor.
- [ ] Worker performs the fishing activity at a valid water task.
- [ ] Fish inventory increases.
- [ ] Tool remains a hand-held generic Fish tool; no passive-net behavior is claimed.

## Log and restoration

- Runtime log SHA-256:
- Baseline log SHA-256 when used:
- New warnings/errors/failures:
- Save/reload result:
- Post-test configuration SHA-256:
- [ ] Game fully exited before restoration.
- [ ] Original configuration restored byte-for-byte and its hash verified.
- [ ] Canonical project bytes still match the pre-test inventory.
- [ ] Evidence copied outside live mod/save directories and sanitized.

## Outcome

- Overall status: pass / fail / partially verified
- Verified claims:
- Unverified claims:
- Required fixes or follow-up tests:
- Save impact:
- Achievement impact:
- Known conflicts:

This record does not authorize Workshop Publish or Update. Those remain separate, single-action,
content-addressed external actions.

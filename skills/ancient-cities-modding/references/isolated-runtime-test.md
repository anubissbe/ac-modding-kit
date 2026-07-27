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
| Relevant log contains no candidate errors/new warnings |  |  |

### Culture timeline extension

- [ ] Early start frame shows only the intended evidence-backed seed.
- [ ] Transition frames expand combined availability without holes.
- [ ] Late frame reaches the declared authored envelope.
- [ ] Predecessor-to-successor culture handoffs do not remove playable land.
- [ ] UI shows only runtime culture entities, not authoring/research-layer IDs.

### Wonder extension

- [ ] Correct runtime Culture and Knowledge XP gate observed below and above threshold.
- [ ] Blueprint plus five cumulative construction snapshots observed in order.
- [ ] Default state contains only intended persistent materials/aids.
- [ ] Uniqueness/count limit observed.
- [ ] Two decay states and repair observed.
- [ ] Footprint, entrance, collision, routing, and optional service slots behave correctly.

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

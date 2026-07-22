# Contributing

Thank you for improving the Ancient Cities Modding Kit. Contributions should be
small enough to review, reproducible, and safe for other players to test.

## Before you start

- Search existing issues and discussions.
- Open an issue before a large feature, format change, or compatibility claim.
- Read the [Code of Conduct](CODE_OF_CONDUCT.md) and the project boundaries in
  [README.md](README.md).
- Never submit game files, extracted assets, proprietary code, another author's
  Workshop item, secrets, personal data, or material obtained through binary reverse
  engineering. Use original or synthetic fixtures only.

By contributing, you affirm that you have the right to submit the material under the
repository's MIT License.

## Development setup

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m ruff format --check src schemas skills/ancient-cities-modding/scripts tests examples tools/blender
python -m ruff check src schemas skills/ancient-cities-modding/scripts tests examples tools/blender
python -m mypy --strict src/acmk
python -m pytest
```

Python 3.11, 3.12, 3.13, and 3.14 are supported. Keep source, Markdown, YAML, and fixtures in
UTF-8 unless a fixture specifically models a game-facing UTF-16LE file. Such fixtures
must be synthetic, minimal, and documented. Do not silently re-encode game-facing
files; preserve their UTF-16LE form and byte-order marker when the documented format
requires one.

Model contributions must follow [`modeling/README.md`](modeling/README.md), use the exact
checksum-pinned Blender toolchain, update provenance/reports/previews/checksums, and pass:

```powershell
blender --background --factory-startup --disable-autoexec --python-exit-code 1 `
  --python tools/blender/validate_models.py
```

Keep `runtime_tested = false` unless an authorized isolated test against the recorded game
build and a relevant sanitized `Log.txt` review have actually been completed.

## Making a change

1. Create a focused branch from `main`.
2. Add or update tests for behavior changes.
3. Run formatting, lint, and the full test suite locally.
4. Update documentation and `CHANGELOG.md` when users will notice the change.
5. Open a pull request and complete every applicable checklist item.

Prefer clear, imperative commit subjects such as `Add encoding check for mod files`.
Avoid unrelated formatting or generated-file churn.

## Compatibility evidence

A claim that something works in game must include:

- the exact Ancient Cities build shown by Steam or the game;
- operating system, test date, and clean-launch status;
- whether the test used a new disposable save;
- observed save and achievement effects;
- minimal reproduction steps and sanitized logs, if relevant.

For standalone-building availability reports, also record the Culture and Knowledge/XP state,
the canonical and deployed `Index.art` SHA-256 values, and every temporary diagnostic delta.
There is no proven direct `Year`/`HistoryRangeYear` building gate. Requirement fields may be
omitted only together in a backed-up live non-numeric loose diagnostic copy, never canonical
`src`; a positive ones-vector is a smoke probe only, and zero `ConstitutionCount` disables the
tested catalogue entry. Restore exact canonical bytes and repeat the final clean launch, manual
save, full exit, restart, and reload cycle before reporting success.

Never test a proposed change first on a valued save. A successful static validation
does not establish runtime compatibility.

## Review and release

Maintainers review scope, provenance, tests, documentation, safety, and licensing.
They may ask for a smaller change or additional current-build evidence. Approval does
not transfer responsibility for third-party rights or in-game consequences. Releases
follow [GOVERNANCE.md](GOVERNANCE.md), the [release checklist](docs/releasing.md), and
use semantic versioning where practical.

Pull-request or release approval is not consent to publish a Workshop item. Immediately before
each Publish/Update, require a fresh single-use confirmation naming the exact action, candidate,
items and SHA-256 hashes, app/item IDs, visibility, and current time window.

# SDK schemas

These schemas cover ACMK-owned contracts only. They do not claim to describe the
complete, build-dependent Ancient Cities `.art` grammar.

Installed wheels expose them through Python's resource API as `acmk.schemas`, so
editors and integrations do not need a source checkout.

- `acmk-project-v1.schema.json` validates the canonical object returned by
  `ProjectConfig.to_dict()`.
- `acmk-report-envelope-v1.schema.json` validates JSON emitted by new SDK commands when
  `--json` is supplied.
- `acmk-runtime-test-v1.schema.json` validates sanitized manual runtime-test evidence.
- `acmk-runtime-test-v2.schema.json` adds a versioned, warning-only clean-launch baseline
  differential. Existing occurrence-counted v2 evidence remains supported; new records use
  repeat-insensitive normalized warning-signature membership.
- `acmk-runtime-test-v3.schema.json` binds evidence to the explicitly selected tested loose-mod
  root and records manual save/reload persistence. Its fingerprint covers only `Index.art`,
  `Thumbnail.jpg`, and `Ancient/**`; the sole excluded game-managed file is an empty root
  `Mod.hms`. A warning baseline is optional in v3 and may represent the same enabled candidate
  set before save/reload; it can suppress warning signatures only, never errors or failures.
- `acmk-workshop-state-v1.schema.json` validates persistent app `667610` identity, visibility,
  bounded immutable predecessor IDs, and the last verified timestamp used by the dry-run-first
  post-publication synchronization workflow.

Existing v1 and v2 evidence remains parseable as legacy evidence and is never rewritten or
silently upgraded. Because those versions do not attest the tested loose-mod root or save/reload
persistence, release validation requires an explicit new v3 `record-test` before staging.

`ProjectConfig` remains authoritative for cross-field rules that JSON Schema cannot express
portably, including case-insensitive relation uniqueness, dependency/conflict overlap,
reserved Windows names, and overlap between configured project paths.

The existing legacy CLI JSON fields remain unchanged for backwards compatibility. Default
pretty output from new SDK commands is unwrapped; only their explicit `--json` mode uses the
report envelope.

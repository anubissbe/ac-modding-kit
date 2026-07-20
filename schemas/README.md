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
  repeat-insensitive normalized warning-signature membership. Existing v1 evidence also remains
  supported.

`ProjectConfig` remains authoritative for cross-field rules that JSON Schema cannot express
portably, including case-insensitive relation uniqueness, dependency/conflict overlap,
reserved Windows names, and overlap between configured project paths.

The existing legacy CLI JSON fields remain unchanged for backwards compatibility. Default
pretty output from new SDK commands is unwrapped; only their explicit `--json` mode uses the
report envelope.

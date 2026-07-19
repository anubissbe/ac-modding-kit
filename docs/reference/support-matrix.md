# Support matrix

Status reflects evidence from the audited local build and public documentation, not an
official engine guarantee.

| Area | Status | Boundary |
| --- | --- | --- |
| Root manifest and overlay layout | Supported | Current skeleton and live validation remain authoritative |
| `.art` and `.loc` encoding | Supported | UTF-16LE with exactly one BOM; unknown syntax is preserved |
| Validation, conflicts, deterministic ZIP staging | Supported | Static/tool compatibility only |
| Languages, landmarks, rivers, fonts, height maps | Supported workflow | Requires current same-category exemplar and in-game test |
| Textures, WAV, FBX plants/buildings/resources | Supported authoring | Original assets only; Blender availability/version check plus manual format and runtime validation |
| Balance/full-file overrides | Experimental/high risk | Rebase after every game update; may break saves |
| Character replacement and broad UI replacement | Undocumented | No compatibility claim |
| Pregnancy or every production parameter | Undocumented | No complete public schema |
| DLL, C#, Harmony, BepInEx, arbitrary code plug-ins | Unsupported | No public supported binary API was found |
| Automatic Steam Workshop publication | Intentionally unsupported | Use the current in-game UI with explicit human review |

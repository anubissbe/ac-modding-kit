# Maintainer release checklist

This checklist covers ACMK toolkit releases. It does not publish or update an Ancient
Cities Steam Workshop item.

1. Start from a reviewed, green `main` branch with no uncommitted files.
2. Choose a PEP 440 package version and update `pyproject.toml`. Change SDK or JSON schema
   versions only when their public contracts require it.
3. Move the relevant `CHANGELOG.md` entries into a dated version heading. Do not add a tag
   link until that tag exists.
4. Confirm that documentation, examples, schemas, and the packaged Codex skill describe the
   same commands and safety boundaries.
5. Audit the diff and built archives for secrets, private paths, game files, extracted
   assets, third-party Workshop material, and unlicensed generated files.
6. Run Ruff, strict mypy, the complete test suite on every supported Python version, and
   source compilation. Let the GitHub CI matrix repeat these checks on Windows and Linux.
7. Build both source and wheel distributions in a clean directory and run `twine check`.
   Install the wheel in an isolated environment; verify the public imports, exact knowledge
   and schema resources, `acmk --help`, `python -m acmk --help`, and `acmk self-test`.
8. Open a release pull request. Require normal review and all protected checks; never merge
   solely because local validation passed.
9. After merge, create the signed or annotated version tag and GitHub release from that exact
   commit. Attach only freshly built, verified distributions. Publication to a package index
   is a separate, explicitly authorized maintainer action.
10. Record which game-build tuples have actual clean-launch evidence. Do not turn static
    validation into an in-game compatibility claim.

If any artifact differs after signing, tagging, or review, stop and rebuild from the tagged
commit instead of replacing it silently.

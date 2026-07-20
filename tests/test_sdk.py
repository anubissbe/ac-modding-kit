"""Public SDK contract tests using only synthetic fixtures."""

from __future__ import annotations

import codecs
import contextlib
import hashlib
import importlib.resources
import io
import json
import os
import shutil
import subprocess
import tomllib
import unittest
import uuid
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator

import acmk
import ancient_cities_mod as legacy
from acmk import (
    ACMKError,
    AncientPath,
    Compatibility,
    ContractError,
    DraftProjectBuilder,
    EngineReference,
    GameVersion,
    ManifestDocument,
    ManifestSpec,
    ProjectConfig,
    ProjectImporter,
    ProjectRelativePath,
    RuntimeStatus,
    SDKProject,
    SourceChangedError,
    SteamModId,
    TextAssetKind,
    Utf16TextDocument,
    ValidationProfile,
)
from acmk.cli import main as cli_main
from acmk.project import FileSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]


def synthetic_jpeg(width: int = 512, height: int = 512) -> bytes:
    sof = b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x01\x01\x11\x00"
    return b"\xff\xd8\xff\xc0" + (len(sof) + 2).to_bytes(2, "big") + sof + b"\xff\xd9"


def write_art(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(codecs.BOM_UTF16_LE + text.encode("utf-16-le"))


def manifest_text(*, title: str = "Synthetic SDK Mod") -> str:
    return legacy.canonical_manifest(
        title=title,
        description=("Only generated test data. License: MIT. Contact: https://github.com/example"),
        changelog="Initial synthetic version",
        game_version="22",
        mod_type="Generic",
        steam_mod_id="0",
    )


def bundled_schema(name: str) -> dict[str, object]:
    resource = importlib.resources.files("acmk.schemas").joinpath(name)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


class SyntheticTempTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = REPO_ROOT / "tests" / f".sdk-{uuid.uuid4().hex}"
        self.root.mkdir(mode=0o777)
        game = self.root / "Game"
        (game / "Ancient" / "Data" / "Ancient").mkdir(parents=True)
        documents = self.root / "Documents"
        user_root = documents / "Uncasual Games" / "Ancient Cities"
        (user_root / "Mod").mkdir(parents=True)
        self.context = legacy.DiscoveryContext(
            game_dir=game,
            documents_dir=documents,
            user_root=user_root,
            semver="1.9.3",
            build_id="23915225",
            content_hash="D9BF481D195671BF9CB98274B4CFF604",
            game_version="22",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)

    def make_skeleton(self, name: str = "SdkSkeleton") -> Path:
        skeleton = self.context.user_root / "Mod" / name
        write_art(skeleton / "Index.art", manifest_text())
        (skeleton / "Thumbnail.jpg").write_bytes(synthetic_jpeg())
        (skeleton / "Ancient").mkdir()
        return skeleton


class ValueObjectTests(unittest.TestCase):
    def test_public_exports_are_real_and_versioned(self) -> None:
        self.assertEqual(acmk.SDK_API_VERSION, "1")
        self.assertEqual(acmk.PROJECT_SCHEMA_VERSION, 1)
        self.assertTrue(acmk.__version__)
        self.assertTrue(acmk.__all__)
        self.assertTrue(all(hasattr(acmk, name) for name in acmk.__all__))

    def test_utf16_document_requires_exactly_one_bom(self) -> None:
        valid = Utf16TextDocument.from_text("Node:{}\n", kind=TextAssetKind.ART)
        self.assertTrue(valid.to_bytes().startswith(codecs.BOM_UTF16_LE))
        with self.assertRaisesRegex(ContractError, "more than one"):
            Utf16TextDocument.from_bytes(
                codecs.BOM_UTF16_LE + valid.to_bytes(), kind=TextAssetKind.ART
            )
        with self.assertRaisesRegex(ContractError, "embedded BOM"):
            Utf16TextDocument.from_text("\ufeffNode:{}", kind=TextAssetKind.ART)
        with self.assertRaisesRegex(ContractError, "does not match original bytes"):
            Utf16TextDocument(
                kind=TextAssetKind.ART,
                text="NEW",
                original_bytes=codecs.BOM_UTF16_LE + "OLD".encode("utf-16-le"),
                newline_style=acmk.NewlineStyle.NONE,
                source_sha256=hashlib.sha256(
                    codecs.BOM_UTF16_LE + "OLD".encode("utf-16-le")
                ).hexdigest(),
            )

    def test_ascii_version_and_u32_pair_are_type_safe(self) -> None:
        self.assertEqual(str(GameVersion("22")), "22")
        self.assertEqual(str(SteamModId.parse("42")), "42,0")
        with self.assertRaises(ContractError):
            GameVersion("٢٢")
        with self.assertRaises(ContractError):
            SteamModId.parse("１２,0")

    def test_ancient_path_and_engine_reference_are_distinct(self) -> None:
        self.assertEqual(
            str(AncientPath.from_payload("Entity/Test.art")), "Ancient/Entity/Test.art"
        )
        self.assertEqual(EngineReference("../Node").value, "../Node")
        for value in ("ancient/Test.art", "Ancient\\Test.art", "Ancient/../Test.art"):
            with self.subTest(value=value), self.assertRaises(ACMKError):
                AncientPath(value)
        with self.assertRaises(ACMKError):
            EngineReference("Ancient/Test.art")

    def test_manifest_scan_preserves_unknown_content_during_targeted_update(self) -> None:
        text = manifest_text() + '\nVendor/Future:{Name:"Opaque" Value:"Keep me"}\n'
        document = ManifestDocument.from_bytes(codecs.BOM_UTF16_LE + text.encode("utf-16-le"))
        changed = document.updated({"Title": "Changed"})
        self.assertEqual(changed.fields["Title"], "Changed")
        self.assertIn('Vendor/Future:{Name:"Opaque" Value:"Keep me"}', changed.document.text)

    def test_project_relative_paths_cannot_escape(self) -> None:
        self.assertEqual(ProjectRelativePath("dist/workshop").value, "dist/workshop")
        for value in ("../outside", "/absolute", "C:/drive", "src\\Ancient"):
            with self.subTest(value=value), self.assertRaises(ACMKError):
                ProjectRelativePath(value)

    def test_project_paths_reject_windows_ambiguous_characters(self) -> None:
        for value in (
            "src/bad?.art",
            "src/bad*.art",
            'src/bad"name',
            "src/control\x01",
            "src/CONIN$",
            "src/COM¹.txt",
            "src/LPT³",
        ):
            with self.subTest(value=value), self.assertRaises(ACMKError):
                ProjectRelativePath(value)


@unittest.skipUnless(os.name == "nt", "Windows junction behavior")
class WindowsReparsePointTests(SyntheticTempTestCase):
    def test_python311_compatible_guard_rejects_junction_ancestor(self) -> None:
        target = self.root / "junction-target"
        target.mkdir()
        junction = self.root / "junction"
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        if completed.returncode != 0:
            self.skipTest("junction creation unavailable")
        self.assertTrue(legacy.path_is_link_like(junction))
        with self.assertRaisesRegex(legacy.ModToolError, "symbolic link or junction"):
            legacy.assert_no_symlink_components(junction / "nested" / "output")


class ConfigTests(SyntheticTempTestCase):
    def test_config_toml_roundtrip(self) -> None:
        config = ProjectConfig(
            identifier="synthetic-sdk",
            name="Synthetic SDK",
            version="0.1.0",
            mod_type="FutureCustomType",
            compatibility=Compatibility(
                game_version="22",
                game_semver="1.9.3",
                steam_build_id="23915225",
                content_hash="ABCD",
            ),
            dependencies=("base-one",),
            conflicts=("old-pack",),
        )
        path = self.root / "acmk.toml"
        path.write_text(config.to_toml(), encoding="utf-8")
        self.assertEqual(ProjectConfig.load(path), config)
        self.assertEqual(config.to_dict(), tomllib.loads(config.to_toml()))

    def test_config_enforces_semver_relations_and_nonoverlapping_paths(self) -> None:
        compatibility = Compatibility(game_version="22")
        valid = ProjectConfig(
            identifier="semver-test",
            name="SemVer",
            version="1.2.3-alpha.1+build.7",
            mod_type="Generic",
            compatibility=compatibility,
        )
        self.assertEqual(valid.version, "1.2.3-alpha.1+build.7")
        for version in ("01.2.3", "1.02.3", "1.2.03", "1.2.3-01", "1.2.3-"):
            with self.subTest(version=version), self.assertRaises(ContractError):
                ProjectConfig(
                    identifier="semver-test",
                    name="SemVer",
                    version=version,
                    mod_type="Generic",
                    compatibility=compatibility,
                )
        with self.assertRaisesRegex(ContractError, "must not overlap"):
            acmk.ProjectPaths(
                source=ProjectRelativePath("src"),
                state=ProjectRelativePath("src/.acmk"),
            )
        with self.assertRaisesRegex(ContractError, "dependencies must be unique"):
            ProjectConfig(
                identifier="relation-test",
                name="Relations",
                version="1.0.0",
                mod_type="Generic",
                compatibility=compatibility,
                dependencies=("Base", "base"),
            )

    def test_json_schemas_are_valid_json(self) -> None:
        schema_root = importlib.resources.files("acmk.schemas")
        schema_paths = sorted(
            (path for path in schema_root.iterdir() if path.name.endswith(".json")),
            key=lambda path: path.name,
        )
        self.assertTrue(schema_paths)
        for path in schema_paths:
            with self.subTest(path=path):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")
                Draft202012Validator.check_schema(payload)

    def test_config_rejects_unknown_fields_before_canonical_rewrite(self) -> None:
        config = ProjectConfig(
            identifier="strict-config",
            name="Strict config",
            version="1.0.0",
            mod_type="Generic",
            compatibility=Compatibility(game_version="22"),
        )
        payload = config.to_toml().replace(
            "[project]\n", '[project]\nvendor_extension = "must-not-disappear"\n'
        )
        with self.assertRaisesRegex(ContractError, "unknown vendor_extension"):
            ProjectConfig.from_bytes(payload.encode("utf-8"))

    def test_published_schemas_accept_real_sdk_payloads(self) -> None:
        config = ProjectConfig(
            identifier="schema-test",
            name="Schema test",
            version="1.2.3-alpha.1+build.7",
            mod_type="Generic",
            compatibility=Compatibility(
                game_version="22",
                game_semver="1.9.3",
                steam_build_id="23915225",
                content_hash="ABCD",
            ),
        )
        Draft202012Validator(bundled_schema("acmk-project-v1.schema.json")).validate(
            config.to_dict()
        )
        observed = replace(config, skeleton=acmk.SkeletonSource.OBSERVED_CONSENSUS)
        self.assertEqual(ProjectConfig.from_bytes(observed.to_toml().encode("utf-8")), observed)
        Draft202012Validator(bundled_schema("acmk-project-v1.schema.json")).validate(
            observed.to_dict()
        )
        Draft202012Validator(bundled_schema("acmk-report-envelope-v1.schema.json")).validate(
            acmk.envelope("test", {})
        )


class ImportAndProjectTests(SyntheticTempTestCase):
    def test_game_skeleton_import_is_dry_run_then_atomic_apply(self) -> None:
        source = self.make_skeleton()
        target = self.root / "Authoring" / "synthetic-sdk"
        plan = ProjectImporter.plan(
            source,
            target,
            identifier="synthetic-sdk",
            context=self.context,
        )
        preview = plan.preview()
        self.assertFalse(target.exists())
        self.assertEqual(preview.mode.value, "dry-run")
        applied = plan.apply()
        self.assertEqual(applied.mode.value, "apply")
        self.assertTrue((target / "acmk.toml").is_file())
        self.assertTrue((target / "src" / "Index.art").is_file())
        self.assertTrue((target / "src" / "Ancient").is_dir())
        self.assertFalse((target / ".acmk" / "import.json").read_text().find(str(source)) >= 0)
        project = SDKProject.open(target, context=self.context)
        self.assertTrue(project.validate().valid)

    def test_project_configuration_is_preview_first_and_backed_up(self) -> None:
        source = self.make_skeleton("ConfigSkeleton")
        target = self.root / "configured-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="configured-project",
            context=self.context,
        ).apply()
        project = SDKProject.open(target, context=self.context)
        plan = project.plan_configuration(
            version="1.0.0",
            license="MIT",
            contact="https://github.com/example",
            provenance_status=acmk.ProvenanceStatus.REVIEWED,
            provenance_notes="Synthetic files created entirely by the test suite.",
        )
        self.assertEqual(plan.preview().mode.value, "dry-run")
        self.assertEqual(project.config.version, "0.1.0")
        applied = plan.apply()
        self.assertEqual(applied.mode.value, "apply")
        self.assertIsNotNone(applied.backup)
        reopened = SDKProject.open(target, context=self.context)
        self.assertEqual(reopened.config.version, "1.0.0")
        self.assertEqual(reopened.config.provenance_status.value, "reviewed")

    def test_mutating_plan_refuses_config_changed_after_open(self) -> None:
        source = self.make_skeleton("StaleConfigSkeleton")
        target = self.root / "stale-config-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="stale-config-project",
            context=self.context,
        ).apply()
        project = SDKProject.open(target, context=self.context)
        config_path = target / "acmk.toml"
        externally_changed = config_path.read_text(encoding="utf-8") + "\n"
        config_path.write_text(externally_changed, encoding="utf-8")
        with self.assertRaisesRegex(SourceChangedError, "reopen the project"):
            project.plan_configuration(license="MIT")
        self.assertEqual(config_path.read_text(encoding="utf-8"), externally_changed)

    def test_import_rejects_numeric_or_external_skeleton(self) -> None:
        numeric = self.make_skeleton("123")
        with self.assertRaisesRegex(ACMKError, "numeric"):
            ProjectImporter.plan(
                numeric, self.root / "target-one", identifier="target-one", context=self.context
            )
        external = self.root / "External"
        shutil.copytree(self.make_skeleton("ExternalSource"), external)
        with self.assertRaisesRegex(ACMKError, "discovered user Mod folder"):
            ProjectImporter.plan(
                external, self.root / "target-two", identifier="target-two", context=self.context
            )

    def test_import_snapshot_detects_same_size_source_change(self) -> None:
        source = self.root / "source.bin"
        destination = self.root / "destination.bin"
        source.write_bytes(b"AAAA")
        snapshot = FileSnapshot.capture(source, "source.bin")
        source.write_bytes(b"BBBB")
        with self.assertRaises(SourceChangedError):
            snapshot.copy_verified(destination)
        self.assertFalse(destination.exists())

    def test_public_plans_cannot_bypass_origin_or_draft_labels(self) -> None:
        source = self.make_skeleton("CanonicalPlan")
        canonical = ProjectImporter.plan(
            source,
            self.root / "canonical-target",
            identifier="canonical-target",
            context=self.context,
        )
        forged_source = self.root / "forged-source"
        shutil.copytree(source, forged_source)
        forged_import = acmk.ProjectImportPlan(
            forged_source,
            self.root / "forged-target",
            canonical.config,
            canonical.files,
            self.context,
        )
        with self.assertRaisesRegex(ACMKError, "discovered user Mod folder"):
            forged_import.preview()

        draft_builder = DraftProjectBuilder(
            self.root / "draft-forgery",
            identifier="draft-forgery",
            manifest=ManifestSpec(
                title="Draft forgery",
                description="Synthetic",
                changelog="Initial",
                game_version=GameVersion("22"),
            ),
            context=self.context,
        )
        draft = draft_builder.plan()
        with self.assertRaisesRegex(ContractError, "community-draft"):
            replace(
                draft,
                config=replace(draft.config, skeleton=acmk.SkeletonSource.GAME_GENERATED),
            )
        with self.assertRaisesRegex(ACMKError, "executable"):
            acmk.PlannedContent.create(AncientPath("Ancient/payload.dll"), b"synthetic")

    def test_observed_consensus_reconciliation_is_evidenced_and_resets_runtime(self) -> None:
        target = self.root / "consensus-project"
        builder = DraftProjectBuilder(
            target,
            identifier="consensus-project",
            manifest=ManifestSpec(
                title="Consensus project",
                description=(
                    "Only synthetic test data. License: MIT. Contact: https://github.com/example"
                ),
                changelog="Initial synthetic version",
                game_version=GameVersion("22"),
                content="Pre-reconciliation draft metadata",
            ),
            context=self.context,
            license="MIT",
            contact="https://github.com/example",
        )
        builder.set_thumbnail(synthetic_jpeg())
        builder.plan().apply()
        draft = SDKProject.open(target, context=self.context)
        self.assertIn(
            "RELEASE_NONCANONICAL_SKELETON",
            {issue.code for issue in draft.validate(ValidationProfile.RELEASE).issues},
        )

        log = self.root / "consensus-log.txt"
        log.write_bytes(
            (
                "[12:00:00] Ancient Cities.1.9.3\n"
                "[12:00:01] Enabling Mod: C:/Synthetic/Consensus (Consensus project)\n"
            ).encode("utf-16-le")
        )
        draft.plan_runtime_test(
            log,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
        ).apply()
        tested = SDKProject.open(target, context=self.context)
        self.assertEqual(tested.config.runtime_status, RuntimeStatus.PASSED)

        plan = tested.plan_observed_consensus()
        preview = plan.preview()
        self.assertEqual(preview.mode, acmk.ExecutionMode.DRY_RUN)
        self.assertTrue(preview.runtime_reset)
        self.assertEqual(tested.config.skeleton, acmk.SkeletonSource.COMMUNITY_DRAFT)
        forged = replace(plan, updated_config=replace(plan.updated_config, name="Forged"))
        with self.assertRaisesRegex(ContractError, "unauthorized"):
            forged.preview()

        applied = plan.apply()
        self.assertEqual(applied.mode, acmk.ExecutionMode.APPLY)
        self.assertIsNotNone(applied.config_backup)
        self.assertIsNotNone(applied.manifest_backup)
        assert applied.config_backup is not None and applied.manifest_backup is not None
        self.assertTrue(applied.config_backup.is_relative_to(target / ".acmk" / "backups"))
        self.assertTrue(applied.manifest_backup.is_relative_to(target / ".acmk" / "backups"))
        self.assertFalse((target / "src" / "Index.art.bak").exists())
        reopened = SDKProject.open(target, context=self.context)
        self.assertEqual(reopened.config.skeleton, acmk.SkeletonSource.OBSERVED_CONSENSUS)
        self.assertEqual(reopened.config.runtime_status, RuntimeStatus.UNTESTED)
        manifest = ManifestDocument.read(target / "src" / "Index.art")
        content_block = manifest.document.text.split('Name:"Content"', 1)[1].split("}", 1)[0]
        self.assertNotIn("Value:", content_block)
        evidence = json.loads((target / ".acmk" / "import.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], 2)
        self.assertEqual(evidence["source"], "observed-consensus")
        self.assertEqual(evidence["consensus_profile"], "generic-gv22-b23915225-v1")
        release_codes = {
            issue.code for issue in reopened.validate(ValidationProfile.RELEASE).issues
        }
        self.assertNotIn("RELEASE_NONCANONICAL_SKELETON", release_codes)
        self.assertIn("RELEASE_RUNTIME_UNTESTED", release_codes)
        self.assertNotIn("RELEASE_CONSENSUS_EVIDENCE_INVALID", release_codes)
        self.assertNotIn("RELEASE_CONSENSUS_MANIFEST_MISMATCH", release_codes)

        retest_log = self.root / "consensus-retest-log.txt"
        retest_log.write_bytes(
            (
                "[13:00:00] Ancient Cities.1.9.3\n"
                "[13:00:01] Enabling Mod: C:/Synthetic/Consensus (Consensus project)\n"
            ).encode("utf-16-le")
        )
        reopened.plan_runtime_test(
            retest_log,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
        ).apply()
        tested_again = SDKProject.open(target, context=self.context)
        manifest_before_rejected_update = (target / "src" / "Index.art").read_bytes()
        for field in ("Date", "Version"):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ContractError, "observed-consensus metadata updates"),
            ):
                tested_again.update_metadata({field: "synthetic"}, apply=True)
        self.assertEqual(
            (target / "src" / "Index.art").read_bytes(), manifest_before_rejected_update
        )
        metadata_result = tested_again.update_metadata(
            {
                "Changelog": "Metadata refreshed after reconciliation",
                "Content": "License: MIT. Contact: https://github.com/example",
            },
            apply=True,
            backup=False,
        )
        self.assertTrue(metadata_result["changed"])
        metadata_edited = SDKProject.open(target, context=self.context)
        stale_codes = {
            issue.code for issue in metadata_edited.validate(ValidationProfile.RELEASE).issues
        }
        self.assertIn("RELEASE_CONSENSUS_EVIDENCE_INVALID", stale_codes)

        refresh = metadata_edited.plan_observed_consensus()
        self.assertTrue(refresh.preview().runtime_reset)
        refresh.apply()
        refreshed = SDKProject.open(target, context=self.context)
        self.assertEqual(refreshed.config.runtime_status, RuntimeStatus.UNTESTED)
        refreshed_manifest = ManifestDocument.read(target / "src" / "Index.art")
        self.assertEqual(
            refreshed_manifest.fields["Content"],
            "License: MIT. Contact: https://github.com/example",
        )
        refreshed_codes = {
            issue.code for issue in refreshed.validate(ValidationProfile.RELEASE).issues
        }
        self.assertNotIn("RELEASE_CONSENSUS_EVIDENCE_INVALID", refreshed_codes)
        self.assertNotIn("RELEASE_CONSENSUS_MANIFEST_MISMATCH", refreshed_codes)
        evidence = json.loads((target / ".acmk" / "import.json").read_text(encoding="utf-8"))
        self.assertEqual(
            evidence["manifest_sha256"],
            hashlib.sha256((target / "src" / "Index.art").read_bytes()).hexdigest(),
        )

        evidence["consensus_profile"] = "forged-profile"
        (target / ".acmk" / "import.json").write_text(json.dumps(evidence), encoding="utf-8")
        tampered = SDKProject.open(target, context=self.context)
        tampered_codes = {
            issue.code for issue in tampered.validate(ValidationProfile.RELEASE).issues
        }
        self.assertIn("RELEASE_CONSENSUS_EVIDENCE_INVALID", tampered_codes)

        evidence["consensus_profile"] = "generic-gv22-b23915225-v1"
        evidence["manifest_sha256"] = "0" * 64
        (target / ".acmk" / "import.json").write_text(json.dumps(evidence), encoding="utf-8")
        digest_tampered = SDKProject.open(target, context=self.context)
        digest_tampered_codes = {
            issue.code for issue in digest_tampered.validate(ValidationProfile.RELEASE).issues
        }
        self.assertIn("RELEASE_CONSENSUS_EVIDENCE_INVALID", digest_tampered_codes)
        self.assertNotIn("RELEASE_CONSENSUS_MANIFEST_MISMATCH", digest_tampered_codes)

    def test_observed_consensus_rejects_linked_backup_directory(self) -> None:
        target = self.root / "linked-consensus-backups"
        builder = DraftProjectBuilder(
            target,
            identifier="linked-consensus-backups",
            manifest=ManifestSpec(
                title="Linked consensus backups",
                description="Only synthetic test data",
                changelog="Initial synthetic version",
                game_version=GameVersion("22"),
            ),
            context=self.context,
        )
        builder.set_thumbnail(synthetic_jpeg())
        builder.plan().apply()
        plan = SDKProject.open(target, context=self.context).plan_observed_consensus()

        external = self.root / "external-consensus-backups"
        external.mkdir()
        backup_root = target / ".acmk" / "backups"
        if os.name == "nt":
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(backup_root), str(external)],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
            if completed.returncode != 0:
                self.skipTest("junction creation unavailable")
        else:
            try:
                backup_root.symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

        with self.assertRaisesRegex(ACMKError, "symbolic links or junctions"):
            plan.apply()
        self.assertEqual(list(external.iterdir()), [])
        unchanged = SDKProject.open(target, context=self.context)
        self.assertEqual(unchanged.config.skeleton, acmk.SkeletonSource.COMMUNITY_DRAFT)

    def test_release_profile_and_isolated_preview(self) -> None:
        source = self.make_skeleton("ReleaseSkeleton")
        (source / "Ancient" / "payload.txt").write_bytes(b"synthetic")
        target = self.root / "release-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="release-project",
            license="MIT",
            contact="https://github.com/example",
            provenance_status=acmk.ProvenanceStatus.REVIEWED,
            provenance_notes="All synthetic fixtures were created by the test suite.",
            context=self.context,
        ).apply()
        project = SDKProject.open(target, context=self.context)
        blocked = project.validate(ValidationProfile.RELEASE)
        self.assertIn("RELEASE_RUNTIME_UNTESTED", {issue.code for issue in blocked.issues})

        log = self.root / "Log.txt"
        log.write_bytes(
            (
                "[12:00:00] Ancient Cities.1.9.3\n"
                "[12:00:01] Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
            ).encode("utf-16-le")
        )
        runtime_plan = project.plan_runtime_test(
            log,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
        )
        self.assertEqual(runtime_plan.preview().status, RuntimeStatus.PASSED)
        runtime_plan.apply()
        runtime_record = json.loads(
            (target / ".acmk" / "runtime-test.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(bundled_schema("acmk-runtime-test-v1.schema.json")).validate(
            runtime_record
        )
        ready = SDKProject.open(target, context=self.context)
        release_plan = ready.plan_release()
        release = release_plan.preview()
        self.assertFalse(ready.layout.distribution_root.joinpath("Mod.zip").exists())
        self.assertGreater(release.archive_size, 0)
        self.assertEqual(len(release.archive_sha256), 64)
        applied = release_plan.apply()
        self.assertEqual(applied.archive_sha256, release.archive_sha256)
        self.assertTrue((ready.layout.distribution_root / "Index.art").is_file())
        self.assertTrue((ready.layout.distribution_root / "Thumbnail.jpg").is_file())
        self.assertTrue((ready.layout.distribution_root / "Mod.zip").is_file())
        replaced = ready.plan_release().apply(replace=True)
        self.assertIsNotNone(replaced.backup)
        assert replaced.backup is not None
        self.assertTrue(replaced.backup.is_dir())

    def test_passing_runtime_record_rejects_error_log(self) -> None:
        source = self.make_skeleton("FailedLogSkeleton")
        target = self.root / "failed-log-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="failed-log-project",
            context=self.context,
        ).apply()
        log = self.root / "ErrorLog.txt"
        log.write_bytes("[12:00:00] ERROR synthetic failure\n".encode("utf-16-le"))
        project = SDKProject.open(target, context=self.context)
        with self.assertRaisesRegex(ACMKError, "contains 1 errors or failures"):
            project.plan_runtime_test(
                log,
                passed=True,
                save_impact=acmk.SaveImpact.UNKNOWN,
                achievement_impact=acmk.AchievementImpact.UNKNOWN,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            )

    def test_warning_baseline_allows_only_recurring_base_warnings(self) -> None:
        source = self.make_skeleton("WarningBaselineSkeleton")
        target = self.root / "warning-baseline-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="warning-baseline-project",
            context=self.context,
        ).apply()
        baseline = self.root / "BaselineLog.txt"
        baseline.write_bytes(
            (
                "[11:00:00] Ancient Cities.1.9.3\n"
                "[11:00:01] Enabling Mod: C:/BuiltIn/English (English)\n"
                "[11:00:02] Warning - [1] Node: '/Ancient/Menu/Base' Property: 'TextInput'\n"
            ).encode("utf-16-le")
        )
        runtime = self.root / "RuntimeWithBaseWarning.txt"
        runtime.write_bytes(
            (
                "[12:00:00] Ancient Cities.1.9.3\n"
                "[12:00:01] Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
                "[12:00:02.250] Warning - [1] Node: '/Ancient/Menu/Base' "
                "Property: 'TextInput'\n"
            ).encode("utf-16-le")
        )
        project = SDKProject.open(target, context=self.context)
        plan = project.plan_runtime_test(
            runtime,
            baseline_log_path=baseline,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
        )
        preview = plan.preview().to_dict()
        self.assertEqual(preview["warning_baseline"]["ignored_warnings"], 1)
        self.assertEqual(preview["warning_baseline"]["unmatched_warnings"], 0)
        preview_result = plan.preview()
        assert preview_result.warning_baseline is not None
        baseline_summary = preview_result.warning_baseline["log_summary"]
        assert isinstance(baseline_summary, Mapping)
        with self.assertRaises(TypeError):
            baseline_summary["warnings"] = 99  # type: ignore[index]
        serialized = preview_result.to_dict()
        serialized["warning_baseline"]["log_summary"]["warnings"] = 99
        self.assertEqual(preview_result.warning_baseline["log_summary"]["warnings"], 1)
        result = plan.apply()
        payload = json.loads(result.record_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["log_summary"]["warnings"], 1)
        self.assertEqual(
            payload["warning_baseline"]["algorithm"],
            "normalized-warning-signature-set-v1",
        )
        self.assertNotIn(str(baseline), json.dumps(payload))
        Draft202012Validator(bundled_schema("acmk-runtime-test-v2.schema.json")).validate(payload)
        codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", codes)

        payload["warning_baseline"]["algorithm"] = "normalized-warning-line-multiset-v1"
        result.record_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        Draft202012Validator(bundled_schema("acmk-runtime-test-v2.schema.json")).validate(payload)
        legacy_codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", legacy_codes)

    def test_warning_baseline_normalizes_only_leading_engine_occurrence_ordinal(self) -> None:
        source = self.make_skeleton("WarningOrdinalSkeleton")
        target = self.root / "warning-ordinal-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="warning-ordinal-project",
            context=self.context,
        ).apply()
        baseline = self.root / "OrdinalBaseline.txt"
        baseline.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Warning - [1] Node: '/Ancient/Menu/Base' Property: 'TextInput [7]'\n"
            ).encode("utf-16-le")
        )
        runtime = self.root / "OrdinalRuntime.txt"
        runtime.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
                "Warning - [1] Node: '/Ancient/Menu/Base' Property: 'TextInput [7]'\n"
                "Warning - [2] Node: '/Ancient/Menu/Base' Property: 'TextInput [7]'\n"
                "Warning - [3] Node: '/Ancient/Menu/Base' Property: 'TextInput [7]'\n"
                "Warning - [4] Node: '/Ancient/Menu/Base' Property: 'TextInput [7]'\n"
                "Warning - [5] Node: '/Ancient/Menu/Base' Property: 'TextInput [7]'\n"
            ).encode("utf-16-le")
        )
        project = SDKProject.open(target, context=self.context)
        plan = project.plan_runtime_test(
            runtime,
            baseline_log_path=baseline,
            passed=True,
            save_impact=acmk.SaveImpact.UNKNOWN,
            achievement_impact=acmk.AchievementImpact.UNKNOWN,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
        )
        preview = plan.preview().to_dict()
        self.assertEqual(preview["warning_baseline"]["ignored_warnings"], 5)
        self.assertEqual(preview["warning_baseline"]["unmatched_warnings"], 0)

        changed_payload = self.root / "ChangedOrdinalPayload.txt"
        changed_payload.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
                "Warning - [6] Node: '/Ancient/Menu/Base' Property: 'TextInput [8]'\n"
            ).encode("utf-16-le")
        )
        with self.assertRaisesRegex(ACMKError, "1 warnings not present in the warning baseline"):
            project.plan_runtime_test(
                changed_payload,
                baseline_log_path=baseline,
                passed=True,
                save_impact=acmk.SaveImpact.UNKNOWN,
                achievement_impact=acmk.AchievementImpact.UNKNOWN,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            )

        result = plan.apply()
        payload = json.loads(result.record_path.read_text(encoding="utf-8"))
        codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", codes)

        payload["warning_baseline"]["algorithm"] = "normalized-warning-line-multiset-v1"
        result.record_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        legacy_codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertIn("RELEASE_RUNTIME_EVIDENCE_INVALID", legacy_codes)

    def test_warning_baseline_does_not_hide_candidate_warning_or_error(self) -> None:
        source = self.make_skeleton("WarningDifferentialSkeleton")
        target = self.root / "warning-differential-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="warning-differential-project",
            context=self.context,
        ).apply()
        baseline = self.root / "DifferentialBaseline.txt"
        baseline.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Warning - recurring base warning\n"
                "ERROR recurring base error\n"
            ).encode("utf-16-le")
        )
        candidate_warning = self.root / "CandidateWarning.txt"
        candidate_warning.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
                "Warning - recurring base warning\n"
                "Warning - candidate mesh mismatch\n"
            ).encode("utf-16-le")
        )
        project = SDKProject.open(target, context=self.context)
        with self.assertRaisesRegex(ACMKError, "1 warnings not present in the warning baseline"):
            project.plan_runtime_test(
                candidate_warning,
                baseline_log_path=baseline,
                passed=True,
                save_impact=acmk.SaveImpact.UNKNOWN,
                achievement_impact=acmk.AchievementImpact.UNKNOWN,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            )

        duplicate_warning = self.root / "DuplicateBaseWarning.txt"
        duplicate_warning.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
                "Warning - recurring base warning\n"
                "Warning - recurring base warning\n"
            ).encode("utf-16-le")
        )
        duplicate_plan = project.plan_runtime_test(
            duplicate_warning,
            baseline_log_path=baseline,
            passed=True,
            save_impact=acmk.SaveImpact.UNKNOWN,
            achievement_impact=acmk.AchievementImpact.UNKNOWN,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
        )
        duplicate_preview = duplicate_plan.preview().to_dict()
        self.assertEqual(duplicate_preview["warning_baseline"]["ignored_warnings"], 2)
        self.assertEqual(duplicate_preview["warning_baseline"]["unmatched_warnings"], 0)

        candidate_error = self.root / "CandidateError.txt"
        candidate_error.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
                "ERROR recurring base error\n"
            ).encode("utf-16-le")
        )
        with self.assertRaisesRegex(ACMKError, "1 errors or failures"):
            project.plan_runtime_test(
                candidate_error,
                baseline_log_path=baseline,
                passed=True,
                save_impact=acmk.SaveImpact.UNKNOWN,
                achievement_impact=acmk.AchievementImpact.UNKNOWN,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            )

    def test_warning_baseline_must_predate_candidate_and_remain_unchanged(self) -> None:
        source = self.make_skeleton("BaselineIntegritySkeleton")
        target = self.root / "baseline-integrity-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="baseline-integrity-project",
            context=self.context,
        ).apply()
        runtime = self.root / "BaselineIntegrityRuntime.txt"
        runtime.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
                "Warning - recurring base warning\n"
            ).encode("utf-16-le")
        )
        invalid_baseline = self.root / "CandidateEnabledBaseline.txt"
        invalid_baseline.write_bytes(runtime.read_bytes())
        project = SDKProject.open(target, context=self.context)
        with self.assertRaisesRegex(ACMKError, "baseline enables the tested mod"):
            project.plan_runtime_test(
                runtime,
                baseline_log_path=invalid_baseline,
                passed=True,
                save_impact=acmk.SaveImpact.UNKNOWN,
                achievement_impact=acmk.AchievementImpact.UNKNOWN,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            )

        baseline = self.root / "StableBaseline.txt"
        baseline.write_bytes(
            ("Ancient Cities.1.9.3\nWarning - recurring base warning\n").encode("utf-16-le")
        )
        plan = project.plan_runtime_test(
            runtime,
            baseline_log_path=baseline,
            passed=True,
            save_impact=acmk.SaveImpact.UNKNOWN,
            achievement_impact=acmk.AchievementImpact.UNKNOWN,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
        )
        baseline.write_bytes(
            ("Ancient Cities.1.9.3\nWarning - changed base warning\n").encode("utf-16-le")
        )
        with self.assertRaisesRegex(SourceChangedError, "baseline Log.txt changed"):
            plan.preview()

    def test_failed_runtime_record_matches_schema_and_reports_backups(self) -> None:
        source = self.make_skeleton("FailedEvidenceSkeleton")
        target = self.root / "failed-evidence-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="failed-evidence-project",
            context=self.context,
        ).apply()
        config_path = target / "acmk.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8") + "# user note preserved in backup\n",
            encoding="utf-8",
        )
        log = self.root / "FailedEvidenceLog.txt"
        log.write_bytes("[12:00:00] ERROR synthetic failure\n".encode("utf-16-le"))
        result = (
            SDKProject.open(target, context=self.context)
            .plan_runtime_test(
                log,
                passed=False,
                save_impact=acmk.SaveImpact.UNKNOWN,
                achievement_impact=acmk.AchievementImpact.UNKNOWN,
                clean_launch=False,
                save_type=acmk.RuntimeSaveType.NO_SAVE,
            )
            .apply()
        )
        self.assertIsNotNone(result.config_backup)
        assert result.config_backup is not None
        self.assertIn(
            "user note preserved in backup",
            result.config_backup.read_text(encoding="utf-8"),
        )
        self.assertIsNone(result.record_backup)
        payload = json.loads(result.record_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["environment"]["tested_mod"], "")
        self.assertEqual(payload["environment"]["observed_game_semver"], "")
        Draft202012Validator(bundled_schema("acmk-runtime-test-v1.schema.json")).validate(payload)

    def test_runtime_log_must_remain_outside_project(self) -> None:
        source = self.make_skeleton("InternalLogSkeleton")
        target = self.root / "internal-log-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="internal-log-project",
            context=self.context,
        ).apply()
        internal_log = target / "src" / "Log.txt"
        internal_log.write_bytes("synthetic\n".encode("utf-16-le"))
        project = SDKProject.open(target, context=self.context)
        with self.assertRaisesRegex(ACMKError, "outside the ACMK project tree"):
            project.plan_runtime_test(
                internal_log,
                passed=False,
                save_impact=acmk.SaveImpact.UNKNOWN,
                achievement_impact=acmk.AchievementImpact.UNKNOWN,
                clean_launch=False,
                save_type=acmk.RuntimeSaveType.NO_SAVE,
            )

    def test_none_observed_save_impact_requires_existing_save_test(self) -> None:
        source = self.make_skeleton("SaveEvidenceSkeleton")
        target = self.root / "save-evidence-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="save-evidence-project",
            context=self.context,
        ).apply()
        log = self.root / "SaveEvidenceLog.txt"
        log.write_bytes(
            ("Ancient Cities.1.9.3\nEnabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n").encode(
                "utf-16-le"
            )
        )
        project = SDKProject.open(target, context=self.context)
        with self.assertRaisesRegex(ACMKError, "existing-disposable save test"):
            project.plan_runtime_test(
                log,
                passed=True,
                save_impact=acmk.SaveImpact.NONE_OBSERVED,
                achievement_impact=acmk.AchievementImpact.NONE_OBSERVED,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            )

    def test_release_promotes_broken_content_and_mod_type_mismatch(self) -> None:
        source = self.make_skeleton("ReleaseStrictSkeleton")
        target = self.root / "release-strict-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="release-strict-project",
            context=self.context,
        ).apply()
        manifest = ManifestDocument.read(target / "src" / "Index.art")
        (target / "src" / "Index.art").write_bytes(
            manifest.updated({"Type": "DifferentType"}).document.to_bytes()
        )
        report = SDKProject.open(target, context=self.context).validate(ValidationProfile.RELEASE)
        severity = {issue.code: issue.severity for issue in report.issues}
        self.assertEqual(severity["CONFIG_MOD_TYPE_MISMATCH"], acmk.Severity.ERROR)
        self.assertEqual(severity["CONTENT_EMPTY"], acmk.Severity.ERROR)

    def test_passing_runtime_record_must_identify_this_mod_and_game(self) -> None:
        source = self.make_skeleton("WrongModLogSkeleton")
        target = self.root / "wrong-mod-log-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="wrong-mod-log-project",
            context=self.context,
        ).apply()
        log = self.root / "OtherModLog.txt"
        log.write_bytes("Ancient Cities.1.9.3\nEnabling Mod: Some Other Mod\n".encode("utf-16-le"))
        project = SDKProject.open(target, context=self.context)
        with self.assertRaisesRegex(ACMKError, "no exact enabled entry"):
            project.plan_runtime_test(
                log,
                passed=True,
                save_impact=acmk.SaveImpact.NONE_OBSERVED,
                achievement_impact=acmk.AchievementImpact.NONE_OBSERVED,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            )

    def test_release_rejects_source_changed_after_runtime_test(self) -> None:
        source = self.make_skeleton("ChangedAfterTest")
        target = self.root / "changed-after-test"
        ProjectImporter.plan(
            source,
            target,
            identifier="changed-after-test",
            license="MIT",
            contact="https://github.com/example",
            provenance_status=acmk.ProvenanceStatus.REVIEWED,
            provenance_notes="All synthetic fixtures were created by the test suite.",
            context=self.context,
        ).apply()
        log = self.root / "CleanLog.txt"
        log.write_bytes(
            (
                "[12:00:00] Ancient Cities.1.9.3\n"
                "[12:00:01] Enabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n"
            ).encode("utf-16-le")
        )
        project = SDKProject.open(target, context=self.context)
        project.plan_runtime_test(
            log,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
        ).apply()
        (target / "src" / "Ancient" / "changed.txt").write_text("changed", encoding="utf-8")
        reopened = SDKProject.open(target, context=self.context)
        codes = {issue.code for issue in reopened.validate(ValidationProfile.RELEASE).issues}
        self.assertIn("RELEASE_SOURCE_CHANGED_AFTER_TEST", codes)

    def test_draft_builder_is_typed_and_release_blocked(self) -> None:
        target = self.root / "draft-project"
        spec = ManifestSpec(
            title="Synthetic Draft",
            description="Generated test data",
            changelog="Initial",
            game_version=GameVersion("22"),
        )
        builder = DraftProjectBuilder(
            target,
            identifier="draft-project",
            manifest=spec,
            context=self.context,
        )
        builder.add_art("Entity/Synthetic/Index.art", "Node:{}\n")
        builder.set_thumbnail(synthetic_jpeg())
        plan = builder.plan()
        self.assertFalse(target.exists())
        plan.apply()
        project = SDKProject.open(target, context=self.context)
        codes = {issue.code for issue in project.validate(ValidationProfile.RELEASE).issues}
        self.assertIn("RELEASE_NONCANONICAL_SKELETON", codes)
        self.assertEqual(
            (target / "src" / "Ancient" / "Entity" / "Synthetic" / "Index.art").read_bytes()[:2],
            codecs.BOM_UTF16_LE,
        )


class CliContractTests(unittest.TestCase):
    def test_default_success_output_is_unwrapped_pretty_json(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli_main(["sdk-info"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertNotIn("schema_version", payload)
        self.assertNotIn("issues", payload)
        self.assertFalse(payload["publishes_workshop_items"])

    def test_default_error_output_is_unwrapped_pretty_json(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli_main(["knowledge", "read", "definitely-not-a-topic"])
        issue = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertNotIn("schema_version", issue)
        self.assertEqual(issue["code"], "KNOWLEDGE_TOPIC_UNKNOWN")

    def test_sdk_info_uses_versioned_json_envelope(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli_main(["--json", "sdk-info"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "sdk-info")
        self.assertEqual(payload["issues"], [])
        self.assertFalse(payload["data"]["publishes_workshop_items"])

    def test_json_error_uses_versioned_envelope(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli_main(["--json", "knowledge", "read", "definitely-not-a-topic"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "knowledge.read")
        self.assertEqual(payload["issues"][0]["code"], "KNOWLEDGE_TOPIC_UNKNOWN")

    def test_python_api_errors_have_stable_serialization(self) -> None:
        error = ContractError("synthetic", code="SYNTHETIC_ERROR", path="fixture")
        self.assertEqual(
            error.to_dict(),
            {"code": "SYNTHETIC_ERROR", "message": "synthetic", "path": "fixture"},
        )


if __name__ == "__main__":
    unittest.main()

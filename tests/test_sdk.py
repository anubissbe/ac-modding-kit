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
from acmk.project import FileSnapshot, _capture_source_tree

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
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
        )
        self.assertEqual(runtime_plan.preview().status, RuntimeStatus.PASSED)
        runtime_plan.apply()
        runtime_record = json.loads(
            (target / ".acmk" / "runtime-test.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(bundled_schema("acmk-runtime-test-v3.schema.json")).validate(
            runtime_record
        )
        ready = SDKProject.open(target, context=self.context)
        release_plan = ready.plan_release()
        release = release_plan.preview()
        self.assertFalse(ready.layout.distribution_root.joinpath("Mod.zip").exists())
        self.assertGreater(release.archive_size, 0)
        self.assertEqual(len(release.archive_sha256), 64)
        preview_payload = release.to_dict()
        for legacy_key in (
            "mode",
            "output_directory",
            "archive",
            "backup",
            "validation",
        ):
            self.assertIn(legacy_key, preview_payload)
        self.assertEqual(
            [artifact.name for artifact in release.artifacts],
            ["Index.art", "Thumbnail.jpg", "Mod.zip"],
        )
        self.assertEqual(
            list(preview_payload["artifacts"]),
            ["Index.art", "Thumbnail.jpg", "Mod.zip"],
        )
        for artifact_name in ("Index.art", "Thumbnail.jpg"):
            source_bytes = (ready.layout.source_root / artifact_name).read_bytes()
            artifact = preview_payload["artifacts"][artifact_name]
            self.assertEqual(
                artifact["path"],
                str(ready.layout.distribution_root / artifact_name),
            )
            self.assertEqual(artifact["bytes"], len(source_bytes))
            self.assertEqual(artifact["sha256"], hashlib.sha256(source_bytes).hexdigest())
        self.assertEqual(
            preview_payload["artifacts"]["Mod.zip"],
            {
                "path": str(ready.layout.distribution_root / "Mod.zip"),
                "bytes": preview_payload["archive"]["bytes"],
                "sha256": preview_payload["archive"]["sha256"],
            },
        )
        self.assertEqual(preview_payload["archive"]["bytes"], release.archive_size)
        self.assertEqual(preview_payload["archive"]["sha256"], release.archive_sha256)
        self.assertEqual(preview_payload["archive"]["members"], list(release.members))
        applied = release_plan.apply()
        self.assertEqual(applied.archive_sha256, release.archive_sha256)
        self.assertTrue((ready.layout.distribution_root / "Index.art").is_file())
        self.assertTrue((ready.layout.distribution_root / "Thumbnail.jpg").is_file())
        self.assertTrue((ready.layout.distribution_root / "Mod.zip").is_file())
        applied_payload = applied.to_dict()
        self.assertEqual(applied_payload["artifacts"], preview_payload["artifacts"])
        for artifact_name, artifact in applied_payload["artifacts"].items():
            artifact_bytes = (ready.layout.distribution_root / artifact_name).read_bytes()
            self.assertEqual(artifact["bytes"], len(artifact_bytes))
            self.assertEqual(artifact["sha256"], hashlib.sha256(artifact_bytes).hexdigest())
        replaced = ready.plan_release().apply(replace=True)
        self.assertIsNotNone(replaced.backup)
        assert replaced.backup is not None
        self.assertTrue(replaced.backup.is_dir())
        self.assertEqual(replaced.to_dict()["artifacts"], preview_payload["artifacts"])

    def test_runtime_v3_hashes_explicit_loose_root_and_ignores_empty_mod_hms(self) -> None:
        source = self.make_skeleton("ExplicitTestedSourceSkeleton")
        (source / "Ancient" / "payload.txt").write_bytes(b"tested payload")
        target = self.root / "explicit-tested-source-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="explicit-tested-source-project",
            context=self.context,
        ).apply()
        (source / "Mod.hms").write_bytes(b"")
        log = self.root / "ExplicitTestedSourceLog.txt"
        log.write_bytes(
            ("Ancient Cities.1.9.3\nEnabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n").encode(
                "utf-16-le"
            )
        )
        plan = SDKProject.open(target, context=self.context).plan_runtime_test(
            log,
            tested_source=source,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
        )
        preview = plan.preview()
        self.assertEqual(preview.tested_source, source)
        self.assertEqual(preview.source_fingerprint.files, 3)
        (source / "Mod.hms").unlink()
        result = plan.apply()
        payload = json.loads(result.record_path.read_text(encoding="utf-8"))
        runtime_schema = Draft202012Validator(bundled_schema("acmk-runtime-test-v3.schema.json"))
        runtime_schema.validate(payload)
        for key in ("lines", "mods_enabled"):
            invalid = json.loads(json.dumps(payload))
            invalid["log_summary"][key] = 0
            self.assertFalse(runtime_schema.is_valid(invalid), key)
        warning_without_baseline = json.loads(json.dumps(payload))
        warning_without_baseline["log_summary"]["warnings"] = 1
        self.assertFalse(runtime_schema.is_valid(warning_without_baseline))
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(payload["source_fingerprint"]["algorithm"], "sha256-loose-mod-v1")
        self.assertEqual(
            payload["environment"]["save_persistence"],
            "manual-save-reload-passed",
        )
        self.assertNotIn(str(source), json.dumps(payload))
        codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertNotIn("RELEASE_SOURCE_CHANGED_AFTER_TEST", codes)
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", codes)
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_MIGRATION_REQUIRED", codes)

    def test_release_blocks_when_explicit_tested_loose_root_differs_from_src(self) -> None:
        source = self.make_skeleton("MismatchedTestedSourceSkeleton")
        (source / "Ancient" / "payload.txt").write_bytes(b"canonical payload")
        target = self.root / "mismatched-tested-source-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="mismatched-tested-source-project",
            context=self.context,
        ).apply()
        (source / "Ancient" / "payload.txt").write_bytes(b"different deployed payload")
        log = self.root / "MismatchedTestedSourceLog.txt"
        log.write_bytes(
            ("Ancient Cities.1.9.3\nEnabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n").encode(
                "utf-16-le"
            )
        )
        SDKProject.open(target, context=self.context).plan_runtime_test(
            log,
            tested_source=source,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
        ).apply()
        codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertIn("RELEASE_SOURCE_CHANGED_AFTER_TEST", codes)
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", codes)

    def test_runtime_v3_rejects_unscoped_tested_source_files_and_bad_persistence(self) -> None:
        source = self.make_skeleton("StrictTestedSourceSkeleton")
        target = self.root / "strict-tested-source-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="strict-tested-source-project",
            context=self.context,
        ).apply()
        log = self.root / "StrictTestedSourceLog.txt"
        log.write_bytes(
            ("Ancient Cities.1.9.3\nEnabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n").encode(
                "utf-16-le"
            )
        )
        project = SDKProject.open(target, context=self.context)
        (source / "Mod.hms").write_bytes(b"game state")
        with self.assertRaisesRegex(ACMKError, "only an empty game-managed Mod.hms"):
            project.plan_runtime_test(
                log,
                tested_source=source,
                passed=True,
                save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
                achievement_impact=acmk.AchievementImpact.DISABLED,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
            )
        (source / "Mod.hms").unlink()
        (source / "notes.txt").write_text("not runtime content", encoding="utf-8")
        with self.assertRaisesRegex(ACMKError, "unexpected root entries"):
            project.plan_runtime_test(
                log,
                tested_source=source,
                passed=True,
                save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
                achievement_impact=acmk.AchievementImpact.DISABLED,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
            )
        (source / "notes.txt").unlink()
        with self.assertRaisesRegex(ACMKError, "manual-save-reload-passed"):
            project.plan_runtime_test(
                log,
                tested_source=source,
                passed=True,
                save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
                achievement_impact=acmk.AchievementImpact.DISABLED,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.EXISTING_DISPOSABLE,
                save_persistence=acmk.SavePersistence.NOT_TESTED,
            )
        with self.assertRaisesRegex(ContractError, "no-save.*not-applicable"):
            project.plan_runtime_test(
                log,
                tested_source=source,
                passed=False,
                save_impact=acmk.SaveImpact.UNKNOWN,
                achievement_impact=acmk.AchievementImpact.UNKNOWN,
                clean_launch=False,
                save_type=acmk.RuntimeSaveType.NO_SAVE,
                save_persistence=acmk.SavePersistence.FAILED,
            )

    def test_v1_and_v2_runtime_evidence_stays_readable_but_requires_v3_rerecord(self) -> None:
        source = self.make_skeleton("LegacyRuntimeEvidenceSkeleton")
        target = self.root / "legacy-runtime-evidence-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="legacy-runtime-evidence-project",
            context=self.context,
        ).apply()
        log = self.root / "LegacyRuntimeEvidenceLog.txt"
        log.write_bytes(
            ("Ancient Cities.1.9.3\nEnabling Mod: C:/Synthetic/123 (Synthetic SDK Mod)\n").encode(
                "utf-16-le"
            )
        )
        result = (
            SDKProject.open(target, context=self.context)
            .plan_runtime_test(
                log,
                tested_source=source,
                passed=True,
                save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
                achievement_impact=acmk.AchievementImpact.DISABLED,
                clean_launch=True,
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
            )
            .apply()
        )
        v1 = json.loads(result.record_path.read_text(encoding="utf-8"))
        v1["schema_version"] = 1
        del v1["environment"]["save_persistence"]
        v1["source_fingerprint"] = _capture_source_tree(target / "src")[1].to_dict()
        Draft202012Validator(bundled_schema("acmk-runtime-test-v1.schema.json")).validate(v1)
        result.record_path.write_text(json.dumps(v1, indent=2) + "\n", encoding="utf-8")
        v1_codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertIn("RELEASE_RUNTIME_EVIDENCE_MIGRATION_REQUIRED", v1_codes)
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", v1_codes)
        self.assertNotIn("RELEASE_SOURCE_CHANGED_AFTER_TEST", v1_codes)

        v2 = dict(v1)
        v2["schema_version"] = 2
        v2["warning_baseline"] = {
            "algorithm": "normalized-warning-signature-set-v1",
            "log_sha256": "0" * 64,
            "log_summary": {
                "lines": 1,
                "warnings": 0,
                "errors_or_failures": 0,
                "mods_enabled": 0,
            },
            "ignored_warnings": 0,
            "unmatched_warnings": 0,
        }
        Draft202012Validator(bundled_schema("acmk-runtime-test-v2.schema.json")).validate(v2)
        result.record_path.write_text(json.dumps(v2, indent=2) + "\n", encoding="utf-8")
        v2_codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertIn("RELEASE_RUNTIME_EVIDENCE_MIGRATION_REQUIRED", v2_codes)
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", v2_codes)
        self.assertNotIn("RELEASE_SOURCE_CHANGED_AFTER_TEST", v2_codes)

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
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
            )

    def test_exact_achievement_warning_is_expected_only_when_impact_is_disabled(self) -> None:
        source = self.make_skeleton("ExpectedAchievementWarningSkeleton")
        target = self.root / "expected-achievement-warning-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="expected-achievement-warning-project",
            context=self.context,
        ).apply()
        log = self.root / "ExpectedAchievementWarning.txt"
        log.write_bytes(
            (
                "[12:00:00] Ancient Cities.1.9.3\n"
                "[12:00:01] Warning - This enabled Mod has *.art files that disables "
                "Achievements: [3768682609] (Synthetic SDK Mod)\n"
                "[12:00:02] Enabling Mod: C:/Synthetic/3768682609 (Synthetic SDK Mod)\n"
            ).encode("utf-16-le")
        )
        project = SDKProject.open(target, context=self.context)
        with self.assertRaisesRegex(ACMKError, "contains 1 warnings"):
            project.plan_runtime_test(
                log,
                passed=True,
                save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
                achievement_impact=acmk.AchievementImpact.NONE_OBSERVED,
                clean_launch=True,
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
            )

        plan = project.plan_runtime_test(
            log,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
        )
        self.assertEqual(plan.preview().log_summary["warnings"], 0)
        result = plan.apply()
        payload = json.loads(result.record_path.read_text(encoding="utf-8"))
        Draft202012Validator(bundled_schema("acmk-runtime-test-v3.schema.json")).validate(payload)
        self.assertEqual(payload["log_summary"]["warnings"], 0)
        codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", codes)

    def test_achievement_warning_allowance_is_exact_and_preserves_baseline_strictness(
        self,
    ) -> None:
        source = self.make_skeleton("StrictAchievementWarningSkeleton")
        target = self.root / "strict-achievement-warning-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="strict-achievement-warning-project",
            context=self.context,
        ).apply()
        baseline = self.root / "StrictAchievementBaseline.txt"
        baseline.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Enabling Mod: C:/BuiltIn/English (English)\n"
                "Warning - recurring base warning\n"
            ).encode("utf-16-le")
        )
        runtime = self.root / "StrictAchievementRuntime.txt"
        runtime.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Warning - This enabled Mod has *.art files that disables Achievements: "
                "[3768682609] (Synthetic SDK Mod)\n"
                "Enabling Mod: C:/Synthetic/3768682609 (Synthetic SDK Mod)\n"
                "Warning - recurring base warning\n"
                "Warning - candidate mesh mismatch\n"
            ).encode("utf-16-le")
        )
        project = SDKProject.open(target, context=self.context)
        with self.assertRaisesRegex(ACMKError, "1 warnings not present in the warning baseline"):
            project.plan_runtime_test(
                runtime,
                baseline_log_path=baseline,
                passed=True,
                save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
                achievement_impact=acmk.AchievementImpact.DISABLED,
                clean_launch=True,
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
            )

        wrong_title = self.root / "WrongAchievementTitle.txt"
        wrong_title.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Warning - This enabled Mod has *.art files that disables Achievements: "
                "[3768682609] (Another Mod)\n"
                "Enabling Mod: C:/Synthetic/3768682609 (Synthetic SDK Mod)\n"
            ).encode("utf-16-le")
        )
        with self.assertRaisesRegex(ACMKError, "contains 1 warnings"):
            project.plan_runtime_test(
                wrong_title,
                passed=True,
                save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
                achievement_impact=acmk.AchievementImpact.DISABLED,
                clean_launch=True,
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
            )

        clean_runtime = self.root / "ExpectedAchievementWithBaseline.txt"
        clean_runtime.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                "Warning - This enabled Mod has *.art files that disables Achievements: "
                "[3768682609] (Synthetic SDK Mod)\n"
                "Enabling Mod: C:/Synthetic/3768682609 (Synthetic SDK Mod)\n"
                "Warning - recurring base warning\n"
            ).encode("utf-16-le")
        )
        preview = project.plan_runtime_test(
            clean_runtime,
            baseline_log_path=baseline,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
        ).preview()
        self.assertEqual(preview.log_summary["warnings"], 1)
        assert preview.warning_baseline is not None
        self.assertEqual(preview.warning_baseline["ignored_warnings"], 1)
        self.assertEqual(preview.warning_baseline["unmatched_warnings"], 0)

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
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(payload["log_summary"]["warnings"], 1)
        self.assertEqual(
            payload["warning_baseline"]["algorithm"],
            "normalized-warning-signature-set-v1",
        )
        self.assertNotIn(str(baseline), json.dumps(payload))
        Draft202012Validator(bundled_schema("acmk-runtime-test-v3.schema.json")).validate(payload)
        codes = {
            issue.code
            for issue in SDKProject.open(target, context=self.context)
            .validate(ValidationProfile.RELEASE)
            .issues
        }
        self.assertNotIn("RELEASE_RUNTIME_EVIDENCE_INVALID", codes)

        payload["warning_baseline"]["algorithm"] = "normalized-warning-line-multiset-v1"
        result.record_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        Draft202012Validator(bundled_schema("acmk-runtime-test-v3.schema.json")).validate(payload)
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
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
            )

    def test_warning_baseline_may_enable_candidate_but_must_remain_unchanged(self) -> None:
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
        same_target_baseline = self.root / "CandidateEnabledBaseline.txt"
        same_target_baseline.write_bytes(runtime.read_bytes())
        project = SDKProject.open(target, context=self.context)
        plan = project.plan_runtime_test(
            runtime,
            baseline_log_path=same_target_baseline,
            passed=True,
            save_impact=acmk.SaveImpact.UNKNOWN,
            achievement_impact=acmk.AchievementImpact.UNKNOWN,
            clean_launch=True,
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
        )
        preview = plan.preview().to_dict()
        self.assertEqual(preview["warning_baseline"]["ignored_warnings"], 1)
        self.assertEqual(preview["warning_baseline"]["unmatched_warnings"], 0)
        same_target_baseline.write_bytes(
            ("Ancient Cities.1.9.3\nWarning - changed base warning\n").encode("utf-16-le")
        )
        with self.assertRaisesRegex(SourceChangedError, "baseline Log.txt changed"):
            plan.preview()

    def test_same_ten_mod_clean_launch_baseline_supports_save_reload_evidence(self) -> None:
        source = self.make_skeleton("CombinedTenModEvidenceSkeleton")
        target = self.root / "combined-ten-mod-evidence-project"
        ProjectImporter.plan(
            source,
            target,
            identifier="combined-ten-mod-evidence-project",
            context=self.context,
        ).apply()
        enabled_lines = [
            f"Enabling Mod: C:/Synthetic/{index} (Synthetic companion {index})"
            for index in range(1, 10)
        ]
        enabled_lines.append("Enabling Mod: C:/Synthetic/10 (Synthetic SDK Mod)")
        baseline = self.root / "CombinedTenModCleanLaunch.txt"
        baseline.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                + "\n".join(enabled_lines)
                + "\nWarning - recurring combined-mod warning\n"
            ).encode("utf-16-le")
        )
        candidate = self.root / "CombinedTenModAfterSaveReload.txt"
        candidate.write_bytes(
            (
                "Ancient Cities.1.9.3\n"
                + "\n".join(enabled_lines)
                + "\nWarning - recurring combined-mod warning\n"
                + "Manual save completed\nFull exit and restart completed\n"
                + "Disposable save reloaded\n"
            ).encode("utf-16-le")
        )
        plan = SDKProject.open(target, context=self.context).plan_runtime_test(
            candidate,
            tested_source=source,
            baseline_log_path=baseline,
            passed=True,
            save_impact=acmk.SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=acmk.AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=acmk.RuntimeSaveType.EXISTING_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
        )
        preview = plan.preview().to_dict()
        self.assertEqual(preview["log_summary"]["mods_enabled"], 10)
        self.assertEqual(preview["warning_baseline"]["ignored_warnings"], 1)
        self.assertEqual(preview["warning_baseline"]["unmatched_warnings"], 0)
        result = plan.apply()
        payload = json.loads(result.record_path.read_text(encoding="utf-8"))
        Draft202012Validator(bundled_schema("acmk-runtime-test-v3.schema.json")).validate(payload)

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
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NO_SAVE,
                save_persistence=acmk.SavePersistence.NOT_APPLICABLE,
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
        Draft202012Validator(bundled_schema("acmk-runtime-test-v3.schema.json")).validate(payload)

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
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NO_SAVE,
                save_persistence=acmk.SavePersistence.NOT_APPLICABLE,
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
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
                tested_source=target / "src",
                save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
                save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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
            tested_source=target / "src",
            save_type=acmk.RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=acmk.SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
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

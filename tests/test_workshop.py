"""Synthetic contract tests for Workshop preparation and identity synchronization."""

from __future__ import annotations

import codecs
import copy
import hashlib
import json
import shutil
import unittest
import uuid
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

import ancient_cities_mod as legacy
from acmk import (
    AchievementImpact,
    ManifestDocument,
    ProjectImporter,
    ProvenanceStatus,
    RuntimeSaveType,
    RuntimeStatus,
    SaveImpact,
    SavePersistence,
    SDKProject,
    SteamModId,
)
from acmk.errors import ContractError, ProjectError, SourceChangedError, ValidationFailedError
from acmk.workshop import (
    CandidateKind,
    PublishAction,
    VisibilityControl,
    WorkshopArtifact,
    WorkshopState,
    WorkshopStatus,
    WorkshopVisibility,
    plan_workshop_sync,
    prepare_publish_packet,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSHOP_SCHEMA = REPO_ROOT / "schemas" / "acmk-workshop-state-v1.schema.json"


def synthetic_jpeg(width: int = 512, height: int = 512) -> bytes:
    sof = b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big")
    sof += b"\x01\x01\x11\x00"
    return b"\xff\xd8\xff\xc0" + (len(sof) + 2).to_bytes(2, "big") + sof + b"\xff\xd9"


def manifest_bytes(*, steam_mod_id: str = "0,0") -> bytes:
    text = legacy.canonical_manifest(
        title="Synthetic Workshop Mod",
        description="Synthetic test data. License: MIT. Contact: https://github.com/example",
        changelog="Initial synthetic version",
        game_version="22",
        mod_type="Generic",
        steam_mod_id=steam_mod_id,
    )
    return codecs.BOM_UTF16_LE + text.encode("utf-16-le")


def without_manifest_blocks(payload: bytes, names: set[str]) -> bytes:
    text = legacy.decode_utf16le_art(payload)
    spans: dict[str, tuple[int, int]] = {}
    for _kind, body, start, end, _body_start, _body_end in legacy._iter_art_block_spans(text):
        name = legacy._body_property(body, "Name")
        if name in names:
            spans[name] = (start, end)
    if set(spans) != names:
        raise AssertionError("synthetic manifest does not contain the requested blocks")
    for start, end in sorted(spans.values(), reverse=True):
        text = text[:start] + text[end:]
    return legacy.encode_utf16le_art(text)


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold())
        if path.is_file()
    }


def expected_artifacts(root: Path) -> list[dict[str, object]]:
    snapshot = tree_snapshot(root)
    return [
        {
            "path": relative,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for relative, payload in sorted(snapshot.items(), key=lambda item: item[0].casefold())
    ]


def workshop_validator() -> Draft202012Validator:
    schema = json.loads(WORKSHOP_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class WorkshopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = REPO_ROOT / "tests" / f".workshop-{uuid.uuid4().hex}"
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

    def make_ready_project(
        self,
        identifier: str,
        *,
        steam_mod_id: str = "0,0",
    ) -> tuple[SDKProject, Path]:
        candidate = self.context.user_root / "Mod" / f"Candidate-{identifier}"
        candidate.mkdir()
        (candidate / "Index.art").write_bytes(manifest_bytes(steam_mod_id=steam_mod_id))
        (candidate / "Thumbnail.jpg").write_bytes(synthetic_jpeg())
        payload = candidate / "Ancient" / "Entity" / "payload.bin"
        payload.parent.mkdir(parents=True)
        payload.write_bytes(b"synthetic Workshop payload")

        target = self.root / "Authoring" / identifier
        ProjectImporter.plan(
            candidate,
            target,
            identifier=identifier,
            license="MIT",
            contact="https://github.com/example",
            provenance_status=ProvenanceStatus.REVIEWED,
            provenance_notes="Every fixture byte was generated by this synthetic test suite.",
            context=self.context,
        ).apply()
        project = SDKProject.open(target, context=self.context)
        log = self.root / f"{identifier}-Log.txt"
        log.write_bytes(
            (
                "[12:00:00] Ancient Cities.1.9.3\n"
                "[12:00:01] Enabling Mod: C:/Synthetic/Workshop "
                "(Synthetic Workshop Mod)\n"
            ).encode("utf-16-le")
        )
        project.plan_runtime_test(
            log,
            tested_source=project.layout.source_root,
            passed=True,
            save_impact=SaveImpact.NEW_SAVE_RECOMMENDED,
            achievement_impact=AchievementImpact.DISABLED,
            clean_launch=True,
            save_type=RuntimeSaveType.NEW_DISPOSABLE,
            save_persistence=SavePersistence.MANUAL_SAVE_RELOAD_PASSED,
        ).apply()
        return SDKProject.open(target, context=self.context), candidate

    @staticmethod
    def assign_live_id(candidate: Path, steam_mod_id: str) -> None:
        manifest = ManifestDocument.read(candidate / "Index.art")
        (candidate / "Index.art").write_bytes(
            manifest.updated({"SteamModId": steam_mod_id}).to_bytes()
        )

    @staticmethod
    def packet_kwargs() -> dict[str, object]:
        return {
            "action": PublishAction.PUBLISH,
            "candidate_kind": CandidateKind.LOOSE,
            "visibility": WorkshopVisibility.PRIVATE,
            "visibility_control": VisibilityControl.SHOWN,
            "account_preflight_passed": True,
            "generated_at": datetime(2026, 7, 22, 10, 0, tzinfo=UTC),
        }


class WorkshopStateTests(WorkshopTestCase):
    def test_state_round_trips_and_matches_the_bundled_schema(self) -> None:
        state = WorkshopState(
            status=WorkshopStatus.PUBLISHED,
            steam_mod_id=SteamModId(3_456_789_012, 4_294_967_295),
            visibility=WorkshopVisibility.UNLISTED,
            predecessor_ids=(SteamModId(17, 0), SteamModId(23, 1)),
            last_verified_at="2026-07-22T08:09:10+00:00",
        )
        payload = state.to_bytes()
        self.assertTrue(payload.endswith(b"\n"))
        self.assertEqual(WorkshopState.from_bytes(payload), state)

        state_path = self.root / "workshop.json"
        state_path.write_bytes(payload)
        self.assertEqual(WorkshopState.load(state_path), state)
        workshop_validator().validate(state.to_dict())

    def test_state_and_schema_reject_invalid_identity_relationships(self) -> None:
        with self.assertRaisesRegex(ContractError, "unpublished.*0,0"):
            WorkshopState(
                status=WorkshopStatus.UNPUBLISHED,
                steam_mod_id=SteamModId(1, 0),
            )
        with self.assertRaisesRegex(ContractError, "requires a nonzero"):
            WorkshopState(
                status=WorkshopStatus.PUBLISHED,
                steam_mod_id=SteamModId(),
            )
        with self.assertRaisesRegex(ContractError, "predecessor IDs must be unique"):
            WorkshopState(
                status=WorkshopStatus.PUBLISHED,
                steam_mod_id=SteamModId(9, 0),
                predecessor_ids=(SteamModId(8, 0), SteamModId(8, 0)),
            )
        with self.assertRaisesRegex(ContractError, "cannot also be a predecessor"):
            WorkshopState(
                status=WorkshopStatus.PUBLISHED,
                steam_mod_id=SteamModId(9, 0),
                predecessor_ids=(SteamModId(9, 0),),
            )
        with self.assertRaisesRegex(ContractError, "RFC 3339"):
            WorkshopState(
                status=WorkshopStatus.PUBLISHED,
                steam_mod_id=SteamModId(9, 0),
                last_verified_at="2026-07-22T08:09:10",
            )
        with self.assertRaisesRegex(ContractError, "schema"):
            WorkshopState(
                status=WorkshopStatus.PUBLISHED,
                steam_mod_id=SteamModId(9, 0),
                schema_version=True,
            )
        with self.assertRaisesRegex(ContractError, "app_id"):
            WorkshopState(
                status=WorkshopStatus.PUBLISHED,
                steam_mod_id=SteamModId(9, 0),
                app_id=667610.0,
            )
        for invalid_timestamp in (None, False, 0):
            with (
                self.subTest(invalid_timestamp=invalid_timestamp),
                self.assertRaisesRegex(ContractError, "last_verified_at"),
            ):
                WorkshopState(
                    status=WorkshopStatus.PUBLISHED,
                    steam_mod_id=SteamModId(9, 0),
                    last_verified_at=invalid_timestamp,
                )

        valid = WorkshopState(
            status=WorkshopStatus.PUBLISHED,
            steam_mod_id=SteamModId(9, 0),
        ).to_dict()
        validator = workshop_validator()
        validator.validate(valid)
        invalid_values: list[dict[str, object]] = []
        for field, value in (
            ("steam_mod_id", "4294967296,0"),
            ("predecessor_ids", ["0,0"]),
            ("last_verified_at", "2026-07-22T08:09:10"),
        ):
            changed = copy.deepcopy(valid)
            changed[field] = value
            invalid_values.append(changed)
        unpublished_nonzero = copy.deepcopy(valid)
        unpublished_nonzero.update(status="unpublished", steam_mod_id="1,0")
        invalid_values.append(unpublished_nonzero)
        published_zero = copy.deepcopy(valid)
        published_zero["steam_mod_id"] = "0,0"
        invalid_values.append(published_zero)
        duplicate_predecessors = copy.deepcopy(valid)
        duplicate_predecessors["predecessor_ids"] = ["1,0", "1,0"]
        invalid_values.append(duplicate_predecessors)
        extra_field = copy.deepcopy(valid)
        extra_field["unexpected"] = True
        invalid_values.append(extra_field)
        for value in invalid_values:
            with self.subTest(value=value):
                self.assertFalse(validator.is_valid(value))

        unknown = copy.deepcopy(valid)
        unknown["unexpected"] = True
        with self.assertRaisesRegex(ContractError, "unknown unexpected"):
            WorkshopState.from_dict(unknown)
        for field, value in (
            ("steam_mod_id", "9"),
            ("steam_mod_id", "0009,0"),
            ("predecessor_ids", ["7"]),
            ("last_verified_at", "20260722T080910+00:00"),
            ("last_verified_at", "2026-07-22 08:09:10+00:00"),
        ):
            changed = copy.deepcopy(valid)
            changed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                WorkshopState.from_dict(changed)


class PublishPacketTests(WorkshopTestCase):
    def test_first_publish_adapter_is_an_exact_two_block_transformation(self) -> None:
        project, candidate = self.make_ready_project("exact-adapter")
        canonical = project.layout.manifest.read_bytes()
        adapted = without_manifest_blocks(canonical, {"GameVersion", "SteamModId"})
        (candidate / "Index.art").write_bytes(adapted)

        packet = prepare_publish_packet(project, candidate, **self.packet_kwargs())
        self.assertEqual(packet.steam_mod_id, SteamModId())

        partial = without_manifest_blocks(canonical, {"SteamModId"})
        (candidate / "Index.art").write_bytes(partial)
        with self.assertRaisesRegex(ValidationFailedError, "exact two-block adapter"):
            prepare_publish_packet(project, candidate, **self.packet_kwargs())

        (candidate / "Index.art").write_bytes(adapted + " ".encode("utf-16-le"))
        with self.assertRaisesRegex(ValidationFailedError, "exact two-block adapter"):
            prepare_publish_packet(project, candidate, **self.packet_kwargs())

    def test_persistent_state_blocks_reset_or_deleted_identity_publication(self) -> None:
        project, candidate = self.make_ready_project("persistent-identity")
        state_path = project.layout.state_root / "workshop.json"
        state_path.write_bytes(
            WorkshopState(
                status=WorkshopStatus.PUBLISHED,
                steam_mod_id=SteamModId(3_456_789_012, 0),
                visibility=WorkshopVisibility.PUBLIC,
            ).to_bytes()
        )
        with self.assertRaisesRegex(ValidationFailedError, "does not match the canonical"):
            prepare_publish_packet(project, candidate, **self.packet_kwargs())

        state_path.write_bytes(
            WorkshopState(
                status=WorkshopStatus.DELETED_PREDECESSOR,
                steam_mod_id=SteamModId(3_456_789_012, 0),
            ).to_bytes()
        )
        with self.assertRaisesRegex(ValidationFailedError, "deleted Workshop identity"):
            prepare_publish_packet(project, candidate, **self.packet_kwargs())

        state_path.write_bytes(b"")
        with self.assertRaisesRegex(ContractError, "cannot decode Workshop state"):
            prepare_publish_packet(project, candidate, **self.packet_kwargs())

    def test_loose_publish_packet_has_exact_hashes_and_records_no_authorization(self) -> None:
        project, candidate = self.make_ready_project("loose-publish")
        project_before = tree_snapshot(project.layout.root)
        candidate_before = tree_snapshot(candidate)
        generated_at = datetime(2026, 7, 22, 10, 11, 12, 987_654, tzinfo=UTC)

        packet = prepare_publish_packet(
            project,
            candidate,
            action=PublishAction.PUBLISH,
            candidate_kind=CandidateKind.LOOSE,
            visibility=WorkshopVisibility.PRIVATE,
            visibility_control=VisibilityControl.NOT_EXPOSED,
            account_preflight_passed=True,
            valid_minutes=12,
            generated_at=generated_at,
        )
        payload = packet.to_dict()

        self.assertEqual(payload["action"], "publish")
        self.assertEqual(payload["target"], {"kind": "new-item", "steam_mod_id": "0,0"})
        self.assertEqual(payload["candidate"]["kind"], "loose")
        self.assertEqual(payload["candidate"]["root"], str(candidate.resolve()))
        self.assertEqual(payload["candidate"]["artifacts"], expected_artifacts(candidate))
        release = project.plan_release().preview()
        self.assertEqual(
            payload["candidate"]["deterministic_mod_zip"],
            {
                "path": "Mod.zip",
                "bytes": release.archive_size,
                "sha256": release.archive_sha256,
            },
        )
        self.assertEqual(payload["generated_at"], "2026-07-22T10:11:12+00:00")
        self.assertEqual(payload["valid_until"], "2026-07-22T10:23:12+00:00")
        self.assertTrue(payload["single_use"])
        self.assertFalse(payload["authorization_recorded"])
        self.assertFalse(payload["publishes_workshop_items"])
        self.assertEqual(
            payload["account_preflight"],
            {
                "intended_account_confirmed": True,
                "target_exists_and_owned": None,
                "stores_account_identity": False,
            },
        )
        unsigned = dict(payload)
        unsigned.pop("packet_id")
        encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(payload["packet_id"], hashlib.sha256(encoded).hexdigest())

        self.assertEqual(tree_snapshot(project.layout.root), project_before)
        self.assertEqual(tree_snapshot(candidate), candidate_before)
        self.assertFalse(project.layout.distribution_root.exists())
        self.assertFalse((project.layout.state_root / "workshop.json").exists())

    def test_staged_update_packet_has_exact_stage_artifacts(self) -> None:
        project, _candidate = self.make_ready_project(
            "staged-update",
            steam_mod_id="3456789012,1",
        )
        project.plan_release().apply()
        stage = project.layout.distribution_root
        before = tree_snapshot(project.layout.root)

        packet = prepare_publish_packet(
            project,
            stage,
            action=PublishAction.UPDATE,
            candidate_kind=CandidateKind.STAGED,
            visibility=WorkshopVisibility.PUBLIC,
            visibility_control=VisibilityControl.SHOWN,
            account_preflight_passed=True,
            target_ownership_verified=True,
            generated_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        )
        payload = packet.to_dict()

        self.assertEqual(
            payload["target"],
            {"kind": "existing-item", "steam_mod_id": "3456789012,1"},
        )
        self.assertEqual(payload["visibility"], {"value": "public", "ui_control": "shown"})
        self.assertEqual(payload["candidate"]["kind"], "staged")
        self.assertEqual(payload["candidate"]["artifacts"], expected_artifacts(stage))
        self.assertIsNone(payload["candidate"]["deterministic_mod_zip"])
        self.assertEqual(tree_snapshot(project.layout.root), before)
        self.assertFalse(payload["authorization_recorded"])
        self.assertFalse(payload["publishes_workshop_items"])
        self.assertFalse((project.layout.state_root / "workshop.json").exists())

    def test_loose_packet_verifies_an_exact_generated_game_package(self) -> None:
        project, candidate = self.make_ready_project("generated-package")
        project.plan_release().apply()
        generated_package = project.layout.distribution_root
        before = tree_snapshot(project.layout.root)

        packet = prepare_publish_packet(
            project,
            candidate,
            action=PublishAction.PUBLISH,
            candidate_kind=CandidateKind.LOOSE,
            visibility=WorkshopVisibility.PRIVATE,
            visibility_control=VisibilityControl.SHOWN,
            account_preflight_passed=True,
            generated_package_root=generated_package,
            generated_at=datetime(2026, 7, 22, 12, 30, tzinfo=UTC),
        )
        generated = packet.to_dict()["generated_game_package"]
        self.assertIsNotNone(generated)
        assert generated is not None
        self.assertEqual(generated["root"], str(generated_package.resolve()))
        self.assertEqual(generated["artifacts"], expected_artifacts(generated_package))
        self.assertEqual(
            generated["archive_members"],
            [
                artifact
                for artifact in expected_artifacts(candidate)
                if str(artifact["path"]).startswith("Ancient/")
            ],
        )
        self.assertEqual(tree_snapshot(project.layout.root), before)
        self.assertFalse(packet.to_dict()["authorization_recorded"])
        self.assertFalse(packet.to_dict()["publishes_workshop_items"])

    def test_loose_packet_rejects_mismatched_generated_archive_members(self) -> None:
        project, candidate = self.make_ready_project("generated-package-mismatch")
        project.plan_release().apply()
        generated_package = self.root / "generated-package-mismatch"
        shutil.copytree(project.layout.distribution_root, generated_package)
        with zipfile.ZipFile(
            generated_package / "Mod.zip",
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("Ancient/Entity/payload.bin", b"mismatched generated payload")

        with self.assertRaisesRegex(
            ValidationFailedError,
            "Mod.zip inventory or member bytes differ",
        ):
            prepare_publish_packet(
                project,
                candidate,
                action=PublishAction.PUBLISH,
                candidate_kind=CandidateKind.LOOSE,
                visibility=WorkshopVisibility.PRIVATE,
                visibility_control=VisibilityControl.SHOWN,
                account_preflight_passed=True,
                generated_package_root=generated_package,
            )

    def test_packet_rejects_loose_and_staged_payload_mismatches(self) -> None:
        loose_project, loose_candidate = self.make_ready_project("loose-mismatch")
        (loose_candidate / "Ancient" / "Entity" / "payload.bin").write_bytes(b"mismatch")
        with self.assertRaisesRegex(ValidationFailedError, "payload or thumbnail differs"):
            prepare_publish_packet(
                loose_project,
                loose_candidate,
                **self.packet_kwargs(),
            )

        staged_project, _candidate = self.make_ready_project("staged-mismatch")
        staged_project.plan_release().apply()
        archive = staged_project.layout.distribution_root / "Mod.zip"
        archive.write_bytes(archive.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValidationFailedError, "fresh deterministic release preview"):
            prepare_publish_packet(
                staged_project,
                staged_project.layout.distribution_root,
                action=PublishAction.PUBLISH,
                candidate_kind=CandidateKind.STAGED,
                visibility=WorkshopVisibility.PRIVATE,
                visibility_control=VisibilityControl.SHOWN,
                account_preflight_passed=True,
            )

    def test_packet_enforces_expiry_scope_and_target_constraints(self) -> None:
        project, candidate = self.make_ready_project("packet-constraints")
        without_account = self.packet_kwargs()
        without_account["account_preflight_passed"] = False
        with self.assertRaisesRegex(ContractError, "active Steam account"):
            prepare_publish_packet(project, candidate, **without_account)
        with self.assertRaisesRegex(ContractError, "target existence"):
            prepare_publish_packet(
                project,
                candidate,
                **{**self.packet_kwargs(), "action": PublishAction.UPDATE},
            )
        with self.assertRaisesRegex(ContractError, "applies only to Update"):
            prepare_publish_packet(
                project,
                candidate,
                **{**self.packet_kwargs(), "target_ownership_verified": True},
            )
        for minutes in (False, 0, 61, 1.5):
            with self.subTest(valid_minutes=minutes), self.assertRaises(ContractError):
                prepare_publish_packet(
                    project,
                    candidate,
                    **self.packet_kwargs(),
                    valid_minutes=minutes,
                )
        with self.assertRaisesRegex(ContractError, "timezone-aware"):
            prepare_publish_packet(
                project,
                candidate,
                **{
                    **self.packet_kwargs(),
                    "generated_at": datetime(2026, 7, 22, 10, 0),
                },
            )
        with self.assertRaisesRegex(ContractError, "visibility must be explicit"):
            prepare_publish_packet(
                project,
                candidate,
                **{
                    **self.packet_kwargs(),
                    "visibility": WorkshopVisibility.UNKNOWN,
                },
            )
        with self.assertRaisesRegex(ValidationFailedError, "Update requires"):
            prepare_publish_packet(
                project,
                candidate,
                **{
                    **self.packet_kwargs(),
                    "action": PublishAction.UPDATE,
                    "target_ownership_verified": True,
                },
            )

        external = self.root / "external-candidate"
        shutil.copytree(candidate, external)
        with self.assertRaisesRegex(ProjectError, "direct child of the discovered user Mod"):
            prepare_publish_packet(project, external, **self.packet_kwargs())

        packet = prepare_publish_packet(project, candidate, **self.packet_kwargs())
        packet.assert_active(at=datetime(2026, 7, 22, 10, 0, tzinfo=UTC))
        (candidate / "Ancient" / "Entity" / "payload.bin").write_bytes(b"changed")
        with self.assertRaisesRegex(SourceChangedError, "candidate changed"):
            packet.assert_active(at=datetime(2026, 7, 22, 10, 1, tzinfo=UTC))
        with self.assertRaisesRegex(ContractError, "not active yet"):
            packet.assert_active(at=datetime(2026, 7, 22, 9, 59, 59, tzinfo=UTC))
        with self.assertRaisesRegex(ContractError, "has expired"):
            packet.assert_active(at=datetime(2026, 7, 22, 10, 15, tzinfo=UTC))
        with self.assertRaisesRegex(ContractError, "timezone-aware"):
            packet.assert_active(at=datetime(2026, 7, 22, 10, 1))
        with self.assertRaisesRegex(ContractError, "expiry must be after"):
            replace(packet, valid_until=packet.generated_at)
        with self.assertRaisesRegex(ContractError, "app_id"):
            replace(packet, app_id=1)
        with self.assertRaisesRegex(ContractError, "schema"):
            replace(packet, schema_version=999)
        with self.assertRaisesRegex(ContractError, "schema"):
            replace(packet, schema_version=True)
        with self.assertRaisesRegex(ContractError, "safe relative path"):
            WorkshopArtifact("../Index.art", 1, "0" * 64)
        with self.assertRaisesRegex(ContractError, "lowercase digest"):
            WorkshopArtifact("Index.art", 1, "A" * 64)


class WorkshopSyncTests(WorkshopTestCase):
    def test_sync_preview_is_dry_run_and_apply_is_atomic_and_schema_valid(self) -> None:
        project, candidate = self.make_ready_project("sync-apply")
        self.assign_live_id(candidate, "3000000001,0")
        canonical_before = (project.layout.manifest).read_bytes()
        config_before = project.layout.config_path.read_bytes()
        live_before = tree_snapshot(candidate)
        verified_at = datetime(2026, 7, 22, 14, 30, 15, 999_999, tzinfo=UTC)

        plan = plan_workshop_sync(
            project,
            candidate,
            visibility=WorkshopVisibility.PUBLIC,
            predecessor_ids=("101,0", 202, SteamModId(101, 0)),
            verified_at=verified_at,
        )
        self.assertEqual(
            plan.updated_state.predecessor_ids,
            (SteamModId(101, 0), SteamModId(202, 0)),
        )
        preview = plan.preview()
        self.assertEqual(preview.mode.value, "dry-run")
        self.assertTrue(preview.runtime_reset)
        self.assertEqual(project.layout.manifest.read_bytes(), canonical_before)
        self.assertEqual(project.layout.config_path.read_bytes(), config_before)
        self.assertFalse(plan.state_path.exists())
        self.assertEqual(tree_snapshot(candidate), live_before)

        result = plan.apply()
        self.assertEqual(result.mode.value, "apply")
        self.assertEqual(result.steam_mod_id, SteamModId(3_000_000_001, 0))
        self.assertTrue(result.runtime_reset)
        self.assertIsNotNone(result.config_backup)
        self.assertIsNotNone(result.manifest_backup)
        self.assertIsNone(result.state_backup)
        assert result.config_backup is not None and result.manifest_backup is not None
        backup_root = project.layout.state_root / "backups"
        self.assertTrue(result.config_backup.is_relative_to(backup_root))
        self.assertTrue(result.manifest_backup.is_relative_to(backup_root))
        self.assertFalse(project.layout.source_root.joinpath("Index.art.bak").exists())
        self.assertEqual(tree_snapshot(candidate), live_before)

        state = WorkshopState.load(plan.state_path)
        self.assertEqual(state, plan.updated_state)
        self.assertEqual(state.last_verified_at, "2026-07-22T14:30:15+00:00")
        workshop_validator().validate(json.loads(plan.state_path.read_text(encoding="utf-8")))
        canonical_after = ManifestDocument.read(project.layout.manifest)
        canonical_before_document = ManifestDocument.from_bytes(canonical_before)
        self.assertEqual(canonical_after.fields["SteamModId"], "3000000001,0")
        self.assertEqual(
            {k: v for k, v in canonical_after.fields.items() if k != "SteamModId"},
            {k: v for k, v in canonical_before_document.fields.items() if k != "SteamModId"},
        )
        reopened = SDKProject.open(project.layout.root, context=self.context)
        self.assertEqual(reopened.config.runtime_status, RuntimeStatus.UNTESTED)
        self.assertEqual(
            result.manifest_sha256,
            hashlib.sha256(project.layout.manifest.read_bytes()).hexdigest(),
        )

    def test_sync_preserves_permanent_ids_and_rejects_predecessor_reuse(self) -> None:
        project, candidate = self.make_ready_project("sync-identity")
        assigned = "3030303030,0"
        self.assign_live_id(candidate, assigned)

        with self.assertRaisesRegex(ValidationFailedError, "deleted predecessor"):
            plan_workshop_sync(
                project,
                candidate,
                visibility=WorkshopVisibility.UNLISTED,
                predecessor_ids=(assigned,),
            )

        plan_workshop_sync(
            project,
            candidate,
            visibility=WorkshopVisibility.UNLISTED,
            predecessor_ids=("77,0",),
        ).apply()
        reopened = SDKProject.open(project.layout.root, context=self.context)
        same_id = plan_workshop_sync(
            reopened,
            candidate,
            visibility=WorkshopVisibility.UNLISTED,
        )
        self.assertEqual(same_id.updated_state.steam_mod_id, SteamModId(3_030_303_030, 0))
        self.assertFalse(same_id.preview().runtime_reset)

        self.assign_live_id(candidate, "4040404040,0")
        with self.assertRaisesRegex(ValidationFailedError, "permanent and cannot be replaced"):
            plan_workshop_sync(
                reopened,
                candidate,
                visibility=WorkshopVisibility.PUBLIC,
            )

        self.assign_live_id(candidate, assigned)
        conflicting_state = WorkshopState(
            status=WorkshopStatus.PUBLISHED,
            steam_mod_id=SteamModId(909, 0),
            visibility=WorkshopVisibility.PRIVATE,
        )
        (reopened.layout.state_root / "workshop.json").write_bytes(conflicting_state.to_bytes())
        with self.assertRaisesRegex(ValidationFailedError, "another permanent SteamModId"):
            plan_workshop_sync(
                reopened,
                candidate,
                visibility=WorkshopVisibility.PUBLIC,
            )

    def test_sync_plan_rejects_live_source_change_without_writing(self) -> None:
        project, candidate = self.make_ready_project("sync-live-change")
        self.assign_live_id(candidate, "1234567890,0")
        plan = plan_workshop_sync(
            project,
            candidate,
            visibility=WorkshopVisibility.PRIVATE,
        )
        canonical_before = tree_snapshot(project.layout.root)
        (candidate / "Ancient" / "Entity" / "payload.bin").write_bytes(b"changed after plan")

        with self.assertRaisesRegex(SourceChangedError, "live Workshop source changed"):
            plan.preview()
        self.assertEqual(tree_snapshot(project.layout.root), canonical_before)
        self.assertFalse(plan.state_path.exists())

    def test_sync_plan_rejects_canonical_payload_change_without_writing(self) -> None:
        project, candidate = self.make_ready_project("sync-canonical-change")
        self.assign_live_id(candidate, "2234567890,0")
        plan = plan_workshop_sync(
            project,
            candidate,
            visibility=WorkshopVisibility.PRIVATE,
        )
        config_before = project.layout.config_path.read_bytes()
        manifest_before = project.layout.manifest.read_bytes()
        payload = project.layout.payload_root / "Entity" / "payload.bin"
        payload.write_bytes(b"canonical source changed after plan")

        with self.assertRaisesRegex(SourceChangedError, "canonical.*changed"):
            plan.preview()
        self.assertEqual(project.layout.config_path.read_bytes(), config_before)
        self.assertEqual(project.layout.manifest.read_bytes(), manifest_before)
        self.assertFalse(plan.state_path.exists())

    def test_sync_rejects_payload_mismatch_before_planning(self) -> None:
        project, candidate = self.make_ready_project("sync-mismatch")
        self.assign_live_id(candidate, "3234567890,0")
        (candidate / "Thumbnail.jpg").write_bytes(synthetic_jpeg(256, 256))
        with self.assertRaisesRegex(ValidationFailedError, "payload or thumbnail differs"):
            plan_workshop_sync(
                project,
                candidate,
                visibility=WorkshopVisibility.PRIVATE,
            )


if __name__ == "__main__":
    unittest.main()

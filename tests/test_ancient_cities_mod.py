"""Synthetic tests for the Ancient Cities mod CLI (no proprietary fixtures)."""

from __future__ import annotations

import codecs
import hashlib
import importlib.util
import io
import os
import shutil
import sys
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "ancient-cities-modding" / "scripts" / "ancient_cities_mod.py"
SPEC = importlib.util.spec_from_file_location("ancient_cities_mod", SCRIPT)
assert SPEC and SPEC.loader
ac = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ac
SPEC.loader.exec_module(ac)


def write_art(path: Path, text: str, *, bom: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-16-le")
    path.write_bytes((codecs.BOM_UTF16_LE if bom else b"") + data)


def valid_manifest(
    *, title: str = "Synthetic Mod", steam_id: str = "0", game_version: str = "22"
) -> str:
    return ac.canonical_manifest(
        title=title,
        description="Only generated test data",
        changelog="Initial",
        game_version=game_version,
        mod_type="Generic",
        steam_mod_id=steam_id,
    )


def synthetic_jpeg(width: int = 512, height: int = 512) -> bytes:
    """Minimal signature/SOF fixture; pixels are intentionally never decoded."""

    sof_payload = (
        b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x01\x01\x11\x00"
    )
    return (
        b"\xff\xd8\xff\xc0" + (len(sof_payload) + 2).to_bytes(2, "big") + sof_payload + b"\xff\xd9"
    )


def make_project(root: Path, *, title: str = "Synthetic Mod") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    write_art(root / "Index.art", valid_manifest(title=title))
    (root / "Thumbnail.jpg").write_bytes(synthetic_jpeg())
    (root / "Ancient").mkdir(exist_ok=True)
    return root


class SyntheticTempTestCase(unittest.TestCase):
    """Use ordinary 0777 test dirs; Windows can make mode-0700 dirs token-private."""

    def setUp(self) -> None:
        self.root = REPO_ROOT / "tests" / f".fixture-{uuid.uuid4().hex}"
        self.root.mkdir(mode=0o777)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)


class EncodingAndParserTests(unittest.TestCase):
    def test_help_program_name_follows_entry_point(self) -> None:
        with mock.patch.object(sys, "argv", ["acmk"]):
            parser = ac.build_parser()
        self.assertEqual(parser.prog, "acmk")

    def test_art_requires_utf16le_bom(self) -> None:
        with self.assertRaisesRegex(ac.ModToolError, "missing the UTF-16LE BOM"):
            ac.decode_utf16le_art("String:{}".encode("utf-16-le"), "bad.art")

    def test_art_rejects_invalid_surrogate_roundtrip(self) -> None:
        with self.assertRaises(ac.ModToolError):
            ac.decode_utf16le_art(codecs.BOM_UTF16_LE + b"\x00\xd8", "bad.art")

    def test_art_requires_exactly_one_leading_bom(self) -> None:
        doubled = codecs.BOM_UTF16_LE * 2 + "Node:{}".encode("utf-16-le")
        with self.assertRaisesRegex(ac.ModToolError, "more than one leading"):
            ac.decode_utf16le_art(doubled, "double.art")
        with self.assertRaisesRegex(ac.ModToolError, "exactly one BOM"):
            ac.encode_utf16le_art("\ufeffNode:{}")

    def test_parser_tolerates_unknown_blocks(self) -> None:
        text = (
            '\nOuter:{\n Name:"Parent"\n'
            ' Vendor/New.Valid-Type:{\n  Path:"/Synthetic"\n  FutureProperty:[1,2,3]\n }\n}\n'
        )
        self.assertEqual(ac.parse_art_blocks(text)[1]["kind"], "Vendor/New.Valid-Type")

    def test_deeply_nested_parser_has_a_hard_limit(self) -> None:
        depth = ac.MAX_ART_NESTING + 1
        text = "Node:{" * depth + 'Name:"Leaf"' + "}" * depth
        with self.assertRaisesRegex(ac.ModToolError, "nesting exceeds"):
            ac.parse_art_blocks(text)

    def test_accepted_nesting_cannot_multiply_property_scan_work(self) -> None:
        text = "Node:{" * ac.MAX_ART_NESTING + ("x" * 100) + "}" * ac.MAX_ART_NESTING
        with (
            mock.patch.object(ac, "MAX_ART_PROPERTY_SCAN_CHARS", 1_000),
            self.assertRaisesRegex(ac.ModToolError, "property-scan budget"),
        ):
            ac.parse_art_blocks(text)

    def test_real_depth_limit_scans_each_nested_body_only_once(self) -> None:
        text = "Node:{" * ac.MAX_ART_NESTING + ("x" * (32 * 1024)) + "}" * ac.MAX_ART_NESTING
        started = time.perf_counter()
        with mock.patch.object(ac, "_body_properties", wraps=ac._body_properties) as scanner:
            blocks = ac.parse_art_blocks(text)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(blocks), ac.MAX_ART_NESTING)
        self.assertLessEqual(scanner.call_count, ac.MAX_ART_NESTING)
        self.assertLess(elapsed, 2.0, f"real-limit parser regression took {elapsed:.2f}s")

    def test_steam_mod_id_is_bounded_u32x2(self) -> None:
        self.assertEqual(ac.normalise_steam_mod_id("4294967295", allow_single=True), "4294967295,0")
        with self.assertRaisesRegex(ac.ModToolError, "unsigned 32-bit"):
            ac.normalise_steam_mod_id("4294967296,0", allow_single=False)

    def test_huge_steam_mod_id_is_a_user_error_not_an_integer_traceback(self) -> None:
        with self.assertRaisesRegex(ac.ModToolError, "unsigned 32-bit"):
            ac.normalise_steam_mod_id("9" * 10_000 + ",0", allow_single=False)

    def test_game_version_and_steam_id_require_ascii_digits(self) -> None:
        with self.assertRaisesRegex(ac.ModToolError, "unsigned integer pair"):
            ac.normalise_steam_mod_id("١,0", allow_single=False)
        with self.assertRaisesRegex(ac.ModToolError, "unsigned decimal integer"):
            ac.canonical_manifest(
                title="Synthetic",
                description="Synthetic",
                changelog="Initial",
                game_version="٢٢",
                mod_type="Generic",
                steam_mod_id="0",
            )

    def test_literal_file_references(self) -> None:
        text = 'Node:{\nFile:"Images/Picture.jpg"\n}\nString:{Name:"File" Value:"Sound.wav"}'
        self.assertEqual(ac.parse_literal_file_refs(text), ["Images/Picture.jpg", "Sound.wav"])

    def test_engine_references_are_not_normalised_as_files(self) -> None:
        current = "Ancient/Entity/Index.art"
        for reference in ("../Node", "~/Node", "/System/Node"):
            with self.subTest(reference=reference):
                self.assertIsNone(ac._normalise_reference(current, reference))
        self.assertEqual(
            ac._normalise_reference(current, "Images/Picture.png"),
            "Ancient/Entity/Images/Picture.png",
        )


class ValidationTests(SyntheticTempTestCase):
    def test_thumbnail_is_required_and_dimensions_are_checked(self) -> None:
        project = make_project(self.root / "thumbnail")
        (project / "Ancient" / "data.txt").write_bytes(b"data")
        (project / "Thumbnail.jpg").unlink()
        missing = ac.validate_target(project)
        self.assertIn("THUMBNAIL_MISSING", {issue["code"] for issue in missing["issues"]})
        (project / "Thumbnail.jpg").write_bytes(synthetic_jpeg(256, 128))
        dimensions = ac.validate_target(project)
        self.assertIn("THUMBNAIL_DIMENSIONS", {issue["code"] for issue in dimensions["issues"]})
        (project / "Thumbnail.jpg").write_bytes(b"not jpeg")
        signature = ac.validate_target(project)
        self.assertIn("THUMBNAIL_SIGNATURE", {issue["code"] for issue in signature["issues"]})

    def test_wrong_bom_is_an_error(self) -> None:
        project = make_project(self.root / "wrong-bom")
        write_art(project / "Ancient" / "Broken.art", "Node:{}", bom=False)
        report = ac.validate_target(project)
        self.assertFalse(report["valid"])
        self.assertIn("ART_ENCODING", {issue["code"] for issue in report["issues"]})

    def test_missing_type_is_an_error(self) -> None:
        project = make_project(self.root / "missing-type")
        manifest = valid_manifest()
        manifest = manifest.replace('\n\nString:\n{\n\tName:"Type"\n\tValue:"Generic"\n}\n', "\n")
        write_art(project / "Index.art", manifest)
        (project / "Ancient" / "data.txt").write_text("synthetic", encoding="utf-8")
        report = ac.validate_target(project)
        missing = [issue for issue in report["issues"] if issue["code"] == "MANIFEST_MISSING_FIELD"]
        self.assertTrue(any("Type" in issue["message"] for issue in missing))

    def test_zip_slip_and_wrong_root_are_rejected(self) -> None:
        project = make_project(self.root / "zip-slip")
        with zipfile.ZipFile(project / "Mod.zip", "w") as archive:
            archive.writestr("Ancient/good.txt", b"ok")
            archive.writestr("../escape.txt", b"bad")
            archive.writestr("ancient/wrong-case.txt", b"bad")
        report = ac.validate_target(project / "Mod.zip")
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("ZIP_SLIP", codes)
        self.assertIn("ZIP_ROOT", codes)
        self.assertFalse(report["valid"])

    def test_zip_declared_oversize_is_rejected_before_read(self) -> None:
        project = make_project(self.root / "zip-limit")
        archive_path = project / "Mod.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("Ancient/small.art", ac.encode_utf16le_art("Node:{}"))
        raw = bytearray(archive_path.read_bytes())
        central = raw.index(b"PK\x01\x02")
        raw[central + 24 : central + 28] = (ac.MAX_ZIP_MEMBER_BYTES + 1).to_bytes(4, "little")
        archive_path.write_bytes(raw)
        report = ac.validate_target(archive_path)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("ZIP_RESOURCE_LIMIT", codes)
        self.assertIn("CONTENT_UNREADABLE", codes)

    def test_zip_file_count_is_a_hard_limit(self) -> None:
        project = make_project(self.root / "zip-count")
        with zipfile.ZipFile(project / "Mod.zip", "w") as archive:
            for index in range(3):
                archive.writestr(f"Ancient/{index}.txt", b"x")
        with mock.patch.object(ac, "MAX_ZIP_FILES", 2):
            report = ac.validate_target(project / "Mod.zip")
        self.assertIn("ZIP_FILE_COUNT_LIMIT", {issue["code"] for issue in report["issues"]})

    def test_central_directory_is_counted_before_zipfile_allocates_entries(self) -> None:
        project = make_project(self.root / "central-count")
        archive_path = project / "Mod.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for index in range(3):
                archive.writestr(f"Ancient/{index}.txt", b"x")
        with (
            mock.patch.object(ac, "MAX_ZIP_FILES", 2),
            self.assertRaisesRegex(ac.ZipPreflightError, "hard limit is 2"),
        ):
            ac._preflight_zip_directory(archive_path)

    def test_false_small_end_record_count_cannot_hide_central_directory_bomb(self) -> None:
        project = make_project(self.root / "central-mismatch")
        archive_path = project / "Mod.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for index in range(3):
                archive.writestr(f"Ancient/{index}.txt", b"x")
        raw = bytearray(archive_path.read_bytes())
        end_record = raw.rindex(b"PK\x05\x06")
        raw[end_record + 8 : end_record + 10] = (1).to_bytes(2, "little")
        raw[end_record + 10 : end_record + 12] = (1).to_bytes(2, "little")
        archive_path.write_bytes(raw)
        with self.assertRaisesRegex(ac.ZipPreflightError, "declares 1 entries"):
            ac._preflight_zip_directory(archive_path)

    def test_central_directory_has_a_preallocation_byte_cap(self) -> None:
        project = make_project(self.root / "central-size")
        archive_path = project / "Mod.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("Ancient/value.txt", b"x")
        with (
            mock.patch.object(ac, "MAX_ZIP_CENTRAL_DIRECTORY_BYTES", 1),
            self.assertRaisesRegex(ac.ZipPreflightError, "central directory declares"),
        ):
            ac._preflight_zip_directory(archive_path)

    def test_bounded_zip64_end_metadata_is_supported(self) -> None:
        project = make_project(self.root / "zip64")
        archive_path = project / "Mod.zip"
        with (
            mock.patch.object(zipfile, "ZIP64_LIMIT", 0),
            zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive,
        ):
            archive.writestr("Ancient/value.txt", b"x")
        self.assertEqual(ac._preflight_zip_directory(archive_path)[0], 1)

    def test_case_duplicate_and_executable_are_rejected(self) -> None:
        project = make_project(self.root / "duplicates")
        with zipfile.ZipFile(project / "Mod.zip", "w") as archive:
            archive.writestr("Ancient/Data.txt", b"one")
            archive.writestr("Ancient/data.TXT", b"two")
            archive.writestr("Ancient/run.exe", b"MZ")
        report = ac.validate_target(project / "Mod.zip")
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("ZIP_CASE_DUPLICATE", codes)
        self.assertIn("EXECUTABLE_CONTENT", codes)

    def test_media_signature_and_missing_reference(self) -> None:
        project = make_project(self.root / "assets")
        write_art(project / "Ancient" / "Entity" / "Index.art", 'Node:{File:"Missing.png"}')
        (project / "Ancient" / "bad.png").write_bytes(b"not-a-png")
        report = ac.validate_target(project)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("MEDIA_SIGNATURE", codes)
        self.assertIn("MISSING_FILE_REFERENCE", codes)
        self.assertIn("ACHIEVEMENTS_DISABLED", codes)

    def test_file_reference_case_must_match_payload_and_base(self) -> None:
        project = make_project(self.root / "case-ref")
        write_art(
            project / "Ancient" / "Entity" / "Index.art",
            'Node:{File:"Image.png"}\nNode:{File:"/Ancient/Base/Picture.png"}',
        )
        (project / "Ancient" / "Entity" / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        base = self.root / "game" / "Ancient" / "Data" / "Ancient" / "Base"
        base.mkdir(parents=True)
        (base / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        report = ac.validate_target(project, ac.DiscoveryContext(game_dir=self.root / "game"))
        case_issues = [
            issue for issue in report["issues"] if issue["code"] == "FILE_REFERENCE_CASE"
        ]
        self.assertEqual(len(case_issues), 2)

    def test_base_new_override_identical_and_save_warning(self) -> None:
        project = make_project(self.root / "classify")
        base = self.root / "game" / "Ancient" / "Data" / "Ancient"
        base.mkdir(parents=True)
        (base / "same.txt").write_bytes(b"same")
        (base / "changed.txt").write_bytes(b"base")
        (project / "Ancient" / "same.txt").write_bytes(b"same")
        (project / "Ancient" / "changed.txt").write_bytes(b"mod")
        (project / "Ancient" / "new.txt").write_bytes(b"new")
        ctx = ac.DiscoveryContext(game_dir=self.root / "game")
        report = ac.validate_target(project, ctx)
        self.assertEqual(report["classifications"]["Ancient/same.txt"], "identical")
        self.assertEqual(report["classifications"]["Ancient/changed.txt"], "override")
        self.assertEqual(report["classifications"]["Ancient/new.txt"], "new")
        self.assertIn("SAVE_COMPATIBILITY", {issue["code"] for issue in report["issues"]})

    def test_override_path_case_must_match_base(self) -> None:
        project = make_project(self.root / "override-case")
        base = self.root / "game" / "Ancient" / "Data" / "Ancient" / "Entity"
        base.mkdir(parents=True)
        (base / "Value.txt").write_bytes(b"base")
        payload = project / "Ancient" / "entity"
        payload.mkdir()
        (payload / "value.txt").write_bytes(b"mod")
        report = ac.validate_target(project, ac.DiscoveryContext(game_dir=self.root / "game"))
        self.assertIn("BASE_OVERRIDE_CASE", {issue["code"] for issue in report["issues"]})

    def test_ambiguous_root_file_case_variants_are_errors(self) -> None:
        project = make_project(self.root / "ambiguous-root")
        (project / "Ancient" / "data.txt").write_bytes(b"data")
        original = ac._root_file_matches
        cases = (
            ("Index.art", "index.ART", "MANIFEST_AMBIGUOUS"),
            ("Thumbnail.jpg", "thumbnail.JPG", "THUMBNAIL_AMBIGUOUS"),
        )
        for expected, variant, code in cases:
            with self.subTest(expected=expected):

                def matches(
                    root: Path,
                    name: str,
                    expected_name: str = expected,
                    variant_name: str = variant,
                ) -> list[Path]:
                    if name == expected_name:
                        return [root / expected_name, root / variant_name]
                    return original(root, name)

                with mock.patch.object(ac, "_root_file_matches", side_effect=matches):
                    report = ac.validate_target(project)
                self.assertIn(code, {issue["code"] for issue in report["issues"]})

    def test_symlink_payload_root_is_rejected_by_validation_and_build(self) -> None:
        project = make_project(self.root / "payload-link")
        payload = project / "Ancient"
        payload.rmdir()
        external = self.root / "external-payload"
        external.mkdir()
        (external / "private.txt").write_bytes(b"must not be packaged")
        try:
            os.symlink(external, payload, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")
        report = ac.validate_target(project)
        self.assertIn("CONTENT_ROOT_SYMLINK", {issue["code"] for issue in report["issues"]})
        with self.assertRaisesRegex(ac.ModToolError, "source validation failed"):
            ac.build_project(project, output=None, apply=False)


class ConflictBuildAndMetadataTests(SyntheticTempTestCase):
    def test_directory_enumeration_stops_at_entry_limit(self) -> None:
        tree = self.root / "bounded-tree"
        tree.mkdir()
        (tree / "one.txt").write_bytes(b"1")
        (tree / "two.txt").write_bytes(b"2")
        with self.assertRaisesRegex(ac.ModToolError, "1-entry limit"):
            ac._bounded_tree_entries(tree, limit=1)

    def test_conflict_detection_reports_winner_and_difference(self) -> None:
        first = make_project(self.root / "one", title="First")
        second = make_project(self.root / "two", title="Second")
        (first / "Ancient" / "Shared.txt").write_bytes(b"first")
        (second / "Ancient" / "shared.TXT").write_bytes(b"second")
        report = ac.find_conflicts([first, second])
        self.assertEqual(report["different_conflicts"], 1)
        self.assertEqual(report["conflicts"][0]["kind"], "different")
        self.assertEqual(report["conflicts"][0]["winner"]["title"], "Second")

    def test_deterministic_zip_has_exact_root_and_stable_hash(self) -> None:
        project = make_project(self.root / "build")
        nested = project / "Ancient" / "Entity" / "Synthetic"
        nested.mkdir(parents=True)
        (nested / "b.txt").write_bytes(b"B")
        (nested / "a.txt").write_bytes(b"A")
        first, members1 = ac.build_zip_bytes(project)
        second, members2 = ac.build_zip_bytes(project)
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
        self.assertEqual(members1, members2)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertTrue(
                all(
                    name == "Ancient/" or name.startswith("Ancient/") for name in archive.namelist()
                )
            )
            self.assertTrue(
                all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
            )

    def test_builder_stores_extreme_ratio_member_so_its_validator_accepts_it(self) -> None:
        project = make_project(self.root / "ratio")
        (project / "Ancient" / "zeros.bin").write_bytes(b"\0" * (1024 * 1024))
        result = ac.build_project(project, output=None, apply=True)
        archive_path = Path(result["output"])
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(archive.getinfo("Ancient/zeros.bin").compress_type, zipfile.ZIP_STORED)
        report = ac.validate_target(project)
        self.assertNotIn("ZIP_RESOURCE_LIMIT", {issue["code"] for issue in report["issues"]})
        self.assertTrue(report["valid"])

    def test_byte_compatibility_helper_has_a_separate_memory_cap(self) -> None:
        project = make_project(self.root / "memory-cap")
        (project / "Ancient" / "payload.txt").write_bytes(b"payload")
        with (
            mock.patch.object(ac, "MAX_IN_MEMORY_ZIP_BYTES", 1),
            self.assertRaisesRegex(ac.ModToolError, "in-memory limit"),
        ):
            ac.build_zip_bytes(project)

    def test_build_project_uses_streaming_archive_path(self) -> None:
        project = make_project(self.root / "stream-build")
        (project / "Ancient" / "payload.txt").write_bytes(b"payload")
        with mock.patch.object(
            ac, "build_zip_bytes", side_effect=AssertionError("must not buffer archive")
        ):
            preview = ac.build_project(project, output=None, apply=False)
        self.assertGreater(preview["bytes"], 0)

    def test_build_dry_run_then_apply(self) -> None:
        project = make_project(self.root / "apply-build")
        (project / "Ancient" / "payload.txt").write_text("data", encoding="utf-8")
        preview = ac.build_project(project, output=None, apply=False)
        self.assertFalse((project / "Mod.zip").exists())
        result = ac.build_project(project, output=None, apply=True)
        self.assertTrue((project / "Mod.zip").is_file())
        self.assertEqual(preview["sha256"], result["sha256"])
        original_zip = (project / "Mod.zip").read_bytes()
        (project / "Ancient" / "payload.txt").write_text("changed", encoding="utf-8")
        rebuilt = ac.build_project(project, output=None, apply=True)
        self.assertTrue(Path(rebuilt["backup"]).is_file())
        self.assertEqual(Path(rebuilt["backup"]).read_bytes(), original_zip)
        self.assertNotEqual(rebuilt["sha256"], result["sha256"])

    def test_build_output_cannot_replace_project_sources(self) -> None:
        project = make_project(self.root / "build-output-collision")
        payload = project / "Ancient" / "payload.txt"
        payload.write_bytes(b"payload")
        protected = (project / "Index.art", project / "Thumbnail.jpg", payload)
        before = {path: path.read_bytes() for path in protected}
        destinations = (*protected, project / "Ancient", project / "Ancient" / "nested.zip")
        for destination in destinations:
            for apply in (False, True):
                with self.subTest(destination=destination, apply=apply):
                    with self.assertRaisesRegex(ac.ModToolError, "collides with project source"):
                        ac.build_project(project, output=destination, apply=apply)
        self.assertEqual({path: path.read_bytes() for path in protected}, before)
        self.assertFalse(any(project.glob("*.bak*")))

    def test_metadata_dry_run_and_apply_creates_backup(self) -> None:
        project = make_project(self.root / "metadata")
        original = (project / "Index.art").read_bytes()
        preview = ac.apply_metadata(project, {"Title": "Changed"}, apply=False, backup=True)
        self.assertTrue(preview["changed"])
        self.assertEqual((project / "Index.art").read_bytes(), original)
        applied = ac.apply_metadata(project, {"Title": "Changed"}, apply=True, backup=True)
        self.assertTrue(Path(applied["backup"]).is_file())
        fields, _, _ = ac.manifest_fields(
            ac.decode_utf16le_art((project / "Index.art").read_bytes())
        )
        self.assertEqual(fields["Title"], "Changed")
        self.assertEqual(Path(applied["backup"]).read_bytes(), original)

    def test_metadata_refuses_duplicate_or_wrong_type_fields_without_writing(self) -> None:
        duplicate_project = make_project(self.root / "metadata-duplicate")
        duplicate_manifest = duplicate_project / "Index.art"
        duplicate_text = ac.decode_utf16le_art(duplicate_manifest.read_bytes())
        duplicate_text += '\nString:{Name:"Title" Value:"Duplicate"}\n'
        write_art(duplicate_manifest, duplicate_text)
        duplicate_before = duplicate_manifest.read_bytes()
        with self.assertRaisesRegex(ac.ModToolError, "duplicate manifest fields"):
            ac.apply_metadata(duplicate_project, {"Title": "Changed"}, apply=True, backup=True)
        self.assertEqual(duplicate_manifest.read_bytes(), duplicate_before)

        type_project = make_project(self.root / "metadata-type")
        type_manifest = type_project / "Index.art"
        type_text = ac.decode_utf16le_art(type_manifest.read_bytes())
        expected = 'String:\n{\n\tName:"Title"'
        replacement = 'U32:\n{\n\tName:"Title"'
        self.assertIn(expected, type_text)
        write_art(type_manifest, type_text.replace(expected, replacement, 1))
        type_before = type_manifest.read_bytes()
        with self.assertRaisesRegex(ac.ModToolError, "invalid manifest field type"):
            ac.apply_metadata(type_project, {"Title": "Changed"}, apply=True, backup=True)
        self.assertEqual(type_manifest.read_bytes(), type_before)

    def test_metadata_refuses_empty_required_field_without_writing(self) -> None:
        project = make_project(self.root / "metadata-empty")
        manifest = project / "Index.art"
        before = manifest.read_bytes()
        for field in ("Title", "Description", "Changelog", "Type"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ac.ModToolError, "missing or empty"):
                    ac.apply_metadata(project, {field: "   "}, apply=True, backup=True)
                self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(any(project.glob("Index.art.bak*")))

    def test_metadata_refuses_unbalanced_art_without_writing(self) -> None:
        cases = {
            "brace": valid_manifest() + "\nNode:{\n",
            "quote": valid_manifest() + '\nNode:{Name:"unterminated}\n',
        }
        for name, malformed in cases.items():
            with self.subTest(name=name):
                project = make_project(self.root / f"metadata-unbalanced-{name}")
                manifest = project / "Index.art"
                write_art(manifest, malformed)
                before = manifest.read_bytes()
                with self.assertRaisesRegex(ac.ModToolError, "refusing metadata mutation"):
                    ac.apply_metadata(project, {"Title": "Changed"}, apply=True, backup=True)
                self.assertEqual(manifest.read_bytes(), before)
                self.assertFalse(any(project.glob("Index.art.bak*")))

    def test_backup_creation_treats_dangling_link_name_as_occupied(self) -> None:
        project = make_project(self.root / "backup-link")
        original_open = ac.os.open
        blocked = project / "Index.art.bak"

        def simulate_dangling_link(path: os.PathLike[str] | str, flags: int, mode: int) -> int:
            if Path(path) == blocked:
                raise FileExistsError(path)
            return original_open(path, flags, mode)

        with mock.patch.object(ac.os, "open", side_effect=simulate_dangling_link):
            applied = ac.apply_metadata(project, {"Title": "Changed"}, apply=True, backup=True)
        self.assertEqual(Path(applied["backup"]).name, "Index.art.bak.1")
        self.assertFalse(blocked.exists())

    def test_metadata_apply_refuses_lexical_symlink(self) -> None:
        real = make_project(self.root / "real")
        alias = self.root / "alias"
        alias.mkdir()
        link = alias / "Index.art"
        try:
            os.symlink(real / "Index.art", link)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")
        with self.assertRaisesRegex(ac.ModToolError, "symbolic link"):
            ac.apply_metadata(alias, {"Title": "Redirected"}, apply=True, backup=True)

    def test_metadata_added_block_preserves_crlf(self) -> None:
        project = make_project(self.root / "crlf")
        text = valid_manifest().replace("\n", "\r\n")
        type_block = '\r\n\r\nString:\r\n{\r\n\tName:"Type"\r\n\tValue:"Generic"\r\n}\r\n'
        text = text.replace(type_block, "\r\n")
        write_art(project / "Index.art", text)
        ac.apply_metadata(project, {"Type": "Generic"}, apply=True, backup=False)
        changed = ac.decode_utf16le_art((project / "Index.art").read_bytes())
        self.assertNotIn("\n", changed.replace("\r\n", ""))
        self.assertEqual(ac.manifest_fields(changed)[0]["Type"], "Generic")

    def test_canonical_manifest_includes_content(self) -> None:
        text = valid_manifest()
        fields, _, _ = ac.manifest_fields(text)
        self.assertIn("Content", fields)
        self.assertEqual(fields["Content"], "")
        content_block = text.split('Name:"Content"', 1)[1].split("}", 1)[0]
        self.assertNotIn("Value:", content_block)

    def test_canonical_manifest_can_render_explicit_content_value(self) -> None:
        text = ac.canonical_manifest(
            title="Synthetic",
            description="Synthetic description",
            changelog="Initial",
            game_version="22",
            mod_type="Generic",
            steam_mod_id="0,0",
            content="Explicit content",
        )
        content_block = text.split('Name:"Content"', 1)[1].split("}", 1)[0]
        self.assertIn('Value:"Explicit content"', content_block)

    def test_initialise_project_is_dry_run_first(self) -> None:
        project = self.root / "new-project"
        preview = ac.initialise_project(
            project,
            title="New",
            description="Synthetic",
            changelog="Initial",
            game_version="22",
            mod_type="Generic",
            steam_mod_id="0",
            apply=False,
        )
        self.assertEqual(preview["mode"], "dry-run")
        self.assertFalse(project.exists())
        ac.initialise_project(
            project,
            title="New",
            description="Synthetic",
            changelog="Initial",
            game_version="22",
            mod_type="Generic",
            steam_mod_id="0",
            apply=True,
        )
        self.assertTrue((project / "Index.art").is_file())
        self.assertTrue((project / "Ancient").is_dir())
        self.assertFalse((project / "Thumbnail.jpg").exists())

    def test_initialise_project_refuses_non_empty_directory(self) -> None:
        project = self.root / "non-empty-project"
        project.mkdir()
        marker = project / "keep.txt"
        marker.write_bytes(b"keep")
        for apply in (False, True):
            with self.subTest(apply=apply):
                with self.assertRaisesRegex(ac.ModToolError, "non-empty project directory"):
                    ac.initialise_project(
                        project,
                        title="New",
                        description="Synthetic",
                        changelog="Initial",
                        game_version="22",
                        mod_type="Generic",
                        steam_mod_id="0",
                        apply=apply,
                    )
        self.assertEqual(marker.read_bytes(), b"keep")
        self.assertFalse((project / "Index.art").exists())


class DiscoveryAndLogTests(SyntheticTempTestCase):
    def test_catalog_query_filters_title_and_type(self) -> None:
        collection = self.root / "collection"
        stone = make_project(collection / "100", title="Stone Tools")
        wood = make_project(collection / "200", title="Woodland")
        (stone / "Ancient" / "stone.txt").write_bytes(b"stone")
        (wood / "Ancient" / "wood.txt").write_bytes(b"wood")
        report = ac.catalog_mods(ac.DiscoveryContext(), [collection], query="stone")
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["mods"][0]["title"], "Stone Tools")

    def test_dynamic_steam_manifest_version_and_enabled_order(self) -> None:
        steam = self.root / "Steam"
        steamapps = steam / "steamapps"
        game = steamapps / "common" / "Ancient Cities Synthetic"
        data_root = game / "Ancient" / "Data" / "Ancient"
        builtin = data_root / "Mod" / "English"
        builtin.mkdir(parents=True)
        steamapps.mkdir(parents=True, exist_ok=True)
        (steamapps / "libraryfolders.vdf").write_text(
            f'"libraryfolders"\n{{\n "0" {{ "path" "{steam}" }}\n}}', encoding="utf-8"
        )
        (steamapps / "appmanifest_667610.acf").write_text(
            '"AppState"\n{\n"appid" "667610"\n"installdir" "Ancient Cities Synthetic"\n'
            '"buildid" "424242"\n"StateFlags" "4"\n}',
            encoding="utf-8",
        )
        (data_root / "version.txt").write_text("1.2.3\n0123456789abcdef\n", encoding="utf-8")
        write_art(builtin / "Index.art", valid_manifest(game_version="22"))

        docs = self.root / "Documents"
        config = docs / "Uncasual Games" / "Ancient Cities" / "User" / "Configuration.art"
        write_art(
            config,
            "\nString/Vector:{Name:\"Id\" Data:\"'A','B','C'\"}\n"
            'U32/Vector:{Name:"Enabled" Value:"1,1,4294967295"}\n',
        )
        ctx = ac.discover_context(steam_root=steam, game_dir=game, documents_dir=docs)
        self.assertEqual(ctx.build_id, "424242")
        self.assertEqual(ctx.semver, "1.2.3")
        self.assertEqual(ctx.content_hash, "0123456789abcdef")
        self.assertEqual(ctx.game_version, "22")
        self.assertEqual([item["id"] for item in ctx.enabled_configured], ["A", "B"])
        self.assertEqual([item["id"] for item in ctx.enabled_load_order], ["B", "A"])

    def test_default_conflicts_resolve_every_enabled_source_in_effective_order(self) -> None:
        user_root = self.root / "UserRoot"
        workshop = self.root / "Workshop"
        game = self.root / "Game"
        built_in = game / "Ancient" / "Data" / "Ancient" / "Mod"
        expected = [
            user_root / "Mod" / "UserOnly",
            workshop / "WorkshopOnly",
            built_in / "BuiltInOnly",
            user_root / "Mod" / "Priority",
        ]
        for path in expected:
            path.mkdir(parents=True)
        (workshop / "Priority").mkdir()
        (built_in / "Priority").mkdir()
        ctx = ac.DiscoveryContext(
            game_dir=game,
            user_root=user_root,
            workshop_roots=[workshop],
            enabled_load_order=[
                {"id": "UserOnly"},
                {"id": "WorkshopOnly"},
                {"id": "BuiltInOnly"},
                {"id": "Priority"},
                {"id": "Missing"},
            ],
        )
        self.assertEqual(ac._default_conflict_paths(ctx), expected)

    def test_catalog_exposes_unique_enabled_count_across_physical_copies(self) -> None:
        user_root = self.root / "CatalogUser"
        workshop = self.root / "CatalogWorkshop"
        make_project(user_root / "Mod" / "100", title="User Copy")
        make_project(workshop / "100", title="Workshop Copy")
        ctx = ac.DiscoveryContext(
            user_root=user_root,
            workshop_roots=[workshop],
            enabled_load_order=[{"id": "100", "load_index": 0}],
        )
        report = ac.catalog_mods(ctx)
        self.assertEqual(report["enabled_count"], 2)
        self.assertEqual(report["unique_enabled_count"], 1)

    def test_bomless_utf16le_log_and_filters(self) -> None:
        text = (
            "[12:00:00] Ancient Cities.1.2.3\n"
            "[12:00:01] Warning - synthetic warning\n"
            "[12:00:02] ERROR - synthetic failure\n"
            "[12:00:03] Enabling Mod: X\n"
        )
        path = self.root / "Log.txt"
        path.write_bytes(text.encode("utf-16-le"))
        self.assertEqual(ac.decode_log_bytes(path.read_bytes()), text)
        report = ac.read_log(path, tail=None, severity="error")
        self.assertEqual(report["summary"]["warnings"], 1)
        self.assertEqual(report["summary"]["errors_or_failures"], 1)
        self.assertEqual(report["summary"]["mods_enabled"], 1)
        self.assertEqual(len(report["lines"]), 1)


if __name__ == "__main__":
    unittest.main()

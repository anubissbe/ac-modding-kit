"""Synthetic contract tests for standalone building scaffolds."""

from __future__ import annotations

import codecs
import shutil
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest import mock

import acmk
import ancient_cities_mod as legacy
from acmk import (
    BuildingAssetPath,
    BuildingModel,
    BuildingScaffoldBuilder,
    BuildingSpec,
    ConstructionStage,
    DecayStage,
    EngineReference,
    GameVersion,
    ManifestSpec,
    SkeletonSource,
    SteamModId,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MATERIAL = EngineReference("~/Entity/Local/Resource/List/Stick/Asset/AsMaterial/Material")


def synthetic_jpeg(width: int = 512, height: int = 512) -> bytes:
    sof = b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x01\x01\x11\x00"
    return b"\xff\xd8\xff\xc0" + (len(sof) + 2).to_bytes(2, "big") + sof + b"\xff\xd9"


def synthetic_fbx() -> bytes:
    return b"Kaydara FBX Binary  \x00\x1a\x00" + (7400).to_bytes(4, "little")


def synthetic_tga(
    width: int,
    height: int,
    *,
    pixel_depth: int,
    image_type: int,
    attribute_bits: int = 8,
) -> bytes:
    header = bytearray(18)
    header[2] = image_type
    header[12:14] = width.to_bytes(2, "little")
    header[14:16] = height.to_bytes(2, "little")
    header[16] = pixel_depth
    header[17] = attribute_bits
    bytes_per_pixel = pixel_depth // 8
    pixels = width * height
    if image_type in {2, 3}:
        body = bytes(pixels * bytes_per_pixel)
    else:
        packets = bytearray()
        remaining = pixels
        while remaining:
            count = min(remaining, 128)
            packets.append(0x80 | (count - 1))
            packets.extend(bytes(bytes_per_pixel))
            remaining -= count
        body = bytes(packets)
    return bytes(header) + body


def building_spec(
    *,
    identifier: str = "SyntheticBranchHut",
    material: EngineReference = MATERIAL,
) -> BuildingSpec:
    return BuildingSpec(
        identifier=identifier,
        display_name="synthetic branch hut",
        plural_name="synthetic branch huts",
        description="Original synthetic test dwelling.",
        preview_model=BuildingAssetPath("Blueprint.fbx"),
        default_models=(
            BuildingModel("Struct", BuildingAssetPath("Struct_Default.fbx"), material),
        ),
        construction_stages=(
            ConstructionStage(
                "00-Labour",
                None,
                10,
                (BuildingModel("Struct", BuildingAssetPath("Struct_Build_00.fbx"), material),),
            ),
            ConstructionStage(
                "01-Stick",
                EngineReference("~/Entity/Local/Resource/List/Stick/Entity"),
                24,
                (BuildingModel("Struct", BuildingAssetPath("Struct_Build_01.fbx"), material),),
            ),
        ),
        decay_stages=(
            DecayStage(
                "00-Light",
                (BuildingModel("Struct", BuildingAssetPath("Struct_Decay_00.fbx"), material),),
            ),
        ),
        mod_dependencies=("SyntheticMaterials",),
        mod_conflicts=("LegacySyntheticHut",),
    )


class BuildingScaffoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = REPO_ROOT / "tests" / f".building-{uuid.uuid4().hex}"
        self.root.mkdir()
        game = self.root / "Game"
        base = game / "Ancient" / "Data" / "Ancient"
        (base / "Entity" / "Local" / "Building").mkdir(parents=True)
        (base / "Entity" / "Local" / "Building" / "Building.art").write_bytes(
            codecs.BOM_UTF16_LE + "Group:{}\n".encode("utf-16-le")
        )
        (base / "Entity" / "Local" / "Building" / "Master.art").write_bytes(
            codecs.BOM_UTF16_LE + "Group:{}\n".encode("utf-16-le")
        )
        for relative in (
            "Entity/Local/Resource/Stick",
            "Entity/Knowledge/Architecture",
            "Entity/Local/Location/Door",
        ):
            directory = base.joinpath(*relative.split("/"))
            directory.mkdir(parents=True)
            (directory / "Index.art").write_bytes(
                codecs.BOM_UTF16_LE + "Group:{}\n".encode("utf-16-le")
            )
        for relative, name in (
            ("Entity/Local/Environment", "Environment.art"),
            ("Entity/Local/Terrain", "Terrain.art"),
        ):
            directory = base.joinpath(*relative.split("/"))
            directory.mkdir(parents=True)
            (directory / name).write_bytes(codecs.BOM_UTF16_LE + "Group:{}\n".encode("utf-16-le"))
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

    def builder(self, *, spec: BuildingSpec | None = None) -> BuildingScaffoldBuilder:
        return BuildingScaffoldBuilder(
            self.root / "project",
            project_identifier="synthetic-building",
            manifest=ManifestSpec(
                title="Synthetic Building",
                description="Original synthetic fixtures only.",
                changelog="Initial authoring draft",
                game_version=GameVersion("22"),
            ),
            building=spec or building_spec(),
            context=self.context,
        )

    def add_valid_assets(self, builder: BuildingScaffoldBuilder) -> None:
        for path in builder.building.model_files:
            builder.add_asset(path, synthetic_fbx())
        builder.add_asset(
            builder.building.icon,
            synthetic_tga(128, 128, pixel_depth=32, image_type=10),
        )
        builder.add_asset(
            builder.building.location_mask,
            synthetic_tga(5, 5, pixel_depth=8, image_type=3),
        )
        builder.set_thumbnail(synthetic_jpeg())

    def test_typed_spec_renders_exact_utf16le_art_and_localization(self) -> None:
        spec = building_spec()
        art = spec.render_index_art()
        localization = spec.render_localization()
        self.assertTrue(art.to_bytes().startswith(codecs.BOM_UTF16_LE))
        self.assertFalse(art.to_bytes().startswith(codecs.BOM_UTF16_LE * 2))
        self.assertEqual(art.newline_style, acmk.NewlineStyle.CRLF)
        self.assertTrue(art.text.endswith("\r\n"))

        expected_localization = (
            "#./Localization/Description\n"
            "Original synthetic test dwelling.\n"
            "#./Localization/Noun\n"
            "NEUTER\n"
            "COUNTABLE\n"
            "synthetic branch hut\n"
            "synthetic branch huts"
        )
        self.assertEqual(localization.newline_style, acmk.NewlineStyle.LF)
        self.assertFalse(localization.text.endswith(("\r", "\n")))
        self.assertEqual(localization.text, expected_localization)
        self.assertEqual(
            localization.to_bytes(),
            codecs.BOM_UTF16_LE + expected_localization.encode("utf-16-le"),
        )
        self.assertIn("Entity/Construction/Building:", art.text)
        self.assertIn('Category:"Housing"', art.text)
        self.assertIn('ServiceVacant:"4"', art.text)
        self.assertIn('File:"Blueprint.fbx"', art.text)
        self.assertIn('Name:"LocationMask"', art.text)
        self.assertIn('File:"LocationMask.tga"', art.text)
        self.assertEqual(
            spec.index_path.value,
            "Ancient/Entity/Local/Building/SyntheticBranchHut/Index.art",
        )
        self.assertEqual(
            [line for line in localization.text.splitlines() if line.startswith("#")],
            ["#./Localization/Description", "#./Localization/Noun"],
        )

    def test_requirement_fields_can_only_be_omitted_together(self) -> None:
        ungated = replace(
            building_spec(),
            requirements=(),
            requirement_percent=(),
        )
        art = ungated.render_index_art().text
        self.assertNotIn('RequirementPercent:"', art)
        self.assertNotIn('Requirement:"', art)

        with self.assertRaisesRegex(acmk.ContractError, "align exactly"):
            replace(
                ungated,
                requirements=(EngineReference("~/Entity/Knowledge/List/Fishing/Entity"),),
            )
        with self.assertRaisesRegex(acmk.ContractError, "align exactly"):
            replace(ungated, requirement_percent=(0.25,))

    def test_constitution_counts_accept_positive_numbers_and_render_canonically(self) -> None:
        spec = building_spec()
        fractional = replace(
            spec,
            construction_stages=(
                replace(spec.construction_stages[0], count=1),
                replace(spec.construction_stages[1], count=0.25),
            ),
        )
        self.assertIn('ConstitutionCount:"1,0.25"', fractional.render_index_art().text)

        for invalid in (0, -1, float("inf"), float("nan"), True, "1", 10**10_000):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(acmk.ContractError, "positive finite number"):
                    replace(  # type: ignore[arg-type]
                        spec.construction_stages[0],
                        count=invalid,
                    )

    def test_validation_rejects_non_runtime_localization_newlines(self) -> None:
        bad_localization = acmk.Utf16TextDocument.from_text(
            "#./Localization/Description\r\n"
            "Description\r\n"
            "#./Localization/Noun\r\n"
            "NEUTER\r\n"
            "COUNTABLE\r\n"
            "hut\r\n"
            "huts\r\n",
            kind=acmk.TextAssetKind.LOC,
        )
        with mock.patch.object(
            BuildingSpec,
            "render_localization",
            return_value=bad_localization,
        ):
            codes = {issue.code for issue in self.builder().validate().issues}
        self.assertIn("BUILDING_LOCALIZATION_NEWLINES", codes)

        content = self.builder().validate().content
        self.assertEqual(
            content["generated_art"],
            "UTF-16LE+BOM; CRLF; terminal-CRLF",
        )
        self.assertEqual(
            content["generated_localization"],
            "UTF-16LE+BOM; LF; no-terminal-newline",
        )

    def test_validation_reports_missing_and_malformed_assets(self) -> None:
        builder = self.builder()
        initial_codes = {issue.code for issue in builder.validate().issues}
        self.assertIn("BUILDING_ASSET_MISSING", initial_codes)
        self.assertIn("BUILDING_THUMBNAIL_MISSING", initial_codes)

        for path in builder.building.model_files:
            builder.add_asset(path, synthetic_fbx())
        builder.add_asset(
            builder.building.icon,
            synthetic_tga(128, 128, pixel_depth=32, image_type=10),
        )
        builder.add_asset(
            builder.building.location_mask,
            synthetic_tga(4, 5, pixel_depth=8, image_type=3),
        )
        builder.set_thumbnail(synthetic_jpeg())
        report = builder.validate()
        self.assertFalse(report.valid)
        self.assertIn("BUILDING_MASK_TGA", {issue.code for issue in report.issues})

        malformed = self.builder()
        for index, path in enumerate(malformed.building.model_files):
            malformed.add_asset(
                path.value.lower() if index == 0 else path,
                b"not an FBX" if index == 0 else synthetic_fbx(),
            )
        malformed.add_asset(
            malformed.building.icon,
            synthetic_tga(
                128,
                128,
                pixel_depth=32,
                image_type=10,
                attribute_bits=0,
            ),
        )
        malformed.add_asset(
            malformed.building.location_mask,
            synthetic_tga(5, 5, pixel_depth=8, image_type=3),
        )
        malformed.set_thumbnail(synthetic_jpeg())
        malformed_codes = {issue.code for issue in malformed.validate().issues}
        self.assertIn("BUILDING_ASSET_CASE", malformed_codes)
        self.assertIn("BUILDING_MODEL_SIGNATURE", malformed_codes)
        self.assertIn("BUILDING_ICON_TGA", malformed_codes)

    def test_preview_is_write_free_and_apply_is_atomic(self) -> None:
        builder = self.builder()
        self.add_valid_assets(builder)
        plan = builder.plan()
        preview = plan.preview()
        self.assertEqual(preview.mode, acmk.ExecutionMode.DRY_RUN)
        self.assertFalse(preview.project_root.exists())
        self.assertTrue(preview.validation.valid)
        self.assertIn(MATERIAL.value, preview.engine_references)
        self.assertEqual(preview.mod_dependencies, ("SyntheticMaterials",))
        self.assertEqual(preview.mod_conflicts, ("LegacySyntheticHut",))
        self.assertNotIn("dependencies", preview.to_dict())
        self.assertIn(
            "src/Ancient/Entity/Local/Building/SyntheticBranchHut/Index.art",
            preview.files,
        )

        result = plan.apply()
        self.assertEqual(result.mode, acmk.ExecutionMode.APPLY)
        self.assertTrue(result.project_root.is_dir())
        art_path = (
            result.project_root
            / "src"
            / "Ancient"
            / "Entity"
            / "Local"
            / "Building"
            / "SyntheticBranchHut"
            / "Index.art"
        )
        loc_path = art_path.with_name("Index.en.loc")
        art_data = art_path.read_bytes()
        loc_data = loc_path.read_bytes()
        for data in (art_data, loc_data):
            self.assertTrue(data.startswith(codecs.BOM_UTF16_LE))
            self.assertFalse(data.startswith(codecs.BOM_UTF16_LE * 2))
        self.assertTrue(art_data.endswith("\r\n".encode("utf-16-le")))
        self.assertFalse(loc_data.endswith(("\r\n".encode("utf-16-le"), "\n".encode("utf-16-le"))))
        project = plan.open()
        self.assertEqual(project.config.skeleton, SkeletonSource.COMMUNITY_DRAFT)
        self.assertEqual(project.config.dependencies, ("SyntheticMaterials",))
        self.assertEqual(project.config.conflicts, ("LegacySyntheticHut",))
        self.assertTrue(project.validate(acmk.ValidationProfile.AUTHORING).valid)

    def test_base_collision_and_unconfirmed_reference_are_visible(self) -> None:
        building_root = self.context.base_data_root / "Entity" / "Local" / "Building"
        assert building_root is not None
        (building_root / "SyntheticBranchHut").mkdir()
        builder = self.builder(
            spec=building_spec(material=EngineReference("~/Unconfirmed/Material/Node"))
        )
        self.add_valid_assets(builder)
        report = builder.validate()
        codes = {issue.code for issue in report.issues}
        self.assertIn("BUILDING_IDENTIFIER_COLLISION", codes)
        self.assertIn("BUILDING_REFERENCE_UNCONFIRMED", codes)

    def test_manifest_preflight_rejects_wrong_type_version_and_published_id(self) -> None:
        builder = BuildingScaffoldBuilder(
            self.root / "manifest-project",
            project_identifier="manifest-building",
            manifest=ManifestSpec(
                title="Wrong Manifest",
                description="Synthetic test",
                changelog="Test",
                game_version=GameVersion("21"),
                mod_type="Landmark",
                steam_mod_id=SteamModId(42, 0),
                content="noncanonical value",
            ),
            building=building_spec(identifier="ManifestBuilding"),
            context=self.context,
        )
        self.add_valid_assets(builder)
        codes = {issue.code for issue in builder.validate().issues}
        self.assertIn("BUILDING_MANIFEST_TYPE", codes)
        self.assertIn("BUILDING_MANIFEST_GAME_VERSION", codes)
        self.assertIn("BUILDING_MANIFEST_STEAM_ID", codes)
        self.assertIn("BUILDING_MANIFEST_CONTENT", codes)

    def test_contract_rejects_relative_material_and_relation_overlap(self) -> None:
        with self.assertRaisesRegex(acmk.ContractError, "external engine node"):
            BuildingModel(
                "Struct",
                BuildingAssetPath("Struct.fbx"),
                EngineReference("../Asset/Material"),
            )
        with self.assertRaisesRegex(acmk.ContractError, "depend on and conflict"):
            spec = building_spec()
            BuildingSpec(
                identifier="RelationOverlap",
                display_name=spec.display_name,
                plural_name=spec.plural_name,
                description=spec.description,
                preview_model=spec.preview_model,
                default_models=spec.default_models,
                construction_stages=spec.construction_stages,
                decay_stages=spec.decay_stages,
                mod_dependencies=("SameMod",),
                mod_conflicts=("samemod",),
            )

    def test_contract_rejects_case_ambiguous_assets_and_unbounded_counts(self) -> None:
        with self.assertRaisesRegex(acmk.ContractError, "case-insensitively unambiguous"):
            replace(
                building_spec(),
                preview_model=BuildingAssetPath("struct_default.fbx"),
            )

        with self.assertRaisesRegex(acmk.ContractError, "positive finite number"):
            ConstructionStage(
                "00-TooLarge",
                None,
                1_000_001,
                (BuildingModel("Struct", BuildingAssetPath("Struct.fbx"), MATERIAL),),
            )

    def test_oversized_rle_tga_is_rejected_before_packet_expansion(self) -> None:
        builder = self.builder()
        for path in builder.building.model_files:
            builder.add_asset(path, synthetic_fbx())
        builder.add_asset(
            builder.building.icon,
            synthetic_tga(128, 128, pixel_depth=32, image_type=10),
        )
        oversized_header = bytearray(18)
        oversized_header[2] = 11
        oversized_header[12:14] = (65535).to_bytes(2, "little")
        oversized_header[14:16] = (65535).to_bytes(2, "little")
        oversized_header[16] = 8
        builder.add_asset(builder.building.location_mask, bytes(oversized_header))
        builder.set_thumbnail(synthetic_jpeg())

        mask_issues = [
            issue for issue in builder.validate().issues if issue.code == "BUILDING_MASK_TGA"
        ]
        self.assertEqual(len(mask_issues), 1)
        self.assertIn("must be 5x5", mask_issues[0].message)
        self.assertNotIn("packet stream", mask_issues[0].message)


if __name__ == "__main__":
    unittest.main()

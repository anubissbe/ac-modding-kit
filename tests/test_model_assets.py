from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path, PurePosixPath

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODELING_ROOT = REPOSITORY_ROOT / "modeling"
TOOLCHAIN_LOCK = MODELING_ROOT / "toolchain.lock.json"
REQUIRE_OUTPUTS = os.environ.get("ACMK_REQUIRE_MODEL_OUTPUTS") == "1"
MAX_REGULAR_GIT_BINARY_BYTES = 10 * 1024 * 1024

if not MODELING_ROOT.is_dir():
    pytest.skip("model assets are repository-source content", allow_module_level=True)

PRIVATE_PATH_MARKERS = (
    b"c:\\users\\",
    b"c:/users/",
    b"users\\",
    b"/home/",
    b"/users/",
    b"onedrive\\",
    b"appdata\\",
)

ASSETS = {
    "building": MODELING_ROOT / "assets" / "building" / "starter_shelter",
    "plant": MODELING_ROOT / "assets" / "plant" / "starter_plant",
    "resource": MODELING_ROOT / "assets" / "resource" / "starter_resource",
}

EXPECTED_TEXTURES = [
    "textures/C.tga",
    "textures/N.tga",
    "textures/T.tga",
    "textures/O.tga",
]
EXPECTED_TOOLCHAIN_SHA256 = "2d184b626c001692c362291911293b6a297179d618d95e9e9192c3a80318adc4"


def load_manifest(asset_dir: Path) -> dict[str, object]:
    with (asset_dir / "asset.toml").open("rb") as stream:
        return tomllib.load(stream)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def assert_safe_relative_path(value: str) -> PurePosixPath:
    normalized_text = value.replace("\\", "/")
    normalized = PurePosixPath(normalized_text)
    assert not normalized_text.startswith("/")
    assert not re.match(r"^[A-Za-z]:/", normalized_text)
    assert ".." not in normalized.parts
    return normalized


def fixed_output_paths(asset_dir: Path, manifest: dict[str, object]) -> list[Path]:
    outputs = manifest["outputs"]
    assert isinstance(outputs, dict)
    relative_paths = [
        *outputs["textures"],
        outputs["preview"],
        outputs["report"],
        outputs["checksums"],
    ]
    return [asset_dir / str(path) for path in relative_paths]


def all_generated_paths(asset_dir: Path, manifest: dict[str, object]) -> list[Path]:
    outputs = manifest["outputs"]
    assert isinstance(outputs, dict)
    source_files = sorted(asset_dir.glob(str(outputs["source_glob"])))
    export_files = sorted(asset_dir.glob(str(outputs["export_glob"])))
    return [*source_files, *export_files, *fixed_output_paths(asset_dir, manifest)]


def assert_not_lfs_pointer(path: Path) -> None:
    with path.open("rb") as stream:
        prefix = stream.read(128)
    assert not prefix.startswith(b"version https://git-lfs.github.com/spec/v1"), (
        f"{path} is an LFS pointer; compact starter assets must remain regular Git files"
    )


def assert_no_private_path(path: Path) -> None:
    payload = path.read_bytes().lower()
    markers = [*PRIVATE_PATH_MARKERS]
    markers.extend(marker.decode("ascii").encode("utf-16-le") for marker in PRIVATE_PATH_MARKERS)
    assert not any(marker in payload for marker in markers), f"{path} contains a private user path"


def assert_tga_contract(path: Path) -> None:
    header = path.read_bytes()[:18]
    assert len(header) == 18, f"{path} has a truncated TGA header"
    assert header[2] in {2, 3, 10, 11}, f"{path} is not a supported true-colour/grayscale TGA"
    width = int.from_bytes(header[12:14], "little")
    height = int.from_bytes(header[14:16], "little")
    depth = header[16]
    assert is_power_of_two(width) and is_power_of_two(height), (
        f"{path} dimensions must be powers of two, got {width}x{height}"
    )
    assert depth in {8, 24, 32}, f"{path} has unsupported {depth}-bit pixels"


def assert_png_has_no_private_metadata(path: Path) -> None:
    payload = path.read_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    chunk_types: list[bytes] = []
    while offset < len(payload):
        assert offset + 12 <= len(payload), f"{path} has a truncated PNG chunk"
        length = int.from_bytes(payload[offset : offset + 4], "big")
        chunk_end = offset + 12 + length
        assert chunk_end <= len(payload), f"{path} has an invalid PNG chunk length"
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_types.append(chunk_type)
        offset = chunk_end
        if chunk_type == b"IEND":
            break
    assert offset == len(payload) and chunk_types[-1] == b"IEND", f"{path} has invalid PNG data"
    forbidden = {b"eXIf", b"iTXt", b"tEXt", b"tIME", b"zTXt"}
    assert forbidden.isdisjoint(chunk_types), f"{path} contains private/free-form PNG metadata"


def parse_checksums(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        assert len(parts) == 2, f"{path}:{line_number} is not a SHA-256 manifest entry"
        digest, relative_path = parts
        relative_path = relative_path.lstrip("*")
        assert re.fullmatch(r"[0-9a-f]{64}", digest), (
            f"{path}:{line_number} has an invalid SHA-256 digest"
        )
        normalized = assert_safe_relative_path(relative_path)
        key = normalized.as_posix()
        assert key not in entries, f"{path}:{line_number} duplicates {key}"
        entries[key] = digest
    return entries


def test_toolchain_is_exactly_pinned() -> None:
    assert (MODELING_ROOT / "BLENDER_VERSION").read_text(encoding="utf-8").strip() == "5.2.0"
    lock = json.loads(TOOLCHAIN_LOCK.read_text(encoding="utf-8"))
    assert lock["schema_version"] == 1
    blender = lock["blender"]
    assert blender == {
        "version": "5.2.0",
        "release_line": "LTS",
        "platform": "windows-x64",
        "distribution": "portable-zip",
        "archive": "blender-5.2.0-windows-x64.zip",
        "url": ("https://download.blender.org/release/Blender5.2/blender-5.2.0-windows-x64.zip"),
        "sha256": EXPECTED_TOOLCHAIN_SHA256,
    }


def test_every_asset_manifest_is_registered() -> None:
    discovered = {path.parent.resolve() for path in MODELING_ROOT.glob("assets/*/*/asset.toml")}
    registered = {path.resolve() for path in ASSETS.values()}
    assert discovered == registered, (
        "every modeling/assets/*/*/asset.toml directory must be registered in ASSETS; "
        f"missing={sorted(str(path) for path in discovered - registered)}, "
        f"stale={sorted(str(path) for path in registered - discovered)}"
    )


@pytest.mark.parametrize(("category", "asset_dir"), ASSETS.items())
def test_asset_manifest_contract(category: str, asset_dir: Path) -> None:
    manifest = load_manifest(asset_dir)
    expected_id = {
        "building": "starter_shelter",
        "plant": "starter_plant",
        "resource": "starter_resource",
    }[category]

    assert manifest["schema_version"] == 1
    assert manifest["id"] == expected_id
    assert manifest["category"] == category
    assert manifest["status"] == "authoring-example"
    assert manifest["license"] == "MIT"
    assert manifest["author"] == "Bert Colemont (@anubissbe)"
    assert manifest["contact"] == "https://github.com/anubissbe/ac-modding-kit/issues"
    assert manifest["ai_assisted"] is True
    assert manifest["contains_game_assets"] is False
    assert manifest["contains_workshop_assets"] is False
    assert manifest["runtime_tested"] is False

    toolchain = manifest["toolchain"]
    assert toolchain["blender_version"] == "5.2.0"
    assert (asset_dir / toolchain["lock_file"]).resolve() == TOOLCHAIN_LOCK.resolve()

    compatibility = manifest["compatibility"]
    assert compatibility == {
        "steam_app_id": 667610,
        "game_semver": "1.9.3",
        "steam_build_id": 23915225,
        "internal_game_version": "22",
        "claim": "authoring-only",
    }

    outputs = manifest["outputs"]
    assert outputs["source_glob"] == "source/*.blend"
    assert outputs["export_glob"] == "exports/*.fbx"
    assert outputs["textures"] == EXPECTED_TEXTURES
    assert outputs["preview"] == "preview.png"
    assert outputs["report"] == "report.json"
    assert outputs["checksums"] == "checksums.sha256"

    for value in [
        outputs["source_glob"],
        outputs["export_glob"],
        *outputs["textures"],
        outputs["preview"],
        outputs["report"],
        outputs["checksums"],
    ]:
        assert_safe_relative_path(str(value))

    model_contract = manifest["model_contract"]
    assert model_contract["source_up_axis"] == "Z"
    assert model_contract["fbx_up_axis"] == "Y"


def test_category_specific_contracts() -> None:
    building = load_manifest(ASSETS["building"])["model_contract"]
    assert set(building["required_roles"]) == {
        "blueprint",
        "collider",
        "dark",
        "build",
        "decay",
        "default",
    }

    plant = load_manifest(ASSETS["plant"])["model_contract"]
    assert plant["mesh_names"] == ["LOD0", "LOD1"]
    assert plant["states"] == ["Alive"]
    assert plant["mode_rgba"] == "WindNone"

    resource = load_manifest(ASSETS["resource"])["model_contract"]
    assert set(resource["required_roles"]) == {"resource", "heap", "pile", "load"}
    assert resource["mode_rgba"] == "ColorVSplit"
    assert resource["split_alpha_range_u8"] == [254, 0]
    assert resource["load_demo_alpha_u8"] == [254, 127, 0]


@pytest.mark.parametrize("asset_dir", ASSETS.values())
def test_asset_readme_states_rights_and_runtime_boundary(asset_dir: Path) -> None:
    text = (asset_dir / "README.md").read_text(encoding="utf-8").lower()
    assert "mit" in text
    assert "no ancient cities or workshop" in text
    assert "not tested" in text


def test_binary_git_attributes_and_no_lfs_filters() -> None:
    lines = (REPOSITORY_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    stripped = {line.strip() for line in lines}
    for rule in {
        "*.blend binary",
        "*.fbx binary",
        "*.FBX binary",
        "*.tga binary",
        "*.TGA binary",
        "*.dds binary",
        "*.DDS binary",
    }:
        assert rule in stripped
    assert not any("filter=lfs" in line for line in lines)


@pytest.mark.parametrize(("category", "asset_dir"), ASSETS.items())
def test_complete_generated_output_set(category: str, asset_dir: Path) -> None:
    manifest = load_manifest(asset_dir)
    outputs = manifest["outputs"]
    source_files = sorted(asset_dir.glob(outputs["source_glob"]))
    export_files = sorted(asset_dir.glob(outputs["export_glob"]))
    fixed_files = fixed_output_paths(asset_dir, manifest)
    present = [path for path in [*source_files, *export_files, *fixed_files] if path.exists()]

    if not present:
        if REQUIRE_OUTPUTS:
            pytest.fail(f"{category} generated outputs are required but entirely absent")
        pytest.skip(f"{category} outputs have not been generated yet")

    assert source_files, f"{category} must contain at least one source/*.blend"
    assert export_files, f"{category} must contain at least one exports/*.fbx"
    missing = [path for path in fixed_files if not path.is_file()]
    assert not missing, f"{category} has a partial output set; missing: {missing}"

    generated_files = [*source_files, *export_files, *fixed_files]
    for path in generated_files:
        assert path.is_file() and path.stat().st_size > 0
        assert_no_private_path(path)
        if path.suffix.lower() in {".blend", ".fbx", ".tga", ".png"}:
            assert path.stat().st_size <= MAX_REGULAR_GIT_BINARY_BYTES, (
                f"{path} exceeds the compact regular-Git asset policy"
            )
            assert_not_lfs_pointer(path)

    for path in source_files:
        header = path.read_bytes()[:21]
        assert header == b"BLENDER17-01v0502REND", (
            f"{path} must be an inspectable uncompressed Blender 5.2 source"
        )
    for path in export_files:
        assert path.read_bytes()[:18] == b"Kaydara FBX Binary", f"{path} is not binary FBX"
    for relative_path in EXPECTED_TEXTURES:
        assert_tga_contract(asset_dir / relative_path)

    preview = asset_dir / outputs["preview"]
    assert_png_has_no_private_metadata(preview)

    report = asset_dir / outputs["report"]
    assert b"\r\n" not in report.read_bytes(), f"{report} must use repository-stable LF endings"
    report_data = json.loads(report.read_text(encoding="utf-8"))
    assert isinstance(report_data, dict) and report_data
    assert report_data["schema_version"] == 1
    assert report_data["asset_id"] == manifest["id"]
    assert report_data["category"] == category
    assert report_data["license"] == "MIT"
    assert report_data["authoring_example"] is True
    assert report_data["contains_game_or_workshop_assets"] is False
    assert report_data["runtime_tested"] is False
    assert report_data["blender"]["version"].startswith("5.2.0")
    assert report_data["scene"] == {
        "scale_length": 1.0,
        "source_up_axis": "Z",
        "unit_system": "METRIC",
    }
    assert report_data["fbx"] == {
        "axis_forward": "-Z",
        "axis_up": "Y",
        "binary": True,
        "embedded_textures": False,
        "triangulated": True,
    }
    assert set(report_data["exports"]) == {
        path.relative_to(asset_dir).as_posix() for path in export_files
    }
    assert report_data["textures"] == EXPECTED_TEXTURES

    objects = report_data["objects"]
    assert isinstance(objects, list) and objects
    object_names = [item["name"] for item in objects]
    assert len(object_names) == len(set(object_names))
    for item in objects:
        assert item["vertices"] > 0
        assert item["triangles"] > 0
        assert item["all_faces_triangles"] is True
        assert item["transform_identity"] is True
        assert item["uv_layers"]
        assert item["color_attributes"]
        assert len(item["bounds_m"]["min"]) == 3
        assert len(item["bounds_m"]["max"]) == 3

    expected_rgba_mode = {
        "building": None,
        "plant": "WindNone",
        "resource": "ColorVSplit",
    }[category]
    assert report_data["rgba_mode"] == expected_rgba_mode
    assert min(item["bounds_m"]["min"][2] for item in objects) >= -0.00001

    serialized_report = json.dumps(report_data, sort_keys=True)
    assert not re.search(r"(?i)([a-z]:\\\\users\\\\|/home/|/users/)", serialized_report)

    checksum_file = asset_dir / outputs["checksums"]
    assert b"\r\n" not in checksum_file.read_bytes(), (
        f"{checksum_file} must use repository-stable LF endings"
    )
    checksums = parse_checksums(checksum_file)
    checksum_targets = [*source_files, *export_files, *fixed_files]
    checksum_targets.remove(checksum_file)
    expected_checksum_paths = {
        target.relative_to(asset_dir).as_posix() for target in checksum_targets
    }
    assert set(checksums) == expected_checksum_paths
    for target in checksum_targets:
        relative = target.relative_to(asset_dir).as_posix()
        assert relative in checksums, f"{checksum_file} does not cover {relative}"
        assert checksums[relative] == sha256_file(target), f"stale checksum for {target}"

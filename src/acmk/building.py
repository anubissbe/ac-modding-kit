"""Typed, dry-run-first scaffolding for standalone Ancient Cities buildings.

This module intentionally models only the small building subset demonstrated by
the audited v1.9.3 data.  It is not a universal ART schema and every generated
project remains a ``community-draft`` until rebased onto a current in-game
skeleton and runtime-tested.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

import ancient_cities_mod as _legacy

from .builder import DraftProjectBuilder, DraftProjectPlan
from .errors import ContractError, ProjectError
from .manifest import ManifestSpec, NewlineStyle, TextAssetKind, Utf16TextDocument
from .paths import AncientPath, EngineReference, ProjectRelativePath
from .project import SDKProject
from .reports import ExecutionMode, Issue, Severity, ValidationProfile, ValidationReport

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,63}\Z")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_CATEGORY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_LOCALE = re.compile(r"[a-z]{2,3}(?:-[A-Z]{2})?\Z")
_FBX_BINARY_HEADER = b"Kaydara FBX Binary  \x00\x1a\x00"
_MAX_CONSTRUCTION_STAGE_COUNT = 1_000_000
_FIXED_REFERENCES = (
    EngineReference("~/Entity/Local/Building/Asset/DistanceRange.Value"),
    EngineReference("~/Entity/Local/Building/Asset/Master"),
    EngineReference("~/Entity/Local/Building/Set/Pick"),
    EngineReference("~/Entity/Local/Building/Set/3D"),
    EngineReference("~/Entity/Local/Environment/Object"),
    EngineReference("~/Entity/Local/Location/List/Door/Entity"),
    EngineReference("~/Entity/Local/Terrain/Shape/Heightmap"),
)


@dataclass(frozen=True, slots=True, order=True)
class BuildingAssetPath:
    """Safe path relative to one standalone building directory."""

    value: str

    def __post_init__(self) -> None:
        ProjectRelativePath(self.value)
        if not self.value.isascii():
            raise ContractError("building asset paths must use portable ASCII names")
        if self.value.startswith("Ancient/"):
            raise ContractError("building asset paths are relative to the building directory")
        if not PurePosixPath(self.value).suffix:
            raise ContractError("building asset paths must identify a file with an extension")
        if any(character in self.value for character in ('"', "'", "\r", "\n")):
            raise ContractError("building asset paths contain ART-unsafe characters")

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.value).suffix

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BuildingModel:
    """One FBX render binding and its already-installed engine material."""

    name: str
    file: BuildingAssetPath
    material: EngineReference
    z_layer: int = 6000
    heightmap_blend: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _LABEL.fullmatch(self.name) is None:
            raise ContractError("building model name must be a short ASCII identifier")
        if not isinstance(self.file, BuildingAssetPath) or self.file.suffix.casefold() != ".fbx":
            raise ContractError("building models require a typed .fbx BuildingAssetPath")
        _validate_external_reference(self.material, label="building model material")
        if isinstance(self.z_layer, bool) or not isinstance(self.z_layer, int):
            raise ContractError("building model z_layer must be an integer")
        if not 0 <= self.z_layer <= 1_000_000:
            raise ContractError("building model z_layer is outside the supported range")
        _validate_finite(self.heightmap_blend, label="building model heightmap_blend")
        if not 0.0 <= float(self.heightmap_blend) <= 1.0:
            raise ContractError("building model heightmap_blend must be between zero and one")


@dataclass(frozen=True, slots=True)
class ConstructionStage:
    """A complete visual snapshot for one ordered construction resource step."""

    name: str
    resource: EngineReference | None
    count: int | float
    models: tuple[BuildingModel, ...]

    def __post_init__(self) -> None:
        _validate_stage_name(self.name)
        if self.resource is not None:
            _validate_external_reference(self.resource, label="construction resource")
        valid_count = not isinstance(self.count, bool) and (
            (isinstance(self.count, int) and 0 < self.count <= _MAX_CONSTRUCTION_STAGE_COUNT)
            or (
                isinstance(self.count, float)
                and math.isfinite(self.count)
                and 0 < self.count <= _MAX_CONSTRUCTION_STAGE_COUNT
            )
        )
        if not valid_count:
            raise ContractError(
                "construction stage count must be a positive finite number no greater than "
                f"{_MAX_CONSTRUCTION_STAGE_COUNT}"
            )
        _validate_model_snapshot(self.models, label=f"construction stage {self.name}")


@dataclass(frozen=True, slots=True)
class DecayStage:
    """A complete visual snapshot for one ordered decay step."""

    name: str
    models: tuple[BuildingModel, ...]

    def __post_init__(self) -> None:
        _validate_stage_name(self.name)
        _validate_model_snapshot(self.models, label=f"decay stage {self.name}")


@dataclass(frozen=True, slots=True)
class BuildingSpec:
    """Audited minimal contract for an independently listed building entity.

    The rendered ART intentionally uses only structures observed in current base
    buildings.  Unknown gameplay properties remain outside this contract.
    """

    identifier: str
    display_name: str
    plural_name: str
    description: str
    preview_model: BuildingAssetPath
    default_models: tuple[BuildingModel, ...]
    construction_stages: tuple[ConstructionStage, ...]
    decay_stages: tuple[DecayStage, ...]
    icon: BuildingAssetPath = BuildingAssetPath("Icon.tga")
    location_mask: BuildingAssetPath = BuildingAssetPath("LocationMask.tga")
    locale: str = "en"
    category: str = "Housing"
    location_size: tuple[int, int] = (5, 5)
    location_deep: tuple[float, float] = (0.0, -0.25)
    location_slope: tuple[float, float] = (3.0, 0.0)
    aabb_offset: tuple[float, float, float] = (-2.1, 0.0, -1.85)
    aabb_size: tuple[float, float, float] = (4.2, 2.65, 3.7)
    door_position: tuple[float, float, float] = (0.0, 0.0, 2.5)
    door_angle: tuple[float, float, float] = (0.0, 0.0, 0.0)
    requirements: tuple[EngineReference, ...] = (
        EngineReference("~/Entity/Knowledge/List/Architecture/Entity"),
    )
    requirement_percent: tuple[float, ...] = (0.0,)
    service_vacant: int = 4
    sleep: float = 1.0
    count_limit: int = 64
    constitution_repair: float = 0.8
    constitution_ready: float = 0.7
    constitution: float = 3.0
    disband: float = 0.75
    ui_offset: float = 2.75
    mod_dependencies: tuple[str, ...] = ()
    mod_conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or _IDENTIFIER.fullmatch(self.identifier) is None:
            raise ContractError(
                "building identifier must be 2-64 ASCII letters, digits, or underscores "
                "and start with a letter"
            )
        for label, value in (
            ("display name", self.display_name),
            ("plural name", self.plural_name),
            ("description", self.description),
        ):
            _validate_localization_line(value, label=label)
        if not isinstance(self.preview_model, BuildingAssetPath):
            raise ContractError("preview_model must be a BuildingAssetPath")
        if self.preview_model.suffix.casefold() != ".fbx":
            raise ContractError("preview_model must identify an FBX file")
        if not isinstance(self.icon, BuildingAssetPath) or self.icon.suffix.casefold() != ".tga":
            raise ContractError("building icon must be a typed TGA BuildingAssetPath")
        if (
            not isinstance(self.location_mask, BuildingAssetPath)
            or self.location_mask.value != "LocationMask.tga"
        ):
            raise ContractError("standalone buildings require exact LocationMask.tga naming")
        if not isinstance(self.locale, str) or _LOCALE.fullmatch(self.locale) is None:
            raise ContractError("building locale must look like en or pt-BR")
        if not isinstance(self.category, str) or _CATEGORY.fullmatch(self.category) is None:
            raise ContractError("building category must be an ASCII engine identifier")
        _validate_model_snapshot(self.default_models, label="default building state")
        _validate_stages(self.construction_stages, ConstructionStage, label="construction")
        _validate_stages(self.decay_stages, DecayStage, label="decay")
        _validate_asset_path_case(
            (
                self.preview_model,
                self.icon,
                self.location_mask,
                *(model.file for model in self._all_models()),
            )
        )
        _validate_int_pair(self.location_size, label="location_size", positive=True)
        _validate_number_tuple(self.location_deep, 2, label="location_deep")
        _validate_number_tuple(self.location_slope, 2, label="location_slope")
        _validate_number_tuple(self.aabb_offset, 3, label="aabb_offset")
        _validate_number_tuple(self.aabb_size, 3, label="aabb_size")
        if any(float(value) <= 0 for value in self.aabb_size):
            raise ContractError("aabb_size components must be positive")
        _validate_number_tuple(self.door_position, 3, label="door_position")
        _validate_number_tuple(self.door_angle, 3, label="door_angle")
        if not isinstance(self.requirements, tuple) or any(
            not isinstance(item, EngineReference) for item in self.requirements
        ):
            raise ContractError("requirements must be a tuple of EngineReference values")
        for requirement in self.requirements:
            _validate_external_reference(requirement, label="building requirement")
        if not isinstance(self.requirement_percent, tuple) or len(self.requirement_percent) != len(
            self.requirements
        ):
            raise ContractError("requirement_percent must align exactly with requirements")
        for requirement_value in self.requirement_percent:
            _validate_finite(requirement_value, label="requirement_percent")
            if not 0.0 <= float(requirement_value) <= 1.0:
                raise ContractError("requirement_percent values must be between zero and one")
        for integer_label, integer_value, lower_bound, upper_bound in (
            ("service_vacant", self.service_vacant, 1, 128),
            ("count_limit", self.count_limit, 1, 4096),
        ):
            if (
                isinstance(integer_value, bool)
                or not isinstance(integer_value, int)
                or not lower_bound <= integer_value <= upper_bound
            ):
                raise ContractError(f"{integer_label} is outside the supported integer range")
        for scalar_label, scalar_value, minimum in (
            ("sleep", self.sleep, 0.0),
            ("constitution_repair", self.constitution_repair, 0.0),
            ("constitution_ready", self.constitution_ready, 0.0),
            ("constitution", self.constitution, 0.0),
            ("disband", self.disband, 0.0),
            ("ui_offset", self.ui_offset, 0.0),
        ):
            _validate_finite(scalar_value, label=scalar_label)
            if float(scalar_value) < minimum:
                raise ContractError(f"{scalar_label} cannot be negative")
        _validate_relations(self.mod_dependencies, self.mod_conflicts)

    @property
    def index_path(self) -> AncientPath:
        """Exact virtual path of the generated building definition."""

        return AncientPath.from_payload(f"Entity/Local/Building/{self.identifier}/Index.art")

    @property
    def localization_filename(self) -> str:
        return f"Index.{self.locale}.loc"

    @property
    def model_files(self) -> tuple[BuildingAssetPath, ...]:
        paths = {self.preview_model.value: self.preview_model}
        for model in self._all_models():
            paths.setdefault(model.file.value, model.file)
        return tuple(paths[key] for key in sorted(paths, key=str.casefold))

    @property
    def required_assets(self) -> tuple[BuildingAssetPath, ...]:
        paths = {item.value: item for item in self.model_files}
        paths[self.icon.value] = self.icon
        paths[self.location_mask.value] = self.location_mask
        return tuple(paths[key] for key in sorted(paths, key=str.casefold))

    @property
    def engine_references(self) -> tuple[EngineReference, ...]:
        references: list[EngineReference] = list(_FIXED_REFERENCES)
        references.extend(self.requirements)
        references.extend(
            stage.resource for stage in self.construction_stages if stage.resource is not None
        )
        references.extend(model.material for model in self._all_models())
        unique: dict[str, EngineReference] = {}
        for reference in references:
            unique.setdefault(reference.value, reference)
        return tuple(unique.values())

    def render_index_art(self) -> Utf16TextDocument:
        """Render deterministic CRLF ART bytes with exactly one UTF-16LE BOM."""

        return Utf16TextDocument.from_text(_render_building_art(self), kind=TextAssetKind.ART)

    def render_localization(self) -> Utf16TextDocument:
        """Render the runtime-proven English LOC bytes for Ancient Cities 1.9.3."""

        text = "\n".join(
            (
                "#./Localization/Description",
                self.description,
                "#./Localization/Noun",
                "NEUTER",
                "COUNTABLE",
                self.display_name,
                self.plural_name,
            )
        )
        return Utf16TextDocument.from_text(text, kind=TextAssetKind.LOC)

    def _all_models(self) -> tuple[BuildingModel, ...]:
        result = list(self.default_models)
        for construction_stage in self.construction_stages:
            result.extend(construction_stage.models)
        for decay_stage in self.decay_stages:
            result.extend(decay_stage.models)
        return tuple(result)


@dataclass(frozen=True, slots=True)
class BuildingScaffoldResult:
    mode: ExecutionMode
    project_root: Path
    building_identifier: str
    files: tuple[str, ...]
    engine_references: tuple[str, ...]
    mod_dependencies: tuple[str, ...]
    mod_conflicts: tuple[str, ...]
    validation: ValidationReport
    warning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "project_root": str(self.project_root),
            "building_identifier": self.building_identifier,
            "files": list(self.files),
            "engine_references": list(self.engine_references),
            "mod_dependencies": list(self.mod_dependencies),
            "mod_conflicts": list(self.mod_conflicts),
            "validation": self.validation.to_dict(),
            "warning": self.warning,
        }


@dataclass(frozen=True, slots=True)
class BuildingScaffoldPlan:
    """Immutable, validated plan; preview never writes and apply stays atomic."""

    spec: BuildingSpec
    draft: DraftProjectPlan
    validation: ValidationReport

    def __post_init__(self) -> None:
        if not isinstance(self.spec, BuildingSpec):
            raise ContractError("building scaffold plan requires a BuildingSpec")
        if not isinstance(self.draft, DraftProjectPlan):
            raise ContractError("building scaffold plan requires a DraftProjectPlan")
        if not isinstance(self.validation, ValidationReport):
            raise ContractError("building scaffold validation has an invalid type")
        self.validation.raise_for_errors()

    @property
    def planned_files(self) -> tuple[str, ...]:
        return self.draft.planned_files

    def preview(self) -> BuildingScaffoldResult:
        result = self.draft.preview()
        return self._result(result.mode, result.project_root, result.files, result.warning)

    def apply(self) -> BuildingScaffoldResult:
        result = self.draft.apply()
        return self._result(result.mode, result.project_root, result.files, result.warning)

    def open(self) -> SDKProject:
        return self.draft.open()

    def _result(
        self,
        mode: ExecutionMode,
        project_root: Path,
        files: tuple[str, ...],
        warning: str,
    ) -> BuildingScaffoldResult:
        return BuildingScaffoldResult(
            mode=mode,
            project_root=project_root,
            building_identifier=self.spec.identifier,
            files=files,
            engine_references=tuple(reference.value for reference in self.spec.engine_references),
            mod_dependencies=self.spec.mod_dependencies,
            mod_conflicts=self.spec.mod_conflicts,
            validation=self.validation,
            warning=warning,
        )


class BuildingScaffoldBuilder:
    """Collect original assets and create a validated standalone building draft."""

    def __init__(
        self,
        target: str | os.PathLike[str],
        *,
        project_identifier: str,
        manifest: ManifestSpec,
        building: BuildingSpec,
        context: _legacy.DiscoveryContext,
        version: str = "0.1.0",
        license: str = "NOASSERTION",
        contact: str = "",
        context_refresher: Callable[[], _legacy.DiscoveryContext] | None = None,
    ) -> None:
        if not isinstance(manifest, ManifestSpec) or not isinstance(building, BuildingSpec):
            raise ContractError("building scaffold requires ManifestSpec and BuildingSpec values")
        if not isinstance(context, _legacy.DiscoveryContext):
            raise ContractError("building scaffold context must be a DiscoveryContext")
        self._target = Path(target)
        self._project_identifier = project_identifier
        self._manifest = manifest
        self._building = building
        self._context = context
        self._version = version
        self._license = license
        self._contact = contact
        self._context_refresher = context_refresher
        self._assets: dict[str, tuple[BuildingAssetPath, bytes]] = {}
        self._thumbnail: bytes | None = None

    @property
    def building(self) -> BuildingSpec:
        return self._building

    def add_asset(self, path: str | BuildingAssetPath, data: bytes) -> BuildingScaffoldBuilder:
        asset = path if isinstance(path, BuildingAssetPath) else BuildingAssetPath(path)
        if not isinstance(data, bytes):
            raise ContractError("building asset data must be immutable bytes")
        if len(data) > _legacy.MAX_ZIP_MEMBER_BYTES:
            raise ProjectError("building asset exceeds the per-file resource limit")
        suffix = asset.suffix.casefold()
        if suffix in {".art", ".loc"}:
            raise ProjectError("generated ART/LOC paths cannot be replaced by binary assets")
        if suffix in _legacy.EXECUTABLE_EXTENSIONS:
            raise ProjectError("executable building assets are forbidden")
        key = asset.value.casefold()
        if key in self._assets:
            raise ProjectError(
                f"case-insensitive duplicate building asset: {self._assets[key][0]} and {asset}",
                code="PATH_COLLISION",
            )
        self._assets[key] = (asset, bytes(data))
        return self

    def add_asset_file(
        self, path: str | BuildingAssetPath, source: str | os.PathLike[str]
    ) -> BuildingScaffoldBuilder:
        source_path = Path(source)
        if _legacy.path_is_link_like(source_path) or not source_path.is_file():
            raise ProjectError("asset source must be a regular, non-symlink file", path=source_path)
        try:
            data = _legacy._read_file_bounded(source_path, _legacy.MAX_ZIP_MEMBER_BYTES)
        except (OSError, _legacy.ModToolError) as exc:
            raise ProjectError(f"cannot read {source_path}: {exc}", path=source_path) from exc
        return self.add_asset(path, data)

    def set_thumbnail(self, data: bytes) -> BuildingScaffoldBuilder:
        if not isinstance(data, bytes):
            raise ContractError("thumbnail data must be immutable bytes")
        if len(data) > _legacy.MAX_ZIP_MEMBER_BYTES:
            raise ProjectError("thumbnail exceeds the per-file resource limit")
        problem = _legacy._signature_problem("Thumbnail.jpg", data)
        dimensions = _legacy.jpeg_dimensions(data)
        if problem is not None or dimensions is None or dimensions[0] != dimensions[1]:
            raise ProjectError("building thumbnail must be a valid square JPEG")
        self._thumbnail = bytes(data)
        return self

    def set_thumbnail_file(self, source: str | os.PathLike[str]) -> BuildingScaffoldBuilder:
        source_path = Path(source)
        if _legacy.path_is_link_like(source_path) or not source_path.is_file():
            raise ProjectError(
                "thumbnail source must be a regular, non-symlink file", path=source_path
            )
        try:
            data = _legacy._read_file_bounded(source_path, _legacy.MAX_ZIP_MEMBER_BYTES)
        except (OSError, _legacy.ModToolError) as exc:
            raise ProjectError(f"cannot read {source_path}: {exc}", path=source_path) from exc
        return self.set_thumbnail(data)

    def validate(self) -> ValidationReport:
        return _validate_scaffold(
            target=self._target,
            manifest=self._manifest,
            spec=self._building,
            assets=MappingProxyType({asset.value: data for asset, data in self._assets.values()}),
            thumbnail=self._thumbnail,
            context=self._context,
        )

    def plan(self) -> BuildingScaffoldPlan:
        validation = self.validate()
        validation.raise_for_errors()
        draft = DraftProjectBuilder(
            self._target,
            identifier=self._project_identifier,
            manifest=self._manifest,
            context=self._context,
            version=self._version,
            license=self._license,
            contact=self._contact,
            dependencies=self._building.mod_dependencies,
            conflicts=self._building.mod_conflicts,
            context_refresher=self._context_refresher,
        )
        base = f"Entity/Local/Building/{self._building.identifier}"
        draft.add_art(f"{base}/Index.art", self._building.render_index_art().text)
        draft.add_localization(
            f"{base}/{self._building.localization_filename}",
            self._building.render_localization().text,
        )
        for asset, data in sorted(self._assets.values(), key=lambda item: item[0].value.casefold()):
            draft.add_binary(f"{base}/{asset.value}", data)
        assert self._thumbnail is not None  # validation makes this invariant explicit
        draft.set_thumbnail(self._thumbnail)
        return BuildingScaffoldPlan(self._building, draft.plan(), validation)


def _validate_scaffold(
    *,
    target: Path,
    manifest: ManifestSpec,
    spec: BuildingSpec,
    assets: Mapping[str, bytes],
    thumbnail: bytes | None,
    context: _legacy.DiscoveryContext,
) -> ValidationReport:
    issues: list[Issue] = []
    document = manifest.render()
    fields = dict(document.fields)
    if manifest.mod_type != "Generic":
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_MANIFEST_TYPE",
                "standalone building scaffolds require a Generic root manifest",
            )
        )
    if manifest.steam_mod_id.low or manifest.steam_mod_id.high:
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_MANIFEST_STEAM_ID",
                "a new standalone building draft must keep SteamModId at 0,0",
            )
        )
    if manifest.content is not None:
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_MANIFEST_CONTENT",
                "standalone building scaffolds require a valueless Content node",
            )
        )
    if context.game_version and str(manifest.game_version) != context.game_version:
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_MANIFEST_GAME_VERSION",
                "building manifest GameVersion does not match the discovered installation",
                detail={
                    "manifest": str(manifest.game_version),
                    "current": context.game_version,
                },
            )
        )
    if thumbnail is None:
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_THUMBNAIL_MISSING",
                "a square root Thumbnail.jpg is required for the scaffold",
            )
        )

    art = spec.render_index_art()
    localization = spec.render_localization()
    _validate_generated_documents(spec, art, localization, issues)

    provided = {name.casefold(): (name, data) for name, data in assets.items()}
    required = {path.value.casefold(): path.value for path in spec.required_assets}
    for folded, name in required.items():
        match = provided.get(folded)
        if match is None:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "BUILDING_ASSET_MISSING",
                    f"required building asset is missing: {name}",
                    Path(name),
                )
            )
        elif match[0] != name:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "BUILDING_ASSET_CASE",
                    "building asset case differs from its generated reference: "
                    f"{match[0]} -> {name}",
                    Path(match[0]),
                )
            )
    for folded, (name, _data) in provided.items():
        if folded not in required:
            issues.append(
                Issue(
                    Severity.NOTICE,
                    "BUILDING_ASSET_EXTRA",
                    f"asset is packaged but not referenced by the minimal scaffold: {name}",
                    Path(name),
                )
            )

    for model_path in spec.model_files:
        match = provided.get(model_path.value.casefold())
        if match is None:
            continue
        problem = _fbx_problem(match[1])
        if problem:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "BUILDING_MODEL_SIGNATURE",
                    f"{model_path}: {problem}",
                    Path(match[0]),
                )
            )
    icon_match = provided.get(spec.icon.value.casefold())
    if icon_match is not None:
        _validate_tga_asset(
            icon_match[1],
            label="building icon",
            path=Path(icon_match[0]),
            expected_dimensions=(128, 128),
            expected_depth=32,
            allowed_types={2, 10},
            expected_attribute_bits=8,
            issues=issues,
            code="BUILDING_ICON_TGA",
        )
    mask_match = provided.get(spec.location_mask.value.casefold())
    if mask_match is not None:
        _validate_tga_asset(
            mask_match[1],
            label="building location mask",
            path=Path(mask_match[0]),
            expected_dimensions=spec.location_size,
            expected_depth=8,
            allowed_types={3, 11},
            expected_attribute_bits=None,
            issues=issues,
            code="BUILDING_MASK_TGA",
        )

    base_root = context.base_data_root
    if base_root is None:
        issues.append(
            Issue(
                Severity.WARNING,
                "BUILDING_BASE_UNAVAILABLE",
                "base data is unavailable; identifier and engine-reference anchors "
                "were not checked",
            )
        )
    else:
        building_root = base_root / "Entity" / "Local" / "Building"
        collision = _casefold_child(building_root, spec.identifier)
        if collision is not None:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "BUILDING_IDENTIFIER_COLLISION",
                    f"building identifier collides with current base content: {collision.name}",
                    collision,
                )
            )
        if not (building_root / "Building.art").is_file():
            issues.append(
                Issue(
                    Severity.WARNING,
                    "BUILDING_LOADER_UNCONFIRMED",
                    "the current base building loader exemplar was not found",
                    building_root / "Building.art",
                )
            )
        for reference in spec.engine_references:
            if not _reference_has_base_anchor(base_root, reference):
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "BUILDING_REFERENCE_UNCONFIRMED",
                        f"no current base-file anchor was found for {reference.value}",
                    )
                )

    issues.append(
        Issue(
            Severity.NOTICE,
            "BUILDING_MODEL_RUNTIME_UNVERIFIED",
            "FBX headers, bindings, and files are statically valid; Blender and in-game "
            "rendering remain unverified",
        )
    )
    content = {
        "building_identifier": spec.identifier,
        "building_path": f"Ancient/Entity/Local/Building/{spec.identifier}",
        "generated_art": "UTF-16LE+BOM; CRLF; terminal-CRLF",
        "generated_localization": "UTF-16LE+BOM; LF; no-terminal-newline",
        "required_assets": [path.value for path in spec.required_assets],
        "provided_assets": sorted(assets, key=str.casefold),
        "engine_references": [item.value for item in spec.engine_references],
        "reference_scope": (
            "syntax and current base-file anchors; engine nodes remain runtime-defined"
        ),
    }
    classifications = {
        f"Ancient/Entity/Local/Building/{spec.identifier}/{name}": "planned-new"
        for name in sorted(assets, key=str.casefold)
    }
    return ValidationReport(
        target=target,
        profile=ValidationProfile.AUTHORING,
        issues=tuple(issues),
        manifest=fields,
        content=content,
        classifications=classifications,
    )


def _validate_generated_documents(
    spec: BuildingSpec,
    art: Utf16TextDocument,
    localization: Utf16TextDocument,
    issues: list[Issue],
) -> None:
    try:
        blocks = _legacy.parse_art_blocks(art.text)
    except _legacy.ModToolError as exc:
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_ART_PARSE",
                f"generated ART does not have a balanced, parseable block structure: {exc}",
            )
        )
        blocks = []
    for label, document in (("Index.art", art), (spec.localization_filename, localization)):
        if not document.to_bytes().startswith(b"\xff\xfe") or document.to_bytes().startswith(
            b"\xff\xfe\xff\xfe"
        ):
            issues.append(
                Issue(
                    Severity.ERROR,
                    "BUILDING_TEXT_ENCODING",
                    f"generated {label} does not contain exactly one UTF-16LE BOM",
                )
            )
    if art.newline_style is not NewlineStyle.CRLF or not art.text.endswith("\r\n"):
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_ART_NEWLINES",
                "generated Index.art must use CRLF and end with CRLF",
            )
        )
    if localization.newline_style is not NewlineStyle.LF or localization.text.endswith(
        ("\r", "\n")
    ):
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_LOCALIZATION_NEWLINES",
                "generated building localization must use LF and have no terminal newline",
            )
        )
    expected_files = {path.value for path in spec.model_files} | {
        spec.icon.value,
        spec.location_mask.value,
    }
    actual_files = set(_literal_file_references(art.text))
    if actual_files != expected_files:
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_FILE_REFERENCE_SET",
                "generated ART literal File references differ from the typed asset contract",
                detail={
                    "expected": sorted(expected_files, key=str.casefold),
                    "actual": sorted(actual_files, key=str.casefold),
                },
            )
        )
    markers = tuple(line for line in localization.text.splitlines() if line.startswith("#"))
    if markers != ("#./Localization/Description", "#./Localization/Noun"):
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_LOCALIZATION_MARKERS",
                "generated localization markers do not match the audited building paths",
            )
        )
    has_entity = any(
        block.get("kind") == "Entity/Construction/Building" and block.get("name") == "Entity"
        for block in blocks
    )
    if not has_entity or 'Category:"' not in art.text:
        issues.append(
            Issue(
                Severity.ERROR,
                "BUILDING_ART_ENTITY",
                "generated ART is missing the standalone building entity block",
            )
        )


def _render_building_art(spec: BuildingSpec) -> str:
    lines: list[str] = []
    resources = ",".join(
        f"'{stage.resource.value if stage.resource is not None else ''}'"
        for stage in spec.construction_stages
    )
    counts = ",".join(_number(stage.count) for stage in spec.construction_stages)
    requirements = ",".join(f"'{item.value}'" for item in spec.requirements)
    requirement_percent = ",".join(_number(value) for value in spec.requirement_percent)
    _line(lines, 0, "Entity/Construction/Building:")
    _line(lines, 0, "{")
    for name, value in (
        ("Name", "Entity"),
        ("State", "Enabled"),
        ("CountLimit", str(spec.count_limit)),
        ("Category", spec.category),
        ("LocationSize", _numbers(spec.location_size)),
        ("LocationDeep", _numbers(spec.location_deep)),
        ("LocationSlope", _numbers(spec.location_slope)),
        ("ConstitutionRepair", _number(spec.constitution_repair)),
        ("ConstitutionResource", resources),
        ("ConstitutionCount", counts),
        ("ConstitutionReady", _number(spec.constitution_ready)),
        ("Constitution", _number(spec.constitution)),
        ("Disband", _number(spec.disband)),
        ("UIOffset", _number(spec.ui_offset)),
    ):
        _line(lines, 1, f'{name}:"{value}"')
    if spec.requirements:
        _line(lines, 1, f'RequirementPercent:"{requirement_percent}"')
        _line(lines, 1, f'Requirement:"{requirements}"')
    _line(lines, 1, f'ServiceVacant:"{spec.service_vacant}"')
    _line(lines, 1, f'Sleep:"{_number(spec.sleep)}"')
    _line(lines, 1)
    _line(lines, 1, "Component/Container:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Component:Container"')
    _line(lines, 1, "}")
    _line(lines, 1)
    _line(lines, 1, "Component/Service/Sleep:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Component:Service:Sleep"')
    _line(lines, 1, "}")
    _line(lines, 1)
    _line(lines, 1, "Link/Vector:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"GenericValues"')
    _line(lines, 2, "Source:\"'~/Entity/Local/Building/Asset/DistanceRange.Value'\"")
    _line(lines, 2, "Target:\"'../.UIDistanceRange'\"")
    _line(lines, 1, "}")
    _line(lines, 0, "}")
    _line(lines, 0)

    _line(lines, 0, "Instancer/Tx:")
    _line(lines, 0, "{")
    _line(lines, 1, 'Name:"Instancer"')
    _line(lines, 1, 'LODTransition:"0"')
    _line(lines, 1, 'LODSize:"1"')
    _line(lines, 1, 'InstanceShape:"../Mesh/Shape"')
    _line(lines, 1)
    _line(lines, 1, "Group:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Body"')
    _line(lines, 2)
    _render_stage_collection(
        lines,
        level=2,
        name="Build",
        stages=tuple((stage.name, stage.models) for stage in spec.construction_stages),
    )
    _line(lines, 2)
    _render_stage_collection(
        lines,
        level=2,
        name="Decay",
        stages=tuple((stage.name, stage.models) for stage in spec.decay_stages),
    )
    _line(lines, 2)
    _render_proxy(lines, 2, "Default", spec.default_models, "../../")
    _line(lines, 1, "}")
    _line(lines, 0, "}")
    _line(lines, 0)

    _line(lines, 0, "Group:")
    _line(lines, 0, "{")
    _line(lines, 1, 'Name:"Localization"')
    _line(lines, 1)
    _line(lines, 1, "String/Localization:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Description"')
    _line(lines, 1, "}")
    _line(lines, 1)
    _line(lines, 1, "String/Localization/Vector:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Noun"')
    _line(lines, 1, "}")
    _line(lines, 0, "}")
    _line(lines, 0)

    _line(lines, 0, "Image/File:")
    _line(lines, 0, "{")
    _line(lines, 1, 'Name:"LocationMask"')
    _line(lines, 1, f'File:"{spec.location_mask.value}"')
    _line(lines, 0, "}")
    _line(lines, 0)

    _line(lines, 0, "Group:")
    _line(lines, 0, "{")
    _line(lines, 1, 'Name:"Mesh"')
    _line(lines, 1)
    _line(lines, 1, "Mesh:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Preview"')
    _line(lines, 2, 'TangentSpace:"true"')
    _line(lines, 2)
    _line(lines, 2, "FBX/Mesh:")
    _line(lines, 2, "{")
    _line(lines, 3, 'Name:"Blueprint"')
    _line(lines, 3, f'File:"{spec.preview_model.value}"')
    _line(lines, 2, "}")
    _line(lines, 1, "}")
    _line(lines, 1)
    _line(lines, 1, "Shape/AABB:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Shape"')
    _line(lines, 2, f'Offset:"{_numbers(spec.aabb_offset)}"')
    _line(lines, 2, f'Size:"{_numbers(spec.aabb_size)}"')
    _line(lines, 1, "}")
    _line(lines, 0, "}")
    _line(lines, 0)

    _line(lines, 0, "Group:")
    _line(lines, 0, "{")
    _line(lines, 1, 'Name:"Pool"')
    _line(lines, 1)
    _line(lines, 1, "Group/Instance:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"3D"')
    _line(lines, 2, 'Asset:"~/Entity/Local/Building/Asset/Master"')
    _line(lines, 2, 'Instancer:"../../Instancer"')
    _line(lines, 1, "}")
    _line(lines, 0, "}")
    _line(lines, 0)

    _line(lines, 0, "Group:")
    _line(lines, 0, "{")
    _line(lines, 1, 'Name:"Portrait"')
    _line(lines, 1)
    _line(lines, 1, "Texture2/File:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Icon"')
    _line(lines, 2, 'PixelFormat:"RGBA8"')
    _line(lines, 2, 'Usage:"Color"')
    _line(lines, 2, f'File:"{spec.icon.value}"')
    _line(lines, 1, "}")
    _line(lines, 0, "}")
    _line(lines, 0)

    _line(lines, 0, "Group:")
    _line(lines, 0, "{")
    _line(lines, 1, 'Name:"Set"')
    _line(lines, 1)
    _line(lines, 1, "Set:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Pick"')
    _line(lines, 2, 'NodeType:"Tx"')
    _line(lines, 2, 'Set:"~/Entity/Local/Building/Set/Pick"')
    _line(lines, 2, "NodeTree:\"'../../Pool/3D'\"")
    _line(lines, 1, "}")
    _line(lines, 1)
    _line(lines, 1, "Set:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"Render"')
    _line(lines, 2, 'NodeType:"Tx:Render"')
    _line(lines, 2, 'Set:"~/Entity/Local/Building/Set/3D"')
    _line(lines, 2, "NodeTree:\"'../../Instancer'\"")
    _line(lines, 1, "}")
    _line(lines, 0, "}")
    _line(lines, 0)

    _line(lines, 0, "Group:")
    _line(lines, 0, "{")
    _line(lines, 1, 'Name:"Slot"')
    _line(lines, 1)
    _line(lines, 1, "Tx:")
    _line(lines, 1, "{")
    _line(lines, 2, 'Name:"00"')
    _line(lines, 2, 'Inherit:"true,true,true"')
    _line(lines, 2, f'Position:"{_numbers(spec.door_position)}"')
    _line(lines, 2, f'Angle:"{_numbers(spec.door_angle)}"')
    _line(lines, 2, 'Scale:"1,1,1"')
    _line(lines, 2, 'ZOffset:"0"')
    _line(lines, 2, 'ZLayer:"0"')
    _line(lines, 2)
    _line(lines, 2, "Reference:")
    _line(lines, 2, "{")
    _line(lines, 3, 'Name:"Door"')
    _line(lines, 3, 'ReferenceNode:"~/Entity/Local/Location/List/Door/Entity"')
    _line(lines, 2, "}")
    _line(lines, 1, "}")
    _line(lines, 0, "}")
    return "\r\n".join(lines) + "\r\n"


def _render_stage_collection(
    lines: list[str],
    *,
    level: int,
    name: str,
    stages: tuple[tuple[str, tuple[BuildingModel, ...]], ...],
) -> None:
    _line(lines, level, "Group:")
    _line(lines, level, "{")
    _line(lines, level + 1, f'Name:"{name}"')
    for index, (stage_name, models) in enumerate(stages):
        _line(lines, level + 1)
        _line(lines, level + 1, "Group:")
        _line(lines, level + 1, "{")
        _line(lines, level + 2, f'Name:"{stage_name}"')
        _line(lines, level + 2)
        _render_proxy(lines, level + 2, f"{index:02d}", models, "../../../../")
        _line(lines, level + 1, "}")
    _line(lines, level, "}")


def _render_proxy(
    lines: list[str],
    level: int,
    name: str,
    models: tuple[BuildingModel, ...],
    instancer_reference: str,
) -> None:
    _line(lines, level, "Instancer/Proxy:")
    _line(lines, level, "{")
    _line(lines, level + 1, f'Name:"{name}"')
    _line(lines, level + 1, f'Instancer:"{instancer_reference}"')
    for model in models:
        _line(lines, level + 1)
        _line(lines, level + 1, "Tx/Render:")
        _line(lines, level + 1, "{")
        _line(lines, level + 2, f'Name:"{model.name}"')
        _line(lines, level + 2, 'Position:"0,0,0"')
        _line(lines, level + 2, f'ZLayer:"{model.z_layer}"')
        _line(lines, level + 2, 'Mesh:"./Mesh"')
        _line(lines, level + 2, f'Render:"{model.material.value}"')
        _line(lines, level + 2, 'Shadow:"true,true,false"')
        _line(lines, level + 2, 'ShadowBias:"0"')
        _line(lines, level + 2, 'ScreenIdMode:"Instance"')
        _line(lines, level + 2, 'Displacement:"0"')
        _line(lines, level + 2, 'Heightmap:"~/Entity/Local/Terrain/Shape/Heightmap"')
        _line(lines, level + 2, f'HeightmapBlend:"{_number(model.heightmap_blend)}"')
        _line(lines, level + 2, "Modifier:\"'~/Entity/Local/Environment/Object'\"")
        _line(lines, level + 2, 'Instancer:"../"')
        _line(lines, level + 2)
        _line(lines, level + 2, "Mesh:")
        _line(lines, level + 2, "{")
        _line(lines, level + 3, 'Name:"Mesh"')
        _line(lines, level + 3, 'TangentSpace:"true"')
        _line(lines, level + 3)
        _line(lines, level + 3, "FBX/Mesh:")
        _line(lines, level + 3, "{")
        _line(lines, level + 4, f'Name:"{model.name}"')
        _line(lines, level + 4, f'File:"{model.file.value}"')
        _line(lines, level + 3, "}")
        _line(lines, level + 2, "}")
        _line(lines, level + 1, "}")
    _line(lines, level, "}")


def _line(lines: list[str], level: int, value: str = "") -> None:
    lines.append("\t" * level + value)


def _number(value: int | float) -> str:
    numeric = float(value)
    if numeric == 0:
        return "0"
    return format(numeric, ".15g")


def _numbers(values: tuple[int | float, ...]) -> str:
    return ",".join(_number(value) for value in values)


def _literal_file_references(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r'\bFile:"([^"\r\n]+)"', text))


def _fbx_problem(data: bytes) -> str | None:
    stripped = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if data.startswith(_FBX_BINARY_HEADER):
        if len(data) < len(_FBX_BINARY_HEADER) + 4:
            return "binary FBX header is truncated"
        version = int.from_bytes(
            data[len(_FBX_BINARY_HEADER) : len(_FBX_BINARY_HEADER) + 4], "little"
        )
        if not 6000 <= version <= 8000:
            return f"binary FBX version {version} is outside the supported range"
        return None
    if stripped.startswith((b"; FBX", b"FBXHeaderExtension")):
        return None
    return "FBX binary or ASCII signature is missing"


@dataclass(frozen=True, slots=True)
class _TgaHeader:
    width: int
    height: int
    pixel_depth: int
    image_type: int
    data_offset: int
    attribute_bits: int


def _parse_tga_header(data: bytes) -> _TgaHeader:
    if len(data) < 18:
        raise ValueError("TGA header is truncated")
    id_length = data[0]
    color_map_type = data[1]
    image_type = data[2]
    color_map_length = int.from_bytes(data[5:7], "little")
    color_map_depth = data[7]
    width = int.from_bytes(data[12:14], "little")
    height = int.from_bytes(data[14:16], "little")
    pixel_depth = data[16]
    attribute_bits = data[17] & 0x0F
    if color_map_type != 0 or color_map_length or color_map_depth:
        raise ValueError("color-mapped TGA files are unsupported for building icons and masks")
    if width <= 0 or height <= 0:
        raise ValueError("TGA dimensions must be positive")
    if pixel_depth not in {8, 24, 32}:
        raise ValueError("TGA pixel depth must be 8, 24, or 32 bits")
    data_offset = 18 + id_length
    if data_offset > len(data):
        raise ValueError("TGA image ID exceeds the file")
    return _TgaHeader(width, height, pixel_depth, image_type, data_offset, attribute_bits)


def _validate_tga_pixel_data(data: bytes, header: _TgaHeader) -> None:
    """Validate pixels only after the caller has bounded the declared dimensions."""

    bytes_per_pixel = header.pixel_depth // 8
    pixels = header.width * header.height
    if header.image_type in {2, 3}:
        required = header.data_offset + pixels * bytes_per_pixel
        if required > len(data):
            raise ValueError("uncompressed TGA pixel data is truncated")
    elif header.image_type in {10, 11}:
        cursor = header.data_offset
        decoded = 0
        while decoded < pixels:
            if cursor >= len(data):
                raise ValueError("RLE TGA packet stream is truncated")
            packet = data[cursor]
            cursor += 1
            count = (packet & 0x7F) + 1
            if decoded + count > pixels:
                raise ValueError("RLE TGA packet stream exceeds the declared dimensions")
            payload = bytes_per_pixel if packet & 0x80 else count * bytes_per_pixel
            if cursor + payload > len(data):
                raise ValueError("RLE TGA pixel data is truncated")
            cursor += payload
            decoded += count
    else:
        raise ValueError(f"unsupported TGA image type {header.image_type}")


def _validate_tga_asset(
    data: bytes,
    *,
    label: str,
    path: Path,
    expected_dimensions: tuple[int, int],
    expected_depth: int,
    allowed_types: set[int],
    expected_attribute_bits: int | None,
    issues: list[Issue],
    code: str,
) -> None:
    try:
        header = _parse_tga_header(data)
    except ValueError as exc:
        issues.append(Issue(Severity.ERROR, code, f"{label}: {exc}", path))
        return
    can_validate_pixels = True
    if (header.width, header.height) != expected_dimensions:
        can_validate_pixels = False
        issues.append(
            Issue(
                Severity.ERROR,
                code,
                f"{label} must be {expected_dimensions[0]}x{expected_dimensions[1]}, "
                f"not {header.width}x{header.height}",
                path,
            )
        )
    if header.pixel_depth != expected_depth:
        can_validate_pixels = False
        issues.append(
            Issue(
                Severity.ERROR,
                code,
                f"{label} must use {expected_depth}-bit pixels, not {header.pixel_depth}-bit",
                path,
            )
        )
    if header.image_type not in allowed_types:
        can_validate_pixels = False
        issues.append(
            Issue(
                Severity.ERROR,
                code,
                f"{label} uses unsupported TGA image type {header.image_type}",
                path,
            )
        )
    if not can_validate_pixels:
        return
    try:
        _validate_tga_pixel_data(data, header)
    except ValueError as exc:
        issues.append(Issue(Severity.ERROR, code, f"{label}: {exc}", path))
    if expected_attribute_bits is not None and header.attribute_bits != expected_attribute_bits:
        issues.append(
            Issue(
                Severity.ERROR,
                code,
                f"{label} must declare {expected_attribute_bits} attribute bits, "
                f"not {header.attribute_bits}",
                path,
            )
        )


def _reference_has_base_anchor(base_root: Path, reference: EngineReference) -> bool:
    if reference.value.startswith("/System/"):
        return True
    if not reference.value.startswith("~/"):
        return False
    parts = reference.value[2:].split("/")
    if "List" in parts:
        index = parts.index("List")
        if index + 1 >= len(parts):
            return False
        parent = _resolve_exact(base_root, parts[:index])
        if parent is None or not parent.is_dir():
            return False
        entity = _casefold_child(parent, parts[index + 1])
        return (
            entity is not None
            and entity.name == parts[index + 1]
            and ((entity / "Index.art").is_file() if entity.is_dir() else entity.suffix == ".art")
        )
    if "Asset" in parts:
        index = parts.index("Asset")
        parent = _resolve_exact(base_root, parts[:index])
        if parent is not None and parent.is_dir() and index + 1 < len(parts):
            candidate = parent / f"{parts[index + 1]}.art"
            if candidate.is_file():
                return True
    current = base_root
    deepest: Path | None = None
    for part in parts:
        match = _casefold_child(current, part)
        if match is None or match.name != part:
            break
        deepest = match
        if match.is_file():
            return match.suffix.casefold() == ".art"
        current = match
        if (current / "Index.art").is_file():
            return True
    if deepest is not None and deepest.is_dir():
        return (deepest / f"{deepest.name}.art").is_file()
    parent = current if current.is_dir() else current.parent
    return (parent / f"{parent.name}.art").is_file()


def _resolve_exact(root: Path, parts: list[str]) -> Path | None:
    current = root
    for part in parts:
        match = _casefold_child(current, part)
        if match is None or match.name != part:
            return None
        current = match
    return current


def _casefold_child(parent: Path, name: str) -> Path | None:
    try:
        matches = [child for child in parent.iterdir() if child.name.casefold() == name.casefold()]
    except OSError:
        return None
    if len(matches) != 1:
        return None
    return matches[0]


def _validate_external_reference(reference: EngineReference, *, label: str) -> None:
    if not isinstance(reference, EngineReference):
        raise ContractError(f"{label} must be an EngineReference")
    if not reference.value.startswith(("~/", "/System/")):
        raise ContractError(f"{label} must target an external engine node, not a relative node")
    if any(character in reference.value for character in ('"', "'", "\r", "\n", "\\")):
        raise ContractError(f"{label} contains ART-unsafe characters")


def _validate_stage_name(value: str) -> None:
    if not isinstance(value, str) or _LABEL.fullmatch(value) is None:
        raise ContractError("building stage names must be short ASCII identifiers")


def _validate_model_snapshot(models: tuple[BuildingModel, ...], *, label: str) -> None:
    if not isinstance(models, tuple) or not models:
        raise ContractError(f"{label} must contain at least one BuildingModel")
    if any(not isinstance(model, BuildingModel) for model in models):
        raise ContractError(f"{label} contains a non-BuildingModel value")
    names = [model.name.casefold() for model in models]
    if len(names) != len(set(names)):
        raise ContractError(f"{label} contains duplicate model render names")


def _validate_asset_path_case(paths: tuple[BuildingAssetPath, ...]) -> None:
    exact_by_folded: dict[str, str] = {}
    for path in paths:
        folded = path.value.casefold()
        previous = exact_by_folded.get(folded)
        if previous is not None and previous != path.value:
            raise ContractError(
                "building asset paths must be case-insensitively unambiguous: "
                f"{previous} and {path.value}"
            )
        exact_by_folded[folded] = path.value


def _validate_stages(values: tuple[Any, ...], expected: type[Any], *, label: str) -> None:
    if not isinstance(values, tuple) or not values:
        raise ContractError(f"{label} stages must be a non-empty tuple")
    if any(not isinstance(item, expected) for item in values):
        raise ContractError(f"{label} stages contain an invalid value")
    names = [item.name.casefold() for item in values]
    if len(names) != len(set(names)):
        raise ContractError(f"{label} stage names must be case-insensitively unique")


def _validate_localization_line(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"building {label} cannot be empty")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ContractError(f"building {label} must be a single localization line")
    if value.startswith("#"):
        raise ContractError(f"building {label} cannot be confused with a localization marker")


def _validate_finite(value: object, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be numeric")
    if not math.isfinite(float(value)):
        raise ContractError(f"{label} must be finite")


def _validate_number_tuple(value: object, length: int, *, label: str) -> None:
    if not isinstance(value, tuple) or len(value) != length:
        raise ContractError(f"{label} must be a {length}-item tuple")
    for component in value:
        _validate_finite(component, label=label)


def _validate_int_pair(value: object, *, label: str, positive: bool) -> None:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ContractError(f"{label} must be a two-item tuple")
    for component in value:
        if isinstance(component, bool) or not isinstance(component, int):
            raise ContractError(f"{label} components must be integers")
        if positive and not 1 <= component <= 64:
            raise ContractError(f"{label} components must be between 1 and 64")


def _validate_relations(dependencies: tuple[str, ...], conflicts: tuple[str, ...]) -> None:
    for label, values in (("mod_dependencies", dependencies), ("mod_conflicts", conflicts)):
        if not isinstance(values, tuple) or any(
            not isinstance(value, str) or not value.strip() or "\x00" in value for value in values
        ):
            raise ContractError(f"{label} must contain non-empty strings")
        folded = [value.casefold() for value in values]
        if len(folded) != len(set(folded)):
            raise ContractError(f"{label} must be case-insensitively unique")
    overlap = {value.casefold() for value in dependencies} & {
        value.casefold() for value in conflicts
    }
    if overlap:
        raise ContractError("a standalone building cannot depend on and conflict with one mod")

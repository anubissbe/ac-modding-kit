"""Safe ACMK authoring projects, skeleton import, and release staging."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, TypeGuard

import ancient_cities_mod as _legacy

from ._version import RUNTIME_TEST_SCHEMA_VERSION, __version__
from .config import (
    MAX_PROJECT_CONFIG_BYTES,
    AchievementImpact,
    Compatibility,
    ProjectConfig,
    ProvenanceStatus,
    RuntimeSaveType,
    RuntimeStatus,
    SaveImpact,
    SavePersistence,
    SkeletonSource,
)
from .errors import ContractError, ProjectError, SourceChangedError, ValidationFailedError
from .manifest import ManifestDocument
from .reports import ExecutionMode, Issue, Severity, ValidationProfile, ValidationReport

_RUNTIME_TEST_SCHEMA_V1 = 1
_RUNTIME_TEST_SCHEMA_V2 = 2
_LEGACY_RUNTIME_TEST_SCHEMA_VERSIONS = frozenset({_RUNTIME_TEST_SCHEMA_V1, _RUNTIME_TEST_SCHEMA_V2})
_LEGACY_SOURCE_FINGERPRINT_ALGORITHM = "sha256-tree-v1"
_LOOSE_MOD_FINGERPRINT_ALGORITHM = "sha256-loose-mod-v1"
_LEGACY_WARNING_BASELINE_ALGORITHM = "normalized-warning-line-multiset-v1"
_WARNING_BASELINE_ALGORITHM = "normalized-warning-signature-set-v1"
_SUPPORTED_WARNING_BASELINE_ALGORITHMS = frozenset(
    {_LEGACY_WARNING_BASELINE_ALGORITHM, _WARNING_BASELINE_ALGORITHM}
)
_OBSERVED_CONSENSUS_IMPORT_SCHEMA_VERSION = 2
_STAGED_ROOT_ARTIFACT_NAMES = ("Index.art", "Thumbnail.jpg", "Mod.zip")
_OBSERVED_CONSENSUS_PROFILES = {
    (
        "22",
        "1.9.3",
        "23915225",
        "D9BF481D195671BF9CB98274B4CFF604",
    ): "generic-gv22-b23915225-v1",
}


@dataclass(frozen=True, slots=True)
class ProjectLayout:
    root: Path
    config: ProjectConfig

    @property
    def config_path(self) -> Path:
        return self.root / "acmk.toml"

    @property
    def source_root(self) -> Path:
        return self.config.paths.source.resolve(self.root)

    @property
    def manifest(self) -> Path:
        return self.source_root / "Index.art"

    @property
    def thumbnail(self) -> Path:
        return self.source_root / "Thumbnail.jpg"

    @property
    def payload_root(self) -> Path:
        return self.source_root / "Ancient"

    @property
    def assets_root(self) -> Path:
        return self.config.paths.assets.resolve(self.root)

    @property
    def state_root(self) -> Path:
        return self.config.paths.state.resolve(self.root)

    @property
    def distribution_root(self) -> Path:
        return self.config.paths.distribution.resolve(self.root)


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    source: Path
    relative_destination: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, Path):
            raise ContractError("file snapshot source must be a pathlib.Path")
        if not isinstance(self.relative_destination, str):
            raise ContractError("file snapshot destination must be a string")
        destination = PurePosixPath(self.relative_destination)
        if (
            not self.relative_destination
            or "\\" in self.relative_destination
            or destination.is_absolute()
            or any(part in {"", ".", ".."} for part in destination.parts)
        ):
            raise ContractError("file snapshot destination must be a safe relative path")
        if not _nonnegative_int(self.size) or self.size > _legacy.MAX_ZIP_MEMBER_BYTES:
            raise ContractError("file snapshot size is outside the supported range")
        if not _valid_sha256(self.sha256):
            raise ContractError("file snapshot SHA-256 must be a lowercase digest")

    @classmethod
    def capture(cls, source: Path, relative_destination: str) -> FileSnapshot:
        try:
            if _is_link_like(source):
                raise ProjectError("symbolic links are not allowed in project sources", path=source)
            if not source.is_file():
                raise ProjectError("expected a regular source file", path=source)
            size = source.stat().st_size
        except OSError as exc:
            raise ProjectError(f"cannot inspect source: {exc}", path=source) from exc
        if size > _legacy.MAX_ZIP_MEMBER_BYTES:
            raise ProjectError(
                f"source exceeds the {_legacy.MAX_ZIP_MEMBER_BYTES}-byte per-file limit",
                code="SOURCE_RESOURCE_LIMIT",
                path=source,
            )
        sha256, hashed_size = _hash_file_and_size(source, limit=_legacy.MAX_ZIP_MEMBER_BYTES)
        if hashed_size != size:
            raise SourceChangedError("source changed while it was being planned", path=source)
        return cls(source, relative_destination, size, sha256)

    def copy_verified(self, destination: Path) -> None:
        try:
            if _is_link_like(self.source) or not self.source.is_file():
                raise SourceChangedError(
                    "planned source is no longer a regular file", path=self.source
                )
        except OSError as exc:
            raise SourceChangedError(
                f"cannot inspect planned source: {exc}", path=self.source
            ) from exc
        digest = hashlib.sha256()
        written = 0
        created = False
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with self.source.open("rb") as src, destination.open("xb") as dst:
                created = True
                while chunk := src.read(1024 * 1024):
                    written += len(chunk)
                    if written > _legacy.MAX_ZIP_MEMBER_BYTES:
                        raise SourceChangedError(
                            "planned source exceeded the file limit", path=self.source
                        )
                    digest.update(chunk)
                    dst.write(chunk)
        except SourceChangedError:
            if created:
                _unlink_quietly(destination)
            raise
        except OSError as exc:
            if created:
                _unlink_quietly(destination)
            raise ProjectError(f"cannot copy {self.source}: {exc}", path=self.source) from exc
        if written != self.size or digest.hexdigest() != self.sha256:
            _unlink_quietly(destination)
            raise SourceChangedError(
                "source changed after the operation was planned", path=self.source
            )


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Content-addressed identity for a complete project runtime source tree."""

    sha256: str
    files: int
    bytes: int
    algorithm: str = _LOOSE_MOD_FINGERPRINT_ALGORITHM

    def __post_init__(self) -> None:
        if not _valid_sha256(self.sha256):
            raise ContractError("source fingerprint must be a lowercase SHA-256 digest")
        if not _nonnegative_int(self.files) or not _nonnegative_int(self.bytes):
            raise ContractError("source fingerprint counts must be non-negative integers")
        if self.algorithm not in {
            _LEGACY_SOURCE_FINGERPRINT_ALGORITHM,
            _LOOSE_MOD_FINGERPRINT_ALGORITHM,
        }:
            raise ContractError("source fingerprint algorithm is unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "sha256": self.sha256,
            "files": self.files,
            "bytes": self.bytes,
        }


@dataclass(frozen=True, slots=True)
class _WarningBaseline:
    """Immutable plan-time evidence for warning-only baseline subtraction."""

    log_path: Path
    log_size: int
    log_sha256: str
    log_summary: Mapping[str, Any]
    ignored_warnings: int
    unmatched_warnings: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "log_summary", MappingProxyType(dict(self.log_summary)))
        if not isinstance(self.log_path, Path):
            raise ContractError("warning baseline path must be a pathlib.Path")
        if not _nonnegative_int(self.log_size):
            raise ContractError("warning baseline size must be a non-negative integer")
        if not _valid_sha256(self.log_sha256):
            raise ContractError("warning baseline must contain a lowercase SHA-256 digest")
        if not _nonnegative_int(self.ignored_warnings) or not _nonnegative_int(
            self.unmatched_warnings
        ):
            raise ContractError("warning baseline counts must be non-negative integers")

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": _WARNING_BASELINE_ALGORITHM,
            "log_sha256": self.log_sha256,
            "log_summary": dict(self.log_summary),
            "ignored_warnings": self.ignored_warnings,
            "unmatched_warnings": self.unmatched_warnings,
        }


@dataclass(frozen=True, slots=True)
class ProjectImportResult:
    mode: ExecutionMode
    project_root: Path
    config: ProjectConfig
    imported_files: tuple[str, ...]
    source_manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "project_root": str(self.project_root),
            "project_id": self.config.identifier,
            "schema_version": self.config.schema_version,
            "imported_files": list(self.imported_files),
            "source_manifest_sha256": self.source_manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class ProjectImportPlan:
    source_root: Path
    target_root: Path
    config: ProjectConfig
    files: tuple[FileSnapshot, ...]
    context: _legacy.DiscoveryContext
    context_refresher: Callable[[], _legacy.DiscoveryContext] | None = None

    @property
    def source_manifest_sha256(self) -> str:
        matches = [
            item.sha256 for item in self.files if item.relative_destination == "src/Index.art"
        ]
        if len(matches) != 1:
            raise ContractError("import plan must contain exactly one src/Index.art")
        return matches[0]

    def _validate(self) -> ProjectImportPlan:
        if not isinstance(self.source_root, Path) or not isinstance(self.target_root, Path):
            raise ContractError("import plan roots must be pathlib.Path values")
        if not isinstance(self.config, ProjectConfig):
            raise ContractError("import plan config must be a ProjectConfig")
        if not isinstance(self.files, tuple) or any(
            not isinstance(item, FileSnapshot) for item in self.files
        ):
            raise ContractError("import plan files must be FileSnapshot values")
        if not isinstance(self.context, _legacy.DiscoveryContext):
            raise ContractError("import plan context must be a DiscoveryContext")
        if self.context_refresher is not None and not callable(self.context_refresher):
            raise ContractError("import plan context_refresher must be callable")
        current_context = (
            self.context_refresher() if self.context_refresher is not None else self.context
        )
        expected = ProjectImporter.plan(
            self.source_root,
            self.target_root,
            identifier=self.config.identifier,
            version=self.config.version,
            license=self.config.license,
            contact=self.config.contact,
            provenance_status=self.config.provenance_status,
            provenance_notes=self.config.provenance_notes,
            context=current_context,
            context_refresher=self.context_refresher,
        )
        if (
            expected.source_root != self.source_root
            or expected.target_root != self.target_root
            or expected.config != self.config
            or expected.files != self.files
        ):
            raise ContractError("import plan differs from a fresh canonical skeleton import plan")
        return expected

    def preview(self) -> ProjectImportResult:
        canonical = self._validate()
        return ProjectImportResult(
            mode=ExecutionMode.DRY_RUN,
            project_root=canonical.target_root,
            config=canonical.config,
            imported_files=tuple(item.relative_destination for item in canonical.files),
            source_manifest_sha256=canonical.source_manifest_sha256,
        )

    def apply(self) -> ProjectImportResult:
        canonical = self._validate()
        active_context = canonical.context
        target = _lexical_absolute(self.target_root)
        _legacy.assert_no_symlink_components(target)
        _legacy.assert_writable_project_path(target, active_context)
        if target.exists():
            raise ProjectError(
                "import target must not already exist", code="TARGET_EXISTS", path=target
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.acmk-import-", dir=target.parent))
        try:
            (staging / "src" / "Ancient").mkdir(parents=True)
            (staging / self.config.paths.assets.value).mkdir(parents=True)
            (staging / self.config.paths.state.value).mkdir(parents=True)
            (staging / self.config.paths.distribution.value).parent.mkdir(parents=True)
            _write_new(staging / "acmk.toml", self.config.to_toml().encode("utf-8"))
            _write_new(staging / ".gitignore", b".acmk/\ndist/\n")
            fingerprint = {
                "schema_version": 1,
                "source": self.config.skeleton.value,
                "manifest_sha256": self.source_manifest_sha256,
                "compatibility": {
                    "game_version": self.config.compatibility.game_version,
                    "game_semver": self.config.compatibility.game_semver,
                    "steam_build_id": self.config.compatibility.steam_build_id,
                    "content_hash": self.config.compatibility.content_hash,
                },
            }
            _write_new(
                staging / self.config.paths.state.value / "import.json",
                (json.dumps(fingerprint, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            )
            for snapshot in self.files:
                destination = _safe_destination(staging, snapshot.relative_destination)
                snapshot.copy_verified(destination)
            staged_source = staging / self.config.paths.source.value
            staged_report = _legacy.validate_target(
                staged_source,
                active_context,
                check_archive=False,
            )
            staged_errors = [
                str(issue.get("code"))
                for issue in staged_report.get("issues", [])
                if issue.get("severity") == "error"
            ]
            if staged_errors:
                raise ValidationFailedError(
                    "copied skeleton validation failed: " + ", ".join(staged_errors),
                    path=staged_source,
                )
            staged_manifest = ManifestDocument.read(staged_source / "Index.art")
            expected_fields = {
                "Title": self.config.name,
                "Type": self.config.mod_type,
                "GameVersion": self.config.compatibility.game_version,
            }
            for field_name, expected in expected_fields.items():
                if staged_manifest.fields.get(field_name) != expected:
                    raise SourceChangedError(
                        f"copied skeleton {field_name} changed after import planning",
                        path=staged_source / "Index.art",
                    )
            os.replace(staging, target)
        except BaseException:
            _remove_temporary_tree(staging)
            raise
        return ProjectImportResult(
            mode=ExecutionMode.APPLY,
            project_root=target,
            config=self.config,
            imported_files=tuple(item.relative_destination for item in self.files),
            source_manifest_sha256=self.source_manifest_sha256,
        )


class ProjectImporter:
    """Plan an atomic import of a non-numeric, game-generated loose mod skeleton."""

    @staticmethod
    def plan(
        source: str | os.PathLike[str],
        target: str | os.PathLike[str],
        *,
        identifier: str,
        version: str = "0.1.0",
        license: str = "NOASSERTION",
        contact: str = "",
        provenance_status: ProvenanceStatus = ProvenanceStatus.UNREVIEWED,
        provenance_notes: str = "",
        context: _legacy.DiscoveryContext,
        context_refresher: Callable[[], _legacy.DiscoveryContext] | None = None,
    ) -> ProjectImportPlan:
        source_root = _lexical_absolute(Path(source))
        target_root = _lexical_absolute(Path(target))
        if source_root.name.isdigit():
            raise ProjectError(
                "numeric mod/cache folders are not canonical authoring skeletons",
                code="NUMERIC_SKELETON",
                path=source_root,
            )
        if not source_root.is_dir():
            raise ProjectError("skeleton source is not a directory", path=source_root)
        try:
            if _is_link_like(source_root):
                raise ProjectError(
                    "skeleton source must not be a symbolic link or junction",
                    code="SKELETON_SYMLINK",
                    path=source_root,
                )
        except OSError as exc:
            raise ProjectError(f"cannot inspect skeleton source: {exc}", path=source_root) from exc
        if context.user_root is None:
            raise ProjectError(
                "canonical import requires a discovered Ancient Cities user folder",
                code="SKELETON_ORIGIN_UNKNOWN",
                path=source_root,
            )
        canonical_parent = (context.user_root / "Mod").resolve(strict=False)
        if source_root.parent.resolve(strict=False) != canonical_parent:
            raise ProjectError(
                "canonical import must use a skeleton directly from the discovered user Mod folder",
                code="SKELETON_ORIGIN",
                path=source_root,
            )
        manifest_path = _exact_child(source_root, "Index.art", required=True)
        thumbnail_path = _exact_child(source_root, "Thumbnail.jpg", required=True)
        ancient_root = _exact_child(source_root, "Ancient", required=True)
        assert manifest_path is not None and thumbnail_path is not None and ancient_root is not None
        if not ancient_root.is_dir() or _is_link_like(ancient_root):
            raise ProjectError("Ancient must be a real directory", path=ancient_root)
        ancient_entries = _bounded_tree_entries(ancient_root)
        manifest = ManifestDocument.read(manifest_path)
        if manifest.duplicates:
            raise ProjectError("cannot import a manifest with duplicate fields", path=manifest_path)
        game_version = manifest.fields.get("GameVersion", "")
        if context.game_version and game_version != context.game_version:
            message = (
                f"skeleton GameVersion {game_version!r} differs from current "
                f"{context.game_version!r}"
            )
            raise ProjectError(
                message,
                code="GAME_VERSION_MISMATCH",
                path=manifest_path,
            )
        report = _legacy.validate_target(source_root, context, check_archive=False)
        error_codes = [
            str(issue.get("code"))
            for issue in report.get("issues", [])
            if issue.get("severity") == "error"
        ]
        if error_codes:
            raise ValidationFailedError(
                "skeleton validation failed: " + ", ".join(error_codes),
                path=source_root,
            )
        compatibility = Compatibility(
            game_version=game_version,
            game_semver=context.semver or "",
            steam_build_id=context.build_id or "",
            content_hash=context.content_hash or "",
        )
        config = ProjectConfig(
            identifier=identifier,
            name=manifest.fields.get("Title", identifier),
            version=version,
            mod_type=manifest.fields.get("Type", "Generic"),
            license=license,
            contact=contact,
            provenance_status=provenance_status,
            provenance_notes=provenance_notes,
            skeleton=SkeletonSource.GAME_GENERATED,
            runtime_status=RuntimeStatus.UNTESTED,
            save_impact=SaveImpact.UNKNOWN,
            achievement_impact=(
                AchievementImpact.DISABLED
                if any(path.suffix.casefold() == ".art" for path in ancient_entries)
                else AchievementImpact.UNKNOWN
            ),
            compatibility=compatibility,
        )
        files = [
            FileSnapshot.capture(manifest_path, "src/Index.art"),
            FileSnapshot.capture(thumbnail_path, "src/Thumbnail.jpg"),
        ]
        folded: dict[str, str] = {
            item.relative_destination.casefold(): item.relative_destination for item in files
        }
        total = sum(item.size for item in files)
        for source_path in ancient_entries:
            if _is_link_like(source_path):
                raise ProjectError("symbolic links are not allowed in a skeleton", path=source_path)
            if not source_path.is_file():
                continue
            relative = source_path.relative_to(source_root).as_posix()
            if source_path.suffix.casefold() in _legacy.EXECUTABLE_EXTENSIONS:
                raise ProjectError("executable payload content is forbidden", path=source_path)
            key = relative.casefold()
            if key in folded:
                raise ProjectError(
                    f"case-insensitive destination collision: {folded[key]} and {relative}",
                    code="PATH_COLLISION",
                    path=source_path,
                )
            folded[key] = relative
            snapshot = FileSnapshot.capture(source_path, f"src/{relative}")
            total += snapshot.size
            if total > _legacy.MAX_ZIP_TOTAL_BYTES:
                raise ProjectError(
                    "skeleton exceeds the total payload limit", code="SOURCE_RESOURCE_LIMIT"
                )
            files.append(snapshot)
        return ProjectImportPlan(
            source_root,
            target_root,
            config,
            tuple(files),
            context,
            context_refresher,
        )


@dataclass(frozen=True, slots=True)
class StagedArtifact:
    name: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if self.name not in _STAGED_ROOT_ARTIFACT_NAMES:
            raise ContractError("staged artifact name is unsupported")
        if not _nonnegative_int(self.size):
            raise ContractError("staged artifact size must be a non-negative integer")
        if not _valid_sha256(self.sha256):
            raise ContractError("staged artifact SHA-256 must be a lowercase digest")

    def to_dict(self, output_directory: Path) -> dict[str, Any]:
        return {
            "path": str(output_directory / self.name),
            "bytes": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    mode: ExecutionMode
    output_directory: Path
    archive_size: int
    archive_sha256: str
    members: tuple[str, ...]
    backup: Path | None
    validation: ValidationReport
    artifacts: tuple[StagedArtifact, ...] = ()

    def __post_init__(self) -> None:
        if self.artifacts and tuple(item.name for item in self.artifacts) != (
            _STAGED_ROOT_ARTIFACT_NAMES
        ):
            raise ContractError(
                "staged artifacts must report Index.art, Thumbnail.jpg, and Mod.zip in order"
            )

    def to_dict(self) -> dict[str, Any]:
        artifact_payload = {
            artifact.name: artifact.to_dict(self.output_directory) for artifact in self.artifacts
        }
        if not artifact_payload:
            # Retain useful serialization for callers that construct the former
            # ReleaseResult shape directly; SDK-produced results always report all three.
            artifact_payload["Mod.zip"] = {
                "path": str(self.output_directory / "Mod.zip"),
                "bytes": self.archive_size,
                "sha256": self.archive_sha256,
            }
        return {
            "mode": self.mode.value,
            "output_directory": str(self.output_directory),
            "artifacts": artifact_payload,
            "archive": {
                "path": str(self.output_directory / "Mod.zip"),
                "bytes": self.archive_size,
                "sha256": self.archive_sha256,
                "members": list(self.members),
            },
            "backup": str(self.backup) if self.backup else None,
            "validation": self.validation.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RuntimeTestResult:
    mode: ExecutionMode
    project_root: Path
    status: RuntimeStatus
    log_sha256: str
    log_summary: Mapping[str, Any]
    source_fingerprint: SourceFingerprint
    tested_source: Path
    operating_system: str
    toolkit_version: str
    clean_launch: bool
    save_type: RuntimeSaveType
    save_persistence: SavePersistence
    tested_mod: str
    observed_game_semver: str
    record_path: Path
    config_backup: Path | None
    record_backup: Path | None
    warning_baseline: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "log_summary", MappingProxyType(dict(self.log_summary)))
        if self.warning_baseline is not None:
            warning_baseline = dict(self.warning_baseline)
            baseline_summary = warning_baseline.get("log_summary")
            if isinstance(baseline_summary, Mapping):
                warning_baseline["log_summary"] = MappingProxyType(dict(baseline_summary))
            object.__setattr__(
                self,
                "warning_baseline",
                MappingProxyType(warning_baseline),
            )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "mode": self.mode.value,
            "project_root": str(self.project_root),
            "runtime_status": self.status.value,
            "log_sha256": self.log_sha256,
            "log_summary": dict(self.log_summary),
            "source_fingerprint": self.source_fingerprint.to_dict(),
            "tested_source": str(self.tested_source),
            "environment": {
                "operating_system": self.operating_system,
                "toolkit_version": self.toolkit_version,
                "clean_launch": self.clean_launch,
                "save_type": self.save_type.value,
                "save_persistence": self.save_persistence.value,
                "tested_mod": self.tested_mod,
                "observed_game_semver": self.observed_game_semver,
            },
            "record_path": str(self.record_path),
            "config_backup": str(self.config_backup) if self.config_backup else None,
            "record_backup": str(self.record_backup) if self.record_backup else None,
        }
        if self.warning_baseline is not None:
            warning_baseline = dict(self.warning_baseline)
            baseline_summary = warning_baseline.get("log_summary")
            if isinstance(baseline_summary, Mapping):
                warning_baseline["log_summary"] = dict(baseline_summary)
            result["warning_baseline"] = warning_baseline
        return result


@dataclass(frozen=True, slots=True)
class ProjectConfigResult:
    mode: ExecutionMode
    project_root: Path
    config: ProjectConfig
    backup: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "project_root": str(self.project_root),
            "config": self.config.to_dict(),
            "backup": str(self.backup) if self.backup else None,
        }


@dataclass(frozen=True, slots=True)
class ProjectConfigPlan:
    project: SDKProject
    updated_config: ProjectConfig
    original_config_sha256: str

    def _validate(self) -> None:
        self.project._assert_config_unchanged()
        if self.original_config_sha256 != self.project._opened_config_sha256:
            raise ContractError("configuration plan has an invalid project snapshot")
        base = self.project.config
        expected = replace(
            base,
            name=self.updated_config.name,
            version=self.updated_config.version,
            license=self.updated_config.license,
            contact=self.updated_config.contact,
            provenance_status=self.updated_config.provenance_status,
            provenance_notes=self.updated_config.provenance_notes,
        )
        if expected != self.updated_config:
            raise ContractError(
                "configuration plan may only update name, version, license, contact, "
                "and provenance fields"
            )

    def preview(self) -> ProjectConfigResult:
        self._validate()
        return ProjectConfigResult(
            ExecutionMode.DRY_RUN,
            self.project.layout.root,
            self.updated_config,
            None,
        )

    def apply(self) -> ProjectConfigResult:
        self._validate()
        path = self.project.layout.config_path
        _legacy.assert_no_symlink_components(path)
        _legacy.assert_writable_project_path(path, self.project._refresh_context())
        original = _read_bounded(path, MAX_PROJECT_CONFIG_BYTES)
        if hashlib.sha256(original).hexdigest() != self.original_config_sha256:
            raise SourceChangedError("acmk.toml changed after configuration was planned", path=path)
        backup = _legacy._create_backup(path)
        if _read_bounded(path, MAX_PROJECT_CONFIG_BYTES) != original:
            raise SourceChangedError("acmk.toml changed before the configuration commit", path=path)
        _legacy._atomic_write(path, self.updated_config.to_toml().encode("utf-8"))
        return ProjectConfigResult(
            ExecutionMode.APPLY,
            self.project.layout.root,
            self.updated_config,
            backup,
        )


@dataclass(frozen=True, slots=True)
class ObservedConsensusResult:
    mode: ExecutionMode
    project_root: Path
    profile: str
    manifest_sha256: str
    runtime_reset: bool
    evidence_path: Path
    config_backup: Path | None
    manifest_backup: Path | None
    evidence_backup: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "project_root": str(self.project_root),
            "source": SkeletonSource.OBSERVED_CONSENSUS.value,
            "profile": self.profile,
            "manifest_sha256": self.manifest_sha256,
            "runtime_reset": self.runtime_reset,
            "evidence_path": str(self.evidence_path),
            "config_backup": str(self.config_backup) if self.config_backup else None,
            "manifest_backup": str(self.manifest_backup) if self.manifest_backup else None,
            "evidence_backup": str(self.evidence_backup) if self.evidence_backup else None,
        }


@dataclass(frozen=True, slots=True)
class ObservedConsensusPlan:
    """Reconcile a Generic community draft with one audited, build-specific profile."""

    project: SDKProject
    updated_config: ProjectConfig
    manifest_bytes: bytes
    evidence_bytes: bytes
    profile: str
    original_config_sha256: str
    original_manifest_sha256: str
    original_evidence_sha256: str | None

    @property
    def evidence_path(self) -> Path:
        return self.project.layout.state_root / "import.json"

    def preview(self) -> ObservedConsensusResult:
        self._validate()
        return self._result(ExecutionMode.DRY_RUN, None, None, None)

    def apply(self) -> ObservedConsensusResult:
        self._validate()
        layout = self.project.layout
        live_context = self.project._refresh_context()
        for path in (layout.config_path, layout.manifest, self.evidence_path):
            _legacy.assert_no_symlink_components(path)
            _legacy.assert_writable_project_path(path, live_context)
        layout.state_root.mkdir(parents=True, exist_ok=True)
        original_config = _read_bounded(layout.config_path, MAX_PROJECT_CONFIG_BYTES)
        original_manifest = _read_bounded(layout.manifest, _legacy.MAX_TEXT_ASSET_BYTES)
        original_evidence = (
            _read_bounded(self.evidence_path, _legacy.MAX_TEXT_ASSET_BYTES)
            if self.evidence_path.exists()
            else None
        )
        self._assert_snapshots(original_config, original_manifest, original_evidence)
        config_bytes = self.updated_config.to_toml().encode("utf-8")
        backup_root = layout.state_root / "backups"
        config_backup = _create_state_backup(
            layout.config_path,
            original_config,
            backup_root,
            boundary=layout.state_root,
        )
        manifest_backup = _create_state_backup(
            layout.manifest,
            original_manifest,
            backup_root,
            boundary=layout.state_root,
        )
        evidence_backup = (
            _legacy._create_backup(self.evidence_path) if original_evidence is not None else None
        )
        self._assert_snapshots(
            _read_bounded(layout.config_path, MAX_PROJECT_CONFIG_BYTES),
            _read_bounded(layout.manifest, _legacy.MAX_TEXT_ASSET_BYTES),
            (
                _read_bounded(self.evidence_path, _legacy.MAX_TEXT_ASSET_BYTES)
                if self.evidence_path.exists()
                else None
            ),
        )
        try:
            _legacy._atomic_write(self.evidence_path, self.evidence_bytes)
            _legacy._atomic_write(layout.manifest, self.manifest_bytes)
            _legacy._atomic_write(layout.config_path, config_bytes)
        except BaseException as exc:
            rollback_errors = _rollback_files(
                (
                    ("acmk.toml", layout.config_path, original_config, config_bytes),
                    ("Index.art", layout.manifest, original_manifest, self.manifest_bytes),
                    (
                        "import.json",
                        self.evidence_path,
                        original_evidence,
                        self.evidence_bytes,
                    ),
                )
            )
            if rollback_errors:
                raise ProjectError(
                    "consensus reconciliation failed and rollback was incomplete: "
                    + "; ".join(rollback_errors),
                    path=layout.root,
                ) from exc
            raise
        return self._result(
            ExecutionMode.APPLY,
            config_backup,
            manifest_backup,
            evidence_backup,
        )

    def _validate(self) -> None:
        self.project._assert_config_unchanged()
        if self.original_config_sha256 != self.project._opened_config_sha256:
            raise ContractError("consensus plan has an invalid configuration snapshot")
        if self.project.config.skeleton not in {
            SkeletonSource.COMMUNITY_DRAFT,
            SkeletonSource.OBSERVED_CONSENSUS,
        }:
            raise ContractError(
                "only a community-draft or observed-consensus project can be reconciled"
            )
        expected_profile = _observed_consensus_profile(self.project.config.compatibility)
        if expected_profile is None or self.profile != expected_profile:
            raise ContractError("consensus plan uses an unsupported compatibility profile")
        current_context = self.project._refresh_context()
        _assert_context_matches(current_context, self.project.config.compatibility)
        expected_config = replace(
            self.project.config,
            skeleton=SkeletonSource.OBSERVED_CONSENSUS,
            runtime_status=RuntimeStatus.UNTESTED,
        )
        if self.updated_config != expected_config:
            raise ContractError("consensus plan contains unauthorized configuration changes")
        original_config = _read_bounded(self.project.layout.config_path, MAX_PROJECT_CONFIG_BYTES)
        original_manifest = _read_bounded(
            self.project.layout.manifest, _legacy.MAX_TEXT_ASSET_BYTES
        )
        original_evidence = (
            _read_bounded(self.evidence_path, _legacy.MAX_TEXT_ASSET_BYTES)
            if self.evidence_path.exists()
            else None
        )
        self._assert_snapshots(original_config, original_manifest, original_evidence)
        expected_manifest = _reconciled_observed_consensus_manifest(
            ManifestDocument.from_bytes(original_manifest),
            self.profile,
            preserve_canonical=(self.project.config.skeleton is SkeletonSource.OBSERVED_CONSENSUS),
        )
        if self.manifest_bytes != expected_manifest:
            raise ContractError("consensus plan manifest differs from the audited profile")
        expected_evidence = _observed_consensus_evidence_bytes(
            self.updated_config,
            self.profile,
            hashlib.sha256(self.manifest_bytes).hexdigest(),
        )
        if self.evidence_bytes != expected_evidence:
            raise ContractError("consensus plan evidence differs from the canonical record")

    def _assert_snapshots(
        self,
        config_bytes: bytes,
        manifest_bytes: bytes,
        evidence_bytes: bytes | None,
    ) -> None:
        if hashlib.sha256(config_bytes).hexdigest() != self.original_config_sha256:
            raise SourceChangedError("acmk.toml changed after consensus planning")
        if hashlib.sha256(manifest_bytes).hexdigest() != self.original_manifest_sha256:
            raise SourceChangedError("Index.art changed after consensus planning")
        evidence_sha256 = (
            hashlib.sha256(evidence_bytes).hexdigest() if evidence_bytes is not None else None
        )
        if evidence_sha256 != self.original_evidence_sha256:
            raise SourceChangedError("import.json changed after consensus planning")

    def _result(
        self,
        mode: ExecutionMode,
        config_backup: Path | None,
        manifest_backup: Path | None,
        evidence_backup: Path | None,
    ) -> ObservedConsensusResult:
        return ObservedConsensusResult(
            mode=mode,
            project_root=self.project.layout.root,
            profile=self.profile,
            manifest_sha256=hashlib.sha256(self.manifest_bytes).hexdigest(),
            runtime_reset=self.project.config.runtime_status is not RuntimeStatus.UNTESTED,
            evidence_path=self.evidence_path,
            config_backup=config_backup,
            manifest_backup=manifest_backup,
            evidence_backup=evidence_backup,
        )


@dataclass(frozen=True, slots=True)
class RuntimeTestPlan:
    project: SDKProject
    updated_config: ProjectConfig
    original_config_sha256: str
    log_path: Path
    log_size: int
    log_sha256: str
    log_summary: Mapping[str, Any]
    source_fingerprint: SourceFingerprint
    tested_source: Path
    operating_system: str
    toolkit_version: str
    clean_launch: bool
    save_type: RuntimeSaveType
    save_persistence: SavePersistence
    tested_mod: str
    observed_game_semver: str
    recorded_at: str
    warning_baseline: _WarningBaseline | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "log_summary", MappingProxyType(dict(self.log_summary)))

    @property
    def record_path(self) -> Path:
        return self.project.layout.state_root / "runtime-test.json"

    def preview(self) -> RuntimeTestResult:
        self._validated_record()
        return RuntimeTestResult(
            mode=ExecutionMode.DRY_RUN,
            project_root=self.project.layout.root,
            status=self.updated_config.runtime_status,
            log_sha256=self.log_sha256,
            log_summary=self.log_summary,
            source_fingerprint=self.source_fingerprint,
            tested_source=self.tested_source,
            operating_system=self.operating_system,
            toolkit_version=self.toolkit_version,
            clean_launch=self.clean_launch,
            save_type=self.save_type,
            save_persistence=self.save_persistence,
            tested_mod=self.tested_mod,
            observed_game_semver=self.observed_game_semver,
            record_path=self.record_path,
            config_backup=None,
            record_backup=None,
            warning_baseline=(
                self.warning_baseline.to_dict() if self.warning_baseline is not None else None
            ),
        )

    def apply(self) -> RuntimeTestResult:
        layout = self.project.layout
        record = self._validated_record()
        _legacy.assert_no_symlink_components(layout.config_path)
        _legacy.assert_no_symlink_components(self.record_path)
        write_context = self.project._refresh_context()
        _assert_context_matches(write_context, self.updated_config.compatibility)
        _legacy.assert_writable_project_path(layout.config_path, write_context)
        _legacy.assert_writable_project_path(self.record_path, write_context)
        layout.state_root.mkdir(parents=True, exist_ok=True)
        original_config = _read_bounded(layout.config_path, MAX_PROJECT_CONFIG_BYTES)
        if hashlib.sha256(original_config).hexdigest() != self.original_config_sha256:
            raise SourceChangedError(
                "acmk.toml changed while runtime evidence was being prepared",
                path=layout.config_path,
            )
        original_record = (
            _read_bounded(self.record_path, _legacy.MAX_TEXT_ASSET_BYTES)
            if self.record_path.exists()
            else None
        )
        config_bytes = self.updated_config.to_toml().encode("utf-8")
        record_bytes = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
        config_backup = _legacy._create_backup(layout.config_path)
        record_backup = (
            _legacy._create_backup(self.record_path) if original_record is not None else None
        )
        if _read_bounded(layout.config_path, MAX_PROJECT_CONFIG_BYTES) != original_config:
            raise SourceChangedError(
                "acmk.toml changed before the runtime evidence commit",
                path=layout.config_path,
            )
        if original_record is None:
            if self.record_path.exists():
                raise SourceChangedError(
                    "runtime-test.json appeared before the evidence commit",
                    path=self.record_path,
                )
        elif _read_bounded(self.record_path, _legacy.MAX_TEXT_ASSET_BYTES) != original_record:
            raise SourceChangedError(
                "runtime-test.json changed before the evidence commit",
                path=self.record_path,
            )
        try:
            _legacy._atomic_write(self.record_path, record_bytes)
            _legacy._atomic_write(layout.config_path, config_bytes)
        except BaseException as exc:
            rollback_errors = _rollback_runtime_record(
                config_path=layout.config_path,
                original_config=original_config,
                written_config=config_bytes,
                record_path=self.record_path,
                original_record=original_record,
                written_record=record_bytes,
            )
            if rollback_errors:
                raise ProjectError(
                    "runtime evidence update failed and rollback was incomplete: "
                    + "; ".join(rollback_errors),
                    path=layout.root,
                ) from exc
            raise
        return RuntimeTestResult(
            mode=ExecutionMode.APPLY,
            project_root=layout.root,
            status=self.updated_config.runtime_status,
            log_sha256=self.log_sha256,
            log_summary=self.log_summary,
            source_fingerprint=self.source_fingerprint,
            tested_source=self.tested_source,
            operating_system=self.operating_system,
            toolkit_version=self.toolkit_version,
            clean_launch=self.clean_launch,
            save_type=self.save_type,
            save_persistence=self.save_persistence,
            tested_mod=self.tested_mod,
            observed_game_semver=self.observed_game_semver,
            record_path=self.record_path,
            config_backup=config_backup,
            record_backup=record_backup,
            warning_baseline=(
                self.warning_baseline.to_dict() if self.warning_baseline is not None else None
            ),
        )

    def _validated_record(self) -> dict[str, Any]:
        self.project._assert_config_unchanged()
        if self.original_config_sha256 != self.project._opened_config_sha256:
            raise ContractError("runtime-test plan has an invalid configuration snapshot")
        if self.updated_config.runtime_status not in {RuntimeStatus.PASSED, RuntimeStatus.FAILED}:
            raise ContractError("runtime-test plan must record passed or failed status")
        expected_config = replace(
            self.project.config,
            runtime_status=self.updated_config.runtime_status,
            save_impact=self.updated_config.save_impact,
            achievement_impact=self.updated_config.achievement_impact,
        )
        if expected_config != self.updated_config:
            raise ContractError("runtime-test plan contains unauthorized configuration changes")
        if (
            not isinstance(self.clean_launch, bool)
            or not isinstance(self.save_type, RuntimeSaveType)
            or not isinstance(self.save_persistence, SavePersistence)
            or not isinstance(self.tested_source, Path)
        ):
            raise ContractError("runtime-test environment fields have invalid types")
        if self.updated_config.runtime_status is RuntimeStatus.FAILED:
            persistence_problem = _save_persistence_evidence_problem(
                self.save_type,
                self.save_persistence,
                passed=False,
            )
            if persistence_problem:
                raise ContractError(persistence_problem)
        expected_os = f"{platform.system()} {platform.release()}".strip()
        if self.operating_system != expected_os or self.toolkit_version != __version__:
            raise ContractError("runtime-test environment changed after planning")
        current_context = self.project._refresh_context()
        _assert_context_matches(current_context, self.updated_config.compatibility)
        try:
            if _is_link_like(self.log_path) or not self.log_path.is_file():
                raise SourceChangedError("runtime log is no longer a regular file")
            log_bytes = _read_bounded(self.log_path, _legacy.MAX_LOG_BYTES)
            log_text = _legacy.decode_log_bytes(log_bytes, str(self.log_path))
        except (OSError, _legacy.ModToolError) as exc:
            raise SourceChangedError(f"cannot re-read runtime log: {exc}") from exc
        if (
            len(log_bytes) != self.log_size
            or hashlib.sha256(log_bytes).hexdigest() != self.log_sha256
        ):
            raise SourceChangedError("Log.txt changed after the runtime record was planned")
        summary, target_enabled, game_version_observed = _analyse_runtime_log(
            log_text,
            project_name=self.project.config.name,
            game_semver=self.project.config.compatibility.game_semver,
            achievement_impact=self.updated_config.achievement_impact,
        )
        if summary != dict(self.log_summary):
            raise ContractError("runtime-test summary does not match the recorded log")
        unmatched_warnings: int | None = None
        if self.warning_baseline is not None:
            baseline = self.warning_baseline
            if baseline.log_path == self.log_path or _is_within(
                baseline.log_path, self.project.layout.root
            ):
                raise ContractError("warning baseline plan has an invalid source path")
            try:
                if _is_link_like(baseline.log_path) or not baseline.log_path.is_file():
                    raise SourceChangedError("warning baseline log is no longer a regular file")
                baseline_bytes = _read_bounded(baseline.log_path, _legacy.MAX_LOG_BYTES)
                baseline_text = _legacy.decode_log_bytes(baseline_bytes, str(baseline.log_path))
            except (OSError, _legacy.ModToolError) as exc:
                raise SourceChangedError(f"cannot re-read warning baseline log: {exc}") from exc
            if (
                len(baseline_bytes) != baseline.log_size
                or hashlib.sha256(baseline_bytes).hexdigest() != baseline.log_sha256
            ):
                raise SourceChangedError(
                    "baseline Log.txt changed after the runtime record was planned"
                )
            baseline_summary, _baseline_target_enabled, baseline_game_version_observed = (
                _analyse_runtime_log(
                    baseline_text,
                    project_name=self.project.config.name,
                    game_semver=self.project.config.compatibility.game_semver,
                )
            )
            if baseline_summary != dict(baseline.log_summary):
                raise ContractError("warning baseline summary does not match the recorded log")
            if not baseline_game_version_observed:
                raise ContractError("warning baseline does not identify the recorded game version")
            ignored_warnings, unmatched_warnings = _warning_differential(
                log_text,
                baseline_text,
                project_name=self.project.config.name,
                allow_achievement_warning=(
                    self.updated_config.achievement_impact is AchievementImpact.DISABLED
                    and target_enabled
                ),
            )
            if (
                ignored_warnings != baseline.ignored_warnings
                or unmatched_warnings != baseline.unmatched_warnings
            ):
                raise ContractError("warning baseline differential changed after planning")
        expected_tested_mod = self.project.config.name if target_enabled else ""
        expected_semver = (
            self.project.config.compatibility.game_semver if game_version_observed else ""
        )
        if self.tested_mod != expected_tested_mod or self.observed_game_semver != expected_semver:
            raise ContractError("runtime-test observations do not match the recorded log")
        if self.updated_config.runtime_status is RuntimeStatus.PASSED:
            blockers = _runtime_blockers(
                summary,
                target_enabled=target_enabled,
                game_version_observed=game_version_observed,
                clean_launch=self.clean_launch,
                project_name=self.project.config.name,
                game_semver=self.project.config.compatibility.game_semver,
                unmatched_warnings=unmatched_warnings,
            )
            impact_problem = _save_impact_evidence_problem(
                self.updated_config.save_impact, self.save_type
            )
            if impact_problem:
                blockers.append(impact_problem)
            persistence_problem = _save_persistence_evidence_problem(
                self.save_type,
                self.save_persistence,
                passed=True,
            )
            if persistence_problem:
                blockers.append(persistence_problem)
            if blockers:
                raise ValidationFailedError(
                    "cannot record a passing test: log contains " + ", ".join(blockers),
                    path=self.log_path,
                )
        current_fingerprint = _capture_loose_mod_root(self.tested_source)[1]
        if current_fingerprint != self.source_fingerprint:
            raise SourceChangedError(
                "tested loose mod source changed after the test record was planned",
                path=self.tested_source,
            )
        try:
            recorded_time = datetime.fromisoformat(self.recorded_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError("runtime-test recorded_at is invalid") from exc
        if recorded_time.tzinfo is None or recorded_time.utcoffset() is None:
            raise ContractError("runtime-test recorded_at must include a timezone")
        record = {
            "schema_version": RUNTIME_TEST_SCHEMA_VERSION,
            "recorded_at": self.recorded_at,
            "runtime_status": self.updated_config.runtime_status.value,
            "compatibility": {
                "game_version": self.updated_config.compatibility.game_version,
                "game_semver": self.updated_config.compatibility.game_semver,
                "steam_build_id": self.updated_config.compatibility.steam_build_id,
                "content_hash": self.updated_config.compatibility.content_hash,
            },
            "log_sha256": self.log_sha256,
            "log_summary": dict(self.log_summary),
            "source_fingerprint": self.source_fingerprint.to_dict(),
            "environment": {
                "operating_system": self.operating_system,
                "toolkit_version": self.toolkit_version,
                "clean_launch": self.clean_launch,
                "save_type": self.save_type.value,
                "save_persistence": self.save_persistence.value,
                "tested_mod": self.tested_mod,
                "observed_game_semver": self.observed_game_semver,
            },
        }
        if self.warning_baseline is not None:
            record["warning_baseline"] = self.warning_baseline.to_dict()
        return record


@dataclass(frozen=True, slots=True)
class ReleasePlan:
    project: SDKProject
    snapshots: tuple[FileSnapshot, ...]
    validation: ValidationReport
    config_sha256: str

    def preview(self) -> ReleaseResult:
        return self._execute(
            apply=False,
            replace=False,
            validation=self._current_validation(),
        )

    def apply(self, *, replace: bool = False) -> ReleaseResult:
        return self._execute(
            apply=True,
            replace=replace,
            validation=self._current_validation(),
        )

    def _current_validation(self) -> ValidationReport:
        if (
            _hash_file(self.project.layout.config_path, limit=MAX_PROJECT_CONFIG_BYTES)
            != self.config_sha256
        ):
            raise SourceChangedError(
                "acmk.toml changed after release staging was planned",
                path=self.project.layout.config_path,
            )
        fresh_project = SDKProject.open(
            self.project.layout.root,
            context=self.project._refresh_context(),
            context_refresher=self.project._context_refresher,
        )
        current_snapshots, _fingerprint = _capture_source_tree(fresh_project.layout.source_root)
        planned_identity = tuple(
            (
                snapshot.source,
                snapshot.relative_destination,
                snapshot.size,
                snapshot.sha256,
            )
            for snapshot in self.snapshots
        )
        current_identity = tuple(
            (
                snapshot.source,
                snapshot.relative_destination,
                snapshot.size,
                snapshot.sha256,
            )
            for snapshot in current_snapshots
        )
        if planned_identity != current_identity:
            raise SourceChangedError(
                "runtime source or release snapshots changed after staging was planned",
                path=fresh_project.layout.source_root,
            )
        return fresh_project.validate(ValidationProfile.RELEASE)

    def _execute(
        self,
        *,
        apply: bool,
        replace: bool,
        validation: ValidationReport | None = None,
    ) -> ReleaseResult:
        active_validation = validation or self.validation
        active_validation.raise_for_errors()
        layout = self.project.layout
        destination = layout.distribution_root
        build_context = self.project._refresh_context()
        _assert_context_matches(build_context, self.project.config.compatibility)
        if apply:
            _legacy.assert_no_symlink_components(destination)
            _legacy.assert_writable_project_path(destination, build_context)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp_parent: Path | None = destination.parent
        else:
            temp_parent = None
        workspace = Path(tempfile.mkdtemp(prefix="acmk-release-", dir=temp_parent))
        backup: Path | None = None
        staged_distribution = workspace / "workshop"
        staged_source = workspace / "source"
        try:
            staged_source.mkdir()
            staged_distribution.mkdir()
            by_relative = {snapshot.relative_destination: snapshot for snapshot in self.snapshots}
            for snapshot in self.snapshots:
                snapshot.copy_verified(
                    _safe_destination(staged_source, snapshot.relative_destination)
                )
            for root_name in ("Index.art", "Thumbnail.jpg"):
                by_relative[root_name].copy_verified(staged_distribution / root_name)
            build = _legacy.build_project(
                staged_source,
                output=staged_distribution / "Mod.zip",
                apply=True,
                ctx=build_context,
            )
            final_validation = self._current_validation()
            final_validation.raise_for_errors()
            result = ReleaseResult(
                mode=ExecutionMode.APPLY if apply else ExecutionMode.DRY_RUN,
                output_directory=destination,
                archive_size=int(build["bytes"]),
                archive_sha256=str(build["sha256"]),
                members=tuple(str(item) for item in build["members"]),
                backup=None,
                validation=final_validation,
                artifacts=(
                    StagedArtifact(
                        "Index.art",
                        by_relative["Index.art"].size,
                        by_relative["Index.art"].sha256,
                    ),
                    StagedArtifact(
                        "Thumbnail.jpg",
                        by_relative["Thumbnail.jpg"].size,
                        by_relative["Thumbnail.jpg"].sha256,
                    ),
                    StagedArtifact(
                        "Mod.zip",
                        int(build["bytes"]),
                        str(build["sha256"]),
                    ),
                ),
            )
            if not apply:
                return result
            if destination.exists():
                if not replace:
                    raise ProjectError(
                        "release destination exists; pass replace=True to create a backup "
                        "and replace it",
                        code="TARGET_EXISTS",
                        path=destination,
                    )
                if not destination.is_dir() or _is_link_like(destination):
                    raise ProjectError(
                        "release destination is not a safe directory", path=destination
                    )
                backup = _next_backup(destination)
                os.replace(destination, backup)
            try:
                os.replace(staged_distribution, destination)
            except BaseException:
                if backup is not None and not destination.exists():
                    os.replace(backup, destination)
                raise
            return ReleaseResult(
                mode=result.mode,
                output_directory=result.output_directory,
                archive_size=result.archive_size,
                archive_sha256=result.archive_sha256,
                members=result.members,
                backup=backup,
                validation=result.validation,
                artifacts=result.artifacts,
            )
        finally:
            _remove_temporary_tree(workspace)


class SDKProject:
    """Opened ACMK authoring project bound to a live discovery context."""

    def __init__(
        self,
        layout: ProjectLayout,
        context: _legacy.DiscoveryContext,
        *,
        opened_config_sha256: str,
        context_refresher: Callable[[], _legacy.DiscoveryContext] | None = None,
    ) -> None:
        self.layout = layout
        self.context = context
        self._opened_config_sha256 = opened_config_sha256
        self._context_refresher = context_refresher

    @classmethod
    def open(
        cls,
        root: str | os.PathLike[str],
        *,
        context: _legacy.DiscoveryContext | None = None,
        context_refresher: Callable[[], _legacy.DiscoveryContext] | None = None,
    ) -> SDKProject:
        project_root = _lexical_absolute(Path(root))
        config_path = project_root / "acmk.toml"
        _assert_no_link_components(config_path, project_root)
        if not config_path.is_file():
            raise ProjectError("acmk.toml not found", path=config_path)
        config_bytes = _read_bounded(config_path, MAX_PROJECT_CONFIG_BYTES)
        config = ProjectConfig.from_bytes(config_bytes, source=config_path)
        config_sha256 = hashlib.sha256(config_bytes).hexdigest()
        live = context or _legacy.discover_context()
        project = cls(
            ProjectLayout(project_root, config),
            live,
            opened_config_sha256=config_sha256,
            context_refresher=context_refresher,
        )
        project._assert_project_paths_safe()
        return project

    @property
    def config(self) -> ProjectConfig:
        return self.layout.config

    def manifest(self) -> ManifestDocument:
        return ManifestDocument.read(self.layout.manifest)

    def validate(
        self, profile: ValidationProfile = ValidationProfile.AUTHORING
    ) -> ValidationReport:
        raw = _legacy.validate_target(self.layout.source_root, self.context, check_archive=False)
        extra = list(self._project_issues(profile))
        return ValidationReport.from_legacy(raw, profile=profile, extra_issues=extra)

    def plan_release(self) -> ReleasePlan:
        self._assert_config_unchanged()
        source_root = self.layout.source_root
        snapshots, _fingerprint = _capture_source_tree(source_root)
        report = self.validate(ValidationProfile.RELEASE)
        required = {"Index.art", "Thumbnail.jpg"}
        present = {item.relative_destination for item in snapshots}
        if not required.issubset(present):
            missing = ", ".join(sorted(required - present))
            raise ProjectError(f"release source is missing {missing}")
        self._assert_config_unchanged()
        return ReleasePlan(
            self,
            tuple(snapshots),
            report,
            self._opened_config_sha256,
        )

    def plan_runtime_test(
        self,
        log_path: str | os.PathLike[str],
        *,
        tested_source: str | os.PathLike[str],
        passed: bool,
        save_impact: SaveImpact,
        achievement_impact: AchievementImpact,
        clean_launch: bool,
        save_type: RuntimeSaveType,
        save_persistence: SavePersistence,
        baseline_log_path: str | os.PathLike[str] | None = None,
    ) -> RuntimeTestPlan:
        """Record a user-performed test without launching the game.

        A passing record requires the current compatibility fingerprint and a
        log without lines classified as errors or failures. An optional clean
        clean-launch/pre-save-reload baseline may suppress only recurring normalized warning
        signatures, including when that baseline already enables the tested mod.
        Raw logs and their absolute paths are never copied into the project.
        """

        self._assert_config_unchanged()
        if not isinstance(passed, bool) or not isinstance(clean_launch, bool):
            raise ContractError("passed and clean_launch must be booleans")
        if not isinstance(save_impact, SaveImpact):
            raise ContractError("save_impact must be a SaveImpact value")
        if not isinstance(achievement_impact, AchievementImpact):
            raise ContractError("achievement_impact must be an AchievementImpact value")
        if not isinstance(save_type, RuntimeSaveType):
            raise ContractError("save_type must be a RuntimeSaveType value")
        if not isinstance(save_persistence, SavePersistence):
            raise ContractError("save_persistence must be a SavePersistence value")
        persistence_problem = _save_persistence_evidence_problem(
            save_type,
            save_persistence,
            passed=passed,
        )
        if persistence_problem and not passed:
            raise ContractError(persistence_problem)
        live_context = self._refresh_context()
        _assert_context_matches(live_context, self.config.compatibility)
        tested_source_root = _lexical_absolute(Path(tested_source))
        source = _lexical_absolute(Path(log_path))
        if _is_within(source, self.layout.root):
            raise ProjectError(
                "runtime Log.txt must remain outside the ACMK project tree",
                code="LOG_INSIDE_PROJECT",
                path=source,
            )
        try:
            if _is_link_like(source) or not source.is_file():
                raise ProjectError("runtime log must be a regular, non-symlink file", path=source)
        except OSError as exc:
            raise ProjectError(f"cannot inspect runtime log: {exc}", path=source) from exc
        try:
            log_bytes = _read_bounded(source, _legacy.MAX_LOG_BYTES)
            log_text = _legacy.decode_log_bytes(log_bytes, str(source))
            summary, target_enabled, game_version_observed = _analyse_runtime_log(
                log_text,
                project_name=self.config.name,
                game_semver=self.config.compatibility.game_semver,
                achievement_impact=achievement_impact,
            )
        except (_legacy.ModToolError, OSError) as exc:
            raise ProjectError(str(exc), code="LOG_INVALID", path=source) from exc
        warning_baseline: _WarningBaseline | None = None
        unmatched_warnings: int | None = None
        if baseline_log_path is not None:
            baseline_source = _lexical_absolute(Path(baseline_log_path))
            if baseline_source == source:
                raise ProjectError(
                    "warning baseline must be a distinct clean-launch/pre-save-reload log",
                    code="BASELINE_LOG_SAME_AS_RUNTIME",
                    path=baseline_source,
                )
            if _is_within(baseline_source, self.layout.root):
                raise ProjectError(
                    "warning baseline Log.txt must remain outside the ACMK project tree",
                    code="BASELINE_LOG_INSIDE_PROJECT",
                    path=baseline_source,
                )
            try:
                if _is_link_like(baseline_source) or not baseline_source.is_file():
                    raise ProjectError(
                        "warning baseline must be a regular, non-symlink file",
                        path=baseline_source,
                    )
                baseline_bytes = _read_bounded(baseline_source, _legacy.MAX_LOG_BYTES)
                baseline_text = _legacy.decode_log_bytes(baseline_bytes, str(baseline_source))
                (
                    baseline_summary,
                    _baseline_target_enabled,
                    baseline_game_version_observed,
                ) = _analyse_runtime_log(
                    baseline_text,
                    project_name=self.config.name,
                    game_semver=self.config.compatibility.game_semver,
                )
            except (_legacy.ModToolError, OSError) as exc:
                raise ProjectError(
                    str(exc), code="BASELINE_LOG_INVALID", path=baseline_source
                ) from exc
            if not baseline_game_version_observed:
                raise ValidationFailedError(
                    "warning baseline does not contain the exact game-version marker",
                    path=baseline_source,
                )
            ignored_warnings, unmatched_warnings = _warning_differential(
                log_text,
                baseline_text,
                project_name=self.config.name,
                allow_achievement_warning=(
                    achievement_impact is AchievementImpact.DISABLED and target_enabled
                ),
            )
            warning_baseline = _WarningBaseline(
                log_path=baseline_source,
                log_size=len(baseline_bytes),
                log_sha256=hashlib.sha256(baseline_bytes).hexdigest(),
                log_summary=baseline_summary,
                ignored_warnings=ignored_warnings,
                unmatched_warnings=unmatched_warnings,
            )
        if passed:
            blockers = _runtime_blockers(
                summary,
                target_enabled=target_enabled,
                game_version_observed=game_version_observed,
                clean_launch=clean_launch,
                project_name=self.config.name,
                game_semver=self.config.compatibility.game_semver,
                unmatched_warnings=unmatched_warnings,
            )
            impact_problem = _save_impact_evidence_problem(save_impact, save_type)
            if impact_problem:
                blockers.append(impact_problem)
            if persistence_problem:
                blockers.append(persistence_problem)
            if blockers:
                raise ValidationFailedError(
                    "cannot record a passing test: log contains " + ", ".join(blockers),
                    path=source,
                )
        source_fingerprint = _capture_loose_mod_root(tested_source_root)[1]
        updated = ProjectConfig(
            identifier=self.config.identifier,
            name=self.config.name,
            version=self.config.version,
            mod_type=self.config.mod_type,
            compatibility=self.config.compatibility,
            license=self.config.license,
            contact=self.config.contact,
            skeleton=self.config.skeleton,
            runtime_status=RuntimeStatus.PASSED if passed else RuntimeStatus.FAILED,
            save_impact=save_impact,
            achievement_impact=achievement_impact,
            provenance_status=self.config.provenance_status,
            provenance_notes=self.config.provenance_notes,
            dependencies=self.config.dependencies,
            conflicts=self.config.conflicts,
            paths=self.config.paths,
            schema_version=self.config.schema_version,
        )
        self._assert_config_unchanged()
        return RuntimeTestPlan(
            project=self,
            updated_config=updated,
            original_config_sha256=self._opened_config_sha256,
            log_path=source,
            log_size=len(log_bytes),
            log_sha256=hashlib.sha256(log_bytes).hexdigest(),
            log_summary=summary,
            warning_baseline=warning_baseline,
            source_fingerprint=source_fingerprint,
            tested_source=tested_source_root,
            operating_system=(f"{platform.system()} {platform.release()}".strip()),
            toolkit_version=__version__,
            clean_launch=clean_launch,
            save_type=save_type,
            save_persistence=save_persistence,
            tested_mod=self.config.name if target_enabled else "",
            observed_game_semver=(
                self.config.compatibility.game_semver if game_version_observed else ""
            ),
            recorded_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )

    def plan_configuration(
        self,
        *,
        name: str | None = None,
        version: str | None = None,
        license: str | None = None,
        contact: str | None = None,
        provenance_status: ProvenanceStatus | None = None,
        provenance_notes: str | None = None,
    ) -> ProjectConfigPlan:
        """Plan an atomic, backed-up update of distribution metadata."""

        self._assert_config_unchanged()
        if all(
            value is None
            for value in (name, version, license, contact, provenance_status, provenance_notes)
        ):
            raise ContractError("at least one project configuration update is required")
        updated = replace(
            self.config,
            name=self.config.name if name is None else name,
            version=self.config.version if version is None else version,
            license=self.config.license if license is None else license,
            contact=self.config.contact if contact is None else contact,
            provenance_status=(
                self.config.provenance_status if provenance_status is None else provenance_status
            ),
            provenance_notes=(
                self.config.provenance_notes if provenance_notes is None else provenance_notes
            ),
        )
        self._assert_config_unchanged()
        return ProjectConfigPlan(
            self,
            updated,
            self._opened_config_sha256,
        )

    def plan_observed_consensus(self) -> ObservedConsensusPlan:
        """Reconcile or refresh a Generic project for its audited exact-build profile.

        This is deliberately distinct from importing a game-generated skeleton. The
        operation normalizes only the root manifest, writes sanitized origin evidence,
        and invalidates any previous runtime pass because the release source may change.
        An already reconciled project may repeat the operation after an intentional,
        structurally valid manifest metadata update to refresh its bound evidence.
        """

        self._assert_config_unchanged()
        if self.config.skeleton not in {
            SkeletonSource.COMMUNITY_DRAFT,
            SkeletonSource.OBSERVED_CONSENSUS,
        }:
            raise ProjectError(
                "only a community-draft or observed-consensus project can be reconciled",
                code="CONSENSUS_SOURCE_INVALID",
                path=self.layout.config_path,
            )
        live_context = self._refresh_context()
        _assert_context_matches(live_context, self.config.compatibility)
        for path in (self.layout.config_path, self.layout.manifest, self.layout.state_root):
            _legacy.assert_writable_project_path(path, live_context)
        profile = _observed_consensus_profile(self.config.compatibility)
        if profile is None:
            raise ProjectError(
                "no audited observed-consensus profile supports this exact game build",
                code="CONSENSUS_PROFILE_UNSUPPORTED",
                path=self.layout.config_path,
            )
        original_manifest = _read_bounded(self.layout.manifest, _legacy.MAX_TEXT_ASSET_BYTES)
        manifest_bytes = _reconciled_observed_consensus_manifest(
            ManifestDocument.from_bytes(original_manifest),
            profile,
            preserve_canonical=(self.config.skeleton is SkeletonSource.OBSERVED_CONSENSUS),
        )
        updated_config = replace(
            self.config,
            skeleton=SkeletonSource.OBSERVED_CONSENSUS,
            runtime_status=RuntimeStatus.UNTESTED,
        )
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        evidence_bytes = _observed_consensus_evidence_bytes(
            updated_config, profile, manifest_sha256
        )
        evidence_path = self.layout.state_root / "import.json"
        original_evidence = (
            _read_bounded(evidence_path, _legacy.MAX_TEXT_ASSET_BYTES)
            if evidence_path.exists()
            else None
        )
        self._assert_config_unchanged()
        return ObservedConsensusPlan(
            project=self,
            updated_config=updated_config,
            manifest_bytes=manifest_bytes,
            evidence_bytes=evidence_bytes,
            profile=profile,
            original_config_sha256=self._opened_config_sha256,
            original_manifest_sha256=hashlib.sha256(original_manifest).hexdigest(),
            original_evidence_sha256=(
                hashlib.sha256(original_evidence).hexdigest()
                if original_evidence is not None
                else None
            ),
        )

    def update_metadata(
        self,
        updates: Mapping[str, str],
        *,
        apply: bool = False,
        backup: bool = True,
    ) -> Mapping[str, Any]:
        self._assert_config_unchanged()
        normalized_updates = {
            key.strip().casefold().replace("-", "").replace("_", "") for key in updates
        }
        duplicated = normalized_updates & {
            "title",
            "type",
            "gameversion",
        }
        if duplicated:
            raise ContractError(
                "project metadata updates cannot change Title, Type, or GameVersion; "
                "re-import or use a coordinated project migration"
            )
        if self.config.skeleton is SkeletonSource.OBSERVED_CONSENSUS:
            permitted = {"changelog", "content", "description", "steammodid"}
            unsupported = normalized_updates - permitted
            if unsupported:
                raise ContractError(
                    "observed-consensus metadata updates are limited to Changelog, Content, "
                    "Description, and SteamModId; refresh consensus evidence after applying"
                )
        try:
            return dict(
                _legacy.apply_metadata(
                    self.layout.source_root,
                    updates,
                    apply=apply,
                    backup=backup,
                    ctx=self._refresh_context(),
                )
            )
        except _legacy.ModToolError as exc:
            raise ProjectError(str(exc), code="MANIFEST_UPDATE", path=self.layout.manifest) from exc

    def _assert_config_unchanged(self) -> None:
        self._assert_project_paths_safe()
        if (
            _hash_file(self.layout.config_path, limit=MAX_PROJECT_CONFIG_BYTES)
            != self._opened_config_sha256
        ):
            raise SourceChangedError(
                "acmk.toml changed after the project was opened; reopen the project",
                path=self.layout.config_path,
            )

    def _assert_project_paths_safe(self) -> None:
        for path in (
            self.layout.config_path,
            self.layout.source_root,
            self.layout.assets_root,
            self.layout.state_root,
            self.layout.distribution_root,
        ):
            _assert_no_link_components(path, self.layout.root)

    def _refresh_context(self) -> _legacy.DiscoveryContext:
        return self._context_refresher() if self._context_refresher is not None else self.context

    def _project_issues(self, profile: ValidationProfile) -> Iterable[Issue]:
        config = self.config
        manifest: ManifestDocument | None = None
        try:
            manifest = self.manifest()
        except ContractError as exc:
            yield Issue(Severity.ERROR, exc.code, str(exc), self.layout.manifest)
        if manifest is not None:
            if manifest.fields.get("Title") != config.name:
                yield Issue(
                    Severity.ERROR if profile is ValidationProfile.RELEASE else Severity.WARNING,
                    "CONFIG_TITLE_MISMATCH",
                    "acmk.toml and Index.art use different project titles",
                    self.layout.config_path,
                )
            if manifest.fields.get("GameVersion") != config.compatibility.game_version:
                yield Issue(
                    Severity.ERROR,
                    "CONFIG_GAME_VERSION_MISMATCH",
                    "acmk.toml and Index.art use different GameVersion values",
                    self.layout.config_path,
                )
            if manifest.fields.get("Type") != config.mod_type:
                yield Issue(
                    Severity.ERROR if profile is ValidationProfile.RELEASE else Severity.WARNING,
                    "CONFIG_MOD_TYPE_MISMATCH",
                    "acmk.toml and Index.art use different mod types",
                    self.layout.config_path,
                )
            if profile is ValidationProfile.RELEASE:
                distributed_metadata = "\n".join(
                    (
                        manifest.fields.get("Description", ""),
                        manifest.fields.get("Content", ""),
                    )
                ).casefold()
                if config.contact.casefold() not in distributed_metadata:
                    yield Issue(
                        Severity.ERROR,
                        "RELEASE_CONTACT_NOT_DISTRIBUTED",
                        "project contact must also appear in manifest Description or Content",
                        self.layout.manifest,
                    )
                if config.license.casefold() not in distributed_metadata:
                    yield Issue(
                        Severity.ERROR,
                        "RELEASE_LICENSE_NOT_DISTRIBUTED",
                        "project license identifier must also appear in manifest "
                        "Description or Content",
                        self.layout.manifest,
                    )
        live_values = {
            "game version": self.context.semver,
            "Steam build": self.context.build_id,
            "content hash": self.context.content_hash,
            "GameVersion": self.context.game_version,
        }
        for label, value in live_values.items():
            if value:
                continue
            yield Issue(
                Severity.ERROR if profile is ValidationProfile.RELEASE else Severity.WARNING,
                "LIVE_" + label.upper().replace(" ", "_") + "_MISSING",
                f"live {label} could not be discovered",
                self.layout.config_path,
            )
        if (
            self.context.game_version
            and config.compatibility.game_version != self.context.game_version
        ):
            message = (
                f"project targets GameVersion {config.compatibility.game_version}; "
                f"current is {self.context.game_version}"
            )
            yield Issue(
                Severity.ERROR if profile is ValidationProfile.RELEASE else Severity.WARNING,
                "PROJECT_GAME_VERSION_STALE",
                message,
                self.layout.config_path,
            )
        if self.context.build_id and config.compatibility.steam_build_id != self.context.build_id:
            message = (
                f"project records Steam build {config.compatibility.steam_build_id!r}; "
                f"current is {self.context.build_id!r}"
            )
            yield Issue(
                Severity.ERROR if profile is ValidationProfile.RELEASE else Severity.WARNING,
                "PROJECT_BUILD_STALE",
                message,
                self.layout.config_path,
            )
        if self.context.semver and config.compatibility.game_semver != self.context.semver:
            message = (
                f"project records game version {config.compatibility.game_semver!r}; "
                f"current is {self.context.semver!r}"
            )
            yield Issue(
                Severity.ERROR if profile is ValidationProfile.RELEASE else Severity.WARNING,
                "PROJECT_SEMVER_STALE",
                message,
                self.layout.config_path,
            )
        if (
            self.context.content_hash
            and config.compatibility.content_hash != self.context.content_hash
        ):
            message = (
                f"project records content hash {config.compatibility.content_hash!r}; "
                f"current is {self.context.content_hash!r}"
            )
            yield Issue(
                Severity.ERROR if profile is ValidationProfile.RELEASE else Severity.WARNING,
                "PROJECT_CONTENT_HASH_STALE",
                message,
                self.layout.config_path,
            )
        if profile is ValidationProfile.RELEASE:
            for code, message, condition in (
                (
                    "RELEASE_CONTACT_MISSING",
                    "project contact details are required",
                    not config.contact.strip(),
                ),
                (
                    "RELEASE_LICENSE_UNRESOLVED",
                    "project license must be resolved before distribution",
                    config.license.strip().casefold() == "noassertion",
                ),
                (
                    "RELEASE_RUNTIME_UNTESTED",
                    "an explicit clean in-game test must pass before release",
                    config.runtime_status is not RuntimeStatus.PASSED,
                ),
                (
                    "RELEASE_NONCANONICAL_SKELETON",
                    "release projects must originate from a current game-generated skeleton "
                    "or an audited observed-consensus reconciliation",
                    config.skeleton is SkeletonSource.COMMUNITY_DRAFT,
                ),
                (
                    "RELEASE_PROVENANCE_UNREVIEWED",
                    "asset provenance and redistribution rights must be reviewed",
                    config.provenance_status is not ProvenanceStatus.REVIEWED,
                ),
                (
                    "RELEASE_PROVENANCE_NOTES_MISSING",
                    "a reviewed provenance status requires meaningful provenance notes",
                    config.provenance_status is ProvenanceStatus.REVIEWED
                    and len(config.provenance_notes.strip()) < 20,
                ),
                (
                    "RELEASE_SAVE_IMPACT_UNKNOWN",
                    "save impact must be explicitly assessed before release",
                    config.save_impact is SaveImpact.UNKNOWN,
                ),
                (
                    "RELEASE_ACHIEVEMENT_IMPACT_UNKNOWN",
                    "achievement impact must be explicitly assessed before release",
                    config.achievement_impact is AchievementImpact.UNKNOWN,
                ),
            ):
                if condition:
                    yield Issue(Severity.ERROR, code, message, self.layout.config_path)
            if config.skeleton is SkeletonSource.OBSERVED_CONSENSUS:
                yield from self._observed_consensus_issues(manifest)
            if config.runtime_status is RuntimeStatus.PASSED:
                yield from self._runtime_evidence_issues()
            source_entries: list[Path] = []
            try:
                source_entries = _bounded_tree_entries(self.layout.source_root)
                has_art_payload = any(
                    path.is_file() and path.suffix.casefold() == ".art"
                    for path in source_entries
                    if _is_within(path, self.layout.payload_root)
                )
            except ProjectError as exc:
                yield Issue(
                    Severity.ERROR,
                    "RELEASE_PAYLOAD_INSPECTION_FAILED",
                    f"cannot inspect achievement-impacting payload: {exc}",
                    self.layout.payload_root,
                )
                has_art_payload = False
            if has_art_payload and config.achievement_impact is not AchievementImpact.DISABLED:
                yield Issue(
                    Severity.ERROR,
                    "RELEASE_ACHIEVEMENTS_MUST_BE_DISABLED",
                    "ART payloads require achievement impact to be recorded as disabled",
                    self.layout.payload_root,
                )
            authoring_suffixes = {".blend", ".blend1", ".blend2", ".psd", ".xcf", ".kra"}
            for path in source_entries:
                if path.is_file() and path.suffix.casefold() in authoring_suffixes:
                    yield Issue(
                        Severity.ERROR,
                        "AUTHORING_FILE_IN_PAYLOAD",
                        "authoring source must remain outside the runtime source tree",
                        path,
                    )

    def _observed_consensus_issues(self, manifest: ManifestDocument | None) -> Iterable[Issue]:
        profile = _observed_consensus_profile(self.config.compatibility)
        if profile is None:
            yield Issue(
                Severity.ERROR,
                "RELEASE_CONSENSUS_PROFILE_UNSUPPORTED",
                "the observed-consensus profile does not support this exact game build",
                self.layout.config_path,
            )
            return
        evidence_path = self.layout.state_root / "import.json"
        try:
            if _is_link_like(evidence_path) or not evidence_path.is_file():
                raise ValueError("a regular .acmk/import.json record is required")
            payload = json.loads(
                _read_bounded(evidence_path, _legacy.MAX_TEXT_ASSET_BYTES).decode("utf-8")
            )
            if not isinstance(payload, dict):
                raise ValueError("evidence root must be an object")
            expected_keys = {
                "schema_version",
                "source",
                "consensus_profile",
                "manifest_sha256",
                "compatibility",
            }
            if set(payload) != expected_keys:
                raise ValueError("evidence fields do not match schema 2")
            if payload.get("schema_version") != _OBSERVED_CONSENSUS_IMPORT_SCHEMA_VERSION:
                raise ValueError("unsupported evidence schema")
            if payload.get("source") != SkeletonSource.OBSERVED_CONSENSUS.value:
                raise ValueError("evidence source does not match acmk.toml")
            if payload.get("consensus_profile") != profile:
                raise ValueError("evidence profile does not match this game build")
            manifest_sha256 = payload.get("manifest_sha256")
            if not _valid_sha256(manifest_sha256):
                raise ValueError("manifest_sha256 must be a lowercase SHA-256 digest")
            current_manifest_sha256 = _hash_file(
                self.layout.manifest,
                limit=_legacy.MAX_TEXT_ASSET_BYTES,
            )
            if manifest_sha256 != current_manifest_sha256:
                raise ValueError("manifest_sha256 does not match src/Index.art")
            if payload.get("compatibility") != _compatibility_dict(self.config.compatibility):
                raise ValueError("evidence compatibility does not match acmk.toml")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ProjectError) as exc:
            yield Issue(
                Severity.ERROR,
                "RELEASE_CONSENSUS_EVIDENCE_INVALID",
                f"observed-consensus evidence is invalid: {exc}",
                evidence_path,
            )
        if manifest is None or not _matches_observed_consensus_manifest(manifest, profile):
            yield Issue(
                Severity.ERROR,
                "RELEASE_CONSENSUS_MANIFEST_MISMATCH",
                "root Index.art no longer matches the audited Generic manifest structure",
                self.layout.manifest,
            )

    def _runtime_evidence_issues(self) -> Iterable[Issue]:
        path = self.layout.state_root / "runtime-test.json"
        try:
            if _is_link_like(path) or not path.is_file():
                yield Issue(
                    Severity.ERROR,
                    "RELEASE_RUNTIME_EVIDENCE_MISSING",
                    "passing runtime status requires a regular .acmk/runtime-test.json record",
                    path,
                )
                return
            payload = json.loads(_read_bounded(path, _legacy.MAX_TEXT_ASSET_BYTES).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("record root must be an object")
            schema_version = payload.get("schema_version")
            if (
                isinstance(schema_version, bool)
                or not isinstance(schema_version, int)
                or schema_version
                not in {*_LEGACY_RUNTIME_TEST_SCHEMA_VERSIONS, RUNTIME_TEST_SCHEMA_VERSION}
            ):
                raise ValueError("unsupported runtime-test schema")
            expected_root_keys = {
                "schema_version",
                "recorded_at",
                "runtime_status",
                "compatibility",
                "log_sha256",
                "log_summary",
                "source_fingerprint",
                "environment",
            }
            has_warning_baseline = "warning_baseline" in payload
            if schema_version == _RUNTIME_TEST_SCHEMA_V2 or (
                schema_version == RUNTIME_TEST_SCHEMA_VERSION and has_warning_baseline
            ):
                expected_root_keys.add("warning_baseline")
            if set(payload) != expected_root_keys:
                raise ValueError("record fields do not match the runtime-test schema")
            if payload.get("runtime_status") != RuntimeStatus.PASSED.value:
                raise ValueError("record does not describe a passing test")
            recorded_at = payload.get("recorded_at")
            if not isinstance(recorded_at, str):
                raise ValueError("recorded_at must be a string")
            parsed_time = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
            if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
                raise ValueError("recorded_at must include a timezone offset")
            log_sha256 = payload.get("log_sha256")
            if not _valid_sha256(log_sha256):
                raise ValueError("log_sha256 must be a SHA-256 digest")
            log_summary = payload.get("log_summary")
            if not isinstance(log_summary, dict):
                raise ValueError("log_summary must be an object")
            summary_keys = {"lines", "warnings", "errors_or_failures", "mods_enabled"}
            if set(log_summary) != summary_keys or any(
                not _nonnegative_int(log_summary.get(key)) for key in summary_keys
            ):
                raise ValueError("log_summary does not match the runtime-test schema")
            if (
                log_summary["lines"] == 0
                or log_summary["errors_or_failures"] != 0
                or log_summary["mods_enabled"] == 0
            ):
                raise ValueError("passing runtime evidence must contain a clean enabled-mod log")
            if not has_warning_baseline:
                if log_summary["warnings"] != 0:
                    raise ValueError(
                        "passing runtime evidence without a baseline must be warning-free"
                    )
            else:
                warning_baseline = payload.get("warning_baseline")
                baseline_keys = {
                    "algorithm",
                    "log_sha256",
                    "log_summary",
                    "ignored_warnings",
                    "unmatched_warnings",
                }
                if not isinstance(warning_baseline, dict) or set(warning_baseline) != baseline_keys:
                    raise ValueError("warning_baseline does not match the runtime-test schema")
                warning_baseline_algorithm = warning_baseline.get("algorithm")
                if warning_baseline_algorithm not in _SUPPORTED_WARNING_BASELINE_ALGORITHMS:
                    raise ValueError("unsupported warning baseline algorithm")
                if not _valid_sha256(warning_baseline.get("log_sha256")):
                    raise ValueError("warning baseline must contain a SHA-256 digest")
                baseline_summary = warning_baseline.get("log_summary")
                if not isinstance(baseline_summary, dict) or set(baseline_summary) != summary_keys:
                    raise ValueError("warning baseline summary does not match the schema")
                if any(not _nonnegative_int(baseline_summary.get(key)) for key in summary_keys):
                    raise ValueError("warning baseline summary counts must be non-negative")
                ignored_warnings = warning_baseline.get("ignored_warnings")
                unmatched_warnings = warning_baseline.get("unmatched_warnings")
                if not _nonnegative_int(ignored_warnings) or not _nonnegative_int(
                    unmatched_warnings
                ):
                    raise ValueError("warning baseline differential counts must be non-negative")
                if (
                    unmatched_warnings != 0
                    or ignored_warnings != log_summary["warnings"]
                    or (
                        warning_baseline_algorithm == _LEGACY_WARNING_BASELINE_ALGORITHM
                        and ignored_warnings > baseline_summary["warnings"]
                    )
                    or (ignored_warnings > 0 and baseline_summary["warnings"] == 0)
                ):
                    raise ValueError(
                        "passing runtime evidence contains warnings outside the baseline"
                    )
            expected_compatibility = {
                "game_version": self.config.compatibility.game_version,
                "game_semver": self.config.compatibility.game_semver,
                "steam_build_id": self.config.compatibility.steam_build_id,
                "content_hash": self.config.compatibility.content_hash,
            }
            if payload.get("compatibility") != expected_compatibility:
                raise ValueError("record compatibility differs from acmk.toml")
            environment = payload.get("environment")
            environment_keys = {
                "operating_system",
                "toolkit_version",
                "clean_launch",
                "save_type",
                "tested_mod",
                "observed_game_semver",
            }
            if schema_version == RUNTIME_TEST_SCHEMA_VERSION:
                environment_keys.add("save_persistence")
            if not isinstance(environment, dict) or set(environment) != environment_keys:
                raise ValueError("environment does not match the runtime-test schema")
            if (
                not isinstance(environment.get("operating_system"), str)
                or not environment["operating_system"].strip()
            ):
                raise ValueError("operating_system must be a non-empty string")
            if environment.get("toolkit_version") != __version__:
                raise ValueError("runtime evidence was recorded by a different toolkit version")
            if environment.get("clean_launch") is not True:
                raise ValueError("passing runtime evidence requires a clean launch")
            raw_save_type = environment.get("save_type")
            if not isinstance(raw_save_type, str):
                raise ValueError("runtime evidence has an invalid save type")
            try:
                recorded_save_type = RuntimeSaveType(raw_save_type)
            except (TypeError, ValueError) as exc:
                raise ValueError("runtime evidence has an invalid save type") from exc
            impact_problem = _save_impact_evidence_problem(
                self.config.save_impact, recorded_save_type
            )
            if impact_problem:
                raise ValueError(impact_problem)
            if schema_version == RUNTIME_TEST_SCHEMA_VERSION:
                raw_save_persistence = environment.get("save_persistence")
                if not isinstance(raw_save_persistence, str):
                    raise ValueError("runtime evidence has invalid save persistence")
                try:
                    recorded_save_persistence = SavePersistence(raw_save_persistence)
                except (TypeError, ValueError) as exc:
                    raise ValueError("runtime evidence has invalid save persistence") from exc
                persistence_problem = _save_persistence_evidence_problem(
                    recorded_save_type,
                    recorded_save_persistence,
                    passed=True,
                )
                if persistence_problem:
                    raise ValueError(persistence_problem)
            if environment.get("tested_mod") != self.config.name:
                raise ValueError("runtime log evidence does not identify this project title")
            if environment.get("observed_game_semver") != self.config.compatibility.game_semver:
                raise ValueError("runtime log evidence does not identify the recorded game version")
            raw_fingerprint = payload.get("source_fingerprint")
            if not isinstance(raw_fingerprint, dict):
                raise ValueError("source_fingerprint must be an object")
            if set(raw_fingerprint) != {"algorithm", "sha256", "files", "bytes"}:
                raise ValueError("source_fingerprint fields do not match the schema")
            expected_fingerprint_algorithm = (
                _LOOSE_MOD_FINGERPRINT_ALGORITHM
                if schema_version == RUNTIME_TEST_SCHEMA_VERSION
                else _LEGACY_SOURCE_FINGERPRINT_ALGORITHM
            )
            if raw_fingerprint.get("algorithm") != expected_fingerprint_algorithm:
                raise ValueError("unsupported source fingerprint algorithm")
            sha256 = raw_fingerprint.get("sha256")
            file_count = raw_fingerprint.get("files")
            byte_count = raw_fingerprint.get("bytes")
            if not _valid_sha256(sha256):
                raise ValueError("source fingerprint must contain a SHA-256 digest")
            if not _nonnegative_int(file_count) or not _nonnegative_int(byte_count):
                raise ValueError("source fingerprint counts must be non-negative integers")
            recorded = SourceFingerprint(
                sha256,
                file_count,
                byte_count,
                expected_fingerprint_algorithm,
            )
        except (
            ContractError,
            ProjectError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            yield Issue(
                Severity.ERROR,
                "RELEASE_RUNTIME_EVIDENCE_INVALID",
                f"runtime-test evidence is invalid: {exc}",
                path,
            )
            return
        try:
            current = (
                _capture_loose_mod_root(self.layout.source_root)[1]
                if schema_version == RUNTIME_TEST_SCHEMA_VERSION
                else _capture_source_tree(self.layout.source_root)[1]
            )
        except ProjectError as exc:
            yield Issue(
                Severity.ERROR,
                "RELEASE_RUNTIME_EVIDENCE_INVALID",
                f"cannot verify tested source: {exc}",
                self.layout.source_root,
            )
            return
        if current != recorded:
            yield Issue(
                Severity.ERROR,
                "RELEASE_SOURCE_CHANGED_AFTER_TEST",
                "canonical src differs from the tested loose-mod source fingerprint",
                self.layout.source_root,
                {"recorded": recorded.to_dict(), "current": current.to_dict()},
            )
        if schema_version in _LEGACY_RUNTIME_TEST_SCHEMA_VERSIONS:
            yield Issue(
                Severity.ERROR,
                "RELEASE_RUNTIME_EVIDENCE_MIGRATION_REQUIRED",
                f"runtime-test schema v{schema_version} predates explicit tested-source and "
                "save-persistence evidence; explicitly record a new v3 test",
                path,
                {
                    "recorded_schema_version": schema_version,
                    "required_schema_version": RUNTIME_TEST_SCHEMA_VERSION,
                },
            )


def _exact_child(root: Path, name: str, *, required: bool) -> Path | None:
    matches = [child for child in root.iterdir() if child.name.casefold() == name.casefold()]
    if len(matches) > 1:
        raise ProjectError(f"ambiguous case variants for {name}", code="ROOT_AMBIGUOUS", path=root)
    if not matches:
        if required:
            raise ProjectError(f"required skeleton entry {name} is missing", path=root / name)
        return None
    if matches[0].name != name:
        raise ProjectError(f"skeleton entry must be named exactly {name}", path=matches[0])
    return matches[0]


def _capture_source_tree(
    root: Path,
) -> tuple[tuple[FileSnapshot, ...], SourceFingerprint]:
    try:
        if _is_link_like(root) or not root.is_dir():
            raise ProjectError("runtime source must be a regular directory", path=root)
        candidates = _bounded_tree_entries(root)
    except OSError as exc:
        raise ProjectError(f"cannot enumerate runtime source: {exc}", path=root) from exc
    snapshots: list[FileSnapshot] = []
    folded: dict[str, str] = {}
    total = 0
    limit = _legacy.MAX_ZIP_TOTAL_BYTES + (2 * _legacy.MAX_TEXT_ASSET_BYTES)
    for path in candidates:
        try:
            if _is_link_like(path):
                raise ProjectError("symbolic links are not allowed in runtime sources", path=path)
            if path.is_dir():
                continue
            if not path.is_file():
                raise ProjectError("runtime source contains a non-regular entry", path=path)
        except OSError as exc:
            raise ProjectError(f"cannot inspect runtime source: {exc}", path=path) from exc
        relative = path.relative_to(root).as_posix()
        key = relative.casefold()
        if key in folded:
            raise ProjectError(
                f"case-insensitive source collision: {folded[key]} and {relative}",
                code="PATH_COLLISION",
                path=path,
            )
        folded[key] = relative
        snapshot = FileSnapshot.capture(path, relative)
        total += snapshot.size
        if total > limit:
            raise ProjectError(
                "runtime source exceeds the total size limit",
                code="SOURCE_RESOURCE_LIMIT",
                path=root,
            )
        snapshots.append(snapshot)
    digest = hashlib.sha256(b"ACMK-SOURCE-TREE-V1\0")
    for snapshot in snapshots:
        encoded_path = snapshot.relative_destination.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(snapshot.size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(snapshot.sha256))
    fingerprint = SourceFingerprint(
        digest.hexdigest(),
        len(snapshots),
        total,
        _LEGACY_SOURCE_FINGERPRINT_ALGORITHM,
    )
    return tuple(snapshots), fingerprint


def _capture_loose_mod_root(
    root: Path,
) -> tuple[tuple[FileSnapshot, ...], SourceFingerprint]:
    """Fingerprint exactly the loadable loose-mod surface, excluding empty ``Mod.hms``."""

    try:
        if _is_link_like(root) or not root.is_dir():
            raise ProjectError("tested source must be a regular loose-mod directory", path=root)
        top_level = list(root.iterdir())
    except OSError as exc:
        raise ProjectError(f"cannot inspect tested loose-mod source: {exc}", path=root) from exc
    top_names: dict[str, str] = {}
    for child in top_level:
        folded_name = child.name.casefold()
        if folded_name in top_names:
            raise ProjectError(
                f"case-insensitive source collision: {top_names[folded_name]} and {child.name}",
                code="PATH_COLLISION",
                path=child,
            )
        top_names[folded_name] = child.name
    required = {"Index.art", "Thumbnail.jpg", "Ancient"}
    missing = sorted(name for name in required if top_names.get(name.casefold()) != name)
    if missing:
        raise ProjectError(
            "tested loose-mod source is missing exact " + ", ".join(missing),
            code="TESTED_SOURCE_LAYOUT",
            path=root,
        )
    permitted = required | {"Mod.hms"}
    unexpected = sorted(child.name for child in top_level if child.name not in permitted)
    if unexpected:
        raise ProjectError(
            "tested loose-mod source contains unexpected root entries: " + ", ".join(unexpected),
            code="TESTED_SOURCE_LAYOUT",
            path=root,
        )
    ancient_root = root / "Ancient"
    try:
        for name in ("Index.art", "Thumbnail.jpg"):
            required_file = root / name
            if _is_link_like(required_file) or not required_file.is_file():
                raise ProjectError(
                    f"tested loose-mod {name} must be a regular file",
                    code="TESTED_SOURCE_LAYOUT",
                    path=required_file,
                )
        if _is_link_like(ancient_root) or not ancient_root.is_dir():
            raise ProjectError(
                "tested loose-mod Ancient entry must be a regular directory",
                code="TESTED_SOURCE_LAYOUT",
                path=ancient_root,
            )
        managed_state = root / "Mod.hms"
        if managed_state.exists():
            if _is_link_like(managed_state) or not managed_state.is_file():
                raise ProjectError(
                    "game-managed Mod.hms must be a regular file",
                    code="TESTED_SOURCE_LAYOUT",
                    path=managed_state,
                )
            if managed_state.stat().st_size != 0:
                raise ProjectError(
                    "only an empty game-managed Mod.hms may be excluded from the fingerprint",
                    code="TESTED_SOURCE_LAYOUT",
                    path=managed_state,
                )
        candidates = _bounded_tree_entries(root)
    except OSError as exc:
        raise ProjectError(f"cannot enumerate tested loose-mod source: {exc}", path=root) from exc
    snapshots: list[FileSnapshot] = []
    folded: dict[str, str] = {}
    total = 0
    limit = _legacy.MAX_ZIP_TOTAL_BYTES + (2 * _legacy.MAX_TEXT_ASSET_BYTES)
    for path in candidates:
        try:
            if _is_link_like(path):
                raise ProjectError(
                    "symbolic links are not allowed in tested loose-mod sources", path=path
                )
            if path.is_dir():
                continue
            if not path.is_file():
                raise ProjectError(
                    "tested loose-mod source contains a non-regular entry", path=path
                )
        except OSError as exc:
            raise ProjectError(f"cannot inspect tested source: {exc}", path=path) from exc
        relative = path.relative_to(root).as_posix()
        if relative == "Mod.hms":
            continue
        if relative not in {"Index.art", "Thumbnail.jpg"} and not relative.startswith("Ancient/"):
            raise ProjectError(
                f"tested loose-mod source contains an out-of-scope file: {relative}",
                code="TESTED_SOURCE_LAYOUT",
                path=path,
            )
        key = relative.casefold()
        if key in folded:
            raise ProjectError(
                f"case-insensitive source collision: {folded[key]} and {relative}",
                code="PATH_COLLISION",
                path=path,
            )
        folded[key] = relative
        snapshot = FileSnapshot.capture(path, relative)
        total += snapshot.size
        if total > limit:
            raise ProjectError(
                "tested loose-mod source exceeds the total size limit",
                code="SOURCE_RESOURCE_LIMIT",
                path=root,
            )
        snapshots.append(snapshot)
    snapshots.sort(key=lambda snapshot: snapshot.relative_destination)
    digest = hashlib.sha256(b"ACMK-LOOSE-MOD-TREE-V1\0")
    for snapshot in snapshots:
        encoded_path = snapshot.relative_destination.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(snapshot.size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(snapshot.sha256))
    fingerprint = SourceFingerprint(digest.hexdigest(), len(snapshots), total)
    return tuple(snapshots), fingerprint


def _assert_context_matches(
    context: _legacy.DiscoveryContext,
    compatibility: Compatibility,
) -> None:
    live = {
        "GameVersion": context.game_version,
        "game version": context.semver,
        "Steam build": context.build_id,
        "content hash": context.content_hash,
    }
    recorded = {
        "GameVersion": compatibility.game_version,
        "game version": compatibility.game_semver,
        "Steam build": compatibility.steam_build_id,
        "content hash": compatibility.content_hash,
    }
    for label, current in live.items():
        if not current:
            raise ProjectError(f"cannot continue without a live {label}")
        if current != recorded[label]:
            raise ProjectError(f"cannot continue against a stale {label}")


def _analyse_runtime_log(
    text: str,
    *,
    project_name: str,
    game_semver: str,
    achievement_impact: AchievementImpact = AchievementImpact.UNKNOWN,
) -> tuple[dict[str, Any], bool, bool]:
    summary = dict(_legacy.summarise_log(text))
    expected_title = project_name.casefold()
    target_enabled = False
    for line in text.splitlines():
        if "Enabling Mod:" not in line:
            continue
        entry = line.split("Enabling Mod:", 1)[1].strip()
        trailing_title = re.search(r"\(([^()]*)\)\s*$", entry)
        candidates = [entry]
        if trailing_title is not None:
            candidates.append(trailing_title.group(1).strip())
        if any(candidate.casefold() == expected_title for candidate in candidates):
            target_enabled = True
            break
    marker = re.compile(
        rf"Ancient Cities\.{re.escape(game_semver)}(?![0-9A-Za-z.])",
        re.IGNORECASE,
    )
    game_version_observed = any(marker.search(line) is not None for line in text.splitlines())
    if target_enabled and achievement_impact is AchievementImpact.DISABLED:
        expected_achievement_warnings = sum(
            _is_expected_achievement_warning(line, project_name)
            for line in _normalised_warning_lines(text)
        )
        summary["warnings"] = max(
            0,
            int(summary.get("warnings", 0)) - expected_achievement_warnings,
        )
    return summary, target_enabled, game_version_observed


def _runtime_blockers(
    summary: Mapping[str, Any],
    *,
    target_enabled: bool,
    game_version_observed: bool,
    clean_launch: bool,
    project_name: str,
    game_semver: str,
    unmatched_warnings: int | None = None,
) -> list[str]:
    failures = int(summary.get("errors_or_failures", 0))
    warnings = int(summary.get("warnings", 0)) if unmatched_warnings is None else unmatched_warnings
    lines = int(summary.get("lines", 0))
    mods_enabled = int(summary.get("mods_enabled", 0))
    blockers: list[str] = []
    if failures:
        blockers.append(f"{failures} errors or failures")
    if warnings:
        suffix = " not present in the warning baseline" if unmatched_warnings is not None else ""
        blockers.append(f"{warnings} warnings{suffix}")
    if lines == 0:
        blockers.append("no log lines")
    if mods_enabled == 0:
        blockers.append("no enabled mod entry")
    elif not target_enabled:
        blockers.append(f"no exact enabled entry for {project_name!r}")
    if not game_version_observed:
        blockers.append(f"no exact game-version marker for {game_semver!r}")
    if not clean_launch:
        blockers.append("clean-launch confirmation is missing")
    return blockers


def _warning_differential(
    runtime_text: str,
    baseline_text: str,
    *,
    project_name: str = "",
    allow_achievement_warning: bool = False,
) -> tuple[int, int]:
    """Return baseline-signature-matched and remaining runtime warning occurrences."""

    runtime_warnings = tuple(
        warning
        for warning in _normalised_warning_lines(runtime_text)
        if not (
            allow_achievement_warning and _is_expected_achievement_warning(warning, project_name)
        )
    )
    baseline_signatures = set(_normalised_warning_lines(baseline_text))
    ignored = sum(warning in baseline_signatures for warning in runtime_warnings)
    return ignored, len(runtime_warnings) - ignored


def _is_expected_achievement_warning(normalized_line: str, project_name: str) -> bool:
    """Match only Ancient Cities' normal ART/achievement notification for this project."""

    if not project_name:
        return False
    pattern = re.compile(
        r"Warning - This enabled Mod has \*\.art files that disables Achievements: "
        rf"\[[^\[\]\r\n]+\] \({re.escape(project_name)}\)"
    )
    return pattern.fullmatch(normalized_line) is not None


def _normalised_warning_lines(text: str) -> Iterable[str]:
    for line in text.splitlines():
        if re.search(r"\bwarning\b", line, re.IGNORECASE) is None:
            continue
        without_timestamp = re.sub(
            r"^\s*\[\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\]\s*",
            "",
            line,
            count=1,
        )
        normalized = without_timestamp.strip()
        normalized = re.sub(
            r"^(Warning - )\[\d+\](?=\s)",
            r"\1[#]",
            normalized,
            count=1,
        )
        yield normalized


def _save_impact_evidence_problem(
    save_impact: SaveImpact, save_type: RuntimeSaveType
) -> str | None:
    if (
        save_impact is SaveImpact.NONE_OBSERVED
        and save_type is not RuntimeSaveType.EXISTING_DISPOSABLE
    ):
        return "save impact 'none-observed' requires an existing-disposable save test"
    return None


def _save_persistence_evidence_problem(
    save_type: RuntimeSaveType,
    save_persistence: SavePersistence,
    *,
    passed: bool,
) -> str | None:
    if save_type is RuntimeSaveType.NO_SAVE:
        if save_persistence is not SavePersistence.NOT_APPLICABLE:
            return "save type 'no-save' requires save persistence 'not-applicable'"
        return None
    if save_persistence is SavePersistence.NOT_APPLICABLE:
        return "disposable save tests cannot use save persistence 'not-applicable'"
    if passed and save_persistence is not SavePersistence.MANUAL_SAVE_RELOAD_PASSED:
        return "passing new/existing-disposable save evidence requires 'manual-save-reload-passed'"
    return None


def _observed_consensus_profile(compatibility: Compatibility) -> str | None:
    key = (
        compatibility.game_version,
        compatibility.game_semver,
        compatibility.steam_build_id,
        compatibility.content_hash.upper(),
    )
    return _OBSERVED_CONSENSUS_PROFILES.get(key)


def _compatibility_dict(compatibility: Compatibility) -> dict[str, str]:
    return {
        "game_version": compatibility.game_version,
        "game_semver": compatibility.game_semver,
        "steam_build_id": compatibility.steam_build_id,
        "content_hash": compatibility.content_hash,
    }


def _observed_manifest_fields(manifest: ManifestDocument, profile: str) -> Mapping[str, str]:
    if profile not in _OBSERVED_CONSENSUS_PROFILES.values():
        raise ProjectError(
            "unsupported observed-consensus profile", code="CONSENSUS_PROFILE_UNSUPPORTED"
        )
    expected_kinds = {
        "Changelog": "String",
        "Content": "String",
        "Description": "String",
        "GameVersion": "String",
        "SteamModId": "U32x2",
        "Title": "String",
        "Type": "String",
    }
    if manifest.duplicates or set(manifest.fields) != set(expected_kinds):
        raise ProjectError(
            "root manifest must contain exactly the seven audited Generic fields",
            code="CONSENSUS_MANIFEST_MISMATCH",
        )
    if dict(manifest.kinds) != expected_kinds:
        raise ProjectError(
            "root manifest field types differ from the audited Generic profile",
            code="CONSENSUS_MANIFEST_MISMATCH",
        )
    fields = manifest.fields
    for name in ("Changelog", "Description", "Title"):
        if not fields[name].strip():
            raise ProjectError(
                f"root manifest {name} cannot be empty",
                code="CONSENSUS_MANIFEST_MISMATCH",
            )
    if fields["GameVersion"] != "22" or fields["Type"] != "Generic":
        raise ProjectError(
            "root manifest must target Generic GameVersion 22",
            code="CONSENSUS_MANIFEST_MISMATCH",
        )
    try:
        steam_mod_id = _legacy.normalise_steam_mod_id(fields["SteamModId"], allow_single=False)
    except _legacy.ModToolError as exc:
        raise ProjectError(
            f"invalid root manifest SteamModId: {exc}",
            code="CONSENSUS_MANIFEST_MISMATCH",
        ) from exc
    if steam_mod_id != fields["SteamModId"]:
        raise ProjectError(
            "root manifest SteamModId must use canonical U32x2 formatting",
            code="CONSENSUS_MANIFEST_MISMATCH",
        )
    return fields


def _render_observed_consensus_manifest(manifest: ManifestDocument, profile: str) -> bytes:
    fields = _observed_manifest_fields(manifest, profile)
    try:
        text = _legacy.canonical_manifest(
            title=fields["Title"],
            description=fields["Description"],
            changelog=fields["Changelog"],
            game_version=fields["GameVersion"],
            mod_type=fields["Type"],
            steam_mod_id=fields["SteamModId"],
            content=None,
        )
        data = _legacy.encode_utf16le_art(text)
    except _legacy.ModToolError as exc:
        raise ProjectError(str(exc), code="CONSENSUS_MANIFEST_MISMATCH") from exc
    rendered = ManifestDocument.from_bytes(data)
    if not _matches_observed_consensus_manifest(rendered, profile, allow_content_value=False):
        raise ContractError("internal observed-consensus renderer violated its profile")
    return data


def _reconciled_observed_consensus_manifest(
    manifest: ManifestDocument,
    profile: str,
    *,
    preserve_canonical: bool,
) -> bytes:
    if preserve_canonical and _matches_observed_consensus_manifest(manifest, profile):
        return manifest.to_bytes()
    return _render_observed_consensus_manifest(manifest, profile)


def _matches_observed_consensus_manifest(
    manifest: ManifestDocument,
    profile: str,
    *,
    allow_content_value: bool = True,
) -> bool:
    try:
        fields = _observed_manifest_fields(manifest, profile)
        content_variants: tuple[str | None, ...] = (
            (None, fields["Content"]) if allow_content_value else (None,)
        )
        for content in content_variants:
            text = _legacy.canonical_manifest(
                title=fields["Title"],
                description=fields["Description"],
                changelog=fields["Changelog"],
                game_version=fields["GameVersion"],
                mod_type=fields["Type"],
                steam_mod_id=fields["SteamModId"],
                content=content,
            )
            if manifest.to_bytes() == _legacy.encode_utf16le_art(text):
                return True
    except (ContractError, ProjectError, _legacy.ModToolError):
        return False
    return False


def _observed_consensus_evidence_bytes(
    config: ProjectConfig, profile: str, manifest_sha256: str
) -> bytes:
    if config.skeleton is not SkeletonSource.OBSERVED_CONSENSUS:
        raise ContractError("observed-consensus evidence requires the matching source label")
    if _observed_consensus_profile(config.compatibility) != profile:
        raise ContractError("observed-consensus evidence uses an unsupported profile")
    if not _valid_sha256(manifest_sha256):
        raise ContractError("observed-consensus manifest hash is invalid")
    record = {
        "schema_version": _OBSERVED_CONSENSUS_IMPORT_SCHEMA_VERSION,
        "source": SkeletonSource.OBSERVED_CONSENSUS.value,
        "consensus_profile": profile,
        "manifest_sha256": manifest_sha256,
        "compatibility": _compatibility_dict(config.compatibility),
    }
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _hash_file(path: Path, *, limit: int | None = None) -> str:
    return _hash_file_and_size(path, limit=limit)[0]


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise ProjectError(f"cannot read file: {exc}", path=path) from exc
    if len(data) > limit:
        raise ProjectError(f"file exceeds the {limit}-byte limit", path=path)
    return data


def _bounded_tree_entries(root: Path) -> list[Path]:
    try:
        return _legacy._bounded_tree_entries(root, limit=_legacy.MAX_ZIP_FILES)
    except _legacy.ModToolError as exc:
        raise ProjectError(str(exc), code="SOURCE_RESOURCE_LIMIT", path=root) from exc


def _is_within(path: Path, root: Path) -> bool:
    lexical_path = _lexical_absolute(path)
    lexical_root = _lexical_absolute(root)
    try:
        lexical_path.relative_to(lexical_root)
        return True
    except ValueError:
        pass
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _hash_file_and_size(path: Path, *, limit: int | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                if limit is not None and size > limit:
                    raise ProjectError(f"file exceeds the {limit}-byte limit", path=path)
                digest.update(chunk)
    except OSError as exc:
        raise ProjectError(f"cannot hash file: {exc}", path=path) from exc
    return digest.hexdigest(), size


def _valid_sha256(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _nonnegative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_link_like(path: Path) -> bool:
    return _legacy.path_is_link_like(path)


def _assert_no_link_components(path: Path, boundary: Path) -> None:
    lexical_path = _lexical_absolute(path)
    lexical_boundary = _lexical_absolute(boundary)
    try:
        relative = lexical_path.relative_to(lexical_boundary)
    except ValueError as exc:
        raise ProjectError(
            "project path escapes its lexical root", code="UNSAFE_PATH", path=lexical_path
        ) from exc
    components = [lexical_boundary]
    current = lexical_boundary
    for part in relative.parts:
        current = current / part
        components.append(current)
    try:
        linked = next((component for component in components if _is_link_like(component)), None)
    except OSError as exc:
        raise ProjectError(
            f"cannot inspect project path components: {exc}", path=lexical_path
        ) from exc
    if linked is not None:
        raise ProjectError(
            "project paths must not traverse symbolic links or junctions",
            code="PROJECT_PATH_LINK",
            path=linked,
        )
    try:
        resolved_path = lexical_path.resolve(strict=False)
        resolved_boundary = lexical_boundary.resolve(strict=False)
        resolved_path.relative_to(resolved_boundary)
    except OSError as exc:
        raise ProjectError(
            f"cannot resolve project path components: {exc}", path=lexical_path
        ) from exc
    except ValueError as exc:
        raise ProjectError(
            "project path resolves outside its permitted root",
            code="UNSAFE_PATH",
            path=lexical_path,
        ) from exc


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _rollback_runtime_record(
    *,
    config_path: Path,
    original_config: bytes,
    written_config: bytes,
    record_path: Path,
    original_record: bytes | None,
    written_record: bytes,
) -> list[str]:
    return _rollback_files(
        (
            ("acmk.toml", config_path, original_config, written_config),
            ("runtime-test.json", record_path, original_record, written_record),
        )
    )


def _rollback_files(files: Iterable[tuple[str, Path, bytes | None, bytes]]) -> list[str]:
    errors: list[str] = []
    for label, path, original, written in files:
        try:
            if not path.exists():
                if original is not None:
                    _legacy._atomic_write(path, original)
                continue
            current = _read_bounded(path, max(len(written), len(original or b"")) + 1)
            if hashlib.sha256(current).digest() != hashlib.sha256(written).digest():
                if current != original:
                    errors.append(f"{label} changed concurrently")
                continue
            if original is None:
                path.unlink()
            else:
                _legacy._atomic_write(path, original)
        except (OSError, ProjectError, _legacy.ModToolError) as exc:
            errors.append(f"cannot restore {label}: {exc}")
    return errors


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ProjectError(f"cannot create {path}: {exc}", path=path) from exc


def _create_state_backup(
    source: Path,
    data: bytes,
    backup_root: Path,
    *,
    boundary: Path,
) -> Path:
    _assert_no_link_components(backup_root, boundary)
    backup_root.mkdir(parents=True, exist_ok=True)
    _assert_no_link_components(backup_root, boundary)
    destination = _next_backup(backup_root / source.name)
    _assert_no_link_components(destination, boundary)
    _write_new(destination, data)
    return destination


def _safe_destination(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ProjectError(f"unsafe planned destination {relative!r}")
    destination = root.joinpath(*pure.parts).resolve(strict=False)
    try:
        destination.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ProjectError(f"planned destination escapes root: {relative!r}") from exc
    return destination


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _next_backup(path: Path) -> Path:
    index = 0
    while True:
        suffix = ".bak" if index == 0 else f".bak.{index}"
        candidate = path.with_name(path.name + suffix)
        if not candidate.exists() and not _is_link_like(candidate):
            return candidate
        index += 1


def _remove_temporary_tree(path: Path) -> None:
    if not path.exists():
        return
    # Only SDK-created temp directories with a fixed prefix are eligible.
    if not (path.name.startswith("acmk-release-") or ".acmk-import-" in path.name):
        raise ProjectError(f"refusing to remove unexpected temporary path {path}")
    shutil.rmtree(path)

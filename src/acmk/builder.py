"""Dry-run-first builders for explicitly noncanonical draft projects."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ancient_cities_mod as _legacy

from .config import (
    AchievementImpact,
    Compatibility,
    ProjectConfig,
    RuntimeStatus,
    SaveImpact,
    SkeletonSource,
)
from .errors import ContractError, ProjectError
from .manifest import ManifestDocument, ManifestSpec, TextAssetKind, Utf16TextDocument
from .paths import AncientPath
from .project import ProjectLayout, SDKProject
from .reports import ExecutionMode


@dataclass(frozen=True, slots=True)
class PlannedContent:
    path: AncientPath
    data: bytes
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, AncientPath) or not isinstance(self.data, bytes):
            raise ContractError("planned content requires an AncientPath and immutable bytes")
        if len(self.data) > _legacy.MAX_ZIP_MEMBER_BYTES:
            raise ProjectError("planned payload exceeds the per-file resource limit")
        if self.path.suffix.casefold() in _legacy.EXECUTABLE_EXTENSIONS:
            raise ProjectError("executable payload content is forbidden")
        if self.path.suffix.casefold() in {".art", ".loc"}:
            kind = TextAssetKind.ART if self.path.suffix.casefold() == ".art" else TextAssetKind.LOC
            Utf16TextDocument.from_bytes(self.data, kind=kind)
        expected = hashlib.sha256(self.data).hexdigest()
        if self.sha256 != expected:
            raise ContractError("planned content SHA-256 does not match its bytes")

    @classmethod
    def create(cls, path: AncientPath, data: bytes) -> PlannedContent:
        if len(data) > _legacy.MAX_ZIP_MEMBER_BYTES:
            raise ProjectError("planned payload exceeds the per-file resource limit")
        return cls(path, bytes(data), hashlib.sha256(data).hexdigest())


@dataclass(frozen=True, slots=True)
class DraftProjectResult:
    mode: ExecutionMode
    project_root: Path
    files: tuple[str, ...]
    warning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "project_root": str(self.project_root),
            "files": list(self.files),
            "warning": self.warning,
        }


@dataclass(frozen=True, slots=True)
class DraftProjectPlan:
    target: Path
    config: ProjectConfig
    manifest: bytes
    contents: tuple[PlannedContent, ...]
    thumbnail: bytes | None
    context: _legacy.DiscoveryContext
    context_refresher: Callable[[], _legacy.DiscoveryContext] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, Path):
            raise ContractError("draft target must be a pathlib.Path")
        if not isinstance(self.config, ProjectConfig):
            raise ContractError("draft config must be a ProjectConfig")
        if self.config.skeleton is not SkeletonSource.COMMUNITY_DRAFT:
            raise ContractError("draft plans must remain labelled community-draft")
        if (
            self.config.runtime_status is not RuntimeStatus.UNTESTED
            or self.config.save_impact is not SaveImpact.UNKNOWN
            or self.config.achievement_impact is not AchievementImpact.UNKNOWN
        ):
            raise ContractError("draft plans cannot pre-claim runtime or impact evidence")
        if not isinstance(self.manifest, bytes):
            raise ContractError("draft manifest must be immutable bytes")
        manifest = ManifestDocument.from_bytes(self.manifest)
        if manifest.duplicates:
            raise ContractError("draft manifest cannot contain duplicate fields")
        expected_fields = {
            "Title": self.config.name,
            "Type": self.config.mod_type,
            "GameVersion": self.config.compatibility.game_version,
        }
        for name, expected in expected_fields.items():
            if manifest.fields.get(name) != expected:
                raise ContractError(f"draft manifest {name} does not match its config")
        if not isinstance(self.contents, tuple) or any(
            not isinstance(item, PlannedContent) for item in self.contents
        ):
            raise ContractError("draft contents must be PlannedContent values")
        folded = [item.path.value.casefold() for item in self.contents]
        if len(folded) != len(set(folded)):
            raise ContractError("draft plan contains case-insensitive duplicate paths")
        if len(self.contents) + 3 > _legacy.MAX_ZIP_FILES:
            raise ProjectError("draft plan exceeds the payload entry limit")
        if self.thumbnail is not None:
            if not isinstance(self.thumbnail, bytes):
                raise ContractError("draft thumbnail must be immutable bytes")
            if len(self.thumbnail) > _legacy.MAX_ZIP_MEMBER_BYTES:
                raise ProjectError("draft thumbnail exceeds the per-file resource limit")
            problem = _legacy._signature_problem("Thumbnail.jpg", self.thumbnail)
            dimensions = _legacy.jpeg_dimensions(self.thumbnail)
            if problem is not None or dimensions is None or dimensions[0] != dimensions[1]:
                raise ProjectError("draft thumbnail must be a valid square JPEG")
        total = len(self.manifest) + sum(len(item.data) for item in self.contents)
        if self.thumbnail is not None:
            total += len(self.thumbnail)
        if total > _legacy.MAX_ZIP_TOTAL_BYTES:
            raise ProjectError("draft plan exceeds the total payload limit")
        if not isinstance(self.context, _legacy.DiscoveryContext):
            raise ContractError("draft context must be a DiscoveryContext")
        if self.context_refresher is not None and not callable(self.context_refresher):
            raise ContractError("draft context_refresher must be callable")

    @property
    def planned_files(self) -> tuple[str, ...]:
        base = ["acmk.toml", "src/Index.art"]
        if self.thumbnail is not None:
            base.append("src/Thumbnail.jpg")
        base.extend(f"src/{item.path.value}" for item in self.contents)
        return tuple(base)

    def preview(self) -> DraftProjectResult:
        return DraftProjectResult(
            ExecutionMode.DRY_RUN,
            self.target,
            self.planned_files,
            _DRAFT_WARNING,
        )

    def apply(self) -> DraftProjectResult:
        target = Path(os.path.abspath(os.fspath(self.target.expanduser())))
        active_context = (
            self.context_refresher() if self.context_refresher is not None else self.context
        )
        _assert_draft_context(active_context, self.config.compatibility)
        _legacy.assert_no_symlink_components(target)
        _legacy.assert_writable_project_path(target, active_context)
        if target.exists():
            raise ProjectError(
                "draft target must not already exist", code="TARGET_EXISTS", path=target
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.acmk-draft-", dir=target.parent))
        try:
            layout = ProjectLayout(staging, self.config)
            layout.payload_root.mkdir(parents=True)
            layout.assets_root.mkdir(parents=True)
            layout.state_root.mkdir(parents=True)
            layout.distribution_root.parent.mkdir(parents=True)
            _write(layout.config_path, self.config.to_toml().encode("utf-8"))
            _write(staging / ".gitignore", b".acmk/\ndist/\n")
            _write(layout.manifest, self.manifest)
            if self.thumbnail is not None:
                _write(layout.thumbnail, self.thumbnail)
            for content in self.contents:
                if hashlib.sha256(content.data).hexdigest() != content.sha256:
                    raise ProjectError("planned in-memory content changed", code="SOURCE_CHANGED")
                _write(content.path.on_disk(layout.source_root), content.data)
            staged_report = _legacy.validate_target(
                layout.source_root, active_context, check_archive=False
            )
            staged_errors = [
                str(issue.get("code"))
                for issue in staged_report.get("issues", [])
                if issue.get("severity") == "error"
            ]
            if staged_errors:
                raise ProjectError(
                    "draft validation failed after staging: " + ", ".join(staged_errors),
                    path=layout.source_root,
                )
            os.replace(staging, target)
        except BaseException:
            if staging.exists() and ".acmk-draft-" in staging.name:
                shutil.rmtree(staging)
            raise
        return DraftProjectResult(ExecutionMode.APPLY, target, self.planned_files, _DRAFT_WARNING)

    def open(self) -> SDKProject:
        active_context = (
            self.context_refresher() if self.context_refresher is not None else self.context
        )
        return SDKProject.open(
            self.target,
            context=active_context,
            context_refresher=self.context_refresher,
        )


class DraftProjectBuilder:
    """Build an isolated SDK draft when no game-generated skeleton is available.

    This builder intentionally labels the project ``community-draft``. Passing all
    static checks does not make the output canonical or engine-compatible.
    """

    def __init__(
        self,
        target: str | os.PathLike[str],
        *,
        identifier: str,
        manifest: ManifestSpec,
        context: _legacy.DiscoveryContext,
        version: str = "0.1.0",
        license: str = "NOASSERTION",
        contact: str = "",
        context_refresher: Callable[[], _legacy.DiscoveryContext] | None = None,
    ) -> None:
        self._target = Path(target)
        self._manifest = manifest
        self._context = context
        self._context_refresher = context_refresher
        self._config = ProjectConfig(
            identifier=identifier,
            name=manifest.title,
            version=version,
            mod_type=manifest.mod_type,
            license=license,
            contact=contact,
            skeleton=SkeletonSource.COMMUNITY_DRAFT,
            compatibility=Compatibility(
                game_version=str(manifest.game_version),
                game_semver=context.semver or "",
                steam_build_id=context.build_id or "",
                content_hash=context.content_hash or "",
            ),
        )
        self._contents: dict[str, PlannedContent] = {}
        self._thumbnail: bytes | None = None

    def add_art(self, path: str | AncientPath, text: str) -> DraftProjectBuilder:
        return self._add_text(path, text, TextAssetKind.ART)

    def add_localization(self, path: str | AncientPath, text: str) -> DraftProjectBuilder:
        return self._add_text(path, text, TextAssetKind.LOC)

    def add_binary(self, path: str | AncientPath, data: bytes) -> DraftProjectBuilder:
        content_path = path if isinstance(path, AncientPath) else AncientPath.from_payload(path)
        suffix = content_path.suffix.casefold()
        if suffix in {".art", ".loc"}:
            raise ProjectError("use add_art or add_localization so UTF-16LE is enforced")
        if suffix in _legacy.EXECUTABLE_EXTENSIONS:
            raise ProjectError("executable payload content is forbidden")
        self._insert(PlannedContent.create(content_path, data))
        return self

    def add_file(
        self, path: str | AncientPath, source: str | os.PathLike[str]
    ) -> DraftProjectBuilder:
        source_path = Path(source)
        if _legacy.path_is_link_like(source_path) or not source_path.is_file():
            raise ProjectError("asset source must be a regular, non-symlink file", path=source_path)
        try:
            data = _legacy._read_file_bounded(source_path, _legacy.MAX_ZIP_MEMBER_BYTES)
        except (OSError, _legacy.ModToolError) as exc:
            raise ProjectError(f"cannot read {source_path}: {exc}", path=source_path) from exc
        return self.add_binary(path, data)

    def set_thumbnail(self, data: bytes) -> DraftProjectBuilder:
        if len(data) > _legacy.MAX_ZIP_MEMBER_BYTES:
            raise ProjectError("thumbnail exceeds the per-file resource limit")
        problem = _legacy._signature_problem("Thumbnail.jpg", data)
        dimensions = _legacy.jpeg_dimensions(data)
        if problem is not None or dimensions is None:
            raise ProjectError("thumbnail must be a valid JPEG with readable dimensions")
        if dimensions[0] != dimensions[1]:
            raise ProjectError("thumbnail must be square")
        self._thumbnail = bytes(data)
        return self

    def plan(self) -> DraftProjectPlan:
        manifest = self._manifest.render().to_bytes()
        total = len(manifest) + sum(len(item.data) for item in self._contents.values())
        if self._thumbnail is not None:
            total += len(self._thumbnail)
        if total > _legacy.MAX_ZIP_TOTAL_BYTES:
            raise ProjectError("planned payload exceeds the total resource limit")
        return DraftProjectPlan(
            target=self._target,
            config=self._config,
            manifest=manifest,
            contents=tuple(
                sorted(self._contents.values(), key=lambda item: item.path.value.casefold())
            ),
            thumbnail=self._thumbnail,
            context=self._context,
            context_refresher=self._context_refresher,
        )

    def _add_text(
        self, path: str | AncientPath, text: str, kind: TextAssetKind
    ) -> DraftProjectBuilder:
        content_path = path if isinstance(path, AncientPath) else AncientPath.from_payload(path)
        expected = ".art" if kind is TextAssetKind.ART else ".loc"
        if content_path.suffix.casefold() != expected:
            raise ProjectError(f"{kind.value} content path must end in {expected}")
        document = Utf16TextDocument.from_text(text, kind=kind)
        self._insert(PlannedContent.create(content_path, document.to_bytes()))
        return self

    def _insert(self, content: PlannedContent) -> None:
        key = content.path.value.casefold()
        if key in self._contents:
            message = (
                "case-insensitive duplicate payload path: "
                f"{self._contents[key].path} and {content.path}"
            )
            raise ProjectError(
                message,
                code="PATH_COLLISION",
            )
        self._contents[key] = content


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except OSError as exc:
        raise ProjectError(f"cannot create {path}: {exc}", path=path) from exc


def _assert_draft_context(context: _legacy.DiscoveryContext, compatibility: Compatibility) -> None:
    for label, current, recorded in (
        ("GameVersion", context.game_version, compatibility.game_version),
        ("game version", context.semver, compatibility.game_semver),
        ("Steam build", context.build_id, compatibility.steam_build_id),
        ("content hash", context.content_hash, compatibility.content_hash),
    ):
        if current and current != recorded:
            raise ProjectError(f"draft plan targets a stale {label}")


_DRAFT_WARNING = (
    "This is a noncanonical community draft. Import a current in-game generated skeleton "
    "and complete an authorized clean runtime test before claiming compatibility."
)

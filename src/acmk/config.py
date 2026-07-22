"""Versioned ``acmk.toml`` project model."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from ._version import PROJECT_SCHEMA_VERSION
from .errors import ContractError
from .paths import ProjectRelativePath

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,63}\Z")
_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    rf"(?:-{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
_ASCII_DIGITS = re.compile(r"[0-9]+\Z")
MAX_PROJECT_CONFIG_BYTES = 1024 * 1024
_LICENSE_EXPRESSION = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9.+-]*(?: (?:AND|OR|WITH) [A-Za-z0-9][A-Za-z0-9.+-]*)*\Z"
)


class SkeletonSource(StrEnum):
    GAME_GENERATED = "game-generated"
    OBSERVED_CONSENSUS = "observed-consensus"
    COMMUNITY_DRAFT = "community-draft"


class RuntimeStatus(StrEnum):
    UNTESTED = "untested"
    PASSED = "passed"
    FAILED = "failed"


class SaveImpact(StrEnum):
    UNKNOWN = "unknown"
    NONE_OBSERVED = "none-observed"
    NEW_SAVE_RECOMMENDED = "new-save-recommended"
    NEW_SAVE_REQUIRED = "new-save-required"


class AchievementImpact(StrEnum):
    UNKNOWN = "unknown"
    DISABLED = "disabled"
    NONE_OBSERVED = "none-observed"


class ProvenanceStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"


class RuntimeSaveType(StrEnum):
    NEW_DISPOSABLE = "new-disposable"
    EXISTING_DISPOSABLE = "existing-disposable"
    NO_SAVE = "no-save"


class SavePersistence(StrEnum):
    MANUAL_SAVE_RELOAD_PASSED = "manual-save-reload-passed"
    FAILED = "failed"
    NOT_TESTED = "not-tested"
    NOT_APPLICABLE = "not-applicable"


@dataclass(frozen=True, slots=True)
class Compatibility:
    game_version: str
    game_semver: str = ""
    steam_build_id: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str)
            for value in (
                self.game_version,
                self.game_semver,
                self.steam_build_id,
                self.content_hash,
            )
        ):
            raise ContractError("compatibility values must be strings")
        if not _ASCII_DIGITS.fullmatch(self.game_version):
            raise ContractError("compatibility.game_version must contain ASCII digits")
        if self.steam_build_id and not _ASCII_DIGITS.fullmatch(self.steam_build_id):
            raise ContractError("compatibility.steam_build_id must contain ASCII digits")
        if self.content_hash and not re.fullmatch(r"[0-9A-Fa-f]+", self.content_hash):
            raise ContractError("compatibility.content_hash must be hexadecimal")


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    source: ProjectRelativePath = ProjectRelativePath("src")
    assets: ProjectRelativePath = ProjectRelativePath("assets-src")
    state: ProjectRelativePath = ProjectRelativePath(".acmk")
    distribution: ProjectRelativePath = ProjectRelativePath("dist/workshop")

    def __post_init__(self) -> None:
        if any(
            not isinstance(item, ProjectRelativePath)
            for item in (self.source, self.assets, self.state, self.distribution)
        ):
            raise ContractError("project paths must be ProjectRelativePath values")
        named = {
            "source": self.source,
            "assets": self.assets,
            "state": self.state,
            "distribution": self.distribution,
        }
        segments = {
            name: tuple(part.casefold() for part in PurePosixPath(path.value).parts)
            for name, path in named.items()
        }
        for left_name, left in segments.items():
            for right_name, right in segments.items():
                if left_name >= right_name:
                    continue
                shared = min(len(left), len(right))
                if left[:shared] == right[:shared]:
                    raise ContractError(
                        f"project paths {left_name} and {right_name} must not overlap"
                    )


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    identifier: str
    name: str
    version: str
    mod_type: str
    compatibility: Compatibility
    license: str = "NOASSERTION"
    contact: str = ""
    skeleton: SkeletonSource = SkeletonSource.GAME_GENERATED
    runtime_status: RuntimeStatus = RuntimeStatus.UNTESTED
    save_impact: SaveImpact = SaveImpact.UNKNOWN
    achievement_impact: AchievementImpact = AchievementImpact.UNKNOWN
    provenance_status: ProvenanceStatus = ProvenanceStatus.UNREVIEWED
    provenance_notes: str = ""
    dependencies: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    paths: ProjectPaths = field(default_factory=ProjectPaths)
    schema_version: int = PROJECT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str)
            for value in (
                self.identifier,
                self.name,
                self.version,
                self.mod_type,
                self.license,
                self.contact,
                self.provenance_notes,
            )
        ):
            raise ContractError("project text fields must be strings")
        if not isinstance(self.compatibility, Compatibility):
            raise ContractError("project compatibility must be a Compatibility value")
        if not isinstance(self.paths, ProjectPaths):
            raise ContractError("project paths must be a ProjectPaths value")
        for value, expected, label in (
            (self.skeleton, SkeletonSource, "skeleton"),
            (self.runtime_status, RuntimeStatus, "runtime_status"),
            (self.save_impact, SaveImpact, "save_impact"),
            (self.achievement_impact, AchievementImpact, "achievement_impact"),
            (self.provenance_status, ProvenanceStatus, "provenance_status"),
        ):
            if not isinstance(value, expected):
                raise ContractError(f"project {label} has an invalid enum type")
        if not isinstance(self.dependencies, tuple) or not isinstance(self.conflicts, tuple):
            raise ContractError("project dependencies and conflicts must be tuples")
        if any(not isinstance(relation, str) for relation in (*self.dependencies, *self.conflicts)):
            raise ContractError("project dependency and conflict values must be strings")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != PROJECT_SCHEMA_VERSION
        ):
            raise ContractError(
                f"unsupported acmk.toml schema {self.schema_version}; "
                f"expected {PROJECT_SCHEMA_VERSION}"
            )
        if not _IDENTIFIER.fullmatch(self.identifier):
            raise ContractError(
                "project id must be 2-64 ASCII letters, digits, underscores, or hyphens "
                "and start with a letter"
            )
        if not self.name.strip() or "\x00" in self.name:
            raise ContractError("project name cannot be empty or contain NUL")
        if not _VERSION.fullmatch(self.version):
            raise ContractError("project version must use SemVer such as 0.1.0")
        if not self.mod_type.strip() or "\x00" in self.mod_type:
            raise ContractError("project mod_type cannot be empty or contain NUL")
        if not self.license.strip() or "\x00" in self.license:
            raise ContractError("project license cannot be empty; use NOASSERTION when undecided")
        if self.license != self.license.strip() or not _LICENSE_EXPRESSION.fullmatch(self.license):
            raise ContractError(
                "project license must be a simple SPDX expression or LicenseRef identifier"
            )
        if self.license.casefold() == "noassertion" and self.license != "NOASSERTION":
            raise ContractError("use exact uppercase NOASSERTION for an unresolved license")
        if "\x00" in self.contact:
            raise ContractError("project contact cannot contain NUL")
        if "\x00" in self.provenance_notes:
            raise ContractError("project provenance notes cannot contain NUL")
        for relation in (*self.dependencies, *self.conflicts):
            if not relation.strip() or "\x00" in relation:
                raise ContractError(
                    "dependency and conflict identifiers cannot be empty or contain NUL"
                )
        dependency_keys = [item.casefold() for item in self.dependencies]
        conflict_keys = [item.casefold() for item in self.conflicts]
        if len(dependency_keys) != len(set(dependency_keys)):
            raise ContractError("project dependencies must be unique")
        if len(conflict_keys) != len(set(conflict_keys)):
            raise ContractError("project conflicts must be unique")
        overlap = sorted(set(dependency_keys) & set(conflict_keys))
        if overlap:
            raise ContractError("a relation cannot be both a dependency and a conflict")

    @classmethod
    def load(cls, path: str | Path) -> ProjectConfig:
        source = Path(path)
        try:
            with source.open("rb") as handle:
                payload = handle.read(MAX_PROJECT_CONFIG_BYTES + 1)
            if len(payload) > MAX_PROJECT_CONFIG_BYTES:
                raise ValueError(f"configuration exceeds the {MAX_PROJECT_CONFIG_BYTES}-byte limit")
        except (OSError, ValueError) as exc:
            raise ContractError(
                f"cannot read {source}: {exc}", code="PROJECT_CONFIG", path=source
            ) from exc
        return cls.from_bytes(payload, source=source)

    @classmethod
    def from_bytes(cls, payload: bytes, *, source: str | Path = "acmk.toml") -> ProjectConfig:
        label = Path(source)
        if not isinstance(payload, bytes):
            raise ContractError("project configuration payload must be bytes")
        if len(payload) > MAX_PROJECT_CONFIG_BYTES:
            raise ContractError(
                f"configuration exceeds the {MAX_PROJECT_CONFIG_BYTES}-byte limit",
                code="PROJECT_CONFIG",
                path=label,
            )
        try:
            data = tomllib.loads(payload.decode("utf-8"))
        except (UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ContractError(
                f"cannot read {label}: {exc}", code="PROJECT_CONFIG", path=label
            ) from exc
        try:
            _exact_keys(
                data,
                {"schema_version", "project", "compatibility", "paths", "relations"},
                "root",
            )
            project = _table(data, "project")
            compatibility = _table(data, "compatibility")
            paths = _table(data, "paths")
            relations = _table(data, "relations")
            _exact_keys(
                project,
                {
                    "id",
                    "name",
                    "version",
                    "mod_type",
                    "license",
                    "contact",
                    "skeleton",
                    "runtime_status",
                    "save_impact",
                    "achievement_impact",
                    "provenance_status",
                    "provenance_notes",
                },
                "project",
            )
            _exact_keys(
                compatibility,
                {"game_version", "game_semver", "steam_build_id", "content_hash"},
                "compatibility",
            )
            _exact_keys(paths, {"source", "assets", "state", "distribution"}, "paths")
            _exact_keys(relations, {"dependencies", "conflicts"}, "relations")
            return cls(
                schema_version=_integer(data, "schema_version"),
                identifier=_string(project, "id"),
                name=_string(project, "name"),
                version=_string(project, "version"),
                mod_type=_string(project, "mod_type"),
                license=_string(project, "license"),
                contact=_string(project, "contact"),
                skeleton=SkeletonSource(_string(project, "skeleton")),
                runtime_status=RuntimeStatus(_string(project, "runtime_status")),
                save_impact=SaveImpact(_string(project, "save_impact")),
                achievement_impact=AchievementImpact(_string(project, "achievement_impact")),
                provenance_status=ProvenanceStatus(_string(project, "provenance_status")),
                provenance_notes=_string(project, "provenance_notes"),
                compatibility=Compatibility(
                    game_version=_string(compatibility, "game_version"),
                    game_semver=_string(compatibility, "game_semver"),
                    steam_build_id=_string(compatibility, "steam_build_id"),
                    content_hash=_string(compatibility, "content_hash"),
                ),
                dependencies=_string_tuple(relations, "dependencies"),
                conflicts=_string_tuple(relations, "conflicts"),
                paths=ProjectPaths(
                    source=ProjectRelativePath(_string(paths, "source")),
                    assets=ProjectRelativePath(_string(paths, "assets")),
                    state=ProjectRelativePath(_string(paths, "state")),
                    distribution=ProjectRelativePath(_string(paths, "distribution")),
                ),
            )
        except (KeyError, TypeError, ValueError, ContractError) as exc:
            if isinstance(exc, ContractError):
                raise
            raise ContractError(
                f"invalid {label}: {exc}", code="PROJECT_CONFIG", path=label
            ) from exc

    def to_toml(self) -> str:
        lines = [
            f"schema_version = {self.schema_version}",
            "",
            "[project]",
            f"id = {_toml_string(self.identifier)}",
            f"name = {_toml_string(self.name)}",
            f"version = {_toml_string(self.version)}",
            f"mod_type = {_toml_string(self.mod_type)}",
            f"license = {_toml_string(self.license)}",
            f"contact = {_toml_string(self.contact)}",
            f"skeleton = {_toml_string(self.skeleton.value)}",
            f"runtime_status = {_toml_string(self.runtime_status.value)}",
            f"save_impact = {_toml_string(self.save_impact.value)}",
            f"achievement_impact = {_toml_string(self.achievement_impact.value)}",
            f"provenance_status = {_toml_string(self.provenance_status.value)}",
            f"provenance_notes = {_toml_string(self.provenance_notes)}",
            "",
            "[compatibility]",
            f"game_version = {_toml_string(self.compatibility.game_version)}",
            f"game_semver = {_toml_string(self.compatibility.game_semver)}",
            f"steam_build_id = {_toml_string(self.compatibility.steam_build_id)}",
            f"content_hash = {_toml_string(self.compatibility.content_hash)}",
            "",
            "[paths]",
            f"source = {_toml_string(self.paths.source.value)}",
            f"assets = {_toml_string(self.paths.assets.value)}",
            f"state = {_toml_string(self.paths.state.value)}",
            f"distribution = {_toml_string(self.paths.distribution.value)}",
            "",
            "[relations]",
            f"dependencies = {_toml_array(self.dependencies)}",
            f"conflicts = {_toml_array(self.conflicts)}",
            "",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible project-schema representation."""

        return {
            "schema_version": self.schema_version,
            "project": {
                "id": self.identifier,
                "name": self.name,
                "version": self.version,
                "mod_type": self.mod_type,
                "license": self.license,
                "contact": self.contact,
                "skeleton": self.skeleton.value,
                "runtime_status": self.runtime_status.value,
                "save_impact": self.save_impact.value,
                "achievement_impact": self.achievement_impact.value,
                "provenance_status": self.provenance_status.value,
                "provenance_notes": self.provenance_notes,
            },
            "compatibility": {
                "game_version": self.compatibility.game_version,
                "game_semver": self.compatibility.game_semver,
                "steam_build_id": self.compatibility.steam_build_id,
                "content_hash": self.compatibility.content_hash,
            },
            "paths": {
                "source": self.paths.source.value,
                "assets": self.paths.assets.value,
                "state": self.paths.state.value,
                "distribution": self.paths.distribution.value,
            },
            "relations": {
                "dependencies": list(self.dependencies),
                "conflicts": list(self.conflicts),
            },
        }


def _table(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be a table")
    return value


def _exact_keys(data: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(data)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if unknown:
        details.append("unknown " + ", ".join(unknown))
    raise ValueError(f"{label} fields do not match schema ({'; '.join(details)})")


def _string(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _integer(data: Mapping[str, Any], key: str) -> int:
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{key} must be an integer")
    return value


def _string_tuple(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = data[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{key} must be an array of strings")
    return tuple(value)


def _toml_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\f", "\\f")
        .replace("\r", "\\r")
    )
    if any(ord(char) < 0x20 and char not in "\b\t\n\f\r" for char in escaped):
        raise ContractError("TOML strings cannot contain control characters")
    return f'"{escaped}"'


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"

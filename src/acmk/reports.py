"""Immutable result contracts for SDK operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ._version import REPORT_SCHEMA_VERSION, __version__
from .errors import ContractError, ValidationFailedError

_RELEASE_BLOCKING_WARNING_CODES = {
    "ABSOLUTE_FILE_REFERENCE",
    "BASE_COMPARE",
    "CONTENT_EMPTY",
    "MANIFEST_DUPLICATE_FIELD",
    "MISSING_FILE_REFERENCE",
}


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    NOTICE = "notice"


class ValidationProfile(StrEnum):
    AUTHORING = "authoring"
    RELEASE = "release"


class ExecutionMode(StrEnum):
    DRY_RUN = "dry-run"
    APPLY = "apply"


class CheckStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class Issue:
    severity: Severity
    code: str
    message: str
    path: Path | None = None
    detail: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.detail is not None:
            object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Issue:
        try:
            raw_path = value.get("path")
            raw_detail = value.get("detail")
            return cls(
                severity=Severity(str(value["severity"])),
                code=str(value["code"]),
                message=str(value["message"]),
                path=Path(str(raw_path)) if raw_path is not None else None,
                detail=dict(raw_detail) if isinstance(raw_detail, dict) else None,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ContractError(f"invalid issue payload: {exc}", code="REPORT_CONTRACT") from exc

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
        }
        if self.path is not None:
            result["path"] = str(self.path)
        if self.detail:
            result["detail"] = dict(self.detail)
        return result


@dataclass(frozen=True, slots=True)
class ValidationReport:
    target: Path
    profile: ValidationProfile
    issues: tuple[Issue, ...]
    manifest: Mapping[str, str]
    content: Mapping[str, Any]
    classifications: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", MappingProxyType(dict(self.manifest)))
        object.__setattr__(self, "content", MappingProxyType(dict(self.content)))
        object.__setattr__(
            self,
            "classifications",
            MappingProxyType(dict(self.classifications)),
        )

    @classmethod
    def from_legacy(
        cls,
        value: Mapping[str, Any],
        *,
        profile: ValidationProfile = ValidationProfile.AUTHORING,
        extra_issues: Sequence[Issue] = (),
    ) -> ValidationReport:
        raw_issues = value.get("issues", [])
        if not isinstance(raw_issues, list):
            raise ContractError("validation issues must be a list", code="REPORT_CONTRACT")
        parsed: list[Issue] = []
        for item in raw_issues:
            issue = Issue.from_mapping(item)
            if (
                profile is ValidationProfile.RELEASE
                and issue.severity is Severity.WARNING
                and issue.code in _RELEASE_BLOCKING_WARNING_CODES
            ):
                issue = Issue(
                    Severity.ERROR,
                    issue.code,
                    issue.message,
                    issue.path,
                    issue.detail,
                )
            parsed.append(issue)
        issues = tuple(parsed) + tuple(extra_issues)
        return cls(
            target=Path(str(value.get("target", ""))),
            profile=profile,
            issues=issues,
            manifest=dict(value.get("manifest", {})),
            content=dict(value.get("content", {})),
            classifications=dict(value.get("classifications", {})),
        )

    @property
    def errors(self) -> int:
        return sum(issue.severity is Severity.ERROR for issue in self.issues)

    @property
    def warnings(self) -> int:
        return sum(issue.severity is Severity.WARNING for issue in self.issues)

    @property
    def notices(self) -> int:
        return sum(issue.severity is Severity.NOTICE for issue in self.issues)

    @property
    def valid(self) -> bool:
        return self.errors == 0

    @property
    def strict_valid(self) -> bool:
        return self.errors == 0 and self.warnings == 0

    def raise_for_errors(self) -> None:
        if not self.valid:
            codes = ", ".join(
                issue.code for issue in self.issues if issue.severity is Severity.ERROR
            )
            raise ValidationFailedError(f"validation failed: {codes}", path=self.target)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": str(self.target),
            "profile": self.profile.value,
            "valid": self.valid,
            "strict_valid": self.strict_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "notices": self.notices,
            "manifest": dict(self.manifest),
            "content": dict(self.content),
            "classifications": dict(self.classifications),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class DiscoverySnapshot:
    app_id: str
    game: str
    game_dir: Path | None
    base_data_root: Path | None
    documents_dir: Path | None
    user_root: Path | None
    game_semver: str | None
    steam_build_id: str | None
    content_hash: str | None
    game_version: str | None
    workshop_roots: tuple[Path, ...]
    read_only_roots: tuple[Path, ...]
    enabled_load_order: tuple[Mapping[str, Any], ...]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "enabled_load_order",
            tuple(MappingProxyType(dict(item)) for item in self.enabled_load_order),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> DiscoverySnapshot:
        current = value.get("current", {})
        if not isinstance(current, dict):
            raise ContractError("discovery current field must be an object", code="REPORT_CONTRACT")
        return cls(
            app_id=str(value.get("app_id", "")),
            game=str(value.get("game", "")),
            game_dir=_optional_path(value.get("game_dir")),
            base_data_root=_optional_path(value.get("base_data_root")),
            documents_dir=_optional_path(value.get("documents_dir")),
            user_root=_optional_path(value.get("user_root")),
            game_semver=_optional_string(current.get("semver")),
            steam_build_id=_optional_string(current.get("steam_build_id")),
            content_hash=_optional_string(current.get("content_hash")),
            game_version=_optional_string(current.get("game_version")),
            workshop_roots=tuple(Path(str(item)) for item in value.get("workshop_roots", [])),
            read_only_roots=tuple(Path(str(item)) for item in value.get("read_only_roots", [])),
            enabled_load_order=tuple(dict(item) for item in value.get("effective_load_order", [])),
            notes=tuple(str(item) for item in value.get("notes", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "game": self.game,
            "game_dir": str(self.game_dir) if self.game_dir else None,
            "base_data_root": str(self.base_data_root) if self.base_data_root else None,
            "documents_dir": str(self.documents_dir) if self.documents_dir else None,
            "user_root": str(self.user_root) if self.user_root else None,
            "current": {
                "semver": self.game_semver,
                "steam_build_id": self.steam_build_id,
                "content_hash": self.content_hash,
                "game_version": self.game_version,
            },
            "workshop_roots": [str(path) for path in self.workshop_roots],
            "read_only_roots": [str(path) for path in self.read_only_roots],
            "effective_load_order": [dict(item) for item in self.enabled_load_order],
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    message: str
    detail: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.detail is not None:
            object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
        }
        if self.detail:
            result["detail"] = dict(self.detail)
        return result


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]
    discovery: DiscoverySnapshot

    @property
    def ok(self) -> bool:
        return all(check.status is not CheckStatus.FAIL for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "discovery": self.discovery.to_dict(),
        }


def envelope(
    command: str,
    data: Mapping[str, Any],
    *,
    ok: bool = True,
    issues: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Wrap new SDK command output in the stable report-envelope contract."""

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool_version": __version__,
        "command": command,
        "status": "ok" if ok else "error",
        "data": dict(data),
        "issues": [dict(issue) for issue in issues],
    }


def _optional_path(value: Any) -> Path | None:
    return None if value is None else Path(str(value))


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)

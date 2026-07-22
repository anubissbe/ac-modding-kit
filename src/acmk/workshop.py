"""Workshop preparation and identity reconciliation without Steam upload support.

The in-game Ancient Cities publisher remains the canonical upload path.  This module
only prepares single-item confirmation packets and reconciles a server-assigned Steam
identity back into a local ACMK project after a successful publication.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, overload

import ancient_cities_mod as _legacy

from .config import MAX_PROJECT_CONFIG_BYTES, ProjectConfig, RuntimeStatus
from .errors import ContractError, ProjectError, SourceChangedError, ValidationFailedError
from .manifest import ManifestDocument, SteamModId
from .project import SDKProject, _create_state_backup
from .reports import ExecutionMode, ValidationProfile

WORKSHOP_APP_ID = 667610
WORKSHOP_STATE_SCHEMA_VERSION = 1
PUBLISH_PACKET_SCHEMA_VERSION = 1
MAX_WORKSHOP_STATE_BYTES = 1024 * 1024
MAX_WORKSHOP_PREDECESSORS = 1024
_RFC3339_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


class PublishAction(StrEnum):
    PUBLISH = "publish"
    UPDATE = "update"


class CandidateKind(StrEnum):
    LOOSE = "loose"
    STAGED = "staged"


class WorkshopVisibility(StrEnum):
    PUBLIC = "public"
    FRIENDS_ONLY = "friends-only"
    PRIVATE = "private"
    UNLISTED = "unlisted"
    UNKNOWN = "unknown"


class VisibilityControl(StrEnum):
    SHOWN = "shown"
    NOT_EXPOSED = "not-exposed"


class WorkshopStatus(StrEnum):
    UNPUBLISHED = "unpublished"
    PUBLISHED = "published"
    DELETED_PREDECESSOR = "deleted-predecessor"


@dataclass(frozen=True, slots=True)
class WorkshopArtifact:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.path)
        if (
            not self.path
            or "\\" in self.path
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ContractError("Workshop artifact path must be a safe relative path")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ContractError("Workshop artifact size must be a non-negative integer")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ContractError("Workshop artifact SHA-256 must be a lowercase digest")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "bytes": self.size, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class WorkshopState:
    status: WorkshopStatus
    steam_mod_id: SteamModId
    visibility: WorkshopVisibility = WorkshopVisibility.UNKNOWN
    predecessor_ids: tuple[SteamModId, ...] = ()
    last_verified_at: str = ""
    app_id: int = WORKSHOP_APP_ID
    schema_version: int = WORKSHOP_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkshopStatus):
            raise ContractError("Workshop state status is invalid")
        if not isinstance(self.steam_mod_id, SteamModId):
            raise ContractError("Workshop state SteamModId is invalid")
        if not isinstance(self.visibility, WorkshopVisibility):
            raise ContractError("Workshop state visibility is invalid")
        if (
            isinstance(self.app_id, bool)
            or not isinstance(self.app_id, int)
            or self.app_id != WORKSHOP_APP_ID
        ):
            raise ContractError(f"Workshop state app_id must be {WORKSHOP_APP_ID}")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != WORKSHOP_STATE_SCHEMA_VERSION
        ):
            raise ContractError(f"Workshop state schema must be {WORKSHOP_STATE_SCHEMA_VERSION}")
        if not isinstance(self.predecessor_ids, tuple) or any(
            not isinstance(item, SteamModId) for item in self.predecessor_ids
        ):
            raise ContractError("Workshop predecessor IDs must be SteamModId values")
        if len(set(self.predecessor_ids)) != len(self.predecessor_ids):
            raise ContractError("Workshop predecessor IDs must be unique")
        if len(self.predecessor_ids) > MAX_WORKSHOP_PREDECESSORS:
            raise ContractError(
                f"Workshop state supports at most {MAX_WORKSHOP_PREDECESSORS} predecessors"
            )
        if any(item.low == 0 and item.high == 0 for item in self.predecessor_ids):
            raise ContractError("Workshop predecessor IDs must be nonzero")
        if self.steam_mod_id in self.predecessor_ids:
            raise ContractError("current SteamModId cannot also be a predecessor")
        current_is_zero = self.steam_mod_id.low == 0 and self.steam_mod_id.high == 0
        if self.status is WorkshopStatus.UNPUBLISHED and not current_is_zero:
            raise ContractError("unpublished Workshop state must use SteamModId 0,0")
        if self.status is not WorkshopStatus.UNPUBLISHED and current_is_zero:
            raise ContractError("published/deleted Workshop state requires a nonzero SteamModId")
        if not isinstance(self.last_verified_at, str):
            raise ContractError("Workshop state last_verified_at must be a string")
        if self.last_verified_at:
            _parse_utc_timestamp(self.last_verified_at)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkshopState:
        expected = {
            "schema_version",
            "app_id",
            "status",
            "steam_mod_id",
            "visibility",
            "predecessor_ids",
            "last_verified_at",
        }
        if set(value) != expected:
            missing = sorted(expected - set(value))
            unknown = sorted(set(value) - expected)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise ContractError(
                "Workshop state fields do not match schema (" + "; ".join(details) + ")"
            )
        predecessors = value["predecessor_ids"]
        if not isinstance(predecessors, list) or any(
            not isinstance(item, str) for item in predecessors
        ):
            raise ContractError("Workshop predecessor_ids must be an array of strings")
        try:
            steam_mod_id = _canonical_state_steam_id(
                _strict_string(value["steam_mod_id"], "steam_mod_id")
            )
            return cls(
                schema_version=_strict_int(value["schema_version"], "schema_version"),
                app_id=_strict_int(value["app_id"], "app_id"),
                status=WorkshopStatus(_strict_string(value["status"], "status")),
                steam_mod_id=steam_mod_id,
                visibility=WorkshopVisibility(_strict_string(value["visibility"], "visibility")),
                predecessor_ids=tuple(_canonical_state_steam_id(item) for item in predecessors),
                last_verified_at=_strict_string(value["last_verified_at"], "last_verified_at"),
            )
        except ValueError as exc:
            raise ContractError(f"invalid Workshop state: {exc}") from exc

    @classmethod
    def from_bytes(cls, payload: bytes) -> WorkshopState:
        if not isinstance(payload, bytes):
            raise ContractError("Workshop state payload must be bytes")
        if len(payload) > MAX_WORKSHOP_STATE_BYTES:
            raise ContractError("Workshop state exceeds the size limit")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot decode Workshop state: {exc}") from exc
        if not isinstance(value, dict):
            raise ContractError("Workshop state must be a JSON object")
        return cls.from_dict(value)

    @classmethod
    def load(cls, path: str | Path) -> WorkshopState:
        source = Path(path)
        payload = _read_bounded(source, MAX_WORKSHOP_STATE_BYTES)
        return cls.from_bytes(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "app_id": self.app_id,
            "status": self.status.value,
            "steam_mod_id": str(self.steam_mod_id),
            "visibility": self.visibility.value,
            "predecessor_ids": [str(item) for item in self.predecessor_ids],
            "last_verified_at": self.last_verified_at,
        }

    def to_bytes(self) -> bytes:
        payload = (json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
        if len(payload) > MAX_WORKSHOP_STATE_BYTES:
            raise ContractError("Workshop state exceeds the size limit")
        return payload


@dataclass(frozen=True, slots=True)
class PublishPacket:
    action: PublishAction
    candidate_kind: CandidateKind
    candidate_root: Path
    steam_mod_id: SteamModId
    visibility: WorkshopVisibility
    visibility_control: VisibilityControl
    account_preflight_passed: bool
    target_ownership_verified: bool | None
    generated_at: str
    valid_until: str
    artifacts: tuple[WorkshopArtifact, ...]
    deterministic_mod_zip: WorkshopArtifact | None
    generated_package_root: Path | None
    generated_package_artifacts: tuple[WorkshopArtifact, ...]
    generated_package_members: tuple[WorkshopArtifact, ...]
    project_id: str
    project_name: str
    app_id: int = WORKSHOP_APP_ID
    schema_version: int = PUBLISH_PACKET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.app_id, bool)
            or not isinstance(self.app_id, int)
            or self.app_id != WORKSHOP_APP_ID
        ):
            raise ContractError(f"publish packet app_id must be {WORKSHOP_APP_ID}")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != PUBLISH_PACKET_SCHEMA_VERSION
        ):
            raise ContractError(f"publish packet schema must be {PUBLISH_PACKET_SCHEMA_VERSION}")
        if not isinstance(self.action, PublishAction):
            raise ContractError("publish packet action is invalid")
        if not isinstance(self.candidate_kind, CandidateKind):
            raise ContractError("publish packet candidate kind is invalid")
        if not isinstance(self.candidate_root, Path) or not self.candidate_root.is_absolute():
            raise ContractError("publish packet candidate root must be absolute")
        if not isinstance(self.steam_mod_id, SteamModId):
            raise ContractError("publish packet SteamModId is invalid")
        if not isinstance(self.visibility, WorkshopVisibility):
            raise ContractError("publish packet visibility is invalid")
        if self.visibility is WorkshopVisibility.UNKNOWN:
            raise ContractError("publish packet visibility must be explicit")
        if not isinstance(self.visibility_control, VisibilityControl):
            raise ContractError("publish packet visibility control is invalid")
        if self.account_preflight_passed is not True:
            raise ContractError("publish packet requires an intended-account preflight")
        if self.action is PublishAction.UPDATE:
            if self.target_ownership_verified is not True:
                raise ContractError("Update requires verified target existence and ownership")
        elif self.target_ownership_verified is not None:
            raise ContractError("new-item Publish has no existing target ownership to verify")
        if not isinstance(self.generated_at, str) or not isinstance(self.valid_until, str):
            raise ContractError("publish packet timestamps must be strings")
        generated = _parse_utc_timestamp(self.generated_at)
        expires = _parse_utc_timestamp(self.valid_until)
        if expires <= generated:
            raise ContractError("publish packet expiry must be after generation time")
        if not isinstance(self.artifacts, tuple) or not self.artifacts:
            raise ContractError("publish packet requires at least one artifact")
        if any(not isinstance(item, WorkshopArtifact) for item in self.artifacts):
            raise ContractError("publish packet artifacts are invalid")
        paths = [item.path.casefold() for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ContractError("publish packet artifact paths must be unique")
        if self.action is PublishAction.PUBLISH:
            if self.steam_mod_id.low or self.steam_mod_id.high:
                raise ContractError("Publish requires new-item SteamModId 0,0")
        elif not (self.steam_mod_id.low or self.steam_mod_id.high):
            raise ContractError("Update requires an existing nonzero SteamModId")
        if self.candidate_kind is CandidateKind.LOOSE:
            if not isinstance(self.deterministic_mod_zip, WorkshopArtifact):
                raise ContractError("loose publish packet requires deterministic ZIP evidence")
        elif self.deterministic_mod_zip is not None:
            raise ContractError("staged publish packet cannot duplicate deterministic ZIP evidence")
        if not isinstance(self.generated_package_artifacts, tuple) or any(
            not isinstance(item, WorkshopArtifact) for item in self.generated_package_artifacts
        ):
            raise ContractError("generated package artifacts are invalid")
        if not isinstance(self.generated_package_members, tuple) or any(
            not isinstance(item, WorkshopArtifact) for item in self.generated_package_members
        ):
            raise ContractError("generated package members are invalid")
        generated_parts = (
            self.generated_package_root is not None,
            bool(self.generated_package_artifacts),
            bool(self.generated_package_members),
        )
        if any(generated_parts) and not all(generated_parts):
            raise ContractError("generated package root, artifacts, and members are inseparable")
        if self.generated_package_root is not None:
            if not self.generated_package_root.is_absolute():
                raise ContractError("generated package root must be absolute")
            if self.candidate_kind is not CandidateKind.LOOSE:
                raise ContractError("only a loose in-game candidate can have a generated package")
        if (
            not isinstance(self.project_id, str)
            or not isinstance(self.project_name, str)
            or not self.project_id.strip()
            or not self.project_name.strip()
        ):
            raise ContractError("publish packet project identity cannot be empty")

    @property
    def packet_id(self) -> str:
        payload = self._payload(include_packet_id=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _payload(self, *, include_packet_id: bool) -> dict[str, Any]:
        target_kind = "new-item" if self.action is PublishAction.PUBLISH else "existing-item"
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "app_id": self.app_id,
            "action": self.action.value,
            "single_use": True,
            "authorization_recorded": False,
            "publishes_workshop_items": False,
            "generated_at": self.generated_at,
            "valid_until": self.valid_until,
            "project": {"id": self.project_id, "name": self.project_name},
            "target": {"kind": target_kind, "steam_mod_id": str(self.steam_mod_id)},
            "visibility": {
                "value": self.visibility.value,
                "ui_control": self.visibility_control.value,
            },
            "account_preflight": {
                "intended_account_confirmed": self.account_preflight_passed,
                "target_exists_and_owned": self.target_ownership_verified,
                "stores_account_identity": False,
            },
            "candidate": {
                "kind": self.candidate_kind.value,
                "root": str(self.candidate_root),
                "artifacts": [item.to_dict() for item in self.artifacts],
                "deterministic_mod_zip": (
                    self.deterministic_mod_zip.to_dict()
                    if self.deterministic_mod_zip is not None
                    else None
                ),
            },
            "generated_game_package": (
                {
                    "root": str(self.generated_package_root),
                    "artifacts": [item.to_dict() for item in self.generated_package_artifacts],
                    "archive_members": [item.to_dict() for item in self.generated_package_members],
                }
                if self.generated_package_root is not None
                else None
            ),
        }
        if include_packet_id:
            payload["packet_id"] = self.packet_id
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self._payload(include_packet_id=True)

    def assert_active(self, *, at: datetime | None = None) -> None:
        """Reject use outside this packet's short, explicit confirmation window."""

        checked_at = at or datetime.now(UTC)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ContractError("publish packet check time must be timezone-aware")
        checked_at = checked_at.astimezone(UTC)
        generated = _parse_utc_timestamp(self.generated_at)
        expires = _parse_utc_timestamp(self.valid_until)
        if checked_at < generated:
            raise ContractError("publish packet is not active yet")
        if checked_at >= expires:
            raise ContractError("publish packet has expired; prepare a fresh packet")
        if self.candidate_kind is CandidateKind.LOOSE:
            current = _capture_loose_artifacts(
                self.candidate_root,
                context=_legacy.DiscoveryContext(),
                require_user_mod_root=False,
            )
        else:
            current = _capture_staged_artifacts(self.candidate_root)
        if current != self.artifacts:
            raise SourceChangedError(
                "publish candidate changed after the packet was prepared",
                path=self.candidate_root,
            )
        if self.generated_package_root is not None:
            current_package = _capture_generated_package(self.generated_package_root)
            current_members = _capture_zip_members(self.generated_package_root / "Mod.zip")
            if (
                current_package != self.generated_package_artifacts
                or current_members != self.generated_package_members
            ):
                raise SourceChangedError(
                    "generated game package changed after the packet was prepared",
                    path=self.generated_package_root,
                )


@dataclass(frozen=True, slots=True)
class WorkshopSyncResult:
    mode: ExecutionMode
    project_root: Path
    live_root: Path
    steam_mod_id: SteamModId
    visibility: WorkshopVisibility
    manifest_sha256: str
    state_path: Path
    runtime_reset: bool
    config_backup: Path | None
    manifest_backup: Path | None
    state_backup: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "project_root": str(self.project_root),
            "live_root": str(self.live_root),
            "app_id": WORKSHOP_APP_ID,
            "steam_mod_id": str(self.steam_mod_id),
            "visibility": self.visibility.value,
            "manifest_sha256": self.manifest_sha256,
            "state_path": str(self.state_path),
            "runtime_reset": self.runtime_reset,
            "config_backup": str(self.config_backup) if self.config_backup else None,
            "manifest_backup": str(self.manifest_backup) if self.manifest_backup else None,
            "state_backup": str(self.state_backup) if self.state_backup else None,
        }


@dataclass(frozen=True, slots=True)
class WorkshopSyncPlan:
    project: SDKProject
    live_root: Path
    canonical_artifacts: tuple[WorkshopArtifact, ...]
    live_artifacts: tuple[WorkshopArtifact, ...]
    updated_manifest: bytes
    updated_config: ProjectConfig
    updated_state: WorkshopState
    original_manifest_sha256: str
    original_config_sha256: str
    original_state_sha256: str | None
    identity_changed: bool

    @property
    def state_path(self) -> Path:
        return self.project.layout.state_root / "workshop.json"

    def preview(self) -> WorkshopSyncResult:
        self._validate()
        return self._result(ExecutionMode.DRY_RUN, None, None, None)

    def apply(self) -> WorkshopSyncResult:
        self._validate()
        layout = self.project.layout
        context = self.project._refresh_context()
        paths = (layout.config_path, layout.manifest, self.state_path)
        for path in paths:
            _legacy.assert_no_symlink_components(path)
            _legacy.assert_writable_project_path(path, context)
        layout.state_root.mkdir(parents=True, exist_ok=True)
        original_config = _read_bounded(layout.config_path, MAX_PROJECT_CONFIG_BYTES)
        original_manifest = _read_bounded(layout.manifest, _legacy.MAX_TEXT_ASSET_BYTES)
        original_state = (
            _read_bounded(self.state_path, MAX_WORKSHOP_STATE_BYTES)
            if self.state_path.exists()
            else None
        )
        self._assert_originals(original_config, original_manifest, original_state)
        config_bytes = self.updated_config.to_toml().encode("utf-8")
        state_bytes = self.updated_state.to_bytes()
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
        state_backup = (
            _create_state_backup(
                self.state_path,
                original_state,
                backup_root,
                boundary=layout.state_root,
            )
            if original_state is not None
            else None
        )
        self._assert_originals(
            _read_bounded(layout.config_path, MAX_PROJECT_CONFIG_BYTES),
            _read_bounded(layout.manifest, _legacy.MAX_TEXT_ASSET_BYTES),
            (
                _read_bounded(self.state_path, MAX_WORKSHOP_STATE_BYTES)
                if self.state_path.exists()
                else None
            ),
        )
        self._assert_artifact_snapshots()
        try:
            _legacy._atomic_write(self.state_path, state_bytes)
            _legacy._atomic_write(layout.manifest, self.updated_manifest)
            _legacy._atomic_write(layout.config_path, config_bytes)
        except BaseException as exc:
            errors = _rollback_sync(
                config_path=layout.config_path,
                original_config=original_config,
                written_config=config_bytes,
                manifest_path=layout.manifest,
                original_manifest=original_manifest,
                written_manifest=self.updated_manifest,
                state_path=self.state_path,
                original_state=original_state,
                written_state=state_bytes,
            )
            if errors:
                raise ProjectError(
                    "Workshop identity synchronization failed and rollback was incomplete: "
                    + "; ".join(errors),
                    path=layout.root,
                ) from exc
            raise
        return self._result(
            ExecutionMode.APPLY,
            config_backup,
            manifest_backup,
            state_backup,
        )

    def _validate(self) -> None:
        self.project._assert_config_unchanged()
        _legacy.assert_no_symlink_components(self.state_path)
        if self.original_config_sha256 != self.project._opened_config_sha256:
            raise ContractError("Workshop sync plan has an invalid project snapshot")
        self._assert_artifact_snapshots()
        original_config = _read_bounded(self.project.layout.config_path, MAX_PROJECT_CONFIG_BYTES)
        original_manifest = _read_bounded(
            self.project.layout.manifest, _legacy.MAX_TEXT_ASSET_BYTES
        )
        original_state = (
            _read_bounded(self.state_path, MAX_WORKSHOP_STATE_BYTES)
            if self.state_path.exists()
            else None
        )
        self._assert_originals(original_config, original_manifest, original_state)
        live_manifest = ManifestDocument.read(self.live_root / "Index.art")
        live_id = _manifest_steam_id(live_manifest, required=True)
        if live_id != self.updated_state.steam_mod_id:
            raise SourceChangedError("live SteamModId changed after synchronization was planned")
        expected_manifest = ManifestDocument.from_bytes(original_manifest).updated(
            {"SteamModId": str(live_id)}
        )
        if expected_manifest.to_bytes() != self.updated_manifest:
            raise ContractError("Workshop sync manifest differs from the canonical identity update")
        canonical_id = _manifest_steam_id(
            ManifestDocument.from_bytes(original_manifest), required=True
        )
        expected_config = (
            replace(self.project.config, runtime_status=RuntimeStatus.UNTESTED)
            if canonical_id != live_id
            else self.project.config
        )
        if expected_config != self.updated_config:
            raise ContractError("Workshop sync runtime status does not match the identity change")

    def _assert_artifact_snapshots(self) -> None:
        current_canonical = _capture_project_runtime_artifacts(self.project.layout.source_root)
        if current_canonical != self.canonical_artifacts:
            raise SourceChangedError(
                "canonical project source changed after synchronization was planned",
                path=self.project.layout.source_root,
            )
        current_artifacts = _capture_loose_artifacts(
            self.live_root,
            context=self.project._refresh_context(),
            require_user_mod_root=True,
        )
        if current_artifacts != self.live_artifacts:
            raise SourceChangedError(
                "live Workshop source changed after synchronization was planned",
                path=self.live_root,
            )

    def _assert_originals(
        self,
        config_bytes: bytes,
        manifest_bytes: bytes,
        state_bytes: bytes | None,
    ) -> None:
        if hashlib.sha256(config_bytes).hexdigest() != self.original_config_sha256:
            raise SourceChangedError("acmk.toml changed after Workshop sync planning")
        if hashlib.sha256(manifest_bytes).hexdigest() != self.original_manifest_sha256:
            raise SourceChangedError("canonical Index.art changed after Workshop sync planning")
        state_sha256 = hashlib.sha256(state_bytes).hexdigest() if state_bytes is not None else None
        if state_sha256 != self.original_state_sha256:
            raise SourceChangedError("workshop.json changed after Workshop sync planning")

    def _result(
        self,
        mode: ExecutionMode,
        config_backup: Path | None,
        manifest_backup: Path | None,
        state_backup: Path | None,
    ) -> WorkshopSyncResult:
        return WorkshopSyncResult(
            mode=mode,
            project_root=self.project.layout.root,
            live_root=self.live_root,
            steam_mod_id=self.updated_state.steam_mod_id,
            visibility=self.updated_state.visibility,
            manifest_sha256=hashlib.sha256(self.updated_manifest).hexdigest(),
            state_path=self.state_path,
            runtime_reset=(
                self.identity_changed
                and self.project.config.runtime_status is not RuntimeStatus.UNTESTED
            ),
            config_backup=config_backup,
            manifest_backup=manifest_backup,
            state_backup=state_backup,
        )


def prepare_publish_packet(
    project: SDKProject,
    candidate_root: str | os.PathLike[str],
    *,
    action: PublishAction,
    candidate_kind: CandidateKind,
    visibility: WorkshopVisibility,
    visibility_control: VisibilityControl,
    account_preflight_passed: bool,
    target_ownership_verified: bool | None = None,
    generated_package_root: str | os.PathLike[str] | None = None,
    valid_minutes: int = 15,
    generated_at: datetime | None = None,
) -> PublishPacket:
    """Create one expiring confirmation packet; never upload or record consent."""

    if not isinstance(project, SDKProject):
        raise ContractError("project must be an SDKProject")
    if not isinstance(action, PublishAction):
        raise ContractError("action must be a PublishAction")
    if not isinstance(candidate_kind, CandidateKind):
        raise ContractError("candidate_kind must be a CandidateKind")
    if not isinstance(visibility, WorkshopVisibility):
        raise ContractError("visibility must be a WorkshopVisibility")
    if visibility is WorkshopVisibility.UNKNOWN:
        raise ContractError("visibility must be explicit before confirmation")
    if not isinstance(visibility_control, VisibilityControl):
        raise ContractError("visibility_control must be a VisibilityControl")
    if account_preflight_passed is not True:
        raise ContractError("confirm the intended active Steam account before preparing a packet")
    if action is PublishAction.UPDATE:
        if target_ownership_verified is not True:
            raise ContractError("Update requires verified target existence and account ownership")
    elif target_ownership_verified is not None:
        raise ContractError("target_ownership_verified applies only to Update")
    if isinstance(valid_minutes, bool) or not isinstance(valid_minutes, int):
        raise ContractError("valid_minutes must be an integer")
    if not 1 <= valid_minutes <= 60:
        raise ContractError("valid_minutes must be between 1 and 60")
    project._assert_config_unchanged()
    project.validate(ValidationProfile.RELEASE).raise_for_errors()
    root = _absolute(Path(candidate_root))
    canonical_manifest = project.manifest()
    canonical_id = _manifest_steam_id(canonical_manifest, required=True)
    workshop_state = _load_project_workshop_state(project)
    if workshop_state is not None:
        if workshop_state.status is WorkshopStatus.DELETED_PREDECESSOR:
            raise ValidationFailedError(
                "a deleted Workshop identity cannot authorize Publish or Update",
                path=project.layout.state_root / "workshop.json",
            )
        if workshop_state.status is WorkshopStatus.PUBLISHED:
            if workshop_state.steam_mod_id != canonical_id:
                raise ValidationFailedError(
                    "published Workshop state does not match the canonical SteamModId",
                    path=project.layout.state_root / "workshop.json",
                )
            if action is not PublishAction.UPDATE:
                raise ValidationFailedError(
                    "a published Workshop identity can only authorize Update",
                    path=project.layout.state_root / "workshop.json",
                )
        elif canonical_id != workshop_state.steam_mod_id:
            raise ValidationFailedError(
                "unpublished Workshop state requires canonical SteamModId 0,0",
                path=project.layout.state_root / "workshop.json",
            )
    if action is PublishAction.PUBLISH and (canonical_id.low or canonical_id.high):
        raise ValidationFailedError(
            "Publish requires a canonical project with SteamModId 0,0",
            path=project.layout.manifest,
        )
    if action is PublishAction.UPDATE and not (canonical_id.low or canonical_id.high):
        raise ValidationFailedError(
            "Update requires a canonical project with a nonzero SteamModId",
            path=project.layout.manifest,
        )
    release = project.plan_release().preview()
    deterministic_zip = WorkshopArtifact("Mod.zip", release.archive_size, release.archive_sha256)
    if candidate_kind is CandidateKind.LOOSE:
        artifacts = _capture_loose_artifacts(
            root,
            context=project._refresh_context(),
            require_user_mod_root=True,
        )
        _assert_loose_matches_project(project, root, action=action)
    else:
        if root != _absolute(project.layout.distribution_root):
            raise ProjectError(
                "staged packet candidate must be this project's distribution directory",
                code="WORKSHOP_CANDIDATE_SCOPE",
                path=root,
            )
        artifacts = _capture_staged_artifacts(root)
        _assert_staged_matches_project(project, artifacts, deterministic_zip)
    package_root: Path | None = None
    package_artifacts: tuple[WorkshopArtifact, ...] = ()
    package_members: tuple[WorkshopArtifact, ...] = ()
    if generated_package_root is not None:
        if candidate_kind is not CandidateKind.LOOSE:
            raise ContractError("a generated game package requires a loose candidate")
        package_root = _absolute(Path(generated_package_root))
        package_artifacts = _capture_generated_package(package_root)
        package_members = _capture_zip_members(package_root / "Mod.zip")
        _assert_generated_package_matches_loose(
            artifacts,
            package_artifacts,
            package_members,
            package_root,
        )
    if candidate_kind is CandidateKind.LOOSE:
        if (
            _capture_loose_artifacts(
                root,
                context=project._refresh_context(),
                require_user_mod_root=True,
            )
            != artifacts
        ):
            raise SourceChangedError(
                "loose publish candidate changed while the packet was prepared",
                path=root,
            )
    elif _capture_staged_artifacts(root) != artifacts:
        raise SourceChangedError(
            "staged publish candidate changed while the packet was prepared",
            path=root,
        )
    if package_root is not None:
        if _capture_generated_package(package_root) != package_artifacts:
            raise SourceChangedError(
                "generated game package changed while the packet was prepared",
                path=package_root,
            )
    current = generated_at or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ContractError("generated_at must be timezone-aware")
    current = current.astimezone(UTC).replace(microsecond=0)
    expires = current + timedelta(minutes=valid_minutes)
    return PublishPacket(
        action=action,
        candidate_kind=candidate_kind,
        candidate_root=root,
        steam_mod_id=canonical_id,
        visibility=visibility,
        visibility_control=visibility_control,
        account_preflight_passed=account_preflight_passed,
        target_ownership_verified=target_ownership_verified,
        generated_at=current.isoformat(),
        valid_until=expires.isoformat(),
        artifacts=artifacts,
        deterministic_mod_zip=(
            deterministic_zip if candidate_kind is CandidateKind.LOOSE else None
        ),
        generated_package_root=package_root,
        generated_package_artifacts=package_artifacts,
        generated_package_members=package_members,
        project_id=project.config.identifier,
        project_name=project.config.name,
    )


def plan_workshop_sync(
    project: SDKProject,
    live_root: str | os.PathLike[str],
    *,
    visibility: WorkshopVisibility,
    predecessor_ids: Iterable[str | int | SteamModId] = (),
    verified_at: datetime | None = None,
) -> WorkshopSyncPlan:
    """Plan an atomic 0,0-to-assigned-ID reconciliation after in-game publication."""

    if not isinstance(project, SDKProject):
        raise ContractError("project must be an SDKProject")
    if not isinstance(visibility, WorkshopVisibility) or visibility is WorkshopVisibility.UNKNOWN:
        raise ContractError("a verified non-unknown visibility is required")
    project._assert_config_unchanged()
    root = _absolute(Path(live_root))
    artifacts = _capture_loose_artifacts(
        root,
        context=project._refresh_context(),
        require_user_mod_root=True,
    )
    live_manifest = ManifestDocument.read(root / "Index.art")
    live_id = _manifest_steam_id(live_manifest, required=True)
    if not (live_id.low or live_id.high):
        raise ValidationFailedError(
            "live post-publish manifest still has SteamModId 0,0",
            path=root / "Index.art",
        )
    canonical_manifest = project.manifest()
    canonical_artifacts = _capture_project_runtime_artifacts(project.layout.source_root)
    canonical_id = _manifest_steam_id(canonical_manifest, required=True)
    if canonical_id.low or canonical_id.high:
        if canonical_id != live_id:
            raise ValidationFailedError(
                "a nonzero canonical SteamModId is permanent and cannot be replaced",
                path=project.layout.manifest,
            )
    _assert_loose_matches_project(project, root, action=PublishAction.UPDATE, sync=True)
    if live_manifest.fields.get("GameVersion") != project.config.compatibility.game_version:
        raise ValidationFailedError(
            "live post-publish manifest does not contain the current GameVersion",
            path=root / "Index.art",
        )
    state_path = project.layout.state_root / "workshop.json"
    _legacy.assert_no_symlink_components(state_path)
    original_state = (
        _read_bounded(state_path, MAX_WORKSHOP_STATE_BYTES) if state_path.exists() else None
    )
    existing_state = (
        WorkshopState.from_bytes(original_state) if original_state is not None else None
    )
    if isinstance(predecessor_ids, (str, bytes)):
        raise ContractError("predecessor_ids must be an iterable of complete SteamModId values")
    parsed_predecessor_list: list[SteamModId] = []
    for item in predecessor_ids:
        if len(parsed_predecessor_list) >= MAX_WORKSHOP_PREDECESSORS:
            raise ContractError(
                f"Workshop sync accepts at most {MAX_WORKSHOP_PREDECESSORS} predecessors"
            )
        parsed_predecessor_list.append(SteamModId.parse(item))
    parsed_predecessors = tuple(parsed_predecessor_list)
    combined = tuple(
        dict.fromkeys(
            (
                *(existing_state.predecessor_ids if existing_state is not None else ()),
                *parsed_predecessors,
            )
        )
    )
    if live_id in combined:
        raise ValidationFailedError(
            "assigned SteamModId is recorded as a deleted predecessor and cannot be reused",
            path=state_path,
        )
    if existing_state is not None:
        if existing_state.status is WorkshopStatus.DELETED_PREDECESSOR:
            raise ValidationFailedError(
                "a deleted Workshop identity cannot be resurrected or synchronized",
                path=state_path,
            )
        state_id = existing_state.steam_mod_id
        if existing_state.status is not WorkshopStatus.UNPUBLISHED and state_id != live_id:
            raise ValidationFailedError(
                "existing Workshop state belongs to another permanent SteamModId",
                path=state_path,
            )
    checked_at = verified_at or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ContractError("verified_at must be timezone-aware")
    checked_at = checked_at.astimezone(UTC).replace(microsecond=0)
    updated_state = WorkshopState(
        status=WorkshopStatus.PUBLISHED,
        steam_mod_id=live_id,
        visibility=visibility,
        predecessor_ids=combined,
        last_verified_at=checked_at.isoformat(),
    )
    original_manifest = _read_bounded(project.layout.manifest, _legacy.MAX_TEXT_ASSET_BYTES)
    updated_manifest = canonical_manifest.updated({"SteamModId": str(live_id)}).to_bytes()
    updated_config = (
        replace(project.config, runtime_status=RuntimeStatus.UNTESTED)
        if canonical_id != live_id
        else project.config
    )
    return WorkshopSyncPlan(
        project=project,
        live_root=root,
        canonical_artifacts=canonical_artifacts,
        live_artifacts=artifacts,
        updated_manifest=updated_manifest,
        updated_config=updated_config,
        updated_state=updated_state,
        original_manifest_sha256=hashlib.sha256(original_manifest).hexdigest(),
        original_config_sha256=project._opened_config_sha256,
        original_state_sha256=(
            hashlib.sha256(original_state).hexdigest() if original_state is not None else None
        ),
        identity_changed=canonical_id != live_id,
    )


def _assert_loose_matches_project(
    project: SDKProject,
    live_root: Path,
    *,
    action: PublishAction,
    sync: bool = False,
) -> None:
    canonical = _capture_project_runtime_artifacts(project.layout.source_root)
    live = _capture_loose_artifacts(
        live_root,
        context=project._refresh_context(),
        require_user_mod_root=True,
    )
    canonical_payload = {
        item.path.casefold(): (item.size, item.sha256)
        for item in canonical
        if item.path.casefold() != "index.art"
    }
    live_payload = {
        item.path.casefold(): (item.size, item.sha256)
        for item in live
        if item.path.casefold() != "index.art"
    }
    if canonical_payload != live_payload:
        raise ValidationFailedError(
            "loose candidate payload or thumbnail differs from canonical project src",
            path=live_root,
        )
    canonical_manifest = project.manifest()
    live_manifest = ManifestDocument.read(live_root / "Index.art")
    live_id = _manifest_steam_id(live_manifest, required=False)
    canonical_id = _manifest_steam_id(canonical_manifest, required=True)
    if action is PublishAction.PUBLISH:
        if live_id is not None and (live_id.low or live_id.high):
            raise ValidationFailedError(
                "new-item loose candidate contains an assigned nonzero SteamModId",
                path=live_root / "Index.art",
            )
        live_game_version = live_manifest.fields.get("GameVersion")
        if live_game_version not in {None, project.config.compatibility.game_version}:
            raise ValidationFailedError(
                "loose first-publish candidate has an unexpected GameVersion",
                path=live_root / "Index.art",
            )
        allowed_manifests = {
            canonical_manifest.to_bytes(),
            _manifest_without_complete_blocks(
                canonical_manifest,
                {"GameVersion", "SteamModId"},
            ),
        }
        if live_manifest.to_bytes() not in allowed_manifests:
            raise ValidationFailedError(
                "first-publish Index.art must be canonical bytes or the exact two-block adapter",
                path=live_root / "Index.art",
            )
    elif live_id is None or not (live_id.low or live_id.high):
        raise ValidationFailedError(
            "Update/post-publish source requires a nonzero SteamModId",
            path=live_root / "Index.art",
        )
    else:
        if canonical_id.low or canonical_id.high:
            if live_id != canonical_id:
                raise ValidationFailedError(
                    "loose candidate targets a different existing SteamModId",
                    path=live_root / "Index.art",
                )
            expected_manifest = canonical_manifest.to_bytes()
        elif sync:
            expected_manifest = canonical_manifest.updated({"SteamModId": str(live_id)}).to_bytes()
        else:
            raise ValidationFailedError(
                "Update requires a canonical nonzero SteamModId",
                path=project.layout.manifest,
            )
        if live_manifest.to_bytes() != expected_manifest:
            raise ValidationFailedError(
                "Update/post-publish Index.art differs beyond the exact Steam identity update",
                path=live_root / "Index.art",
            )


def _assert_staged_matches_project(
    project: SDKProject,
    artifacts: tuple[WorkshopArtifact, ...],
    deterministic_zip: WorkshopArtifact,
) -> None:
    by_path = {item.path: item for item in artifacts}
    canonical_root = _capture_project_runtime_artifacts(project.layout.source_root)
    canonical_by_path = {item.path: item for item in canonical_root}
    for name in ("Index.art", "Thumbnail.jpg"):
        if by_path[name].sha256 != canonical_by_path[name].sha256:
            raise ValidationFailedError(
                f"staged {name} differs from canonical project src",
                path=project.layout.distribution_root / name,
            )
    if by_path["Mod.zip"].sha256 != deterministic_zip.sha256:
        raise ValidationFailedError(
            "staged Mod.zip differs from a fresh deterministic release preview",
            path=project.layout.distribution_root / "Mod.zip",
        )


def _directory_entries(root: Path, *, limit: int) -> dict[str, Path]:
    entries: dict[str, Path] = {}
    folded_names: set[str] = set()
    try:
        with os.scandir(root) as iterator:
            for entry in iterator:
                if len(entries) >= limit:
                    raise ProjectError(
                        f"directory has more than the supported {limit} root entries",
                        path=root,
                    )
                folded = entry.name.casefold()
                if folded in folded_names:
                    raise ProjectError(
                        "directory has duplicate case-insensitive root names",
                        path=root,
                    )
                folded_names.add(folded)
                entries[entry.name] = Path(entry.path)
    except ProjectError:
        raise
    except OSError as exc:
        raise ProjectError(f"cannot enumerate directory: {exc}", path=root) from exc
    return entries


def _capture_project_runtime_artifacts(root: Path) -> tuple[WorkshopArtifact, ...]:
    absolute = _absolute(root)
    _legacy.assert_no_symlink_components(absolute)
    if not absolute.is_dir() or _is_link(absolute):
        raise ProjectError("project source must be a regular directory", path=absolute)
    entries = _directory_entries(absolute, limit=4)
    required = {"Index.art", "Thumbnail.jpg", "Ancient"}
    if set(entries) != required:
        raise ProjectError(
            "project source must contain exactly Index.art, Thumbnail.jpg, and Ancient",
            path=absolute,
        )
    artifacts = [
        _artifact(entries["Index.art"], "Index.art"),
        _artifact(entries["Thumbnail.jpg"], "Thumbnail.jpg"),
    ]
    artifacts.extend(_tree_artifacts(entries["Ancient"], prefix="Ancient"))
    return tuple(sorted(artifacts, key=lambda item: item.path.casefold()))


def _capture_loose_artifacts(
    root: Path,
    *,
    context: _legacy.DiscoveryContext,
    require_user_mod_root: bool,
) -> tuple[WorkshopArtifact, ...]:
    absolute = _absolute(root)
    if absolute.name.isdigit():
        raise ProjectError(
            "numeric Workshop/cache roots cannot be live publish candidates",
            code="WORKSHOP_CANDIDATE_NUMERIC",
            path=absolute,
        )
    if require_user_mod_root:
        if context.user_root is None:
            raise ProjectError("discovered Ancient Cities user root is unavailable")
        expected_parent = _absolute(context.user_root / "Mod")
        if absolute.parent != expected_parent:
            raise ProjectError(
                "loose publish candidate must be a direct child of the discovered user Mod folder",
                code="WORKSHOP_CANDIDATE_SCOPE",
                path=absolute,
            )
    _legacy.assert_no_symlink_components(absolute)
    if not absolute.is_dir() or _is_link(absolute):
        raise ProjectError("loose publish candidate must be a regular directory", path=absolute)
    entries = _directory_entries(absolute, limit=5)
    required = {"Index.art", "Thumbnail.jpg", "Ancient"}
    allowed = required | {"Mod.hms"}
    if not required.issubset(entries):
        missing = ", ".join(sorted(required - set(entries)))
        raise ProjectError(f"loose publish candidate is missing {missing}", path=absolute)
    extras = sorted(set(entries) - allowed)
    if extras:
        raise ProjectError(
            "loose publish candidate has unsupported root entries: " + ", ".join(extras),
            path=absolute,
        )
    if "Mod.hms" in entries:
        mod_hms = entries["Mod.hms"]
        if _is_link(mod_hms) or not mod_hms.is_file() or mod_hms.stat().st_size != 0:
            raise ProjectError(
                "only an empty game-managed root Mod.hms may be ignored",
                path=mod_hms,
            )
    artifacts = [
        _artifact(entries["Index.art"], "Index.art"),
        _artifact(entries["Thumbnail.jpg"], "Thumbnail.jpg"),
    ]
    artifacts.extend(_tree_artifacts(entries["Ancient"], prefix="Ancient"))
    return tuple(sorted(artifacts, key=lambda item: item.path.casefold()))


def _capture_staged_artifacts(root: Path) -> tuple[WorkshopArtifact, ...]:
    absolute = _absolute(root)
    _legacy.assert_no_symlink_components(absolute)
    if not absolute.is_dir() or _is_link(absolute):
        raise ProjectError("staged Workshop candidate must be a regular directory", path=absolute)
    entries = _directory_entries(absolute, limit=4)
    expected = {"Index.art", "Thumbnail.jpg", "Mod.zip"}
    if set(entries) != expected:
        raise ProjectError(
            "staged Workshop candidate must contain exactly Index.art, Thumbnail.jpg, Mod.zip",
            path=absolute,
        )
    return tuple(
        _artifact(
            entries[name],
            name,
            limit=(
                _legacy.MAX_ZIP_TOTAL_BYTES if name == "Mod.zip" else _legacy.MAX_ZIP_MEMBER_BYTES
            ),
        )
        for name in sorted(expected)
    )


def _capture_generated_package(root: Path) -> tuple[WorkshopArtifact, ...]:
    absolute = _absolute(root)
    _legacy.assert_no_symlink_components(absolute)
    if not absolute.is_dir() or _is_link(absolute):
        raise ProjectError(
            "generated game package must be a regular directory",
            path=absolute,
        )
    entries = _directory_entries(absolute, limit=4)
    expected = {"Index.art", "Thumbnail.jpg", "Mod.zip"}
    if set(entries) != expected:
        raise ProjectError(
            "generated game package must contain exactly Index.art, Thumbnail.jpg, Mod.zip",
            path=absolute,
        )
    return tuple(
        _artifact(
            entries[name],
            name,
            limit=(
                _legacy.MAX_ZIP_TOTAL_BYTES if name == "Mod.zip" else _legacy.MAX_ZIP_MEMBER_BYTES
            ),
        )
        for name in sorted(expected)
    )


def _capture_zip_members(archive: Path) -> tuple[WorkshopArtifact, ...]:
    result: list[WorkshopArtifact] = []
    seen: set[str] = set()
    try:
        _legacy._preflight_zip_directory(archive)
        with zipfile.ZipFile(archive, "r") as handle:
            infos = handle.infolist()
            _legacy._check_zip_collection_limits(infos)
            for info in infos:
                problem = _legacy._zip_member_problem(info.filename)
                if problem:
                    raise ProjectError(
                        f"generated Mod.zip has an unsafe member: {problem}",
                        path=archive,
                    )
                if info.is_dir():
                    continue
                folded = info.filename.casefold()
                if folded in seen:
                    raise ProjectError(
                        "generated Mod.zip has duplicate case-insensitive member names",
                        path=archive,
                    )
                seen.add(folded)
                digest = hashlib.sha256()
                size = 0
                with handle.open(info, "r") as member:
                    while chunk := member.read(1024 * 1024):
                        size += len(chunk)
                        if size > _legacy.MAX_ZIP_MEMBER_BYTES:
                            raise ProjectError(
                                "generated Mod.zip member exceeds the per-file size limit",
                                path=archive,
                            )
                        digest.update(chunk)
                if size != info.file_size:
                    raise SourceChangedError(
                        "generated Mod.zip member size changed while reading",
                        path=archive,
                    )
                result.append(WorkshopArtifact(info.filename, size, digest.hexdigest()))
    except ProjectError:
        raise
    except (_legacy.ModToolError, OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ProjectError(f"cannot inspect generated Mod.zip: {exc}", path=archive) from exc
    return tuple(sorted(result, key=lambda item: item.path.casefold()))


def _assert_generated_package_matches_loose(
    loose: tuple[WorkshopArtifact, ...],
    package: tuple[WorkshopArtifact, ...],
    members: tuple[WorkshopArtifact, ...],
    package_root: Path,
) -> None:
    loose_by_path = {item.path: item for item in loose}
    package_by_path = {item.path: item for item in package}
    for name in ("Index.art", "Thumbnail.jpg"):
        if package_by_path[name] != loose_by_path[name]:
            raise ValidationFailedError(
                f"generated game package {name} differs from the selected loose root",
                path=package_root / name,
            )
    expected_members = tuple(item for item in loose if item.path.startswith("Ancient/"))
    if members != expected_members:
        raise ValidationFailedError(
            "generated game Mod.zip inventory or member bytes differ from the loose Ancient tree",
            path=package_root / "Mod.zip",
        )


def _tree_artifacts(root: Path, *, prefix: str) -> list[WorkshopArtifact]:
    if not root.is_dir() or _is_link(root):
        raise ProjectError("Ancient payload must be a regular directory", path=root)
    result: list[WorkshopArtifact] = []
    total = 0
    try:
        entries = _legacy._bounded_tree_entries(root, limit=_legacy.MAX_ZIP_FILES)
    except _legacy.ModToolError as exc:
        raise ProjectError(f"cannot enumerate Workshop payload: {exc}", path=root) from exc
    seen: set[str] = set()
    for path in entries:
        if _is_link(path):
            raise ProjectError("Workshop payload cannot contain links or junctions", path=path)
        if path.is_dir():
            continue
        if not path.is_file():
            raise ProjectError("Workshop payload contains a non-regular entry", path=path)
        relative = PurePosixPath(prefix) / PurePosixPath(path.relative_to(root).as_posix())
        folded = relative.as_posix().casefold()
        if folded in seen:
            raise ProjectError(
                "Workshop payload has duplicate case-insensitive paths",
                path=path,
            )
        seen.add(folded)
        artifact = _artifact(path, relative.as_posix())
        total += artifact.size
        if total > _legacy.MAX_ZIP_TOTAL_BYTES:
            raise ProjectError("Workshop payload exceeds the total size limit", path=root)
        result.append(artifact)
        if len(result) > _legacy.MAX_ZIP_FILES:
            raise ProjectError("Workshop payload exceeds the file-count limit", path=root)
    return result


def _artifact(
    path: Path,
    relative: str,
    *,
    limit: int = _legacy.MAX_ZIP_MEMBER_BYTES,
) -> WorkshopArtifact:
    if _is_link(path) or not path.is_file():
        raise ProjectError("Workshop artifact must be a regular file", path=path)
    size = path.stat().st_size
    if size > limit:
        raise ProjectError("Workshop artifact exceeds its size limit", path=path)
    digest = hashlib.sha256()
    read = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                read += len(chunk)
                if read > limit:
                    raise SourceChangedError("Workshop artifact grew while hashing", path=path)
                digest.update(chunk)
    except OSError as exc:
        raise ProjectError(f"cannot hash Workshop artifact: {exc}", path=path) from exc
    if read != size:
        raise SourceChangedError("Workshop artifact changed while hashing", path=path)
    return WorkshopArtifact(relative, size, digest.hexdigest())


def _manifest_without_complete_blocks(
    manifest: ManifestDocument,
    field_names: set[str],
) -> bytes:
    spans: dict[str, tuple[int, int]] = {}
    try:
        for _, body, start, end, _, _ in _legacy._iter_art_block_spans(manifest.document.text):
            name = _legacy._body_property(body, "Name")
            if name not in field_names:
                continue
            if name in spans:
                raise ContractError(f"cannot apply identity adapter to duplicate {name} blocks")
            spans[name] = (start, end)
    except _legacy.ModToolError as exc:
        raise ContractError(f"cannot inspect manifest identity blocks: {exc}") from exc
    if set(spans) != field_names:
        missing = ", ".join(sorted(field_names - set(spans)))
        raise ContractError(f"cannot apply identity adapter; missing complete blocks: {missing}")
    text = manifest.document.text
    for start, end in sorted(spans.values(), reverse=True):
        text = text[:start] + text[end:]
    try:
        return _legacy.encode_utf16le_art(text)
    except _legacy.ModToolError as exc:
        raise ContractError(f"cannot encode exact identity adapter: {exc}") from exc


@overload
def _manifest_steam_id(manifest: ManifestDocument, *, required: Literal[True]) -> SteamModId: ...


@overload
def _manifest_steam_id(
    manifest: ManifestDocument, *, required: Literal[False]
) -> SteamModId | None: ...


def _manifest_steam_id(manifest: ManifestDocument, *, required: bool) -> SteamModId | None:
    value = manifest.fields.get("SteamModId")
    if value is None:
        if required:
            raise ValidationFailedError("manifest is missing SteamModId")
        return None
    return SteamModId.parse(value)


def _rollback_sync(
    *,
    config_path: Path,
    original_config: bytes,
    written_config: bytes,
    manifest_path: Path,
    original_manifest: bytes,
    written_manifest: bytes,
    state_path: Path,
    original_state: bytes | None,
    written_state: bytes,
) -> list[str]:
    errors: list[str] = []
    for label, path, original, written in (
        ("acmk.toml", config_path, original_config, written_config),
        ("Index.art", manifest_path, original_manifest, written_manifest),
        ("workshop.json", state_path, original_state, written_state),
    ):
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


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except OSError as exc:
        raise ProjectError(f"cannot read {path.name}: {exc}", path=path) from exc
    if len(payload) > limit:
        raise ProjectError(f"{path.name} exceeds the size limit", path=path)
    return payload


def _load_project_workshop_state(project: SDKProject) -> WorkshopState | None:
    state_path = project.layout.state_root / "workshop.json"
    _legacy.assert_no_symlink_components(state_path)
    if not state_path.exists():
        return None
    return WorkshopState.from_bytes(_read_bounded(state_path, MAX_WORKSHOP_STATE_BYTES))


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_link(path: Path) -> bool:
    try:
        return bool(_legacy.path_is_link_like(path))
    except OSError as exc:
        raise ProjectError(f"cannot inspect path safety: {exc}", path=path) from exc


def _strict_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"Workshop state {label} must be a string")
    return value


def _strict_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"Workshop state {label} must be an integer")
    return value


def _canonical_state_steam_id(value: str) -> SteamModId:
    parsed = SteamModId.parse(value)
    if value != str(parsed):
        raise ContractError("Workshop state SteamModId values must use canonical U32x2 form")
    return parsed


def _parse_utc_timestamp(value: str) -> datetime:
    if not _RFC3339_TIMESTAMP.fullmatch(value):
        raise ContractError("Workshop timestamp must use canonical RFC 3339 form")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError("Workshop timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError("Workshop timestamp must include a timezone")
    return parsed.astimezone(UTC)


__all__ = [
    "CandidateKind",
    "PUBLISH_PACKET_SCHEMA_VERSION",
    "PublishAction",
    "PublishPacket",
    "VisibilityControl",
    "WORKSHOP_APP_ID",
    "WORKSHOP_STATE_SCHEMA_VERSION",
    "WorkshopArtifact",
    "WorkshopState",
    "WorkshopStatus",
    "WorkshopSyncPlan",
    "WorkshopSyncResult",
    "WorkshopVisibility",
    "plan_workshop_sync",
    "prepare_publish_packet",
]

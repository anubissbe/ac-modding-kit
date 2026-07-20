"""High-level, typed entry point for the Ancient Cities community SDK."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ancient_cities_mod as _legacy

from .builder import DraftProjectBuilder
from .building import BuildingScaffoldBuilder, BuildingSpec
from .config import ProvenanceStatus
from .doctor import run_doctor
from .errors import ACMKError
from .manifest import ManifestSpec
from .project import ObservedConsensusPlan, ProjectImporter, ProjectImportPlan, SDKProject
from .reports import DiscoverySnapshot, DoctorReport, ValidationProfile, ValidationReport


@dataclass(frozen=True, slots=True)
class DiscoveryOptions:
    steam_root: Path | None = None
    game_dir: Path | None = None
    documents_dir: Path | None = None


class AncientCitiesSDK:
    """Stateful facade that binds operations to one discovered installation.

    Discovery is lazy and cached. Pass ``refresh=True`` after a game update,
    Steam library change, or mod load-order change.
    """

    def __init__(self, options: DiscoveryOptions | None = None) -> None:
        self.options = options or DiscoveryOptions()
        self._context: _legacy.DiscoveryContext | None = None

    def discover(self, *, refresh: bool = False) -> DiscoverySnapshot:
        return DiscoverySnapshot.from_mapping(
            _legacy.context_to_dict(self.context(refresh=refresh))
        )

    def context(self, *, refresh: bool = False) -> _legacy.DiscoveryContext:
        if refresh or self._context is None:
            try:
                self._context = _legacy.discover_context(
                    steam_root=self.options.steam_root,
                    game_dir=self.options.game_dir,
                    documents_dir=self.options.documents_dir,
                )
            except _legacy.ModToolError as exc:
                raise ACMKError(str(exc), code="DISCOVERY_FAILED") from exc
        return self._context

    def doctor(
        self,
        *,
        blender: str | os.PathLike[str] | None = None,
        refresh: bool = False,
    ) -> DoctorReport:
        return run_doctor(self.context(refresh=refresh), blender=blender)

    def open_project(self, root: str | os.PathLike[str], *, refresh: bool = False) -> SDKProject:
        return SDKProject.open(
            root,
            context=self.context(refresh=refresh),
            context_refresher=lambda: self.context(refresh=True),
        )

    def plan_import(
        self,
        source: str | os.PathLike[str],
        target: str | os.PathLike[str],
        *,
        identifier: str,
        version: str = "0.1.0",
        license: str = "NOASSERTION",
        contact: str = "",
        provenance_status: ProvenanceStatus = ProvenanceStatus.UNREVIEWED,
        provenance_notes: str = "",
    ) -> ProjectImportPlan:
        return ProjectImporter.plan(
            source,
            target,
            identifier=identifier,
            version=version,
            license=license,
            contact=contact,
            provenance_status=provenance_status,
            provenance_notes=provenance_notes,
            context=self.context(),
            context_refresher=lambda: self.context(refresh=True),
        )

    def plan_observed_consensus(
        self, root: str | os.PathLike[str], *, refresh: bool = False
    ) -> ObservedConsensusPlan:
        """Plan an evidence-backed reconciliation for one supported exact game build."""

        return self.open_project(root, refresh=refresh).plan_observed_consensus()

    def draft_builder(
        self,
        target: str | os.PathLike[str],
        *,
        identifier: str,
        manifest: ManifestSpec,
        version: str = "0.1.0",
        license: str = "NOASSERTION",
        contact: str = "",
        dependencies: Sequence[str] = (),
        conflicts: Sequence[str] = (),
    ) -> DraftProjectBuilder:
        """Create a noncanonical draft builder with live context rechecks on apply."""

        return DraftProjectBuilder(
            target,
            identifier=identifier,
            manifest=manifest,
            context=self.context(),
            version=version,
            license=license,
            contact=contact,
            dependencies=dependencies,
            conflicts=conflicts,
            context_refresher=lambda: self.context(refresh=True),
        )

    def standalone_building_builder(
        self,
        target: str | os.PathLike[str],
        *,
        project_identifier: str,
        manifest: ManifestSpec,
        building: BuildingSpec,
        version: str = "0.1.0",
        license: str = "NOASSERTION",
        contact: str = "",
    ) -> BuildingScaffoldBuilder:
        """Create a dry-run-first, explicitly noncanonical building scaffold."""

        return BuildingScaffoldBuilder(
            target,
            project_identifier=project_identifier,
            manifest=manifest,
            building=building,
            context=self.context(),
            version=version,
            license=license,
            contact=contact,
            context_refresher=lambda: self.context(refresh=True),
        )

    def validate(
        self,
        target: str | os.PathLike[str],
        *,
        profile: ValidationProfile = ValidationProfile.AUTHORING,
    ) -> ValidationReport:
        path = Path(target)
        if path.is_dir() and (path / "acmk.toml").is_file():
            return self.open_project(path).validate(profile)
        try:
            raw = _legacy.validate_target(path, self.context())
        except _legacy.ModToolError as exc:
            raise ACMKError(str(exc), code="VALIDATION_FAILED", path=path) from exc
        return ValidationReport.from_legacy(raw, profile=profile)

    def catalog(
        self,
        paths: Sequence[str | os.PathLike[str]] = (),
        *,
        query: str | None = None,
    ) -> Mapping[str, Any]:
        """Compatibility catalog payload; a typed catalog model is planned before API v2."""

        return dict(
            _legacy.catalog_mods(self.context(), [Path(path) for path in paths], query=query)
        )

    def conflicts(self, paths: Sequence[str | os.PathLike[str]]) -> Mapping[str, Any]:
        """Compatibility conflict payload preserving current CLI JSON fields."""

        return dict(_legacy.find_conflicts([Path(path) for path in paths], self.context()))

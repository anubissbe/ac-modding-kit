"""Read-only environment diagnostics for Ancient Cities mod authoring."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import ancient_cities_mod as _legacy

from .reports import CheckStatus, DiscoverySnapshot, DoctorCheck, DoctorReport


def run_doctor(
    context: _legacy.DiscoveryContext,
    *,
    blender: str | os.PathLike[str] | None = None,
) -> DoctorReport:
    snapshot = DiscoverySnapshot.from_mapping(_legacy.context_to_dict(context))
    checks: list[DoctorCheck] = [
        DoctorCheck(
            "python",
            CheckStatus.PASS if sys.version_info >= (3, 11) else CheckStatus.FAIL,
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        _path_check("game-install", context.game_dir, directory=True),
        _path_check("base-data", context.base_data_root, directory=True),
        _path_check("documents", context.documents_dir, directory=True),
        _path_check(
            "user-mod-directory",
            context.user_root / "Mod" if context.user_root else None,
            directory=True,
            missing_status=CheckStatus.WARNING,
        ),
        _value_check("semantic-version", context.semver),
        _value_check("steam-build", context.build_id),
        _value_check("content-hash", context.content_hash),
        _value_check("game-version", context.game_version),
    ]
    checks.append(_blender_check(_find_blender(blender)))
    return DoctorReport(tuple(checks), snapshot)


def _path_check(
    name: str,
    path: Path | None,
    *,
    directory: bool,
    missing_status: CheckStatus = CheckStatus.FAIL,
) -> DoctorCheck:
    exists = path is not None and (path.is_dir() if directory else path.is_file())
    if exists:
        return DoctorCheck(name, CheckStatus.PASS, str(path))
    return DoctorCheck(name, missing_status, f"not found: {path}" if path else "not discovered")


def _value_check(name: str, value: str | None) -> DoctorCheck:
    return DoctorCheck(
        name,
        CheckStatus.PASS if value else CheckStatus.FAIL,
        value or "not discovered",
    )


def _find_blender(explicit: str | os.PathLike[str] | None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    configured = os.environ.get("ACMK_BLENDER")
    if configured:
        candidates.append(Path(configured))
    executable = shutil.which("blender")
    if executable:
        candidates.append(Path(executable))
    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    for root in (Path(value) for value in program_files if value):
        candidates.extend(
            sorted(root.glob("Blender Foundation/Blender */blender.exe"), reverse=True)
        )
    candidates.extend(
        sorted(
            (Path.home() / "Documents" / "Codex" / "tools").glob("blender-*/blender.exe"),
            reverse=True,
        )
    )
    module_path = Path(__file__).resolve()
    for parent in module_path.parents[:8]:
        tools = parent / "tools"
        if tools.is_dir():
            candidates.extend(sorted(tools.glob("blender-*/blender.exe"), reverse=True))
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.resolve(strict=False)))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate.resolve()
    return None


def _blender_check(path: Path | None) -> DoctorCheck:
    if path is None:
        return DoctorCheck(
            "blender",
            CheckStatus.WARNING,
            "not found; set ACMK_BLENDER or pass an explicit path for model workflows",
        )
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return DoctorCheck("blender", CheckStatus.FAIL, f"cannot execute {path}: {exc}")
    first_line = (completed.stdout or completed.stderr).splitlines()
    version_line = first_line[0].strip() if first_line else "unknown version"
    match = re.search(r"Blender\s+([0-9]+\.[0-9]+\.[0-9]+)", version_line)
    if completed.returncode != 0 or match is None:
        return DoctorCheck("blender", CheckStatus.FAIL, f"unexpected Blender output from {path}")
    status = CheckStatus.PASS if match.group(1) == "5.2.0" else CheckStatus.WARNING
    message = f"{version_line} at {path}"
    if status is CheckStatus.WARNING:
        message += "; the tested ACMK authoring-tool target is Blender 5.2.0 LTS"
    return DoctorCheck("blender", status, message, {"path": str(path), "version": match.group(1)})

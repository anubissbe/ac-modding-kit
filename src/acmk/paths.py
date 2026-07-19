"""Value objects for engine content paths and SDK project paths."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import UnsafePathError

_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
    "COM¹",
    "COM²",
    "COM³",
    "LPT¹",
    "LPT²",
    "LPT³",
}
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_WINDOWS_FORBIDDEN = re.compile(r'[<>:"|?*\x00-\x1f]')


def _validate_segments(value: str, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise UnsafePathError(f"{label} must be a string")
    if not value or "\x00" in value:
        raise UnsafePathError(f"{label} cannot be empty or contain NUL")
    if "\\" in value:
        raise UnsafePathError(f"{label} must use forward slashes, not backslashes")
    if value.startswith("/") or _DRIVE_PREFIX.match(value):
        raise UnsafePathError(f"{label} must be relative")
    raw = value.split("/")
    if any(part in {"", ".", ".."} for part in raw):
        raise UnsafePathError(f"{label} contains an empty, dot, or parent segment")
    for part in raw:
        if _WINDOWS_FORBIDDEN.search(part):
            raise UnsafePathError(f"{label} contains a character forbidden by Windows")
        if part.endswith((" ", ".")):
            raise UnsafePathError(f"{label} has a Windows-ambiguous segment: {part!r}")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise UnsafePathError(f"{label} uses reserved Windows name {part!r}")
    return tuple(raw)


@dataclass(frozen=True, slots=True, order=True)
class AncientPath:
    """Exact virtual file path rooted at ``Ancient/``.

    Engine references such as ``~/``, ``/System/`` and ``../`` are deliberately
    not represented by this type; they are opaque references, not files.
    """

    value: str

    def __post_init__(self) -> None:
        parts = _validate_segments(self.value, label="Ancient path")
        if parts[0] != "Ancient":
            raise UnsafePathError("Ancient path must start with exact-case 'Ancient/'")
        if len(parts) == 1:
            raise UnsafePathError("Ancient path must identify a payload file")

    @classmethod
    def from_payload(cls, value: str | PurePosixPath) -> AncientPath:
        text = str(value)
        first = text.replace("\\", "/").split("/", 1)[0]
        if first.casefold() == "ancient" and first != "Ancient":
            raise UnsafePathError("Ancient payload root must use exact case")
        return cls(text if text.startswith("Ancient/") else f"Ancient/{text}")

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.value).suffix

    @property
    def relative(self) -> PurePosixPath:
        return PurePosixPath(*PurePosixPath(self.value).parts[1:])

    def on_disk(self, source_root: Path) -> Path:
        candidate = source_root.joinpath(*PurePosixPath(self.value).parts)
        try:
            candidate.resolve(strict=False).relative_to(source_root.resolve(strict=False))
        except ValueError as exc:  # Defensive: constructor already rejects traversal.
            raise UnsafePathError("Ancient path escapes its source root") from exc
        return candidate

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class EngineReference:
    """Opaque engine-node reference that must never be resolved as a file path."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise UnsafePathError("engine reference must be a string")
        if not self.value or "\x00" in self.value:
            raise UnsafePathError("engine reference cannot be empty or contain NUL")
        if not self.value.startswith(("~/", "/System/", "../")):
            raise UnsafePathError("value is not a recognized opaque engine reference")


@dataclass(frozen=True, slots=True)
class ProjectRelativePath:
    """Portable, relative path stored in ``acmk.toml``."""

    value: str

    def __post_init__(self) -> None:
        _validate_segments(self.value, label="project path")

    def resolve(self, root: Path) -> Path:
        lexical_root = Path(os.path.abspath(os.fspath(root.expanduser())))
        candidate = lexical_root.joinpath(*PurePosixPath(self.value).parts)
        try:
            candidate.relative_to(lexical_root)
        except ValueError as exc:
            raise UnsafePathError("project path escapes the project root") from exc
        return candidate

    def __str__(self) -> str:
        return self.value

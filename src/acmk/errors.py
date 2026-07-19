"""Stable exception hierarchy for the public Python SDK."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ancient_cities_mod as _legacy


class ACMKError(_legacy.ModToolError):
    """Base class for expected SDK failures.

    ``code`` is stable within a major SDK API version. ``path`` and ``detail``
    are optional structured context and are safe to serialize.
    """

    default_code = "SDK_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        path: str | Path | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.path = Path(path) if path is not None else None
        self.detail = dict(detail or {})

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.path is not None:
            result["path"] = str(self.path)
        if self.detail:
            result["detail"] = dict(self.detail)
        return result


class ContractError(ACMKError):
    """Input violates a versioned SDK contract."""

    default_code = "CONTRACT_ERROR"


class UnsafePathError(ContractError):
    """A path is ambiguous, escapes its root, or is unsafe on Windows."""

    default_code = "UNSAFE_PATH"


class ProjectError(ACMKError):
    """An ACMK authoring project is malformed or cannot be changed safely."""

    default_code = "PROJECT_ERROR"


class SourceChangedError(ProjectError):
    """A planned source changed before an operation was applied."""

    default_code = "SOURCE_CHANGED"


class ValidationFailedError(ProjectError):
    """Release or build validation failed."""

    default_code = "VALIDATION_FAILED"


# Compatibility alias for callers migrating from the original single module.
LegacyModToolError = _legacy.ModToolError

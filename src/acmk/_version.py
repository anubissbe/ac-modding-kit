"""Version identifiers for the public ACMK contracts."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

DIST_NAME = "ancient-cities-modding-kit"
SDK_API_VERSION = "1"
PROJECT_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = "1"
RUNTIME_TEST_SCHEMA_VERSION = 3

try:
    __version__ = version(DIST_NAME)
except PackageNotFoundError:  # Source checkout without an editable installation.
    __version__ = "0+unknown"

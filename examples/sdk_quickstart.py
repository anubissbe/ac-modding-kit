"""Read-only SDK discovery and authoring validation example."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acmk import AncientCitiesSDK, ValidationProfile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", nargs="?", type=Path)
    args = parser.parse_args()

    sdk = AncientCitiesSDK()
    print(json.dumps(sdk.discover().to_dict(), indent=2))
    if args.project is None:
        return 0
    report = sdk.validate(args.project, profile=ValidationProfile.AUTHORING)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

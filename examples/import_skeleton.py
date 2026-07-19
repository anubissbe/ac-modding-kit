"""Preview importing a game-generated skeleton; does not write by default."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acmk import AncientCitiesSDK


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--id", required=True, dest="identifier")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    sdk = AncientCitiesSDK()
    plan = sdk.plan_import(args.source, args.target, identifier=args.identifier)
    result = plan.apply() if args.apply else plan.preview()
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

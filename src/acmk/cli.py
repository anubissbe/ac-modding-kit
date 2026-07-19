"""CLI bridge: new SDK commands plus complete legacy-command compatibility."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import ancient_cities_mod as _legacy

from ._version import (
    PROJECT_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    RUNTIME_TEST_SCHEMA_VERSION,
    SDK_API_VERSION,
    __version__,
)
from .config import AchievementImpact, ProvenanceStatus, RuntimeSaveType, SaveImpact
from .errors import ACMKError
from .reports import ValidationProfile, envelope
from .sdk import AncientCitiesSDK, DiscoveryOptions

_SDK_COMMANDS = {"doctor", "knowledge", "project", "sdk-info"}
_LEGACY_COMMANDS = (
    "discover, catalog, inspect, validate, conflicts, metadata, init-project, build, log, self-test"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_program_name(),
        description="Ancient Cities community SDK and backwards-compatible mod CLI.",
        epilog=f"Existing commands remain available unchanged: {_LEGACY_COMMANDS}.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a versioned JSON envelope for new SDK commands",
    )
    parser.add_argument("--steam-root")
    parser.add_argument("--game-dir")
    parser.add_argument("--documents-dir")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check the live game, user folders, and Blender")
    doctor.add_argument("--blender", help="explicit Blender executable")
    doctor.add_argument("--refresh", action="store_true")

    sub.add_parser("sdk-info", help="show versioned SDK contract information")

    knowledge = sub.add_parser(
        "knowledge", help="read or search the bundled audited knowledge base"
    )
    knowledge_sub = knowledge.add_subparsers(dest="knowledge_command", required=True)
    knowledge_sub.add_parser("list", help="list bundled knowledge topics")
    knowledge_read = knowledge_sub.add_parser("read", help="read one knowledge topic")
    knowledge_read.add_argument("topic")
    knowledge_search = knowledge_sub.add_parser("search", help="search bundled knowledge")
    knowledge_search.add_argument("query")
    knowledge_search.add_argument("--limit", type=int, default=10)

    project = sub.add_parser("project", help="manage a structured ACMK authoring project")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_import = project_sub.add_parser(
        "import", help="import a current game-generated loose skeleton into a new project"
    )
    project_import.add_argument("source")
    project_import.add_argument("target")
    project_import.add_argument("--id", required=True, dest="identifier")
    project_import.add_argument("--version", default="0.1.0")
    project_import.add_argument("--license", default="NOASSERTION")
    project_import.add_argument("--contact", default="")
    project_import.add_argument(
        "--provenance",
        choices=tuple(item.value for item in ProvenanceStatus),
        default=ProvenanceStatus.UNREVIEWED.value,
    )
    project_import.add_argument("--provenance-notes", default="")
    project_import.add_argument("--apply", action="store_true")

    project_show = project_sub.add_parser("show", help="show parsed acmk.toml and project paths")
    project_show.add_argument("root")

    project_configure = project_sub.add_parser(
        "configure", help="update version, contact, license, or provenance metadata"
    )
    project_configure.add_argument("root")
    project_configure.add_argument("--name")
    project_configure.add_argument("--version")
    project_configure.add_argument("--license")
    project_configure.add_argument("--contact")
    project_configure.add_argument(
        "--provenance",
        choices=tuple(item.value for item in ProvenanceStatus),
    )
    project_configure.add_argument("--provenance-notes")
    project_configure.add_argument("--apply", action="store_true")

    project_check = project_sub.add_parser("check", help="validate an authoring or release profile")
    project_check.add_argument("root")
    project_check.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in ValidationProfile),
        default=ValidationProfile.AUTHORING.value,
    )

    project_stage = project_sub.add_parser(
        "stage", help="build an isolated Workshop directory; never uploads it"
    )
    project_stage.add_argument("root")
    project_stage.add_argument("--apply", action="store_true")
    project_stage.add_argument(
        "--replace",
        action="store_true",
        help="back up and replace an existing staged directory (requires --apply)",
    )
    project_test = project_sub.add_parser(
        "record-test", help="record a completed manual in-game test and sanitized log summary"
    )
    project_test.add_argument("root")
    project_test.add_argument("--log", required=True)
    project_test.add_argument("--result", choices=("passed", "failed"), required=True)
    project_test.add_argument(
        "--save-impact",
        choices=tuple(item.value for item in SaveImpact),
        required=True,
    )
    project_test.add_argument(
        "--achievement-impact",
        choices=tuple(item.value for item in AchievementImpact),
        required=True,
    )
    project_test.add_argument(
        "--save-type",
        choices=tuple(item.value for item in RuntimeSaveType),
        required=True,
    )
    project_test.add_argument(
        "--clean-launch",
        action="store_true",
        required=True,
        help="confirm the test started from a complete clean game launch",
    )
    project_test.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = _command_name(arguments)
    if command not in _SDK_COMMANDS:
        if command is None and any(item in {"-h", "--help", "--version"} for item in arguments):
            try:
                build_parser().parse_args(arguments)
            except SystemExit as exc:
                return int(exc.code or 0)
            return 0
        return _legacy.main(arguments)

    parser = build_parser()
    args = parser.parse_args(arguments)
    sdk = AncientCitiesSDK(
        DiscoveryOptions(
            steam_root=Path(args.steam_root) if args.steam_root else None,
            game_dir=Path(args.game_dir) if args.game_dir else None,
            documents_dir=Path(args.documents_dir) if args.documents_dir else None,
        )
    )
    try:
        data, ok = _dispatch(args, sdk)
    except (ACMKError, _legacy.ModToolError) as exc:
        issue = (
            exc.to_dict()
            if isinstance(exc, ACMKError)
            else {"code": "LEGACY_ERROR", "message": str(exc)}
        )
        payload = envelope(_command_label(args), {}, ok=False, issues=(issue,))
        _emit(payload, json_mode=args.json)
        return 1
    payload = envelope(_command_label(args), data, ok=ok)
    _emit(payload if args.json else data, json_mode=args.json)
    return 0 if ok else 1


def _dispatch(args: argparse.Namespace, sdk: AncientCitiesSDK) -> tuple[Mapping[str, Any], bool]:
    if args.command == "sdk-info":
        return (
            {
                "tool_version": __version__,
                "sdk_api_version": SDK_API_VERSION,
                "project_schema_version": PROJECT_SCHEMA_VERSION,
                "report_schema_version": REPORT_SCHEMA_VERSION,
                "runtime_test_schema_version": RUNTIME_TEST_SCHEMA_VERSION,
                "runtime": "stdlib-only",
                "publishes_workshop_items": False,
                "supported_interface": ["ART", "LOC", "assets", "FBX", "WAV", "overlay paths"],
                "unsupported_interface": ["DLL plugins", "C# plugins", "BepInEx", "Harmony"],
            },
            True,
        )
    if args.command == "doctor":
        doctor_report = sdk.doctor(blender=args.blender, refresh=args.refresh)
        return doctor_report.to_dict(), doctor_report.ok
    if args.command == "knowledge":
        from . import knowledge

        if args.knowledge_command == "list":
            topics = [{"id": topic.id, "title": topic.title} for topic in knowledge.topics()]
            return {"count": len(topics), "topics": topics}, True
        if args.knowledge_command == "read":
            document = knowledge.read(args.topic)
            return {
                "topic": {"id": document.topic.id, "title": document.topic.title},
                "text": document.text,
            }, True
        hits = [
            {
                "topic": {"id": hit.topic.id, "title": hit.topic.title},
                "line_number": hit.line_number,
                "excerpt": hit.excerpt,
            }
            for hit in knowledge.search(args.query, limit=args.limit)
        ]
        return {"query": args.query, "count": len(hits), "hits": hits}, True
    if args.command == "project":
        if args.project_command == "import":
            plan = sdk.plan_import(
                args.source,
                args.target,
                identifier=args.identifier,
                version=args.version,
                license=args.license,
                contact=args.contact,
                provenance_status=ProvenanceStatus(args.provenance),
                provenance_notes=args.provenance_notes,
            )
            result = plan.apply() if args.apply else plan.preview()
            return result.to_dict(), True
        project = sdk.open_project(args.root)
        if args.project_command == "show":
            return {
                "root": str(project.layout.root),
                "config": project.config.to_dict(),
                "paths": {
                    "source": str(project.layout.source_root),
                    "assets": str(project.layout.assets_root),
                    "state": str(project.layout.state_root),
                    "distribution": str(project.layout.distribution_root),
                },
            }, True
        if args.project_command == "configure":
            config_plan = project.plan_configuration(
                name=args.name,
                version=args.version,
                license=args.license,
                contact=args.contact,
                provenance_status=(ProvenanceStatus(args.provenance) if args.provenance else None),
                provenance_notes=args.provenance_notes,
            )
            config_result = config_plan.apply() if args.apply else config_plan.preview()
            return config_result.to_dict(), True
        if args.project_command == "check":
            validation_report = project.validate(ValidationProfile(args.profile))
            return validation_report.to_dict(), validation_report.valid
        if args.project_command == "record-test":
            test_plan = project.plan_runtime_test(
                args.log,
                passed=args.result == "passed",
                save_impact=SaveImpact(args.save_impact),
                achievement_impact=AchievementImpact(args.achievement_impact),
                clean_launch=args.clean_launch,
                save_type=RuntimeSaveType(args.save_type),
            )
            test_result = test_plan.apply() if args.apply else test_plan.preview()
            return test_result.to_dict(), True
        if args.replace and not args.apply:
            raise ACMKError("--replace requires --apply", code="ARGUMENT_CONFLICT")
        release_plan = project.plan_release()
        release_result = (
            release_plan.apply(replace=args.replace) if args.apply else release_plan.preview()
        )
        return release_result.to_dict(), True
    raise ACMKError("unknown SDK command", code="COMMAND_UNKNOWN")


def _command_name(arguments: Sequence[str]) -> str | None:
    options_with_values = {"--steam-root", "--game-dir", "--documents-dir"}
    skip = False
    for argument in arguments:
        if skip:
            skip = False
            continue
        if argument in options_with_values:
            skip = True
            continue
        if (
            argument.startswith("--steam-root=")
            or argument.startswith("--game-dir=")
            or argument.startswith("--documents-dir=")
        ):
            continue
        if argument.startswith("-"):
            continue
        return argument
    return None


def _command_label(args: argparse.Namespace) -> str:
    for attribute in ("project_command", "knowledge_command"):
        value = getattr(args, attribute, None)
        if value:
            return f"{args.command}.{value}"
    return str(args.command)


def _program_name() -> str:
    name = Path(sys.argv[0]).name
    if name.casefold() == "__main__.py":
        return "acmk"
    return name[:-4] if name.casefold().endswith(".exe") else name


def _emit(value: Mapping[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))

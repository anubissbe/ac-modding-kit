#!/usr/bin/env python3
"""Ancient Cities mod inspection, validation, and packaging toolkit.

This module intentionally uses only the Python 3.11 standard library.  All
discovery and inspection commands are read-only.  Mutating commands are dry
run by default and refuse to write into the game installation, Steam Workshop
cache, or Ancient Cities' extracted user-mod cache.
"""

from __future__ import annotations

import argparse
import codecs
import ctypes
import difflib
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

APP_ID = "667610"
GAME_NAME = "Ancient Cities"
USER_FOLDER = Path("Uncasual Games") / GAME_NAME
UTF16LE_BOM = codecs.BOM_UTF16_LE
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXECUTABLE_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".cpl",
    ".dll",
    ".exe",
    ".hta",
    ".jar",
    ".js",
    ".jse",
    ".lnk",
    ".msi",
    ".msp",
    ".pif",
    ".ps1",
    ".reg",
    ".scr",
    ".vbe",
    ".vbs",
    ".wsf",
}
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".wav", ".fbx"}
MAX_ZIP_FILES = 10_000
MAX_ZIP_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 500
MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 64 * 1024 * 1024
MAX_ZIP64_END_RECORD_BYTES = 1024 * 1024
MAX_IN_MEMORY_ZIP_BYTES = 256 * 1024 * 1024
MAX_TEXT_ASSET_BYTES = 16 * 1024 * 1024
MAX_LOG_BYTES = 256 * 1024 * 1024
MAX_ART_BLOCKS = 50_000
MAX_ART_NESTING = 64
MAX_ART_PROPERTY_SCAN_CHARS = 64 * 1024 * 1024
MAX_ART_BLOCK_SCAN_MULTIPLIER = 2
MANIFEST_REQUIRED_FIELDS = (
    "Title",
    "Description",
    "Changelog",
    "GameVersion",
    "SteamModId",
    "Type",
)
MANIFEST_FIELD_KINDS: Mapping[str, str] = {
    "Changelog": "String",
    "Content": "String",
    "Date": "String",
    "Description": "String",
    "GameVersion": "String",
    "SteamModId": "U32x2",
    "Title": "String",
    "Type": "String",
    "Version": "F32",
}
MUTABLE_METADATA_FIELDS: Mapping[str, str] = {
    "changelog": "Changelog",
    "content": "Content",
    "date": "Date",
    "description": "Description",
    "gameversion": "GameVersion",
    "game-version": "GameVersion",
    "steammodid": "SteamModId",
    "steam-mod-id": "SteamModId",
    "title": "Title",
    "type": "Type",
    "version": "Version",
}


class ModToolError(RuntimeError):
    """Expected user-facing error."""


class ZipPreflightError(ModToolError):
    """ZIP central-directory failure detected before ZipFile allocates entries."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class Issue:
    severity: str
    code: str
    message: str
    path: str | None = None
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        return {key: value for key, value in result.items() if value is not None}


@dataclass(slots=True)
class SteamInstall:
    appmanifest: Path
    library_root: Path
    game_dir: Path
    build_id: str | None
    state_flags: str | None
    install_dir_name: str


@dataclass(slots=True)
class DiscoveryContext:
    steam_roots: list[Path] = field(default_factory=list)
    library_roots: list[Path] = field(default_factory=list)
    installs: list[SteamInstall] = field(default_factory=list)
    game_dir: Path | None = None
    appmanifest: Path | None = None
    workshop_roots: list[Path] = field(default_factory=list)
    documents_dir: Path | None = None
    user_root: Path | None = None
    semver: str | None = None
    build_id: str | None = None
    content_hash: str | None = None
    game_version: str | None = None
    enabled_configured: list[dict[str, Any]] = field(default_factory=list)
    enabled_load_order: list[dict[str, Any]] = field(default_factory=list)
    discovery_notes: list[str] = field(default_factory=list)

    @property
    def base_data_root(self) -> Path | None:
        if self.game_dir is None:
            return None
        candidate = self.game_dir / "Ancient" / "Data" / "Ancient"
        return candidate if candidate.is_dir() else None


@dataclass(slots=True)
class ContentEntry:
    path: str
    size: int
    read: Callable[[], bytes]
    source: str
    digest: Callable[[], str] | None = None

    def sha256(self) -> str:
        if self.digest is not None:
            return self.digest()
        return hashlib.sha256(self.read()).hexdigest()


_BLOCK_HEADER_RE = re.compile(r"(?<![A-Za-z0-9_./-])(?P<kind>[A-Za-z_][A-Za-z0-9_./-]*)\s*:\s*\{")
_ART_QUOTED = r'"((?:\\.|[^"\\])*)"'
_ASCII_DECIMAL_RE = re.compile(r"[0-9]+\Z")


def _is_ascii_decimal(value: str) -> bool:
    return _ASCII_DECIMAL_RE.fullmatch(value) is not None


def _art_unescape(value: str) -> str:
    """Unescape only syntax-level escapes without interpreting unknown ones."""

    def replace(match: re.Match[str]) -> str:
        char = match.group(1)
        return {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}.get(char, "\\" + char)

    return re.sub(r"\\(.)", replace, value, flags=re.DOTALL)


def _art_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _assert_balanced_art_for_mutation(text: str) -> None:
    """Refuse edits when the limited ART scanner cannot identify safe spans."""

    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
            if depth > MAX_ART_NESTING:
                raise ModToolError(
                    f"ART nesting exceeds the hard {MAX_ART_NESTING}-level parse limit"
                )
        elif char == "}":
            if depth == 0:
                raise ModToolError(
                    f"refusing metadata mutation: unmatched closing brace at character {index}"
                )
            depth -= 1
    if quoted:
        raise ModToolError("refusing metadata mutation: unterminated quoted string")
    if depth:
        raise ModToolError(
            f"refusing metadata mutation: {depth} unclosed ART block" + ("s" if depth != 1 else "")
        )


def _body_properties(body: str, names: Iterable[str]) -> dict[str, str]:
    """Extract requested quoted properties in one lexical pass over a body."""

    wanted = set(names)
    properties: dict[str, str] = {}
    index = 0
    length = len(body)
    while index < length and len(properties) < len(wanted):
        char = body[index]
        if char == '"':
            index += 1
            while index < length:
                if body[index] == "\\":
                    index += 2
                elif body[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            continue
        if not (char.isalpha() or char == "_"):
            index += 1
            continue
        word_start = index
        index += 1
        while index < length and (body[index].isalnum() or body[index] == "_"):
            index += 1
        word = body[word_start:index]
        if word not in wanted or word in properties:
            continue
        cursor = index
        while cursor < length and body[cursor].isspace():
            cursor += 1
        if cursor >= length or body[cursor] != ":":
            continue
        cursor += 1
        while cursor < length and body[cursor].isspace():
            cursor += 1
        if cursor >= length or body[cursor] != '"':
            continue
        value_start = cursor + 1
        cursor = value_start
        while cursor < length:
            if body[cursor] == "\\":
                cursor += 2
            elif body[cursor] == '"':
                properties[word] = _art_unescape(body[value_start:cursor])
                index = cursor + 1
                break
            else:
                cursor += 1
        else:
            index = length
    return properties


def _body_property(body: str, name: str) -> str | None:
    return _body_properties(body, (name,)).get(name)


def _iter_art_block_spans(text: str) -> Iterator[tuple[str, str, int, int, int, int]]:
    """Yield every (including nested) balanced ART block.

    Ancient Cities ART is open-ended and may contain nested blocks.  A flat
    regular expression silently hides the first child of each parent, so this
    deliberately makes only two syntax assumptions: quoted strings use a
    backslash escape, and braces outside strings balance.
    """

    headers = {
        match.end() - 1: (match.group("kind"), match.start())
        for match in _BLOCK_HEADER_RE.finditer(text)
    }
    if len(headers) > MAX_ART_BLOCKS:
        raise ModToolError(f"ART has more than the hard {MAX_ART_BLOCKS}-block parse limit")
    # Stack entries are (kind-or-None, header start, body start). Anonymous
    # braces still participate so future syntax cannot corrupt nesting. Each
    # input character is visited once; sorting restores source/header order.
    stack: list[tuple[str | None, int, int]] = []
    spans: list[tuple[str, int, int, int, int]] = []
    property_scan_chars = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            header = headers.get(index)
            stack.append((header[0], header[1], index + 1) if header else (None, index, index + 1))
            if len(stack) > MAX_ART_NESTING:
                raise ModToolError(
                    f"ART nesting exceeds the hard {MAX_ART_NESTING}-level parse limit"
                )
        elif char == "}" and stack:
            kind, start, body_start = stack.pop()
            if kind is not None:
                property_scan_chars += (index - body_start) * MAX_ART_BLOCK_SCAN_MULTIPLIER
                if property_scan_chars > MAX_ART_PROPERTY_SCAN_CHARS:
                    raise ModToolError(
                        "ART nested block bodies exceed the hard "
                        f"{MAX_ART_PROPERTY_SCAN_CHARS}-character property-scan budget"
                    )
                spans.append((kind, start, index + 1, body_start, index))
    for kind, start, body_start in stack:
        if kind is not None:
            property_scan_chars += (len(text) - body_start) * MAX_ART_BLOCK_SCAN_MULTIPLIER
            if property_scan_chars > MAX_ART_PROPERTY_SCAN_CHARS:
                raise ModToolError(
                    "ART nested block bodies exceed the hard "
                    f"{MAX_ART_PROPERTY_SCAN_CHARS}-character property-scan budget"
                )
            spans.append((kind, start, len(text), body_start, len(text)))
    for kind, start, end, body_start, body_end in sorted(spans, key=lambda item: item[1]):
        yield kind, text[body_start:body_end], start, end, body_start, body_end


def parse_art_blocks(text: str) -> list[dict[str, str]]:
    """Extract simple block properties while tolerating all other ART syntax."""

    blocks: list[dict[str, str]] = []
    for kind, body, _, _, _, _ in _iter_art_block_spans(text):
        item = {"kind": kind}
        property_names = ("Name", "Value", "Data", "Path", "File")
        properties = _body_properties(body, property_names)
        for prop in property_names:
            value = properties.get(prop)
            if value is not None:
                item[prop.lower()] = value
        blocks.append(item)
    return blocks


def manifest_fields(text: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Return manifest Name->value, Name->kind, and duplicate field names."""

    fields: dict[str, str] = {}
    kinds: dict[str, str] = {}
    duplicates: list[str] = []
    for block in parse_art_blocks(text):
        name = block.get("name")
        if not name:
            continue
        value = block.get("value", block.get("data", ""))
        if name in fields:
            duplicates.append(name)
        fields[name] = value
        kinds[name] = block["kind"]
    return fields, kinds, duplicates


def parse_literal_file_refs(text: str) -> list[str]:
    """Extract literal File:"..." properties and Name=File/Value blocks."""

    refs = [
        _art_unescape(match.group(1))
        for match in re.finditer(rf"(?<![A-Za-z0-9_])File\s*:\s*{_ART_QUOTED}", text)
    ]
    for block in parse_art_blocks(text):
        if block.get("name", "").casefold() == "file" and "value" in block:
            refs.append(block["value"])
    return list(dict.fromkeys(refs))


def decode_utf16le_art(data: bytes, label: str = "ART/LOC file") -> str:
    """Strictly decode an Ancient Cities text asset and prove byte round-trip."""

    if data.startswith(codecs.BOM_UTF16_BE):
        raise ModToolError(f"{label} uses UTF-16BE; UTF-16LE with BOM is required")
    if not data.startswith(UTF16LE_BOM):
        raise ModToolError(f"{label} is missing the UTF-16LE BOM")
    payload = data[len(UTF16LE_BOM) :]
    if payload.startswith(UTF16LE_BOM):
        raise ModToolError(f"{label} has more than one leading UTF-16LE BOM")
    if len(payload) % 2:
        raise ModToolError(f"{label} has an odd byte length")
    try:
        text = payload.decode("utf-16-le", errors="strict")
    except UnicodeDecodeError as exc:
        raise ModToolError(f"{label} cannot be decoded as UTF-16LE: {exc}") from exc
    try:
        encoded = UTF16LE_BOM + text.encode("utf-16-le", errors="strict")
    except UnicodeEncodeError as exc:
        raise ModToolError(f"{label} cannot be encoded back to UTF-16LE: {exc}") from exc
    if encoded != data:
        raise ModToolError(f"{label} fails a lossless UTF-16LE round-trip")
    return text


def encode_utf16le_art(text: str) -> bytes:
    if text.startswith("\ufeff"):
        raise ModToolError("text already contains a leading BOM; exactly one BOM is required")
    try:
        return UTF16LE_BOM + text.encode("utf-16-le", errors="strict")
    except UnicodeEncodeError as exc:
        raise ModToolError(f"text cannot be represented as strict UTF-16LE: {exc}") from exc


def normalise_steam_mod_id(value: str, *, allow_single: bool) -> str:
    pattern = r"[0-9]+(?:,[0-9]+)?" if allow_single else r"[0-9]+,[0-9]+"
    clean = value.strip()
    if not re.fullmatch(pattern, clean):
        expected = "an unsigned integer or pair" if allow_single else "an unsigned integer pair"
        raise ModToolError(f"SteamModId must be {expected}")
    decimal_parts = clean.split(",")
    # U32 has at most ten significant decimal digits.  Reject before int()
    # so Python's configurable huge-integer conversion limit cannot leak a
    # ValueError/traceback through the public CLI.
    if any(len(part) > 10 for part in decimal_parts):
        raise ModToolError("SteamModId components must fit unsigned 32-bit U32 values")
    try:
        parts = [int(part) for part in decimal_parts]
    except ValueError as exc:  # defensive for alternate Python Unicode/integer policies
        raise ModToolError("SteamModId components must be unsigned decimal integers") from exc
    if len(parts) == 1:
        parts.append(0)
    if any(part > 0xFFFF_FFFF for part in parts):
        raise ModToolError("SteamModId components must fit unsigned 32-bit U32 values")
    return f"{parts[0]},{parts[1]}"


def decode_log_bytes(data: bytes, label: str = "Log.txt") -> str:
    """Decode BOM or BOM-less UTF-16LE logs without falling back silently."""

    if data.startswith(codecs.BOM_UTF16_BE):
        payload = data[2:]
        encoding = "utf-16-be"
        prefix = codecs.BOM_UTF16_BE
    elif data.startswith(UTF16LE_BOM):
        payload = data[2:]
        encoding = "utf-16-le"
        prefix = UTF16LE_BOM
    else:
        payload = data
        encoding = "utf-16-le"
        prefix = b""
    if len(payload) % 2:
        raise ModToolError(f"{label} has an odd byte length and is not valid {encoding}")
    try:
        text = payload.decode(encoding, errors="strict")
        rebuilt = prefix + text.encode(encoding, errors="strict")
    except UnicodeError as exc:
        raise ModToolError(f"{label} cannot be decoded losslessly as {encoding}: {exc}") from exc
    if rebuilt != data:
        raise ModToolError(f"{label} fails a lossless {encoding} round-trip")
    return text


def _vdf_unescape(value: str) -> str:
    return value.replace("\\\\", "\\").replace('\\"', '"')


def parse_vdf_pairs(text: str) -> list[tuple[str, str]]:
    return [
        (_vdf_unescape(match.group(1)), _vdf_unescape(match.group(2)))
        for match in re.finditer(r'"((?:\\.|[^"\\])*)"\s+"((?:\\.|[^"\\])*)"', text)
    ]


def parse_vdf_mapping(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise ModToolError(f"cannot read Valve manifest {path}: {exc}") from exc
    # Relevant AppState keys are top-level and occur before optional nested
    # branch/depot keys with the same names (notably "buildid").
    result: dict[str, str] = {}
    for key, value in parse_vdf_pairs(text):
        result.setdefault(key, value)
    return result


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        try:
            path = raw.expanduser().resolve(strict=False)
        except OSError:
            path = raw.expanduser().absolute()
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _registry_steam_roots() -> list[Path]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    candidates: list[Path] = []
    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam"),
    )
    for hive, key_name in locations:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                for value_name in ("SteamPath", "InstallPath"):
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if isinstance(value, str) and value:
                        candidates.append(Path(value))
        except OSError:
            continue
    return candidates


def discover_steam_roots(explicit: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.extend(_registry_steam_roots())
    for name in ("ProgramFiles(x86)", "ProgramFiles"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value) / "Steam")
    candidates.extend(
        [
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
            Path.home() / ".steam" / "steam",
            Path.home() / ".local" / "share" / "Steam",
        ]
    )
    return [path for path in _dedupe_paths(candidates) if path.is_dir()]


def discover_library_roots(steam_roots: Iterable[Path]) -> tuple[list[Path], list[str]]:
    libraries: list[Path] = []
    notes: list[str] = []
    for steam_root in steam_roots:
        libraries.append(steam_root)
        library_file = steam_root / "steamapps" / "libraryfolders.vdf"
        if not library_file.is_file():
            continue
        try:
            mapping = parse_vdf_pairs(library_file.read_text(encoding="utf-8-sig", errors="strict"))
        except (OSError, UnicodeError) as exc:
            notes.append(f"Could not read {library_file}: {exc}")
            continue
        for key, value in mapping:
            if key.casefold() == "path" or key.isdigit():
                candidate = Path(value)
                if (candidate / "steamapps").is_dir():
                    libraries.append(candidate)
    return _dedupe_paths(libraries), notes


def discover_installs(library_roots: Iterable[Path]) -> tuple[list[SteamInstall], list[str]]:
    installs: list[SteamInstall] = []
    notes: list[str] = []
    for library in library_roots:
        manifest = library / "steamapps" / f"appmanifest_{APP_ID}.acf"
        if not manifest.is_file():
            continue
        try:
            values = parse_vdf_mapping(manifest)
        except ModToolError as exc:
            notes.append(str(exc))
            continue
        install_name = values.get("installdir", GAME_NAME)
        game_dir = library / "steamapps" / "common" / install_name
        installs.append(
            SteamInstall(
                appmanifest=manifest,
                library_root=library,
                game_dir=game_dir,
                build_id=values.get("buildid"),
                state_flags=values.get("StateFlags"),
                install_dir_name=install_name,
            )
        )
    return installs, notes


def discover_documents(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve(strict=False)
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "Personal")
                if isinstance(value, str) and value:
                    return Path(os.path.expandvars(value)).resolve(strict=False)
        except (OSError, ImportError):
            pass
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            # CSIDL_PERSONAL (5) follows Windows Known Folder redirection.
            result = ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer)
            if result == 0 and buffer.value:
                return Path(buffer.value).resolve(strict=False)
        except (AttributeError, OSError):
            pass
    fallback = Path.home() / "Documents"
    return fallback.resolve(strict=False) if fallback.exists() else None


def _read_version_file(game_dir: Path) -> tuple[str | None, str | None]:
    path = game_dir / "Ancient" / "Data" / "Ancient" / "version.txt"
    if not path.is_file():
        return None, None
    try:
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError):
        return None, None
    return (lines[0] if lines else None, lines[1] if len(lines) > 1 else None)


def _discover_game_version(game_dir: Path) -> str | None:
    mod_root = game_dir / "Ancient" / "Data" / "Ancient" / "Mod"
    versions: list[str] = []
    if mod_root.is_dir():
        for manifest in sorted(mod_root.glob("*/Index.art"), key=lambda p: str(p).casefold()):
            try:
                text = decode_utf16le_art(
                    _read_file_bounded(manifest, MAX_TEXT_ASSET_BYTES), str(manifest)
                )
            except (OSError, ModToolError):
                continue
            fields, _, _ = manifest_fields(text)
            value = fields.get("GameVersion", "").strip()
            if value:
                versions.append(value)
    if not versions:
        return None
    counts = Counter(versions)

    def numeric_rank(value: str) -> tuple[int, int, str]:
        if not _is_ascii_decimal(value):
            return (0, 0, value)
        significant = value.lstrip("0") or "0"
        return (1, len(significant), significant)

    return max(counts, key=lambda value: (counts[value], *numeric_rank(value), value))


def _extract_named_vector(text: str, kind: str, block_name: str, property_name: str) -> str | None:
    for block_kind, body, _, _, _, _ in _iter_art_block_spans(text):
        if block_kind.casefold() != kind.casefold():
            continue
        properties = _body_properties(body, ("Name", property_name))
        if (properties.get("Name") or "").casefold() == block_name.casefold():
            return properties.get(property_name)
    return None


def parse_enabled_mods(
    configuration_text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ids_raw = _extract_named_vector(configuration_text, "String/Vector", "Id", "Data")
    enabled_raw = _extract_named_vector(configuration_text, "U32/Vector", "Enabled", "Value")
    if ids_raw is None or enabled_raw is None:
        return [], []
    ids = [_art_unescape(match.group(1)) for match in re.finditer(r"'((?:\\.|[^'\\])*)'", ids_raw)]
    states = [value.strip() for value in enabled_raw.split(",")]
    configured: list[dict[str, Any]] = []
    for index, mod_id in enumerate(ids):
        state = states[index] if index < len(states) else None
        if state is not None and state != "4294967295":
            configured.append({"id": mod_id, "configured_index": index, "state": state})
    load_order: list[dict[str, Any]] = []
    for load_index, item in enumerate(reversed(configured)):
        copied = dict(item)
        copied["load_index"] = load_index
        load_order.append(copied)
    return configured, load_order


def discover_context(
    *,
    steam_root: Path | None = None,
    game_dir: Path | None = None,
    documents_dir: Path | None = None,
) -> DiscoveryContext:
    ctx = DiscoveryContext()
    ctx.steam_roots = discover_steam_roots(steam_root)
    ctx.library_roots, library_notes = discover_library_roots(ctx.steam_roots)
    ctx.installs, install_notes = discover_installs(ctx.library_roots)
    ctx.discovery_notes.extend(library_notes + install_notes)

    explicit_game = game_dir.expanduser().resolve(strict=False) if game_dir else None
    chosen: SteamInstall | None = None
    if explicit_game is not None:
        ctx.game_dir = explicit_game
        for install in ctx.installs:
            try:
                same = install.game_dir.resolve(strict=False) == explicit_game
            except OSError:
                same = False
            if same:
                chosen = install
                break
    elif ctx.installs:
        chosen = next((item for item in ctx.installs if item.game_dir.is_dir()), ctx.installs[0])
        ctx.game_dir = chosen.game_dir
    if chosen is not None:
        ctx.appmanifest = chosen.appmanifest
        ctx.build_id = chosen.build_id

    ctx.workshop_roots = _dedupe_paths(
        library / "steamapps" / "workshop" / "content" / APP_ID for library in ctx.library_roots
    )
    ctx.documents_dir = discover_documents(documents_dir)
    if ctx.documents_dir is not None:
        ctx.user_root = ctx.documents_dir / USER_FOLDER
    if ctx.game_dir is not None:
        ctx.semver, ctx.content_hash = _read_version_file(ctx.game_dir)
        ctx.game_version = _discover_game_version(ctx.game_dir)
    if ctx.user_root is not None:
        configuration = ctx.user_root / "User" / "Configuration.art"
        if configuration.is_file():
            try:
                text = decode_utf16le_art(
                    _read_file_bounded(configuration, MAX_TEXT_ASSET_BYTES), str(configuration)
                )
                ctx.enabled_configured, ctx.enabled_load_order = parse_enabled_mods(text)
            except (OSError, ModToolError) as exc:
                ctx.discovery_notes.append(f"Could not read enabled mod order: {exc}")
    return ctx


def context_to_dict(ctx: DiscoveryContext) -> dict[str, Any]:
    return {
        "app_id": APP_ID,
        "game": GAME_NAME,
        "steam_roots": [str(path) for path in ctx.steam_roots],
        "library_roots": [str(path) for path in ctx.library_roots],
        "appmanifest": str(ctx.appmanifest) if ctx.appmanifest else None,
        "game_dir": str(ctx.game_dir) if ctx.game_dir else None,
        "base_data_root": str(ctx.base_data_root) if ctx.base_data_root else None,
        "workshop_roots": [str(path) for path in ctx.workshop_roots],
        "documents_dir": str(ctx.documents_dir) if ctx.documents_dir else None,
        "user_root": str(ctx.user_root) if ctx.user_root else None,
        "current": {
            "semver": ctx.semver,
            "steam_build_id": ctx.build_id,
            "content_hash": ctx.content_hash,
            "game_version": ctx.game_version,
        },
        "enabled_configured": ctx.enabled_configured,
        "effective_load_order": ctx.enabled_load_order,
        "notes": ctx.discovery_notes,
        "read_only_roots": [
            value
            for value in (
                str(ctx.game_dir) if ctx.game_dir else None,
                *(str(path) for path in ctx.workshop_roots),
                str(ctx.user_root / "Mod") if ctx.user_root else None,
            )
            if value
        ],
    }


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def assert_writable_project_path(path: Path, ctx: DiscoveryContext) -> None:
    protected: list[Path] = []
    if ctx.game_dir is not None:
        protected.append(ctx.game_dir)
    protected.extend(ctx.workshop_roots)
    if ctx.user_root is not None:
        protected.append(ctx.user_root / "Mod")
    for root in protected:
        if _path_within(path, root):
            raise ModToolError(
                f"refusing to write {path}: installed game and mod-cache roots "
                f"are read-only ({root})"
            )


def path_is_link_like(path: Path) -> bool:
    """Detect symbolic links and Windows reparse points on Python 3.11+."""

    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def assert_no_symlink_components(path: Path) -> None:
    """Reject lexical symlinks before any resolve() can hide them."""

    lexical = Path(os.path.abspath(os.fspath(path.expanduser())))
    for component in (lexical, *lexical.parents):
        try:
            if path_is_link_like(component):
                raise ModToolError(
                    f"refusing to write through symbolic link or junction: {component}"
                )
        except OSError as exc:
            raise ModToolError(f"cannot safely inspect path component {component}: {exc}") from exc


def _zip_member_problem(name: str) -> str | None:
    if not name:
        return "empty member name"
    if "\\" in name:
        return "backslashes are forbidden in ZIP member names"
    if name.startswith("/") or name.startswith("\\"):
        return "absolute member path"
    if re.match(r"^[A-Za-z]:", name):
        return "drive-qualified member path"
    parts = PurePosixPath(name).parts
    if any(part == ".." for part in parts):
        return "parent traversal ('..')"
    if any(part in ("", ".") for part in name.rstrip("/").split("/")):
        return "ambiguous empty or current-directory path segment"
    if any(":" in part for part in parts):
        return "colon/alternate-data-stream path segment"
    return None


def _preflight_zip_directory(path: Path) -> tuple[int, int]:
    """Bound and count a classic ZIP central directory without loading it.

    ``zipfile.ZipFile`` materialises the complete central directory and every
    ``ZipInfo`` before callers can inspect ``infolist()``.  This streaming
    preflight makes the advertised file-count and directory-size caps real.
    ZIP64 end metadata is accepted only when its bounded record is directly
    associated with the classic end record.  The central directory itself is
    then streamed and counted before ``ZipFile`` is allowed to parse it.
    """

    try:
        archive_size = path.stat().st_size
        if archive_size < 22:
            raise ZipPreflightError("ZIP_INVALID", "ZIP is too short to contain an end record")
        tail_size = min(archive_size, 22 + 0xFFFF)
        with path.open("rb") as handle:
            handle.seek(archive_size - tail_size)
            tail = handle.read(tail_size)
            signature = b"PK\x05\x06"
            search_end = len(tail)
            eocd_index = -1
            while True:
                candidate = tail.rfind(signature, 0, search_end)
                if candidate < 0:
                    break
                if candidate + 22 <= len(tail):
                    comment_size = struct.unpack_from("<H", tail, candidate + 20)[0]
                    if candidate + 22 + comment_size == len(tail):
                        eocd_index = candidate
                        break
                search_end = candidate
            if eocd_index < 0:
                raise ZipPreflightError(
                    "ZIP_INVALID", "ZIP end-of-central-directory record not found"
                )

            (
                _,
                disk_number,
                directory_disk,
                entries_on_disk,
                entry_count,
                directory_size,
                directory_offset,
                _,
            ) = struct.unpack_from("<4s4H2LH", tail, eocd_index)
            eocd_offset = archive_size - tail_size + eocd_index
            directory_end = eocd_offset
            zip64_prefix: int | None = None
            locator_offset = eocd_offset - 20
            locator = b""
            if locator_offset >= 0:
                handle.seek(locator_offset)
                locator = handle.read(20)
            uses_zip64 = locator[:4] == b"PK\x06\x07" or (
                entry_count == 0xFFFF
                or directory_size == 0xFFFF_FFFF
                or directory_offset == 0xFFFF_FFFF
            )
            if uses_zip64:
                if len(locator) != 20 or locator[:4] != b"PK\x06\x07":
                    raise ZipPreflightError("ZIP_INVALID", "ZIP64 locator is missing")
                _, zip64_disk, zip64_logical_offset, zip64_disks = struct.unpack("<4sLQL", locator)
                if zip64_disk != 0 or zip64_disks != 1:
                    raise ZipPreflightError(
                        "ZIP_MULTIDISK", "multi-disk ZIP64 archives are unsupported"
                    )
                search_size = min(locator_offset, MAX_ZIP64_END_RECORD_BYTES)
                handle.seek(locator_offset - search_size)
                zip64_window = handle.read(search_size)
                search_end = len(zip64_window)
                zip64_index = -1
                zip64_total_size = 0
                while True:
                    candidate = zip64_window.rfind(b"PK\x06\x06", 0, search_end)
                    if candidate < 0:
                        break
                    if candidate + 12 <= len(zip64_window):
                        record_size = struct.unpack_from("<Q", zip64_window, candidate + 4)[0]
                        total_size = 12 + record_size
                        if (
                            56 <= total_size <= MAX_ZIP64_END_RECORD_BYTES
                            and candidate + total_size == len(zip64_window)
                        ):
                            zip64_index = candidate
                            zip64_total_size = total_size
                            break
                    search_end = candidate
                if zip64_index < 0:
                    raise ZipPreflightError(
                        "ZIP64_END_RECORD_LIMIT",
                        (
                            "ZIP64 end record is missing or exceeds the hard "
                            f"{MAX_ZIP64_END_RECORD_BYTES}-byte limit"
                        ),
                    )
                (
                    _,
                    _,
                    _,
                    _,
                    disk_number,
                    directory_disk,
                    entries_on_disk,
                    entry_count,
                    directory_size,
                    directory_offset,
                ) = struct.unpack_from("<4sQ2H2L4Q", zip64_window, zip64_index)
                directory_end = locator_offset - zip64_total_size
                if zip64_logical_offset > directory_end:
                    raise ZipPreflightError(
                        "ZIP_INVALID", "ZIP64 end-record offset is outside the archive"
                    )
                zip64_prefix = directory_end - zip64_logical_offset

            if disk_number != 0 or directory_disk != 0 or entries_on_disk != entry_count:
                raise ZipPreflightError("ZIP_MULTIDISK", "multi-disk ZIP archives are unsupported")
            if entry_count > MAX_ZIP_FILES:
                raise ZipPreflightError(
                    "ZIP_FILE_COUNT_LIMIT",
                    f"archive declares {entry_count} entries; hard limit is {MAX_ZIP_FILES}",
                )
            if directory_size > MAX_ZIP_CENTRAL_DIRECTORY_BYTES:
                raise ZipPreflightError(
                    "ZIP_DIRECTORY_SIZE_LIMIT",
                    (
                        f"central directory declares {directory_size} bytes; hard limit is "
                        f"{MAX_ZIP_CENTRAL_DIRECTORY_BYTES}"
                    ),
                )

            directory_start = directory_end - directory_size
            if directory_start < 0 or directory_offset > directory_start:
                raise ZipPreflightError(
                    "ZIP_INVALID", "central-directory offsets are outside the archive"
                )
            if zip64_prefix is not None and directory_start - directory_offset != zip64_prefix:
                raise ZipPreflightError(
                    "ZIP_INVALID", "ZIP64 and central-directory offsets disagree"
                )

            handle.seek(directory_start)
            remaining = directory_size
            scanned_entries = 0
            while remaining:
                if remaining < 4:
                    raise ZipPreflightError("ZIP_INVALID", "truncated central-directory record")
                record_signature = handle.read(4)
                if record_signature == b"PK\x01\x02":
                    if remaining < 46:
                        raise ZipPreflightError(
                            "ZIP_INVALID", "truncated central-directory file header"
                        )
                    fixed = record_signature + handle.read(42)
                    name_size, extra_size, comment_size = struct.unpack_from("<3H", fixed, 28)
                    record_size = 46 + name_size + extra_size + comment_size
                    if record_size > remaining:
                        raise ZipPreflightError(
                            "ZIP_INVALID", "central-directory file header exceeds its bounds"
                        )
                    handle.seek(record_size - 46, os.SEEK_CUR)
                    remaining -= record_size
                    scanned_entries += 1
                    if scanned_entries > MAX_ZIP_FILES:
                        raise ZipPreflightError(
                            "ZIP_FILE_COUNT_LIMIT",
                            (
                                f"central directory contains more than the hard "
                                f"{MAX_ZIP_FILES}-entry limit"
                            ),
                        )
                elif record_signature == b"PK\x05\x05":
                    if remaining < 6:
                        raise ZipPreflightError(
                            "ZIP_INVALID", "truncated central-directory signature record"
                        )
                    signature_size_data = handle.read(2)
                    signature_size = struct.unpack("<H", signature_size_data)[0]
                    record_size = 6 + signature_size
                    if record_size != remaining:
                        raise ZipPreflightError(
                            "ZIP_INVALID", "misplaced central-directory signature record"
                        )
                    handle.seek(signature_size, os.SEEK_CUR)
                    remaining = 0
                else:
                    raise ZipPreflightError(
                        "ZIP_INVALID", "unexpected central-directory record signature"
                    )
            if scanned_entries != entry_count:
                raise ZipPreflightError(
                    "ZIP_FILE_COUNT_MISMATCH",
                    (
                        f"end record declares {entry_count} entries but central directory "
                        f"contains {scanned_entries}"
                    ),
                )
    except ZipPreflightError:
        raise
    except OSError as exc:
        raise ZipPreflightError("ZIP_INVALID", f"cannot preflight ZIP directory: {exc}") from exc
    return scanned_entries, directory_size


def _zip_limit_problem(info: zipfile.ZipInfo) -> str | None:
    if info.file_size > MAX_ZIP_MEMBER_BYTES:
        return f"member exceeds hard {MAX_ZIP_MEMBER_BYTES // (1024 * 1024)} MiB limit"
    if info.file_size:
        ratio = float("inf") if info.compress_size == 0 else info.file_size / info.compress_size
        if ratio > MAX_ZIP_COMPRESSION_RATIO:
            return f"compression ratio exceeds hard {MAX_ZIP_COMPRESSION_RATIO}:1 limit"
    return None


def _check_zip_collection_limits(infos: Sequence[zipfile.ZipInfo]) -> None:
    if len(infos) > MAX_ZIP_FILES:
        raise ModToolError(f"ZIP has {len(infos)} entries; hard limit is {MAX_ZIP_FILES}")
    total = sum(info.file_size for info in infos)
    if total > MAX_ZIP_TOTAL_BYTES:
        limit_gib = MAX_ZIP_TOTAL_BYTES / (1024 * 1024 * 1024)
        raise ModToolError(f"ZIP expands to {total} bytes; hard limit is {limit_gib:g} GiB")
    for info in infos:
        problem = _zip_limit_problem(info)
        if problem:
            raise ModToolError(f"unsafe ZIP member {info.filename!r}: {problem}")


def _read_file_bounded(path: Path, limit: int = MAX_ZIP_MEMBER_BYTES) -> bytes:
    size = path.stat().st_size
    if size > limit:
        raise ModToolError(f"refusing to read {path}: {size} bytes exceeds hard {limit}-byte limit")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ModToolError(f"refusing to read {path}: content grew beyond hard {limit}-byte limit")
    return data


def _read_zip_member(archive: Path, name: str) -> bytes:
    _preflight_zip_directory(archive)
    with zipfile.ZipFile(archive, "r") as handle:
        info = handle.getinfo(name)
        problem = _zip_limit_problem(info)
        if problem:
            raise ModToolError(f"refusing to read unsafe ZIP member {name!r}: {problem}")
        output = io.BytesIO()
        total = 0
        with handle.open(info, "r") as member:
            while chunk := member.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ZIP_MEMBER_BYTES:
                    raise ModToolError(f"ZIP member {name!r} expanded beyond the hard limit")
                output.write(chunk)
        return output.getvalue()


def _hash_zip_member(archive: Path, name: str) -> str:
    _preflight_zip_directory(archive)
    digest = hashlib.sha256()
    with zipfile.ZipFile(archive, "r") as handle:
        info = handle.getinfo(name)
        problem = _zip_limit_problem(info)
        if problem:
            raise ModToolError(f"refusing to hash unsafe ZIP member {name!r}: {problem}")
        total = 0
        with handle.open(info, "r") as member:
            while chunk := member.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ZIP_MEMBER_BYTES:
                    raise ModToolError(f"ZIP member {name!r} expanded beyond the hard limit")
                digest.update(chunk)
    return digest.hexdigest()


def _directory_content_root(target: Path) -> tuple[Path | None, str]:
    if target.is_dir() and target.name == "Ancient":
        return target, "Ancient"
    if target.is_dir():
        exact = target / "Ancient"
        if exact.is_dir():
            return exact, "Ancient"
        for child in target.iterdir():
            if child.is_dir() and child.name.casefold() == "ancient":
                return child, child.name
    return None, "Ancient"


def _bounded_tree_entries(root: Path, *, limit: int = MAX_ZIP_FILES) -> list[Path]:
    """Enumerate a tree without following links or retaining more than ``limit`` entries."""

    entries: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        child_directories: list[Path] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    path = Path(entry.path)
                    entries.append(path)
                    if len(entries) > limit:
                        raise ModToolError(
                            f"directory tree exceeds the hard {limit}-entry limit: {root}"
                        )
                    if path_is_link_like(path):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        child_directories.append(path)
        except ModToolError:
            raise
        except OSError as exc:
            raise ModToolError(f"cannot enumerate directory tree {root}: {exc}") from exc
        pending.extend(child_directories)
    return sorted(entries, key=lambda item: (item.as_posix().casefold(), item.as_posix()))


def content_entries(target: Path) -> list[ContentEntry]:
    """Enumerate Ancient/ payload files from a project, extracted mod, or Mod.zip."""

    target = target.resolve(strict=False)
    if target.is_file() and target.suffix.casefold() == ".zip":
        entries: list[ContentEntry] = []
        _preflight_zip_directory(target)
        with zipfile.ZipFile(target, "r") as handle:
            infos = handle.infolist()
            _check_zip_collection_limits(infos)
            for info in infos:
                if info.is_dir() or _zip_member_problem(info.filename):
                    continue
                name = info.filename
                if name == "Ancient" or not name.startswith("Ancient/"):
                    continue
                entries.append(
                    ContentEntry(
                        path=name,
                        size=info.file_size,
                        read=lambda archive=target, member=name: _read_zip_member(archive, member),
                        source=str(target),
                        digest=lambda archive=target, member=name: _hash_zip_member(
                            archive, member
                        ),
                    )
                )
        return entries
    if target.is_file():
        target = target.parent
    root, actual_name = _directory_content_root(target)
    if root is None:
        return []
    if path_is_link_like(root):
        raise ModToolError(f"symbolic link payload root is forbidden: {root}")
    result: list[ContentEntry] = []
    for path in _bounded_tree_entries(root):
        if not path.is_file() or path_is_link_like(path):
            continue
        relative = path.relative_to(root).as_posix()
        logical = f"{actual_name}/{relative}"
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        result.append(
            ContentEntry(
                path=logical,
                size=size,
                read=lambda file_path=path: _read_file_bounded(file_path),
                source=str(path),
                digest=lambda file_path=path: _hash_file(file_path),
            )
        )
    return result


def _root_file_matches(root: Path, expected_name: str) -> list[Path]:
    if not root.is_dir():
        return []
    try:
        matches = [
            child
            for child in root.iterdir()
            if child.is_file() and child.name.casefold() == expected_name.casefold()
        ]
    except OSError:
        return []
    return sorted(matches, key=lambda path: (path.name.casefold(), path.name))


def _manifest_path_for_target(target: Path) -> Path | None:
    root = target.parent if target.is_file() else target
    matches = _root_file_matches(root, "Index.art")
    return matches[0] if len(matches) == 1 else None


def _signature_problem(path: str, data: bytes) -> str | None:
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        if len(data) < 4 or not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
            return "JPEG must start with FF D8 FF and end with FF D9"
    elif suffix == ".png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "PNG signature is missing"
    elif suffix == ".wav":
        if len(data) < 12 or data[:4] not in {b"RIFF", b"RF64"} or data[8:12] != b"WAVE":
            return "WAV must have a RIFF/RF64 + WAVE header"
    elif suffix == ".fbx":
        stripped = data.lstrip(codecs.BOM_UTF8 + b" \t\r\n")
        binary = data.startswith(b"Kaydara FBX Binary  \x00\x1a\x00")
        ascii_fbx = stripped.startswith(b"; FBX") or stripped.startswith(b"FBXHeaderExtension")
        if not binary and not ascii_fbx:
            return "FBX binary or ASCII signature is missing"
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read JPEG SOF dimensions without decoding pixels or external libraries."""

    if not data.startswith(b"\xff\xd8"):
        return None
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    index = 2
    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            return None
        marker = data[index]
        index += 1
        if marker in {0x00, 0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            return None
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            return None
        if marker in sof_markers:
            if length < 7:
                return None
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return (width, height) if width and height else None
        index += length
    return None


def _resolve_relative_file_case(
    root: Path | None, parts: Sequence[str]
) -> tuple[Path | None, bool]:
    """Return (resolved file, every component uses exact case)."""

    if root is None:
        return None, False
    current = root
    exact = True
    for part in parts:
        if not current.is_dir():
            return None, False
        try:
            children = {child.name: child for child in current.iterdir()}
        except OSError:
            return None, False
        child = children.get(part)
        if child is None:
            folded = next(
                (
                    candidate
                    for name, candidate in children.items()
                    if name.casefold() == part.casefold()
                ),
                None,
            )
            if folded is None:
                return None, False
            child = folded
            exact = False
        current = child
    return (current, exact) if current.is_file() else (None, False)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_reference(current_file: str, reference: str) -> str | None:
    clean = reference.strip().replace("\\", "/")
    if (
        not clean
        or "://" in clean
        or clean.startswith(("~", "#", "$", "../"))
        or clean == ".."
        or clean == "/System"
        or clean.startswith("/System/")
    ):
        return None
    if re.match(r"^[A-Za-z]:", clean):
        return clean
    if clean.startswith("/"):
        normal = posixpath.normpath(clean.lstrip("/"))
    else:
        normal = posixpath.normpath(posixpath.join(posixpath.dirname(current_file), clean))
    while normal.startswith("../"):
        normal = normal[3:]
    if normal == "..":
        return None
    if normal.casefold().startswith("ancient/"):
        return normal
    return normal


def _validate_zip_structure(path: Path, issues: list[Issue]) -> list[str]:
    safe_members: list[str] = []
    try:
        _preflight_zip_directory(path)
    except ZipPreflightError as exc:
        issues.append(Issue("error", exc.code, str(exc), str(path)))
        return safe_members
    try:
        with zipfile.ZipFile(path, "r") as handle:
            infos = handle.infolist()
            if len(infos) > MAX_ZIP_FILES:
                issues.append(
                    Issue(
                        "error",
                        "ZIP_FILE_COUNT_LIMIT",
                        f"archive has {len(infos)} entries; hard limit is {MAX_ZIP_FILES}",
                        str(path),
                    )
                )
            declared_total = sum(info.file_size for info in infos)
            if declared_total > MAX_ZIP_TOTAL_BYTES:
                issues.append(
                    Issue(
                        "error",
                        "ZIP_TOTAL_SIZE_LIMIT",
                        (
                            f"archive declares {declared_total} uncompressed bytes; "
                            f"hard limit is {MAX_ZIP_TOTAL_BYTES}"
                        ),
                        str(path),
                    )
                )
            seen: dict[str, str] = {}
            has_ancient = False
            total_uncompressed = 0
            for info in infos[:MAX_ZIP_FILES]:
                name = info.filename
                problem = _zip_member_problem(name)
                if problem:
                    issues.append(Issue("error", "ZIP_SLIP", f"unsafe ZIP member: {problem}", name))
                    continue
                folded = name.rstrip("/").casefold()
                if folded in seen:
                    issues.append(
                        Issue(
                            "error",
                            "ZIP_CASE_DUPLICATE",
                            f"case-insensitive duplicate of {seen[folded]}",
                            name,
                        )
                    )
                else:
                    seen[folded] = name
                first = PurePosixPath(name).parts[0] if PurePosixPath(name).parts else ""
                if first != "Ancient":
                    issues.append(
                        Issue(
                            "error",
                            "ZIP_ROOT",
                            "every Mod.zip member must be under exact root Ancient/",
                            name,
                        )
                    )
                else:
                    has_ancient = True
                if PurePosixPath(name).suffix.casefold() in EXECUTABLE_EXTENSIONS:
                    issues.append(
                        Issue(
                            "error", "EXECUTABLE_CONTENT", "executable content is forbidden", name
                        )
                    )
                if info.flag_bits & 0x1:
                    issues.append(
                        Issue(
                            "error", "ZIP_ENCRYPTED", "encrypted ZIP members are unsupported", name
                        )
                    )
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(unix_mode) == stat.S_IFLNK:
                    issues.append(
                        Issue("error", "ZIP_SYMLINK", "symbolic links are forbidden", name)
                    )
                total_uncompressed += info.file_size
                limit_problem = _zip_limit_problem(info)
                if limit_problem:
                    issues.append(Issue("error", "ZIP_RESOURCE_LIMIT", limit_problem, name))
                if not info.is_dir() and limit_problem is None:
                    safe_members.append(name)
            if not has_ancient:
                issues.append(
                    Issue(
                        "error",
                        "ZIP_ROOT_MISSING",
                        "Mod.zip must contain exact root Ancient/",
                        str(path),
                    )
                )
            if total_uncompressed != declared_total and len(infos) <= MAX_ZIP_FILES:
                issues.append(
                    Issue(
                        "error",
                        "ZIP_SIZE_ACCOUNTING",
                        "could not account for every ZIP member",
                        str(path),
                    )
                )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        issues.append(Issue("error", "ZIP_INVALID", f"cannot read ZIP archive: {exc}", str(path)))
    return safe_members


def validate_target(
    target: Path,
    ctx: DiscoveryContext | None = None,
    *,
    check_archive: bool = True,
) -> dict[str, Any]:
    """Validate a project, extracted mod, Index.art, or Mod.zip."""

    ctx = ctx or DiscoveryContext()
    target = target.expanduser().resolve(strict=False)
    issues: list[Issue] = []
    if not target.exists():
        issues.append(Issue("error", "TARGET_MISSING", "target does not exist", str(target)))
        return _validation_result(target, issues, {}, [], {})

    item_root = target.parent if target.is_file() else target
    manifest: dict[str, str] = {}
    manifest_matches = _root_file_matches(item_root, "Index.art")
    manifest_path = manifest_matches[0] if len(manifest_matches) == 1 else None
    if len(manifest_matches) > 1:
        issues.append(
            Issue(
                "error",
                "MANIFEST_AMBIGUOUS",
                "multiple case-insensitive variants of root Index.art were found",
                str(item_root),
                {"matches": [str(path) for path in manifest_matches]},
            )
        )
    elif manifest_path is None:
        issues.append(Issue("error", "MANIFEST_MISSING", "root Index.art is required", str(target)))
    else:
        if manifest_path.name != "Index.art":
            issues.append(
                Issue(
                    "error",
                    "MANIFEST_CASE",
                    "root manifest must be named exactly Index.art",
                    str(manifest_path),
                )
            )
        try:
            manifest_text = decode_utf16le_art(
                _read_file_bounded(manifest_path, MAX_TEXT_ASSET_BYTES), str(manifest_path)
            )
            manifest, kinds, duplicates = manifest_fields(manifest_text)
            for duplicate in duplicates:
                issues.append(
                    Issue(
                        "warning",
                        "MANIFEST_DUPLICATE_FIELD",
                        f"duplicate manifest field {duplicate}",
                        str(manifest_path),
                    )
                )
            for name in MANIFEST_REQUIRED_FIELDS:
                # Published first-party/community manifests demonstrate that
                # Changelog may intentionally contain an empty/space value;
                # the block itself is nevertheless mandatory.
                missing = name not in manifest or (
                    name != "Changelog" and not manifest[name].strip()
                )
                if missing:
                    issues.append(
                        Issue(
                            "error",
                            "MANIFEST_MISSING_FIELD",
                            f"manifest field {name} is required",
                            str(manifest_path),
                        )
                    )
            steam_id = manifest.get("SteamModId", "")
            if steam_id:
                try:
                    normalise_steam_mod_id(steam_id, allow_single=False)
                except ModToolError as exc:
                    issues.append(
                        Issue(
                            "error",
                            "STEAM_MOD_ID",
                            str(exc),
                            str(manifest_path),
                        )
                    )
            if manifest.get("GameVersion") and not _is_ascii_decimal(manifest["GameVersion"]):
                issues.append(
                    Issue(
                        "error",
                        "GAME_VERSION_FORMAT",
                        "GameVersion must be an unsigned decimal integer such as 22",
                        str(manifest_path),
                    )
                )
            for string_field in (
                "Title",
                "Description",
                "Changelog",
                "Content",
                "GameVersion",
                "Type",
            ):
                if string_field in manifest and kinds.get(string_field, "").casefold() != "string":
                    issues.append(
                        Issue(
                            "error",
                            "MANIFEST_FIELD_TYPE",
                            f"{string_field} must use a String block",
                            str(manifest_path),
                        )
                    )
            if steam_id and kinds.get("SteamModId", "").casefold() != "u32x2":
                issues.append(
                    Issue(
                        "error",
                        "STEAM_MOD_ID_TYPE",
                        "SteamModId must use a U32x2 block",
                        str(manifest_path),
                    )
                )
            folder = manifest_path.parent.name
            if _is_ascii_decimal(folder) and steam_id:
                leading = steam_id.split(",", 1)[0]
                if leading not in {"0", folder}:
                    issues.append(
                        Issue(
                            "warning",
                            "STEAM_MOD_ID_FOLDER",
                            f"SteamModId {leading} differs from numeric folder {folder}",
                            str(manifest_path),
                        )
                    )
            if ctx.game_version and manifest.get("GameVersion") != ctx.game_version:
                issues.append(
                    Issue(
                        "warning",
                        "GAME_VERSION_MISMATCH",
                        f"mod targets GameVersion {manifest.get('GameVersion')!r}; "
                        f"current is {ctx.game_version!r}",
                        str(manifest_path),
                    )
                )
        except (OSError, ModToolError) as exc:
            issues.append(Issue("error", "ART_ENCODING", str(exc), str(manifest_path)))

    thumbnail_matches = _root_file_matches(item_root, "Thumbnail.jpg")
    thumbnail_path = thumbnail_matches[0] if len(thumbnail_matches) == 1 else None
    if len(thumbnail_matches) > 1:
        issues.append(
            Issue(
                "error",
                "THUMBNAIL_AMBIGUOUS",
                "multiple case-insensitive variants of root Thumbnail.jpg were found",
                str(item_root),
                {"matches": [str(path) for path in thumbnail_matches]},
            )
        )
    elif thumbnail_path is None:
        expected_thumbnail = item_root / "Thumbnail.jpg"
        issues.append(
            Issue(
                "error",
                "THUMBNAIL_MISSING",
                "root Thumbnail.jpg is required beside Index.art and Mod.zip",
                str(expected_thumbnail),
            )
        )
    else:
        if thumbnail_path.name != "Thumbnail.jpg":
            issues.append(
                Issue(
                    "error",
                    "THUMBNAIL_CASE",
                    "Workshop thumbnail must be named exactly Thumbnail.jpg",
                    str(thumbnail_path),
                )
            )
        try:
            thumbnail_data = _read_file_bounded(thumbnail_path)
            signature_problem = _signature_problem("Thumbnail.jpg", thumbnail_data)
            if signature_problem:
                issues.append(
                    Issue("error", "THUMBNAIL_SIGNATURE", signature_problem, str(thumbnail_path))
                )
            dimensions = jpeg_dimensions(thumbnail_data)
            if dimensions is None:
                issues.append(
                    Issue(
                        "error",
                        "THUMBNAIL_JPEG",
                        "could not read a JPEG SOF dimensions marker",
                        str(thumbnail_path),
                    )
                )
            elif dimensions != (512, 512):
                issues.append(
                    Issue(
                        "warning",
                        "THUMBNAIL_DIMENSIONS",
                        f"Workshop thumbnail is {dimensions[0]}x{dimensions[1]}; "
                        "use square 512x512",
                        str(thumbnail_path),
                        {"width": dimensions[0], "height": dimensions[1], "recommended": "512x512"},
                    )
                )
        except (ModToolError, OSError) as exc:
            issues.append(
                Issue(
                    "error",
                    "THUMBNAIL_UNREADABLE",
                    f"cannot read thumbnail: {exc}",
                    str(thumbnail_path),
                )
            )

    archive: Path | None = None
    if check_archive:
        if target.is_file() and target.suffix.casefold() == ".zip":
            archive = target
        else:
            root = target.parent if target.is_file() else target
            candidate = root / "Mod.zip"
            if candidate.is_file():
                archive = candidate
    if archive is not None:
        _validate_zip_structure(archive, issues)

    if target.is_file() and target.suffix.casefold() == ".zip":
        entries_target = target
    else:
        root = target.parent if target.is_file() else target
        entries_target = root if (root / "Ancient").is_dir() else (archive or root)
    root_for_case = target.parent if target.is_file() else target
    directory_root, actual_root_name = (
        _directory_content_root(root_for_case) if root_for_case.is_dir() else (None, "Ancient")
    )
    payload_root_symlink = (
        entries_target.is_dir() and directory_root is not None and path_is_link_like(directory_root)
    )
    if payload_root_symlink:
        entries = []
        issues.append(
            Issue(
                "error",
                "CONTENT_ROOT_SYMLINK",
                "symbolic link payload root is forbidden",
                str(directory_root),
            )
        )
    else:
        try:
            entries = content_entries(entries_target)
        except (ModToolError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
            entries = []
            issues.append(
                Issue(
                    "error",
                    "CONTENT_UNREADABLE",
                    f"cannot enumerate content: {exc}",
                    str(entries_target),
                )
            )
    if directory_root is not None and actual_root_name != "Ancient":
        issues.append(
            Issue(
                "error",
                "CONTENT_ROOT_CASE",
                "content root must be named exactly Ancient",
                str(directory_root),
            )
        )

    classifications: dict[str, str] = {}
    known_content: dict[str, str] = {}
    decoded_art: dict[str, str] = {}
    content_art_count = 0
    for entry in entries:
        folded = entry.path.casefold()
        if folded in known_content:
            issues.append(
                Issue(
                    "error",
                    "CONTENT_CASE_DUPLICATE",
                    f"case-insensitive duplicate of {known_content[folded]}",
                    entry.path,
                )
            )
        else:
            known_content[folded] = entry.path
        suffix = PurePosixPath(entry.path).suffix.casefold()
        if suffix in EXECUTABLE_EXTENSIONS:
            issues.append(
                Issue("error", "EXECUTABLE_CONTENT", "executable content is forbidden", entry.path)
            )
        data: bytes | None = None
        if suffix in {".art", ".loc"} | MEDIA_EXTENSIONS:
            if suffix in {".art", ".loc"} and entry.size > MAX_TEXT_ASSET_BYTES:
                issues.append(
                    Issue(
                        "error",
                        "TEXT_ASSET_SIZE_LIMIT",
                        f"text asset exceeds hard {MAX_TEXT_ASSET_BYTES}-byte parse limit",
                        entry.path,
                    )
                )
                continue
            try:
                data = entry.read()
            except (ModToolError, OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
                issues.append(
                    Issue("error", "FILE_UNREADABLE", f"cannot read content: {exc}", entry.path)
                )
                continue
        if suffix in {".art", ".loc"} and data is not None:
            try:
                text = decode_utf16le_art(data, entry.path)
                if suffix == ".art":
                    decoded_art[entry.path] = text
                    content_art_count += 1
            except ModToolError as exc:
                issues.append(Issue("error", "ART_ENCODING", str(exc), entry.path))
        if suffix in MEDIA_EXTENSIONS and data is not None:
            problem = _signature_problem(entry.path, data)
            if problem:
                issues.append(Issue("error", "MEDIA_SIGNATURE", problem, entry.path))

        logical_parts = PurePosixPath(entry.path).parts
        base, exact_base_case = _resolve_relative_file_case(ctx.base_data_root, logical_parts[1:])
        if base is None:
            classifications[entry.path] = "new"
        else:
            if logical_parts[0] != "Ancient" or not exact_base_case:
                issues.append(
                    Issue(
                        "error",
                        "BASE_OVERRIDE_CASE",
                        f"payload path case does not match base-game path: {entry.path}",
                        entry.path,
                    )
                )
            try:
                if base.stat().st_size == entry.size and _hash_file(base) == entry.sha256():
                    classifications[entry.path] = "identical"
                else:
                    classifications[entry.path] = "override"
            except (ModToolError, OSError) as exc:
                classifications[entry.path] = "override"
                issues.append(
                    Issue(
                        "warning", "BASE_COMPARE", f"could not compare base file: {exc}", entry.path
                    )
                )

    for art_path, art_text in decoded_art.items():
        for reference in parse_literal_file_refs(art_text):
            logical = _normalise_reference(art_path, reference)
            if logical is None:
                continue
            if re.match(r"^[A-Za-z]:", logical):
                issues.append(
                    Issue(
                        "warning",
                        "ABSOLUTE_FILE_REFERENCE",
                        f"absolute File reference is not portable: {reference}",
                        art_path,
                    )
                )
                continue
            canonical_mod_path = known_content.get(logical.casefold())
            exists_in_mod = canonical_mod_path is not None
            if canonical_mod_path is not None and canonical_mod_path != logical:
                issues.append(
                    Issue(
                        "error",
                        "FILE_REFERENCE_CASE",
                        (
                            f"File reference case does not match payload: {logical} -> "
                            f"{canonical_mod_path}"
                        ),
                        art_path,
                    )
                )
            logical_parts = PurePosixPath(logical).parts
            if logical_parts and logical_parts[0].casefold() == "ancient":
                resolved_base, exact_base_case = _resolve_relative_file_case(
                    ctx.base_data_root, logical_parts[1:]
                )
                exists_in_base = resolved_base is not None
                if exists_in_base and (logical_parts[0] != "Ancient" or not exact_base_case):
                    issues.append(
                        Issue(
                            "error",
                            "FILE_REFERENCE_CASE",
                            f"File reference case does not match base content: {logical}",
                            art_path,
                        )
                    )
            else:
                exists_in_base = False
            if not exists_in_mod and not exists_in_base:
                issues.append(
                    Issue(
                        "warning",
                        "MISSING_FILE_REFERENCE",
                        f"literal File reference was not found: {reference} -> {logical}",
                        art_path,
                    )
                )

    if content_art_count:
        issues.append(
            Issue(
                "notice",
                "ACHIEVEMENTS_DISABLED",
                "enabled mods containing .art files disable Steam achievements",
                str(target),
                {"art_files": content_art_count},
            )
        )
    override_paths = [path for path, status in classifications.items() if status == "override"]
    if override_paths:
        issues.append(
            Issue(
                "notice",
                "SAVE_COMPATIBILITY",
                "base-game overrides can affect existing saves; test with a backup or a new game",
                str(target),
                {"overrides": len(override_paths)},
            )
        )
    if not entries:
        issues.append(
            Issue(
                "warning",
                "CONTENT_EMPTY",
                "no payload files found below exact root Ancient/",
                str(target),
            )
        )
    counts = Counter(classifications.values())
    summary = {
        "files": len(entries),
        "art_files": content_art_count,
        "new": counts["new"],
        "overrides": counts["override"],
        "identical": counts["identical"],
    }
    return _validation_result(target, issues, manifest, entries, classifications, summary)


def _validation_result(
    target: Path,
    issues: list[Issue],
    manifest: dict[str, str],
    entries: list[ContentEntry],
    classifications: dict[str, str],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    notices = sum(issue.severity == "notice" for issue in issues)
    return {
        "target": str(target),
        "valid": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "notices": notices,
        "manifest": manifest,
        "content": summary or {"files": len(entries)},
        "classifications": classifications,
        "issues": [issue.to_dict() for issue in issues],
    }


def inspect_target(target: Path, ctx: DiscoveryContext | None = None) -> dict[str, Any]:
    report = validate_target(target, ctx)
    target = target.expanduser().resolve(strict=False)
    report["kind"] = (
        "zip"
        if target.is_file() and target.suffix.casefold() == ".zip"
        else "art"
        if target.is_file() and target.suffix.casefold() in {".art", ".loc"}
        else "directory"
    )
    report["file_list"] = sorted(report["classifications"], key=str.casefold)
    return report


def _catalog_one(root: Path, source: str, enabled: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    manifest_path = root / "Index.art"
    fields: dict[str, str] = {}
    errors: list[str] = []
    try:
        fields, _, _ = manifest_fields(
            decode_utf16le_art(
                _read_file_bounded(manifest_path, MAX_TEXT_ASSET_BYTES), str(manifest_path)
            )
        )
    except (OSError, ModToolError) as exc:
        errors.append(str(exc))
    mod_id = root.name
    zip_path = root / "Mod.zip"
    payload_target = zip_path if zip_path.is_file() else root
    try:
        entries = content_entries(payload_target)
    except (ModToolError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
        entries = []
        errors.append(str(exc))
    enabled_item = enabled.get(mod_id)
    return {
        "id": mod_id,
        "title": fields.get("Title"),
        "type": fields.get("Type"),
        "game_version": fields.get("GameVersion"),
        "steam_mod_id": fields.get("SteamModId"),
        "source": source,
        "path": str(root),
        "format": "Mod.zip" if zip_path.is_file() else "loose",
        "payload_files": len(entries),
        "enabled": enabled_item is not None,
        "load_index": enabled_item.get("load_index") if enabled_item else None,
        "errors": errors,
    }


def catalog_mods(
    ctx: DiscoveryContext,
    paths: Sequence[Path] = (),
    query: str | None = None,
) -> dict[str, Any]:
    enabled = {item["id"]: item for item in ctx.enabled_load_order}
    candidates: list[tuple[Path, str]] = []
    if paths:
        for path in paths:
            resolved = path.expanduser().resolve(strict=False)
            if (resolved / "Index.art").is_file():
                candidates.append((resolved, "provided"))
            elif resolved.is_dir():
                candidates.extend(
                    (child, "provided")
                    for child in resolved.iterdir()
                    if child.is_dir() and (child / "Index.art").is_file()
                )
    else:
        for workshop in ctx.workshop_roots:
            if workshop.is_dir():
                candidates.extend(
                    (child, "workshop")
                    for child in workshop.iterdir()
                    if child.is_dir() and (child / "Index.art").is_file()
                )
        if ctx.user_root is not None:
            user_mods = ctx.user_root / "Mod"
            if user_mods.is_dir():
                candidates.extend(
                    (child, "user-cache")
                    for child in user_mods.iterdir()
                    if child.is_dir() and (child / "Index.art").is_file()
                )
        if ctx.base_data_root is not None:
            builtin = ctx.base_data_root / "Mod"
            if builtin.is_dir():
                candidates.extend(
                    (child, "built-in")
                    for child in builtin.iterdir()
                    if child.is_dir() and (child / "Index.art").is_file()
                )
    deduped: list[tuple[Path, str]] = []
    seen: set[tuple[str, str]] = set()
    for path, source in candidates:
        key = (os.path.normcase(str(path.resolve(strict=False))), source)
        if key not in seen:
            seen.add(key)
            deduped.append((path, source))
    mods = [_catalog_one(path, source, enabled) for path, source in deduped]
    mods.sort(key=lambda item: (item["source"], str(item["title"] or item["id"]).casefold()))
    if query:
        needle = query.casefold()
        mods = [
            item
            for item in mods
            if needle
            in " ".join(
                str(item.get(field) or "")
                for field in ("id", "title", "type", "source", "steam_mod_id")
            ).casefold()
        ]
    return {
        "query": query,
        "count": len(mods),
        "enabled_count": sum(bool(item["enabled"]) for item in mods),
        "unique_enabled_count": len({item["id"] for item in mods if item["enabled"]}),
        "mods": mods,
    }


def find_conflicts(paths: Sequence[Path], ctx: DiscoveryContext | None = None) -> dict[str, Any]:
    ctx = ctx or DiscoveryContext()
    providers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    display_path: dict[str, str] = {}
    scanned: list[dict[str, Any]] = []
    for order, raw in enumerate(paths):
        path = raw.expanduser().resolve(strict=False)
        manifest_path = _manifest_path_for_target(path)
        title = path.name
        mod_id = path.name
        if manifest_path:
            try:
                fields, _, _ = manifest_fields(
                    decode_utf16le_art(
                        _read_file_bounded(manifest_path, MAX_TEXT_ASSET_BYTES), str(manifest_path)
                    )
                )
                title = fields.get("Title") or title
                mod_id = (fields.get("SteamModId") or mod_id).split(",", 1)[0]
            except (OSError, ModToolError):
                pass
        payload = path / "Mod.zip" if path.is_dir() and (path / "Mod.zip").is_file() else path
        try:
            entries = content_entries(payload)
        except (ModToolError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
            scanned.append({"path": str(path), "error": str(exc)})
            continue
        scanned.append(
            {"path": str(path), "id": mod_id, "title": title, "files": len(entries), "order": order}
        )
        for entry in entries:
            key = entry.path.casefold()
            display_path.setdefault(key, entry.path)
            try:
                digest = entry.sha256()
            except (ModToolError, OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
                digest = f"unreadable:{exc}"
            providers[key].append(
                {
                    "order": order,
                    "id": mod_id,
                    "title": title,
                    "mod_path": str(path),
                    "content_path": entry.path,
                    "sha256": digest,
                }
            )
    conflicts: list[dict[str, Any]] = []
    for key, items in providers.items():
        if len(items) < 2:
            continue
        hashes = {item["sha256"] for item in items}
        conflicts.append(
            {
                "path": display_path[key],
                "kind": "identical" if len(hashes) == 1 else "different",
                "providers": items,
                "winner": items[-1],
            }
        )
    conflicts.sort(key=lambda item: item["path"].casefold())
    return {
        "mods_scanned": len(scanned),
        "file_collisions": len(conflicts),
        "different_conflicts": sum(item["kind"] == "different" for item in conflicts),
        "load_order_note": (
            "later supplied mods win; automatic enabled order is already effective load order"
        ),
        "scanned": scanned,
        "conflicts": conflicts,
    }


def canonical_manifest(
    *,
    title: str,
    description: str,
    changelog: str,
    game_version: str,
    mod_type: str,
    steam_mod_id: str,
    content: str | None = None,
) -> str:
    for field_name, field_value in (
        ("Title", title),
        ("Description", description),
        ("Changelog", changelog),
        ("GameVersion", game_version),
        ("Type", mod_type),
    ):
        if not field_value.strip():
            raise ModToolError(f"{field_name} cannot be empty in a new project")
    if not _is_ascii_decimal(game_version):
        raise ModToolError("GameVersion must be an unsigned decimal integer such as 22")
    pair = normalise_steam_mod_id(steam_mod_id, allow_single=True)
    if content is not None and not isinstance(content, str):
        raise ModToolError("Content must be text or None")
    blocks: list[tuple[str, str, str | None]] = [
        ("String", "Changelog", changelog),
        ("String", "Content", content),
        ("String", "Description", description),
        ("String", "GameVersion", game_version),
        ("U32x2", "SteamModId", pair),
        ("String", "Title", title),
        ("String", "Type", mod_type),
    ]
    rendered: list[str] = []
    for kind, name, value in blocks:
        value_line = "" if value is None else f'\n\tValue:"{_art_escape(value)}"'
        rendered.append(f'{kind}:\n{{\n\tName:"{_art_escape(name)}"{value_line}\n}}')
    return "\n" + "\n\n".join(rendered) + "\n"


def _normalise_metadata_update(key: str, value: str) -> tuple[str, str, str]:
    canonical = MUTABLE_METADATA_FIELDS.get(key.strip().casefold())
    if canonical is None:
        allowed = ", ".join(sorted(set(MUTABLE_METADATA_FIELDS.values())))
        raise ModToolError(f"unsupported metadata field {key!r}; allowed: {allowed}")
    kind = "U32x2" if canonical == "SteamModId" else "F32" if canonical == "Version" else "String"
    if canonical == "SteamModId":
        value = normalise_steam_mod_id(value, allow_single=True)
    elif canonical == "GameVersion" and not _is_ascii_decimal(value):
        raise ModToolError("GameVersion must be an unsigned decimal integer such as 22")
    return canonical, value, kind


def _manifest_shape_for_mutation(text: str) -> dict[str, str]:
    _assert_balanced_art_for_mutation(text)
    fields, kinds, duplicates = manifest_fields(text)
    ambiguous = list(dict.fromkeys(name for name in duplicates if name in MANIFEST_FIELD_KINDS))
    if ambiguous:
        raise ModToolError(
            "refusing metadata mutation: duplicate manifest fields: " + ", ".join(ambiguous)
        )
    wrong_kinds = [
        f"{name} uses {kinds[name]!r}, expected {expected!r}"
        for name, expected in MANIFEST_FIELD_KINDS.items()
        if name in kinds and kinds[name].casefold() != expected.casefold()
    ]
    if wrong_kinds:
        raise ModToolError(
            "refusing metadata mutation: invalid manifest field type: " + "; ".join(wrong_kinds)
        )
    return fields


def _validate_required_manifest_values(fields: Mapping[str, str]) -> None:
    empty = [name for name in MANIFEST_REQUIRED_FIELDS if not fields.get(name, "").strip()]
    if empty:
        raise ModToolError(
            "refusing metadata mutation: required manifest fields are missing or empty: "
            + ", ".join(empty)
        )
    if not _is_ascii_decimal(fields["GameVersion"]):
        raise ModToolError("GameVersion must be an unsigned decimal integer such as 22")
    normalise_steam_mod_id(fields["SteamModId"], allow_single=False)


def update_manifest_text(text: str, updates: Mapping[str, str]) -> str:
    _manifest_shape_for_mutation(text)
    result = text
    newline = "\r\n" if "\r\n" in text else "\n"
    for raw_key, raw_value in updates.items():
        field_name, value, kind = _normalise_metadata_update(raw_key, str(raw_value))
        replaced = False
        pieces: list[str] = []
        cursor = 0
        for _, body, _, _, body_start, body_end in _iter_art_block_spans(result):
            if _body_property(body, "Name") != field_name:
                continue
            value_match = re.search(rf"(?<![A-Za-z0-9_])Value\s*:\s*{_ART_QUOTED}", body)
            if value_match:
                absolute_start = body_start + value_match.start(1)
                absolute_end = body_start + value_match.end(1)
                pieces.extend([result[cursor:absolute_start], _art_escape(value)])
                cursor = absolute_end
            else:
                insertion = body_end
                prefix = "" if body.endswith("\n") else newline
                pieces.extend(
                    [result[cursor:insertion], f'{prefix}\tValue:"{_art_escape(value)}"{newline}']
                )
                cursor = insertion
            replaced = True
            break
        if replaced:
            pieces.append(result[cursor:])
            result = "".join(pieces)
        else:
            if result and not result.endswith("\n"):
                result += newline
            result += (
                f"{newline}{kind}:{newline}{{{newline}"
                f'\tName:"{_art_escape(field_name)}"{newline}'
                f'\tValue:"{_art_escape(value)}"{newline}}}{newline}'
            )
    final_fields = _manifest_shape_for_mutation(result)
    _validate_required_manifest_values(final_fields)
    return result


def _create_backup(path: Path) -> Path:
    """Copy *path* to a new sibling without ever following a backup symlink."""

    index = 0
    while True:
        suffix = ".bak" if index == 0 else f".bak.{index}"
        candidate = path.with_name(path.name + suffix)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags, 0o600)
            break
        except FileExistsError:
            index += 1
        except OSError as exc:
            raise ModToolError(f"cannot safely create backup {candidate}: {exc}") from exc

    created_stat = os.fstat(descriptor)
    try:
        with path.open("rb") as source, os.fdopen(descriptor, "wb") as destination:
            descriptor = -1
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        # Remove only the exact directory entry we created.  If another local
        # process replaced it, leave that new entry untouched.
        try:
            current = os.lstat(candidate)
            if (current.st_dev, current.st_ino) == (created_stat.st_dev, created_stat.st_ino):
                os.unlink(candidate)
        except OSError:
            pass
        raise
    return candidate


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def apply_metadata(
    target: Path,
    updates: Mapping[str, str],
    *,
    apply: bool,
    backup: bool,
    ctx: DiscoveryContext | None = None,
) -> dict[str, Any]:
    ctx = ctx or DiscoveryContext()
    lexical_target = Path(os.path.abspath(os.fspath(target.expanduser())))
    lexical_root = (
        lexical_target.parent if lexical_target.name.casefold() == "index.art" else lexical_target
    )
    manifest_matches = _root_file_matches(lexical_root, "Index.art")
    if len(manifest_matches) > 1:
        names = ", ".join(path.name for path in manifest_matches)
        raise ModToolError(f"ambiguous root Index.art variants: {names}")
    lexical_manifest = manifest_matches[0] if manifest_matches else lexical_root / "Index.art"
    if apply:
        assert_no_symlink_components(lexical_manifest)
    manifest_path = lexical_manifest.resolve(strict=False)
    if not manifest_path.is_file():
        raise ModToolError(f"Index.art not found: {manifest_path}")
    original_data = _read_file_bounded(manifest_path, MAX_TEXT_ASSET_BYTES)
    original_text = decode_utf16le_art(original_data, str(manifest_path))
    changed_text = update_manifest_text(original_text, updates)
    changed_data = encode_utf16le_art(changed_text)
    if decode_utf16le_art(changed_data, str(manifest_path)) != changed_text:
        raise ModToolError(
            "refusing metadata update because the changed manifest did not round-trip"
        )
    changed = changed_data != original_data
    diff = "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            changed_text.splitlines(keepends=True),
            fromfile=str(manifest_path),
            tofile=str(manifest_path) + " (proposed)",
        )
    )
    backup_path: Path | None = None
    if apply and changed:
        assert_writable_project_path(manifest_path, ctx)
        if backup:
            backup_path = _create_backup(manifest_path)
        _atomic_write(manifest_path, changed_data)
    return {
        "mode": "apply" if apply else "dry-run",
        "path": str(manifest_path),
        "changed": changed,
        "backup": str(backup_path) if backup_path else None,
        "updates": dict(updates),
        "diff": diff,
    }


def initialise_project(
    target: Path,
    *,
    title: str,
    description: str,
    changelog: str,
    game_version: str,
    mod_type: str,
    steam_mod_id: str,
    apply: bool,
    ctx: DiscoveryContext | None = None,
) -> dict[str, Any]:
    ctx = ctx or DiscoveryContext()
    lexical_target = Path(os.path.abspath(os.fspath(target.expanduser())))
    if apply:
        assert_no_symlink_components(lexical_target)
    target = lexical_target.resolve(strict=False)
    manifest_path = target / "Index.art"
    ancient_root = target / "Ancient"
    if manifest_path.exists():
        raise ModToolError(f"refusing to overwrite existing {manifest_path}")
    if target.exists():
        if not target.is_dir():
            raise ModToolError(f"project target exists and is not a directory: {target}")
        try:
            non_empty = next(target.iterdir(), None) is not None
        except OSError as exc:
            raise ModToolError(f"cannot safely inspect project target {target}: {exc}") from exc
        if non_empty:
            raise ModToolError(f"refusing to initialise non-empty project directory: {target}")
    text = canonical_manifest(
        title=title,
        description=description,
        changelog=changelog,
        game_version=game_version,
        mod_type=mod_type,
        steam_mod_id=steam_mod_id,
    )
    data = encode_utf16le_art(text)
    decode_utf16le_art(data, str(manifest_path))
    if apply:
        assert_writable_project_path(target, ctx)
        target.mkdir(parents=True, exist_ok=True)
        ancient_root.mkdir(parents=True, exist_ok=True)
        _atomic_write(manifest_path, data)
    return {
        "mode": "apply" if apply else "dry-run",
        "project": str(target),
        "would_create": [str(manifest_path), str(ancient_root)],
        "manifest": manifest_fields(text)[0],
        "next": (
            "create a square 512x512 Thumbnail.jpg, add payload files below Ancient/, "
            "then run validate and build --apply"
        ),
    }


def _zip_info(
    name: str,
    *,
    directory: bool,
    size: int = 0,
    compress_type: int | None = None,
) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.create_system = 3
    info.file_size = size
    info.compress_type = (
        zipfile.ZIP_STORED
        if directory
        else zipfile.ZIP_DEFLATED
        if compress_type is None
        else compress_type
    )
    info._compresslevel = 9
    info.external_attr = ((stat.S_IFDIR | 0o755) if directory else (stat.S_IFREG | 0o644)) << 16
    if directory:
        info.external_attr |= 0x10
    return info


def _collect_zip_payload(
    project: Path,
) -> tuple[list[tuple[str, Path]], list[tuple[str, Path, int]]]:
    project = project.expanduser().resolve(strict=False)
    root = project / "Ancient"
    if not root.is_dir() or root.name != "Ancient":
        raise ModToolError(f"project must contain exact payload root {root}")
    if path_is_link_like(root):
        raise ModToolError(f"symbolic link payload root is forbidden: {root}")
    directories: list[tuple[str, Path]] = []
    files: list[tuple[str, Path, int]] = []
    for path in _bounded_tree_entries(root):
        if path_is_link_like(path):
            raise ModToolError(f"symbolic links are not allowed in Mod.zip: {path}")
        relative = path.relative_to(project).as_posix()
        if path.is_dir():
            directories.append((relative.rstrip("/") + "/", path))
        elif path.is_file():
            if path.suffix.casefold() in EXECUTABLE_EXTENSIONS:
                raise ModToolError(f"executable content is forbidden: {path}")
            size = path.stat().st_size
            if size > MAX_ZIP_MEMBER_BYTES:
                raise ModToolError(
                    f"payload {path} is {size} bytes; hard per-file limit is {MAX_ZIP_MEMBER_BYTES}"
                )
            files.append((relative, path, size))
    if len(directories) + len(files) + 1 > MAX_ZIP_FILES:
        raise ModToolError(f"payload exceeds the hard {MAX_ZIP_FILES}-entry limit")
    total_size = sum(size for _, _, size in files)
    if total_size > MAX_ZIP_TOTAL_BYTES:
        raise ModToolError(
            f"payload is {total_size} bytes; hard total limit is {MAX_ZIP_TOTAL_BYTES}"
        )
    directories.sort(key=lambda item: (item[0].casefold(), item[0]))
    files.sort(key=lambda item: (item[0].casefold(), item[0]))
    folded: dict[str, str] = {}
    for name in [item[0] for item in directories] + [item[0] for item in files]:
        key = name.rstrip("/").casefold()
        if key in folded:
            raise ModToolError(
                f"case-insensitive duplicate content paths: {folded[key]} and {name}"
            )
        folded[key] = name
    return directories, files


def _safe_compress_type(path: Path, expected_size: int) -> int:
    """Choose DEFLATE only when the resulting member meets our ratio cap."""

    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed_size = 0
    actual_size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                actual_size += len(chunk)
                if actual_size > MAX_ZIP_MEMBER_BYTES:
                    raise ModToolError(f"payload grew beyond the hard per-file limit: {path}")
                compressed_size += len(compressor.compress(chunk))
        compressed_size += len(compressor.flush())
    except (OSError, zlib.error) as exc:
        raise ModToolError(f"cannot analyse payload compression for {path}: {exc}") from exc
    if actual_size != expected_size:
        raise ModToolError(f"payload changed while preparing Mod.zip: {path}")
    if actual_size and (
        compressed_size == 0 or actual_size / compressed_size > MAX_ZIP_COMPRESSION_RATIO
    ):
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


def _write_zip_archive(project: Path, output: Path) -> list[str]:
    directories, files = _collect_zip_payload(project)
    compression = {name: _safe_compress_type(path, size) for name, path, size in files}
    names = ["Ancient/"]
    try:
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
            strict_timestamps=True,
        ) as archive:
            archive.comment = b""
            archive.writestr(_zip_info("Ancient/", directory=True), b"")
            for name, _ in directories:
                archive.writestr(_zip_info(name, directory=True), b"")
                names.append(name)
            for name, path, expected_size in files:
                info = _zip_info(
                    name,
                    directory=False,
                    size=expected_size,
                    compress_type=compression[name],
                )
                written = 0
                with path.open("rb") as source, archive.open(info, "w") as destination:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > MAX_ZIP_MEMBER_BYTES:
                            raise ModToolError(
                                f"payload grew beyond the hard per-file limit: {path}"
                            )
                        destination.write(chunk)
                if written != expected_size:
                    raise ModToolError(f"payload changed while writing Mod.zip: {path}")
                names.append(name)
        _preflight_zip_directory(output)
        with zipfile.ZipFile(output, "r") as archive:
            _check_zip_collection_limits(archive.infolist())
    except ModToolError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ModToolError(f"cannot build Mod.zip: {exc}") from exc
    return names


def _new_temporary_zip(directory: Path | None = None) -> Path:
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".acmk-build-", suffix=".zip.tmp", dir=directory
    )
    os.close(descriptor)
    return Path(temp_name)


def build_zip_bytes(project: Path) -> tuple[bytes, list[str]]:
    """Compatibility helper for small archives; the CLI builder streams to disk."""

    temporary = _new_temporary_zip()
    try:
        names = _write_zip_archive(project, temporary)
        size = temporary.stat().st_size
        if size > MAX_IN_MEMORY_ZIP_BYTES:
            raise ModToolError(
                f"archive is {size} bytes; build_zip_bytes has a hard in-memory limit of "
                f"{MAX_IN_MEMORY_ZIP_BYTES}; use build_project for streamed output"
            )
        return _read_file_bounded(temporary, MAX_IN_MEMORY_ZIP_BYTES), names
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _casefold_path_parts(path: Path) -> tuple[str, ...]:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path.absolute()
    return tuple(part.casefold() for part in resolved.parts)


def _path_within_casefold(path: Path, root: Path) -> bool:
    path_parts = _casefold_path_parts(path)
    root_parts = _casefold_path_parts(root)
    return len(path_parts) >= len(root_parts) and path_parts[: len(root_parts)] == root_parts


def _assert_safe_build_output(project: Path, destination: Path) -> None:
    manifest = project / "Index.art"
    thumbnail = project / "Thumbnail.jpg"
    if _casefold_path_parts(destination) in {
        _casefold_path_parts(manifest),
        _casefold_path_parts(thumbnail),
    } or _path_within_casefold(destination, project / "Ancient"):
        raise ModToolError(f"build output collides with project source content: {destination}")
    if destination.exists() and destination.is_dir():
        raise ModToolError(f"build output must be a file path, not a directory: {destination}")


def build_project(
    project: Path,
    *,
    output: Path | None,
    apply: bool,
    ctx: DiscoveryContext | None = None,
) -> dict[str, Any]:
    ctx = ctx or DiscoveryContext()
    lexical_project = Path(os.path.abspath(os.fspath(project.expanduser())))
    if apply:
        assert_no_symlink_components(lexical_project)
    project = lexical_project.resolve(strict=False)
    manifest = project / "Index.art"
    if not manifest.is_file():
        raise ModToolError(f"project root Index.art not found: {manifest}")
    decode_utf16le_art(_read_file_bounded(manifest, MAX_TEXT_ASSET_BYTES), str(manifest))
    preflight = validate_target(project, ctx, check_archive=False)
    if not preflight["valid"]:
        codes = ", ".join(
            issue["code"] for issue in preflight["issues"] if issue["severity"] == "error"
        )
        raise ModToolError(f"source validation failed; Mod.zip was not built ({codes})")
    lexical_destination = Path(
        os.path.abspath(os.fspath((output or (lexical_project / "Mod.zip")).expanduser()))
    )
    if apply:
        assert_no_symlink_components(lexical_destination)
    destination = lexical_destination.resolve(strict=False)
    _assert_safe_build_output(project, destination)
    backup_path: Path | None = None
    temporary: Path | None = None
    try:
        if apply:
            assert_writable_project_path(destination, ctx)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = _new_temporary_zip(destination.parent)
        else:
            temporary = _new_temporary_zip()
        names = _write_zip_archive(project, temporary)
        archive_size = temporary.stat().st_size
        archive_hash = _hash_file(temporary)
        if apply:
            if destination.exists():
                if not destination.is_file():
                    raise ModToolError(f"build output exists and is not a file: {destination}")
                backup_path = _create_backup(destination)
            os.replace(temporary, destination)
            temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
    return {
        "mode": "apply" if apply else "dry-run",
        "project": str(project),
        "output": str(destination),
        "bytes": archive_size,
        "sha256": archive_hash,
        "backup": str(backup_path) if backup_path else None,
        "members": names,
        "deterministic_timestamp": "1980-01-01T00:00:00",
        "preflight": {
            "errors": preflight["errors"],
            "warnings": preflight["warnings"],
            "notices": preflight["notices"],
        },
    }


def summarise_log(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    warning_lines = [line for line in lines if re.search(r"\bwarning\b", line, re.IGNORECASE)]
    error_lines = [
        line for line in lines if re.search(r"\berror\b|\bfailed\b", line, re.IGNORECASE)
    ]
    mod_enable = [line for line in lines if "Enabling Mod:" in line]
    return {
        "lines": len(lines),
        "warnings": len(warning_lines),
        "errors_or_failures": len(error_lines),
        "mods_enabled": len(mod_enable),
    }


def read_log(path: Path, *, tail: int | None, severity: str) -> dict[str, Any]:
    try:
        text = decode_log_bytes(_read_file_bounded(path, MAX_LOG_BYTES), str(path))
    except (ModToolError, OSError) as exc:
        raise ModToolError(f"cannot read {path}: {exc}") from exc
    lines = text.splitlines()
    if severity == "warning":
        selected = [line for line in lines if re.search(r"\bwarning\b", line, re.IGNORECASE)]
    elif severity == "error":
        selected = [
            line for line in lines if re.search(r"\berror\b|\bfailed\b", line, re.IGNORECASE)
        ]
    else:
        selected = lines
    if tail is not None:
        selected = selected[-tail:]
    return {
        "path": str(path),
        "encoding": "UTF-16LE",
        "summary": summarise_log(text),
        "lines": selected,
    }


def _default_conflict_paths(ctx: DiscoveryContext) -> list[Path]:
    paths: list[Path] = []
    for item in ctx.enabled_load_order:
        mod_id = item["id"]
        candidates: list[Path] = []
        if ctx.user_root is not None:
            candidates.append(ctx.user_root / "Mod" / mod_id)
        candidates.extend(root / mod_id for root in ctx.workshop_roots)
        if ctx.base_data_root is not None:
            candidates.append(ctx.base_data_root / "Mod" / mod_id)
        chosen = next((candidate for candidate in candidates if candidate.is_dir()), None)
        if chosen is not None:
            paths.append(chosen)
    return paths


def _args_context(args: argparse.Namespace) -> DiscoveryContext:
    return discover_context(
        steam_root=Path(args.steam_root) if args.steam_root else None,
        game_dir=Path(args.game_dir) if args.game_dir else None,
        documents_dir=Path(args.documents_dir) if args.documents_dir else None,
    )


def _emit(data: Any, *, json_mode: bool = False) -> None:
    # Pretty JSON is deliberately the stable default; --json uses compact output
    # suitable for scripts while retaining the exact same schema.
    if json_mode:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False))


def _parse_set_values(values: Sequence[str]) -> dict[str, str]:
    updates: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ModToolError(f"--set expects FIELD=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        if not key.strip():
            raise ModToolError("--set field name cannot be empty")
        updates[key.strip()] = value
    return updates


def run_self_tests() -> int:
    """Run the repository's synthetic suite, or a small installed smoke test."""

    repo_root = Path(__file__).resolve().parents[3]
    tests_dir = repo_root / "tests"
    if tests_dir.is_dir() and any(tests_dir.glob("test_*.py")):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(tests_dir),
            "-p",
            "test_*.py",
            "-v",
        ]
        return subprocess.run(command, cwd=repo_root, env=environment, check=False).returncode
    # Installed skills may omit repository tests. Keep a meaningful built-in check.
    sample = canonical_manifest(
        title="Self test",
        description="Synthetic",
        changelog="Initial",
        game_version="1",
        mod_type="Generic",
        steam_mod_id="0",
    )
    data = encode_utf16le_art(sample)
    if decode_utf16le_art(data) != sample or manifest_fields(sample)[0].get("Type") != "Generic":
        print("self-test failed: UTF-16LE or manifest parser", file=sys.stderr)
        return 1
    print("self-test passed (installed smoke test)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    program = Path(sys.argv[0]).name
    if program.lower().endswith(".exe"):
        program = program[:-4]
    parser = argparse.ArgumentParser(
        prog=program,
        description="Read-only discovery plus safe, dry-run-first Ancient Cities mod tooling.",
    )
    parser.add_argument("--json", action="store_true", help="emit compact machine-readable JSON")
    parser.add_argument("--steam-root", help="override the Steam installation root")
    parser.add_argument("--game-dir", help="override the Ancient Cities installation directory")
    parser.add_argument("--documents-dir", help="override the Windows My Documents directory")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "discover", help="discover Steam libraries, game version/build/hash, and enabled order"
    )

    catalog = sub.add_parser("catalog", help="catalog Workshop, user-cache, and built-in mods")
    catalog.add_argument("paths", nargs="*", help="optional mod or collection directories")
    catalog.add_argument("--query", help="case-insensitive ID/title/type/source filter")

    inspect = sub.add_parser("inspect", help="inspect and classify one mod/project/archive")
    inspect.add_argument("target")

    validate = sub.add_parser(
        "validate", help="validate encoding, manifest, archive, assets, and references"
    )
    validate.add_argument("target")
    validate.add_argument("--strict", action="store_true", help="return failure for warnings too")

    conflicts = sub.add_parser("conflicts", help="find path collisions in effective load order")
    conflicts.add_argument("paths", nargs="*", help="mods in load order; later paths win")

    metadata = sub.add_parser("metadata", help="preview or safely update root Index.art metadata")
    metadata.add_argument("target", help="project directory or Index.art")
    metadata.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")
    metadata.add_argument("--title")
    metadata.add_argument("--description")
    metadata.add_argument("--changelog")
    metadata.add_argument("--game-version")
    metadata.add_argument("--type", dest="mod_type")
    metadata.add_argument("--steam-mod-id")
    metadata.add_argument("--content")
    metadata.add_argument("--version")
    metadata.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    metadata.add_argument(
        "--no-backup", action="store_true", help="do not create Index.art.bak on apply"
    )

    init = sub.add_parser(
        "init-project", help="preview or create a minimal community-format project"
    )
    init.add_argument("target")
    init.add_argument("--title", help="display title; defaults to directory name")
    init.add_argument("--description", default="Describe this mod for Workshop users.")
    init.add_argument("--changelog", default="Initial version")
    init.add_argument(
        "--game-version", help="mod API GameVersion; defaults to discovered current value"
    )
    init.add_argument("--type", dest="mod_type", default="Generic")
    init.add_argument("--steam-mod-id", default="0")
    init.add_argument("--apply", action="store_true", help="create files (default is dry-run)")

    build = sub.add_parser("build", help="preview or create deterministic Mod.zip")
    build.add_argument("project")
    build.add_argument("--output")
    build.add_argument("--apply", action="store_true", help="write Mod.zip (default is dry-run)")

    log = sub.add_parser("log", help="decode BOM-less UTF-16LE Log.txt and filter diagnostics")
    log.add_argument("--path", help="override Log.txt")
    log.add_argument(
        "--tail", type=int, default=200, help="show last N selected lines (default 200)"
    )
    log.add_argument("--all", action="store_true", help="show all selected lines")
    log.add_argument("--severity", choices=("all", "warning", "error"), default="all")

    sub.add_parser("self-test", help="run synthetic, non-proprietary unit tests")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "self-test":
        return run_self_tests()
    try:
        ctx = _args_context(args)
        if args.command == "discover":
            result = context_to_dict(ctx)
        elif args.command == "catalog":
            result = catalog_mods(ctx, [Path(path) for path in args.paths], query=args.query)
        elif args.command == "inspect":
            result = inspect_target(Path(args.target), ctx)
        elif args.command == "validate":
            result = validate_target(Path(args.target), ctx)
            _emit(result, json_mode=args.json)
            if not result["valid"] or (args.strict and result["warnings"]):
                return 1
            return 0
        elif args.command == "conflicts":
            paths = [Path(path) for path in args.paths] or _default_conflict_paths(ctx)
            if not paths:
                raise ModToolError(
                    "no mod paths supplied and no enabled user-cache mods were discovered"
                )
            result = find_conflicts(paths, ctx)
        elif args.command == "metadata":
            updates = _parse_set_values(args.set)
            for key, value in (
                ("Title", args.title),
                ("Description", args.description),
                ("Changelog", args.changelog),
                ("GameVersion", args.game_version),
                ("Type", args.mod_type),
                ("SteamModId", args.steam_mod_id),
                ("Content", args.content),
                ("Version", args.version),
            ):
                if value is not None:
                    updates[key] = value
            if not updates:
                raise ModToolError("metadata requires at least one --set or named field option")
            result = apply_metadata(
                Path(args.target),
                updates,
                apply=args.apply,
                backup=not args.no_backup,
                ctx=ctx,
            )
        elif args.command == "init-project":
            target = Path(args.target)
            game_version = args.game_version or ctx.game_version
            if not game_version:
                raise ModToolError("GameVersion could not be discovered; provide --game-version")
            result = initialise_project(
                target,
                title=args.title or target.name,
                description=args.description,
                changelog=args.changelog,
                game_version=game_version,
                mod_type=args.mod_type,
                steam_mod_id=args.steam_mod_id,
                apply=args.apply,
                ctx=ctx,
            )
        elif args.command == "build":
            result = build_project(
                Path(args.project),
                output=Path(args.output) if args.output else None,
                apply=args.apply,
                ctx=ctx,
            )
        elif args.command == "log":
            if args.path:
                path = Path(args.path).expanduser().resolve(strict=False)
            elif ctx.user_root:
                path = ctx.user_root / "Log.txt"
            else:
                raise ModToolError("Log.txt was not discovered; provide --path")
            if args.tail is not None and args.tail < 0:
                raise ModToolError("--tail cannot be negative")
            result = read_log(path, tail=None if args.all else args.tail, severity=args.severity)
        else:  # pragma: no cover - argparse guarantees dispatch
            parser.error(f"unsupported command {args.command}")
            return 2
        _emit(result, json_mode=args.json)
        return 0
    except (ModToolError, OSError, zipfile.BadZipFile) as exc:
        if args.json:
            _emit({"error": str(exc), "command": args.command}, json_mode=True)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

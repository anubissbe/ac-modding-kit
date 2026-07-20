"""Lossless ART/LOC documents and validated manifest specifications."""

from __future__ import annotations

import codecs
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

import ancient_cities_mod as _legacy

from .errors import ContractError

_ASCII_U32_PAIR = re.compile(r"[0-9]+(?:,[0-9]+)?\Z")
_ASCII_GAME_VERSION = re.compile(r"[0-9]+\Z")


class TextAssetKind(StrEnum):
    ART = "art"
    LOC = "loc"


class NewlineStyle(StrEnum):
    LF = "lf"
    CRLF = "crlf"
    NONE = "none"
    MIXED = "mixed"


def _newline_style(text: str) -> NewlineStyle:
    without_crlf = text.replace("\r\n", "")
    has_crlf = "\r\n" in text
    has_lf = "\n" in without_crlf
    has_cr = "\r" in without_crlf
    if has_crlf and (has_lf or has_cr):
        return NewlineStyle.MIXED
    if has_cr or (has_lf and has_crlf):
        return NewlineStyle.MIXED
    if has_crlf:
        return NewlineStyle.CRLF
    if has_lf:
        return NewlineStyle.LF
    return NewlineStyle.NONE


@dataclass(frozen=True, slots=True)
class Utf16TextDocument:
    kind: TextAssetKind
    text: str
    original_bytes: bytes
    newline_style: NewlineStyle
    source_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TextAssetKind):
            raise ContractError("document kind must be TextAssetKind")
        if not isinstance(self.text, str) or not isinstance(self.original_bytes, bytes):
            raise ContractError("document text and original bytes have invalid types")
        if len(self.original_bytes) > _legacy.MAX_TEXT_ASSET_BYTES:
            raise ContractError(
                f"text asset exceeds {_legacy.MAX_TEXT_ASSET_BYTES} bytes",
                code="TEXT_RESOURCE_LIMIT",
            )
        try:
            decoded = _legacy.decode_utf16le_art(self.original_bytes, "ART/LOC document")
        except _legacy.ModToolError as exc:
            raise ContractError(str(exc), code="TEXT_ENCODING") from exc
        if decoded != self.text:
            raise ContractError("document text does not match original bytes")
        if self.source_sha256 != hashlib.sha256(self.original_bytes).hexdigest():
            raise ContractError("document source hash does not match original bytes")
        if self.newline_style is not _newline_style(self.text):
            raise ContractError("document newline style does not match its text")

    @classmethod
    def from_bytes(
        cls, data: bytes, *, kind: TextAssetKind, label: str = "ART/LOC document"
    ) -> Utf16TextDocument:
        if data.startswith(codecs.BOM_UTF16_LE + codecs.BOM_UTF16_LE):
            raise ContractError(f"{label} contains more than one UTF-16LE BOM", code="DOUBLE_BOM")
        try:
            text = _legacy.decode_utf16le_art(data, label)
        except _legacy.ModToolError as exc:
            raise ContractError(str(exc), code="TEXT_ENCODING") from exc
        if text.startswith("\ufeff"):
            raise ContractError(f"{label} contains an embedded leading BOM", code="DOUBLE_BOM")
        return cls(
            kind=kind,
            text=text,
            original_bytes=bytes(data),
            newline_style=_newline_style(text),
            source_sha256=hashlib.sha256(data).hexdigest(),
        )

    @classmethod
    def from_text(cls, text: str, *, kind: TextAssetKind) -> Utf16TextDocument:
        if text.startswith("\ufeff"):
            raise ContractError("text must not contain an embedded BOM", code="DOUBLE_BOM")
        try:
            data = _legacy.encode_utf16le_art(text)
        except _legacy.ModToolError as exc:
            raise ContractError(str(exc), code="TEXT_ENCODING") from exc
        return cls.from_bytes(data, kind=kind)

    @classmethod
    def read(cls, path: str | Path, *, kind: TextAssetKind | None = None) -> Utf16TextDocument:
        source = Path(path)
        selected = kind or (
            TextAssetKind.LOC if source.suffix.casefold() == ".loc" else TextAssetKind.ART
        )
        try:
            data = _legacy._read_file_bounded(source, _legacy.MAX_TEXT_ASSET_BYTES)
        except (OSError, _legacy.ModToolError) as exc:
            raise ContractError(
                f"cannot read {source}: {exc}", code="TEXT_READ", path=source
            ) from exc
        return cls.from_bytes(data, kind=selected, label=str(source))

    def to_bytes(self) -> bytes:
        return bytes(self.original_bytes)


@dataclass(frozen=True, slots=True)
class SteamModId:
    low: int = 0
    high: int = 0

    def __post_init__(self) -> None:
        if (
            isinstance(self.low, bool)
            or isinstance(self.high, bool)
            or not isinstance(self.low, int)
            or not isinstance(self.high, int)
        ):
            raise ContractError("SteamModId components must be integers")
        if not (0 <= self.low <= 0xFFFF_FFFF and 0 <= self.high <= 0xFFFF_FFFF):
            raise ContractError("SteamModId components must be unsigned 32-bit values")

    @classmethod
    def parse(cls, value: str | int | SteamModId) -> SteamModId:
        if isinstance(value, cls):
            return value
        text = str(value).strip()
        if not _ASCII_U32_PAIR.fullmatch(text):
            raise ContractError("SteamModId must contain one or two ASCII-decimal U32 values")
        parts = text.split(",")
        if any(len(part) > 10 for part in parts):
            raise ContractError("SteamModId components must fit unsigned 32-bit values")
        values = [int(part) for part in parts]
        if len(values) == 1:
            values.append(0)
        return cls(values[0], values[1])

    def __str__(self) -> str:
        return f"{self.low},{self.high}"


@dataclass(frozen=True, slots=True)
class GameVersion:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise ContractError("GameVersion must be a string")
        if not _ASCII_GAME_VERSION.fullmatch(self.value):
            raise ContractError("GameVersion must contain ASCII decimal digits such as 22")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ManifestDocument:
    document: Utf16TextDocument
    fields: Mapping[str, str]
    kinds: Mapping[str, str]
    duplicates: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.document.kind is not TextAssetKind.ART:
            raise ContractError("manifest document must contain ART text")
        try:
            fields, kinds, duplicates = _legacy.manifest_fields(self.document.text)
        except _legacy.ModToolError as exc:
            raise ContractError(str(exc), code="ART_PARSE") from exc
        if (
            dict(self.fields) != fields
            or dict(self.kinds) != kinds
            or tuple(self.duplicates) != tuple(duplicates)
        ):
            raise ContractError("manifest scan metadata does not match its document")
        object.__setattr__(self, "fields", MappingProxyType(dict(fields)))
        object.__setattr__(self, "kinds", MappingProxyType(dict(kinds)))
        object.__setattr__(self, "duplicates", tuple(duplicates))

    @classmethod
    def scan(cls, document: Utf16TextDocument) -> ManifestDocument:
        if document.kind is not TextAssetKind.ART:
            raise ContractError("Index.art must be scanned as an ART document")
        try:
            fields, kinds, duplicates = _legacy.manifest_fields(document.text)
        except _legacy.ModToolError as exc:
            raise ContractError(str(exc), code="ART_PARSE") from exc
        return cls(
            document=document,
            fields=MappingProxyType(dict(fields)),
            kinds=MappingProxyType(dict(kinds)),
            duplicates=tuple(duplicates),
        )

    @classmethod
    def from_bytes(cls, data: bytes, *, label: str = "Index.art") -> ManifestDocument:
        return cls.scan(Utf16TextDocument.from_bytes(data, kind=TextAssetKind.ART, label=label))

    @classmethod
    def read(cls, path: str | Path) -> ManifestDocument:
        return cls.scan(Utf16TextDocument.read(path, kind=TextAssetKind.ART))

    def updated(self, updates: Mapping[str, str]) -> ManifestDocument:
        if self.duplicates:
            joined = ", ".join(sorted(set(self.duplicates)))
            raise ContractError(
                f"refusing to mutate manifest with duplicate fields: {joined}",
                code="MANIFEST_AMBIGUOUS",
            )
        if self.document.newline_style is NewlineStyle.MIXED:
            raise ContractError(
                "refusing to mutate a manifest with mixed newline styles",
                code="MANIFEST_AMBIGUOUS",
            )
        try:
            changed = _legacy.update_manifest_text(self.document.text, updates)
        except _legacy.ModToolError as exc:
            raise ContractError(str(exc), code="MANIFEST_UPDATE") from exc
        return ManifestDocument.scan(Utf16TextDocument.from_text(changed, kind=TextAssetKind.ART))

    def to_bytes(self) -> bytes:
        return self.document.to_bytes()


@dataclass(frozen=True, slots=True)
class ManifestSpec:
    title: str
    description: str
    changelog: str
    game_version: GameVersion
    mod_type: str = "Generic"
    steam_mod_id: SteamModId = SteamModId()
    content: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.game_version, GameVersion):
            raise ContractError("manifest game_version must be GameVersion")
        if not isinstance(self.steam_mod_id, SteamModId):
            raise ContractError("manifest steam_mod_id must be SteamModId")
        if any(
            not isinstance(value, str)
            for value in (self.title, self.description, self.changelog, self.mod_type)
        ) or (self.content is not None and not isinstance(self.content, str)):
            raise ContractError("manifest text fields must be strings")
        for name, value in (
            ("title", self.title),
            ("description", self.description),
            ("changelog", self.changelog),
            ("mod_type", self.mod_type),
        ):
            if not value.strip():
                raise ContractError(f"manifest {name} cannot be empty")
            if "\x00" in value:
                raise ContractError(f"manifest {name} cannot contain NUL")
        if self.content is not None and "\x00" in self.content:
            raise ContractError("manifest content cannot contain NUL")

    def render(self) -> ManifestDocument:
        try:
            text = _legacy.canonical_manifest(
                title=self.title,
                description=self.description,
                changelog=self.changelog,
                game_version=str(self.game_version),
                mod_type=self.mod_type,
                steam_mod_id=str(self.steam_mod_id),
                content=self.content,
            )
        except _legacy.ModToolError as exc:
            raise ContractError(str(exc), code="MANIFEST_SPEC") from exc
        return ManifestDocument.scan(Utf16TextDocument.from_text(text, kind=TextAssetKind.ART))

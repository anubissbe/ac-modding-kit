"""Typed, offline access to the bundled Ancient Cities modding knowledge base.

The Markdown documents are package resources so this module works from both an
editable checkout and an installed wheel.  It deliberately performs no network
or game-installation access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable

from .errors import ACMKError, ContractError

KNOWLEDGE_PACKAGE = "acmk.knowledge_data"
MAX_DOCUMENT_BYTES = 512 * 1024
MAX_QUERY_CHARACTERS = 512
MAX_SEARCH_RESULTS = 100

_TOPIC_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_H1 = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)


class KnowledgeError(ACMKError):
    """Base exception for unavailable or malformed bundled knowledge."""

    default_code = "KNOWLEDGE_ERROR"


class UnknownTopicError(KnowledgeError):
    """Raised when a requested topic is not present in the bundle."""

    default_code = "KNOWLEDGE_TOPIC_UNKNOWN"


@dataclass(frozen=True, slots=True, order=True)
class KnowledgeTopic:
    """A discoverable Markdown topic in the offline knowledge base."""

    id: str
    title: str


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """The complete text of one bundled topic."""

    topic: KnowledgeTopic
    text: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One matching source line, retaining its topic and one-based line number."""

    topic: KnowledgeTopic
    line_number: int
    excerpt: str


TopicLike = KnowledgeTopic | str


def _knowledge_root() -> Traversable:
    try:
        return resources.files(KNOWLEDGE_PACKAGE)
    except (ModuleNotFoundError, TypeError) as exc:
        raise KnowledgeError("the bundled knowledge package is unavailable") from exc


def _topic_id(value: TopicLike) -> str:
    topic_id = value.id if isinstance(value, KnowledgeTopic) else value
    if not isinstance(topic_id, str) or _TOPIC_ID.fullmatch(topic_id) is None:
        raise UnknownTopicError(f"unknown knowledge topic: {topic_id!r}")
    return topic_id


def _read_resource(resource: Traversable) -> str:
    try:
        payload = resource.read_bytes()
    except (FileNotFoundError, IsADirectoryError, OSError) as exc:
        raise KnowledgeError(f"cannot read bundled knowledge resource {resource.name!r}") from exc
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise KnowledgeError(
            f"bundled knowledge resource {resource.name!r} exceeds "
            f"the {MAX_DOCUMENT_BYTES}-byte limit"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgeError(
            f"bundled knowledge resource {resource.name!r} is not valid UTF-8"
        ) from exc
    if "\x00" in text:
        raise KnowledgeError(f"bundled knowledge resource {resource.name!r} contains NUL data")
    return text


def _title(text: str, resource_name: str) -> str:
    match = _H1.search(text)
    if match is None or not match.group(1).strip():
        raise KnowledgeError(
            f"bundled knowledge resource {resource_name!r} has no non-empty H1 title"
        )
    return match.group(1).strip()


def _catalog() -> tuple[tuple[KnowledgeTopic, Traversable], ...]:
    entries: list[tuple[KnowledgeTopic, Traversable]] = []
    seen_ids: set[str] = set()
    try:
        candidates = tuple(_knowledge_root().iterdir())
    except OSError as exc:
        raise KnowledgeError("cannot enumerate the bundled knowledge package") from exc

    for resource in sorted(candidates, key=lambda item: (item.name.casefold(), item.name)):
        if not resource.is_file() or not resource.name.endswith(".md"):
            continue
        topic_id = resource.name[:-3]
        if _TOPIC_ID.fullmatch(topic_id) is None:
            raise KnowledgeError(f"unsafe bundled knowledge filename: {resource.name!r}")
        folded_id = topic_id.casefold()
        if folded_id in seen_ids:
            raise KnowledgeError(f"duplicate bundled knowledge topic: {topic_id!r}")
        seen_ids.add(folded_id)
        text = _read_resource(resource)
        entries.append((KnowledgeTopic(id=topic_id, title=_title(text, resource.name)), resource))
    return tuple(entries)


def topics() -> tuple[KnowledgeTopic, ...]:
    """Return every bundled topic in deterministic topic-id order."""

    return tuple(topic for topic, _resource in _catalog())


def read(topic: TopicLike) -> KnowledgeDocument:
    """Read one topic by id, without accepting filesystem paths."""

    wanted = _topic_id(topic)
    for known_topic, resource in _catalog():
        if known_topic.id == wanted:
            return KnowledgeDocument(topic=known_topic, text=_read_resource(resource))
    raise UnknownTopicError(f"unknown knowledge topic: {wanted!r}")


def search(
    query: str,
    *,
    topic: TopicLike | None = None,
    limit: int = 20,
) -> tuple[SearchHit, ...]:
    """Search matching lines case-insensitively in deterministic source order.

    Whitespace in both the query and source lines is normalised before matching.
    Results remain ordered by topic id and then by source line number.
    """

    if not isinstance(query, str):
        raise ContractError("query must be a string", code="KNOWLEDGE_QUERY")
    normalised_query = " ".join(query.split())
    if not normalised_query:
        raise ContractError("query must not be empty", code="KNOWLEDGE_QUERY")
    if len(normalised_query) > MAX_QUERY_CHARACTERS:
        raise ContractError(
            f"query must not exceed {MAX_QUERY_CHARACTERS} characters",
            code="KNOWLEDGE_QUERY",
        )
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ContractError("limit must be an integer", code="KNOWLEDGE_LIMIT")
    if not 1 <= limit <= MAX_SEARCH_RESULTS:
        raise ContractError(
            f"limit must be between 1 and {MAX_SEARCH_RESULTS}",
            code="KNOWLEDGE_LIMIT",
        )

    selected_id = _topic_id(topic) if topic is not None else None
    folded_query = normalised_query.casefold()
    hits: list[SearchHit] = []
    selected_found = selected_id is None

    for known_topic, resource in _catalog():
        if selected_id is not None and known_topic.id != selected_id:
            continue
        selected_found = True
        document = _read_resource(resource)
        for line_number, line in enumerate(document.splitlines(), start=1):
            excerpt = " ".join(line.split())
            if folded_query not in excerpt.casefold():
                continue
            hits.append(SearchHit(topic=known_topic, line_number=line_number, excerpt=excerpt))
            if len(hits) == limit:
                return tuple(hits)

    if not selected_found:
        raise UnknownTopicError(f"unknown knowledge topic: {selected_id!r}")
    return tuple(hits)


__all__ = [
    "KNOWLEDGE_PACKAGE",
    "MAX_DOCUMENT_BYTES",
    "MAX_QUERY_CHARACTERS",
    "MAX_SEARCH_RESULTS",
    "KnowledgeDocument",
    "KnowledgeError",
    "KnowledgeTopic",
    "SearchHit",
    "TopicLike",
    "UnknownTopicError",
    "read",
    "search",
    "topics",
]

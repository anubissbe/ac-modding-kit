"""Offline tests for the packaged Ancient Cities knowledge base."""

from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock

from acmk import knowledge
from acmk.errors import ACMKError, ContractError

REPO_ROOT = Path(__file__).resolve().parents[1]


class BundledKnowledgeTests(unittest.TestCase):
    def test_knowledge_errors_share_the_sdk_error_hierarchy(self) -> None:
        self.assertTrue(issubclass(knowledge.KnowledgeError, ACMKError))
        self.assertTrue(issubclass(knowledge.UnknownTopicError, knowledge.KnowledgeError))

    def test_topics_derive_ids_and_titles_from_markdown(self) -> None:
        bundled = knowledge.topics()
        ids = [topic.id for topic in bundled]

        self.assertEqual(ids, sorted(ids))
        self.assertIn("format-and-layout", ids)
        self.assertIn("workflows", ids)
        self.assertTrue(all(topic.title for topic in bundled))

        format_topic = next(topic for topic in bundled if topic.id == "format-and-layout")
        self.assertEqual(format_topic.title, "Format and layout")

    def test_document_is_read_offline(self) -> None:
        document = knowledge.read("format-and-layout")

        self.assertEqual(document.topic.id, "format-and-layout")
        self.assertTrue(document.text.startswith("# Format and layout"))
        self.assertIn("UTF-16LE", document.text)

    def test_workshop_publish_recovery_is_available_offline(self) -> None:
        error_15 = knowledge.search("Error 15", topic="workflows")
        no_connection = knowledge.search("No Connection", topic="workflows")
        error_9 = knowledge.search("Error 9", topic="workflows")
        file_not_found = knowledge.search("File Not Found", topic="workflows")
        game_temp = knowledge.search("ACZipMod", topic="workflows")
        published_item = knowledge.search("3768682609", topic="local-baseline")
        successor_item = knowledge.search("3769474322", topic="local-baseline")

        self.assertTrue(error_15)
        self.assertTrue(no_connection)
        self.assertTrue(error_9)
        self.assertTrue(file_not_found)
        self.assertTrue(game_temp)
        self.assertTrue(published_item)
        self.assertTrue(successor_item)
        workflows = knowledge.read("workflows").text
        local_baseline = knowledge.read("local-baseline").text
        self.assertIn("Access Denied", workflows)
        self.assertIn("Failed to initialize build on server (Access Denied)", workflows)
        self.assertIn("Getting Workshop info for item <id> failed : File Not Found", workflows)
        self.assertIn("SteamModId", workflows)
        self.assertIn("%TEMP%\\ACZipMod", workflows)
        self.assertIn("Yes/No", workflows)
        self.assertIn("Batch consent", workflows)
        self.assertIn("Mesolithic Branch Hut", local_baseline)
        self.assertIn("visibility `0` (Public)", local_baseline)
        self.assertIn("every remote primary JPEG byte-matched", local_baseline)

        identity_mapping = (
            ("3769249469", "3769474322"),
            ("3769249957", "3769474267"),
            ("3769250418", "3769474212"),
            ("3769250934", "3769474151"),
            ("3769452595", "3769473846"),
            ("3769452717", "3769473919"),
            ("3769452860", "3769473979"),
            ("3769452949", "3769474016"),
            ("3769453122", "3769474067"),
        )
        for predecessor, successor in identity_mapping:
            with self.subTest(predecessor=predecessor, successor=successor):
                self.assertIn(predecessor, local_baseline)
                self.assertIn(successor, local_baseline)

    def test_search_is_case_insensitive_filtered_and_deterministic(self) -> None:
        first = knowledge.search("utf-16le", topic="format-and-layout", limit=20)
        second = knowledge.search("UTF-16LE", topic="format-and-layout", limit=20)

        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertTrue(all(hit.topic.id == "format-and-layout" for hit in first))
        self.assertEqual(
            [hit.line_number for hit in first], sorted(hit.line_number for hit in first)
        )

    def test_read_rejects_paths_and_unknown_topics(self) -> None:
        for topic in ("../format-and-layout", "Format-And-Layout", "missing"):
            with self.subTest(topic=topic), self.assertRaises(knowledge.UnknownTopicError):
                knowledge.read(topic)

    def test_search_rejects_empty_queries(self) -> None:
        for query in ("", " ", "\n\t"):
            with (
                self.subTest(query=query),
                self.assertRaisesRegex(ContractError, "must not be empty"),
            ):
                knowledge.search(query)

    def test_search_rejects_non_string_query(self) -> None:
        with self.assertRaisesRegex(ContractError, "query must be a string"):
            knowledge.search(42)  # type: ignore[arg-type]

    def test_search_rejects_out_of_range_limits(self) -> None:
        for limit in (0, -1, knowledge.MAX_SEARCH_RESULTS + 1):
            with (
                self.subTest(limit=limit),
                self.assertRaisesRegex(ContractError, "limit must be between"),
            ):
                knowledge.search("mod", limit=limit)

    def test_search_rejects_non_integer_limits(self) -> None:
        for limit in (True, 1.5, "2"):
            with (
                self.subTest(limit=limit),
                self.assertRaisesRegex(ContractError, "limit must be an integer"),
            ):
                knowledge.search("mod", limit=limit)  # type: ignore[arg-type]


class SyntheticKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = REPO_ROOT / "tests" / f".knowledge-{uuid.uuid4().hex}"
        self.root.mkdir(mode=0o777)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)

    def test_package_uses_filename_and_first_h1(self) -> None:
        (self.root / "alpha-topic.md").write_text(
            "Preamble\n# Synthetic title\nLine with NeEdLe.\n", encoding="utf-8"
        )
        (self.root / "ignored.txt").write_text("# Not a topic\n", encoding="utf-8")

        with mock.patch.object(knowledge.resources, "files", return_value=self.root):
            self.assertEqual(
                knowledge.topics(),
                (knowledge.KnowledgeTopic(id="alpha-topic", title="Synthetic title"),),
            )
            document = knowledge.read("alpha-topic")
            hits = knowledge.search("needle", limit=1)

        self.assertEqual(document.text.splitlines()[-1], "Line with NeEdLe.")
        self.assertEqual(
            hits,
            (
                knowledge.SearchHit(
                    topic=knowledge.KnowledgeTopic(id="alpha-topic", title="Synthetic title"),
                    line_number=3,
                    excerpt="Line with NeEdLe.",
                ),
            ),
        )

    def test_topic_without_h1_is_rejected(self) -> None:
        (self.root / "broken-topic.md").write_text("No heading here.\n", encoding="utf-8")

        with (
            mock.patch.object(knowledge.resources, "files", return_value=self.root),
            self.assertRaisesRegex(knowledge.KnowledgeError, "has no non-empty H1 title"),
        ):
            knowledge.topics()


if __name__ == "__main__":
    unittest.main()

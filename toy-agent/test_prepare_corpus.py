"""Offline E1 contracts; all mutations are confined to per-test temporary paths."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import prepare_corpus as corpus


class PreparedCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.knowledge = self.root / "knowledge"
        shutil.copytree(corpus.DEFAULT_KNOWLEDGE, self.knowledge)
        self.output = self.root / "build"

    def catalog(self):
        return json.loads((self.knowledge / "catalog.json").read_text())

    def save_catalog(self, entries):
        (self.knowledge / "catalog.json").write_bytes(corpus.json_bytes(entries))

    def chunks(self, output=None):
        return json.loads(((output or self.output) / "corpus/chunks.json").read_text())

    def one_document(self, text):
        entry = self.catalog()[0]
        self.save_catalog([entry])
        (self.knowledge / entry["path"]).write_bytes(text.encode("utf-8"))
        return entry

    def test_real_documents_are_deterministic_and_every_source_slice_round_trips(self):
        first = corpus.prepare(self.knowledge, self.output)
        second_path = self.root / "second"
        second = corpus.prepare(self.knowledge, second_path)
        self.assertEqual(first, second)
        self.assertEqual((self.output / "corpus/chunks.json").read_bytes(),
                         (second_path / "corpus/chunks.json").read_bytes())
        chunks = self.chunks()
        self.assertEqual(len({c["chunk_id"] for c in chunks}), len(chunks))
        self.assertEqual(len(first["inputs"]["documents"]), 3)
        for doc in first["inputs"]["documents"]:
            raw = (self.knowledge / doc["path"]).read_bytes().decode("utf-8")
            parts = [c for c in chunks if c["document_id"] == doc["document_id"]]
            self.assertEqual("".join(c["text"] for c in parts), raw)
            for chunk in parts:
                locator = chunk["source"]
                self.assertEqual(chunk["text"], "".join(corpus.source_lines(raw)[
                    locator["start_line"] - 1:locator["end_line"]]))
                self.assertLessEqual(len(chunk["text"]), corpus.DEFAULT_MAX_CHARS)
        self.assertEqual(corpus.check(self.knowledge, self.output), first)

    def test_migration_checks_and_reexecution_conditions_stay_together(self):
        corpus.prepare(self.knowledge, self.output)
        matching = [c for c in self.chunks() if c["document_id"] == "migration-guide"
                    and c["section"][-1]["title"] == "失败后重跑前的检查"]
        self.assertEqual(len(matching), 1)
        text = matching[0]["text"]
        for evidence in ("执行日志", "迁移版本记录", "是否发生部分执行",
                         "不得直接重跑原脚本", "即使确认没有发生变更"):
            self.assertIn(evidence, text)

    def test_parser_boundaries_handle_repeated_headings_fences_and_crlf(self):
        source = ("# 标题\r\n\r\n## 检查\r\n\r\n重复。\r\n\r\n"
                  "```sql\r\n# 不是章节\r\n```\r\n\r\n"
                  "## 检查\r\n\r\n重复。\r\n\r\n"
                  "> # 引用中的标题\r\n\r\n末尾\u2028仍在同一行")
        self.one_document(source)
        corpus.prepare(self.knowledge, self.output)
        chunks = self.chunks()
        self.assertEqual(len(chunks), 3)
        self.assertEqual([c["source"]["start_line"] for c in chunks], [1, 3, 11])
        self.assertEqual("".join(c["text"] for c in chunks), source)
        self.assertNotEqual(chunks[1]["chunk_id"], chunks[2]["chunk_id"])
        self.assertNotEqual(chunks[1]["section"], chunks[2]["section"])
        self.assertIn("```sql\r\n# 不是章节\r\n```", chunks[1]["text"])
        self.one_document("# 标题\n\n## 相同\n\n重复。\n\n## 相同\n\n重复。\n\n")
        repeated_output = self.root / "repeated"
        corpus.prepare(self.knowledge, repeated_output)
        repeated = self.chunks(repeated_output)
        self.assertEqual(repeated[1]["text"], repeated[2]["text"])
        self.assertNotEqual(repeated[1]["chunk_id"], repeated[2]["chunk_id"])
        self.assertNotEqual(repeated[1]["source"], repeated[2]["source"])

    def test_oversize_section_paragraph_and_code_fail_without_truncation(self):
        for source in ("# 长章节\n" + "完整段落\n\n" * 30,
                       "# 长段落\n" + "甲" * 150,
                       "# 代码\n```\n" + "代码\n" * 40 + "```\n"):
            with self.subTest(source=source[:8]):
                self.one_document(source)
                with self.assertRaisesRegex(corpus.CorpusError, "超过"):
                    corpus.prepare(self.knowledge, self.output, max_chars=100)
                self.assertFalse(self.output.exists())
                self.assertEqual(list(self.root.glob(".e1-prepare-*")), [])

    def test_changes_to_content_metadata_catalog_bytes_and_config_require_rebuild(self):
        corpus.prepare(self.knowledge, self.output)
        original_catalog = (self.knowledge / "catalog.json").read_bytes()
        source = self.knowledge / "migration-guide.md"
        original_source = source.read_bytes()
        for change in ("content", "title", "version", "catalog_format", "config"):
            with self.subTest(change=change):
                (self.knowledge / "catalog.json").write_bytes(original_catalog)
                source.write_bytes(original_source)
                maximum = corpus.DEFAULT_MAX_CHARS
                if change == "content":
                    source.write_bytes(original_source + "\n补充说明。\n".encode())
                elif change in {"title", "version"}:
                    entries = self.catalog()
                    entries[0][change] += "修订"
                    self.save_catalog(entries)
                elif change == "catalog_format":
                    (self.knowledge / "catalog.json").write_bytes(original_catalog + b"\n")
                else:
                    maximum += 1
                with self.assertRaises(corpus.RebuildRequired):
                    corpus.check(self.knowledge, self.output, maximum)

    def test_added_document_is_detected(self):
        corpus.prepare(self.knowledge, self.output)
        entries = self.catalog()
        entries.append({"document_id": "extra", "title": "补充资料", "version": "1", "path": "extra.md"})
        (self.knowledge / "extra.md").write_text("# 补充资料\n\n虚构内容。\n")
        self.save_catalog(entries)
        with self.assertRaises(corpus.RebuildRequired):
            corpus.check(self.knowledge, self.output)

    def test_removed_document_is_detected_and_absent_from_new_build(self):
        corpus.prepare(self.knowledge, self.output)
        entries = self.catalog()
        removed = entries.pop()
        self.save_catalog(entries)
        (self.knowledge / removed["path"]).unlink()
        with self.assertRaises(corpus.RebuildRequired):
            corpus.check(self.knowledge, self.output)
        next_output = self.root / "after-delete"
        result = corpus.prepare(self.knowledge, next_output)
        self.assertEqual(len(result["inputs"]["documents"]), 2)
        self.assertNotIn(removed["document_id"], [c["document_id"] for c in self.chunks(next_output)])
        corpus.check(self.knowledge, next_output)

    def test_missing_or_unreadable_source_is_failure_not_stale_or_match(self):
        corpus.prepare(self.knowledge, self.output)
        original = Path.read_bytes
        def unreadable(path):
            if path.name == "migration-guide.md":
                raise PermissionError("simulated unreadable source")
            return original(path)
        with patch.object(Path, "read_bytes", unreadable):
            with self.assertRaises(corpus.CorpusError) as error:
                corpus.check(self.knowledge, self.output)
            self.assertNotIsInstance(error.exception, corpus.RebuildRequired)
        (self.knowledge / "migration-guide.md").unlink()
        with self.assertRaises(corpus.CorpusError) as error:
            corpus.check(self.knowledge, self.output)
        self.assertNotIsInstance(error.exception, corpus.RebuildRequired)

    def test_invalid_catalog_paths_duplicates_and_encoding_fail(self):
        original = self.catalog()
        invalid = [[], {}, [None], [original[0], original[0]],
                   [{**original[0], "title": " "}], [{**original[0], "version": 1}],
                   [{**original[0], "extra": "x"}]]
        for path in ("../outside.md", "/tmp/outside.md", "./release-policy.md", "a//b.md", "a.txt"):
            invalid.append([{**original[0], "path": path}])
        for entries in invalid:
            with self.subTest(entries=entries):
                self.save_catalog(entries)
                with self.assertRaises(corpus.CorpusError):
                    corpus.prepare(self.knowledge, self.output)
                self.assertFalse(self.output.exists())
        for data in (b"{", b"\xff", b'[{"document_id":"a","document_id":"b"}]'):
            (self.knowledge / "catalog.json").write_bytes(data)
            with self.assertRaises(corpus.CorpusError):
                corpus.load_snapshot(self.knowledge)
        self.save_catalog(original)
        (self.knowledge / original[0]["path"]).write_bytes(b"\xff")
        with self.assertRaises(corpus.CorpusError):
            corpus.load_snapshot(self.knowledge)

    def test_symlink_source_and_output_under_sources_are_rejected(self):
        entries = self.catalog()
        target = self.root / "source.md"
        target.write_text("# 外部资料\n内容\n")
        source = self.knowledge / entries[0]["path"]
        source.unlink()
        source.symlink_to(target)
        with self.assertRaises(corpus.CorpusError):
            corpus.load_snapshot(self.knowledge)
        with self.assertRaises(corpus.CorpusError):
            corpus.prepare(self.knowledge, self.knowledge / "generated")

    def test_artifact_missing_corrupt_or_modified_is_failure_even_when_inputs_stale(self):
        corpus.prepare(self.knowledge, self.output)
        for name in ("chunks.json", "manifest.json"):
            path = self.output / "corpus" / name
            original = path.read_bytes()
            for data in (None, b"{", b"{}", original + b" "):
                # Manifest whitespace is semantically harmless; other cases are corruption.
                if name == "manifest.json" and data == original + b" ":
                    continue
                with self.subTest(name=name, data=data and data[:10]):
                    if data is None:
                        path.unlink()
                    else:
                        path.write_bytes(data)
                    with self.assertRaises(corpus.CorpusError) as error:
                        corpus.check(self.knowledge, self.output)
                    self.assertNotIsInstance(error.exception, corpus.RebuildRequired)
                    path.write_bytes(original)
        (self.knowledge / "migration-guide.md").write_text("# 新资料\n")
        (self.output / "corpus/chunks.json").write_text("[]")
        with self.assertRaises(corpus.CorpusError) as error:
            corpus.check(self.knowledge, self.output)
        self.assertNotIsInstance(error.exception, corpus.RebuildRequired)

    def test_invalid_manifest_version_or_count_is_failure(self):
        corpus.prepare(self.knowledge, self.output)
        path = self.output / "corpus/manifest.json"
        original = json.loads(path.read_text())
        for field, value in (("format_version", 999), ("chunk_count", 999),
                             ("artifact_type", "vector_index")):
            changed = deepcopy(original)
            changed[field] = value
            changed["build_id"] = corpus.sha256(corpus.json_bytes(
                {k: v for k, v in changed.items() if k != "build_id"}))
            path.write_bytes(corpus.json_bytes(changed))
            with self.assertRaises(corpus.CorpusError):
                corpus.check(self.knowledge, self.output)

    def test_input_change_during_build_prevents_publication(self):
        original = corpus.write_artifact
        def change_after_write(*args):
            result = original(*args)
            with (self.knowledge / "migration-guide.md").open("a") as handle:
                handle.write("\n修改。\n")
            return result
        with patch.object(corpus, "write_artifact", side_effect=change_after_write):
            with self.assertRaisesRegex(corpus.CorpusError, "构建期间输入变化"):
                corpus.prepare(self.knowledge, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".e1-prepare-*")), [])

    def test_existing_empty_or_populated_output_and_dangling_link_are_preserved(self):
        self.output.mkdir()
        with self.assertRaises(corpus.CorpusError):
            corpus.prepare(self.knowledge, self.output)
        keep = self.output / "keep.txt"
        keep.write_text("用户数据")
        with self.assertRaises(corpus.CorpusError):
            corpus.prepare(self.knowledge, self.output)
        self.assertEqual(keep.read_text(), "用户数据")
        link = self.root / "link"
        link.symlink_to(self.root / "missing")
        with self.assertRaises(corpus.CorpusError):
            corpus.prepare(self.knowledge, link)
        self.assertTrue(link.is_symlink())

    def test_output_created_during_build_is_not_overwritten_or_cleaned(self):
        original = corpus.write_artifact
        def create_competing_output(*args):
            result = original(*args)
            self.output.mkdir()
            (self.output / "keep.txt").write_text("用户数据")
            return result
        with patch.object(corpus, "write_artifact", side_effect=create_competing_output):
            with self.assertRaises(corpus.CorpusError):
                corpus.prepare(self.knowledge, self.output)
        self.assertEqual((self.output / "keep.txt").read_text(), "用户数据")
        self.assertFalse((self.output / "corpus").exists())
        self.assertEqual(list(self.root.glob(".e1-prepare-*")), [])

    def test_write_and_publish_failures_do_not_leave_a_usable_build(self):
        for target in ("write_artifact", "os.rename"):
            with self.subTest(target=target), patch("prepare_corpus." + target,
                                                   side_effect=OSError("simulated disk failure")):
                with self.assertRaises(corpus.CorpusError):
                    corpus.prepare(self.knowledge, self.output)
                self.assertFalse(self.output.exists())
                self.assertEqual(list(self.root.glob(".e1-prepare-*")), [])
        # A partial write must also be removed, not just a failure before any write.
        def partial_write(directory, *_):
            (directory / "chunks.json").write_text("[")
            raise OSError("simulated partial write")
        with patch.object(corpus, "write_artifact", side_effect=partial_write):
            with self.assertRaises(corpus.CorpusError):
                corpus.prepare(self.knowledge, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".e1-prepare-*")), [])

    def test_cli_exit_codes_distinguish_match_rebuild_and_failure(self):
        args = ["--knowledge", str(self.knowledge), "--output", str(self.output)]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(corpus.main(["prepare", *args]), 0)
            self.assertEqual(corpus.main(["check", *args]), 0)
            self.assertEqual(corpus.main(["check", *args, "--max-chars", "1300"]), 2)
            self.assertEqual(corpus.main(["prepare", *args]), 1)
            (self.output / "corpus/chunks.json").unlink()
            self.assertEqual(corpus.main(["check", *args]), 1)


if __name__ == "__main__":
    unittest.main()

"""Offline checks of the boundary between model output and program data."""

from contextlib import redirect_stdout
import io
import json
import unittest

from deepseek_summary import SummaryError, display_response, parse_summary


class SummaryValidationTests(unittest.TestCase):
    def test_empty_arrays_are_explicit_valid_values(self):
        expected = {"progress": [], "blockers": [], "next_steps": []}
        self.assertEqual(parse_summary(json.dumps(expected)), expected)

    def test_accepts_nonempty_string_arrays(self):
        expected = {"progress": ["接口已完成"], "blockers": ["迁移失败"], "next_steps": ["修复迁移"]}
        self.assertEqual(parse_summary(json.dumps(expected)), expected)

    def test_missing_fields_are_not_silently_filled(self):
        for field in ("progress", "blockers", "next_steps"):
            with self.subTest(field=field):
                payload = {"progress": [], "blockers": [], "next_steps": []}
                del payload[field]
                with self.assertRaisesRegex(SummaryError, field):
                    parse_summary(json.dumps(payload))

    def test_rejects_non_array_values(self):
        for value in (None, "", "迁移失败", {}, 0, False):
            with self.subTest(value=value):
                payload = {"progress": [], "blockers": value, "next_steps": []}
                with self.assertRaisesRegex(SummaryError, "字符串数组"):
                    parse_summary(json.dumps(payload))

    def test_rejects_invalid_array_items(self):
        for value in ("", " \n\t", None, 0, False, {}, []):
            with self.subTest(value=value):
                payload = {"progress": [], "blockers": [value], "next_steps": []}
                with self.assertRaisesRegex(SummaryError, "非空字符串"):
                    parse_summary(json.dumps(payload))

    def test_rejects_non_json_or_incomplete_json(self):
        for content in ("自然语言摘要", '{"progress": [', '```json\n{}\n```'):
            with self.subTest(content=content):
                with self.assertRaisesRegex(SummaryError, "有效 JSON"):
                    parse_summary(content)

    def test_rejects_non_object_root(self):
        for content in ("[]", "null", '"摘要"', "42"):
            with self.subTest(content=content):
                with self.assertRaisesRegex(SummaryError, "JSON 对象"):
                    parse_summary(content)

    def test_rejects_unexpected_fields(self):
        payload = {"progress": [], "blockers": [], "next_steps": [], "ready": True}
        with self.assertRaisesRegex(SummaryError, "约定之外"):
            parse_summary(json.dumps(payload))

    def test_truncation_is_failure_even_if_json_is_complete(self):
        response = {
            "choices": [{"message": {"content": '{"progress":[],"blockers":[],"next_steps":[]}'}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(SummaryError, "截断"):
            display_response(response)
        self.assertNotIn("结构化摘要", output.getvalue())


if __name__ == "__main__":
    unittest.main()

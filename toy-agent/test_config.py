"""Offline configuration checks; all credentials here are fake."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import deepseek_summary as loop
import evaluate_summary as evaluation


INVALID_CONFIGS = (
    ('[model]\napi_key = "private-sentinel" broken', '有效'),
    ('', '缺少'),
    ('[model]\nother = "private-sentinel"', '缺少'),
    ('model = "private-sentinel"', '缺少'),
    ('[model]\napi_key = 123', '字符串'),
    ('[model]\napi_key = false', '字符串'),
    ('[model]\napi_key = ["private-sentinel"]', '字符串'),
    ('[model.api_key]\nvalue = "private-sentinel"', '字符串'),
    ('[model]\napi_key = ""', '不能为空'),
    ('[model]\napi_key = "  "', '不能为空'),
    ('[model]\napi_key = "YOUR_API_KEY"', '占位符'),
    ('[model]\napi_key = "private-sentinel "', '空白'),
)


class ConfigTests(unittest.TestCase):
    def test_default_path_uses_script_root_even_from_other_working_directory(self):
        expected = Path(loop.__file__).resolve().parent.parent / 'config' / 'local.toml'
        self.assertEqual(loop.DEFAULT_CONFIG_PATH, expected)
        self.assertEqual(evaluation.DEFAULT_CONFIG_PATH, expected)
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                with patch.object(Path, 'open', autospec=True, return_value=io.BytesIO(b'[model]\napi_key="fake-key"')) as opened:
                    self.assertEqual(loop.read_config_api_key(), 'fake-key')
                    opened.assert_called_once_with(expected, 'rb')
                self.assertEqual(loop.DEFAULT_CONFIG_PATH, expected)
            finally:
                os.chdir(previous)

    def test_explicit_relative_and_absolute_path(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'custom.toml'
            path.write_text('[model]\napi_key="fake-key"', encoding='utf-8')
            try:
                os.chdir(folder)
                self.assertEqual(loop.read_config_api_key(Path('custom.toml')), 'fake-key')
                self.assertEqual(loop.read_config_api_key(path), 'fake-key')
            finally:
                os.chdir(previous)

    def test_invalid_configs_produce_only_safe_messages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.toml'
            for content, hint in INVALID_CONFIGS:
                with self.subTest(hint=hint):
                    path.write_text(content, encoding='utf-8')
                    with self.assertRaises(loop.SummaryError) as caught:
                        loop.read_config_api_key(path)
                    self.assertIn(hint, str(caught.exception))
                    self.assertNotIn('private-sentinel', str(caught.exception))

    def test_missing_unreadable_or_non_utf8_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'missing.toml'
            with self.assertRaisesRegex(loop.SummaryError, '不存在'):
                loop.read_config_api_key(path)
            path.write_bytes(b'[model]\napi_key="\xff"')
            with self.assertRaisesRegex(loop.SummaryError, 'UTF-8 TOML'):
                loop.read_config_api_key(path)
            with patch.object(Path, 'open', side_effect=PermissionError('private-sentinel')):
                with self.assertRaisesRegex(loop.SummaryError, '权限'):
                    loop.read_config_api_key(path)

    def test_both_cli_entries_use_default_or_explicit_config(self):
        for module in (loop, evaluation):
            for explicit in (False, True):
                with self.subTest(module=module.__name__, explicit=explicit), tempfile.TemporaryDirectory() as folder:
                    output = Path(folder) / 'result.json'
                    selected = Path('custom.toml') if explicit else loop.DEFAULT_CONFIG_PATH
                    argv = [module.__name__, '--output', str(output)]
                    if explicit:
                        argv += ['--config', str(selected)]
                    report = loop.empty_run_result()
                    report.update(status='succeeded', summary={'progress': [], 'blockers': [], 'next_steps': []})
                    with patch.object(sys, 'argv', argv), \
                         patch.object(module, 'read_config_api_key', return_value='fake-key') as read, \
                         patch.object(loop, 'run_project_summary', return_value=report), \
                         patch.object(evaluation, 'evaluate', return_value={'cases': []}), \
                         redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(module.main(), 0)
                    read.assert_called_once_with(selected)

    def test_configuration_failures_never_request_or_leak_in_cli_or_saved_result(self):
        for module in (loop, evaluation):
            for content, hint in (*INVALID_CONFIGS, (None, '不存在')):
                with self.subTest(module=module.__name__, hint=hint), tempfile.TemporaryDirectory() as folder:
                    config = Path(folder) / 'bad.toml'
                    output = Path(folder) / 'result.json'
                    if content is not None:
                        config.write_text(content, encoding='utf-8')
                    argv = [module.__name__, '--config', str(config), '--output', str(output)]
                    captured = io.StringIO()
                    with patch.object(sys, 'argv', argv), \
                         patch.object(module, 'request_completion') as request, \
                         redirect_stdout(captured), redirect_stderr(captured):
                        self.assertEqual(module.main(), 1)
                    request.assert_not_called()
                    self.assertIn(hint, captured.getvalue())
                    saved = ''
                    if module is loop:
                        saved = output.read_text()
                        result = json.loads(saved)
                        self.assertEqual(result['error']['category'], 'configuration')
                        self.assertEqual(result['model_requests'], 0)
                        self.assertEqual(result['trace'][-1]['stage'], 'configuration')
                    else:
                        self.assertFalse(output.exists())
                    for secret in ('private-sentinel', 'YOUR_API_KEY'):
                        self.assertNotIn(secret, captured.getvalue() + saved)


if __name__ == '__main__':
    unittest.main()

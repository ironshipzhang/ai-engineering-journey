"""Offline checks of retained run records and CLI output boundaries."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from deepseek_summary import SummaryError, load_projects, main, run_project_summary
from test_project_tool import response, tool_message


class RunResultTests(unittest.TestCase):
    def test_malformed_message_retains_independently_valid_usage(self):
        payload = response(None, 'stop')
        with patch('deepseek_summary.request_completion', return_value=payload) as request:
            result = run_project_summary('fake-key')
        request.assert_called_once()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['usage']['total_tokens'], 15)
        self.assertTrue(result['usage']['complete'])
        self.assertEqual(result['trace'][0]['finish_reason'], 'stop')
        self.assertEqual(result['trace'][-1]['stage'], 'response_validation')

    def test_invalid_usage_is_unknown_and_does_not_execute_tool(self):
        for usage in (None, {}, {'prompt_tokens': True, 'completion_tokens': 5, 'total_tokens': 6},
                      {'prompt_tokens': -1, 'completion_tokens': 5, 'total_tokens': 4}):
            payload = response(tool_message(), 'tool_calls')
            payload['usage'] = usage
            with self.subTest(usage=usage), \
                 patch('deepseek_summary.request_completion', return_value=payload), \
                 patch('deepseek_summary.get_project') as execute:
                result = run_project_summary('fake-key')
            execute.assert_not_called()
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['usage']['complete'])
            self.assertIsNone(result['trace'][0]['usage'])
            self.assertEqual(result['model_requests'], 1)

    def test_http_and_unparseable_response_keep_safe_failure_records(self):
        for error in (HTTPError('https://example.invalid', 401, 'private-body', {}, io.BytesIO(b'private-body')),
                      ValueError('private-body')):
            with self.subTest(error=type(error)), \
                 patch('deepseek_summary.request_completion', side_effect=error) as request:
                result = run_project_summary('fake-key')
            request.assert_called_once()
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['model_requests'], 1)
            self.assertFalse(result['usage']['complete'])
            self.assertEqual(result['trace'][-1]['stage'], 'request')
            saved = json.dumps(result)
            for private in ('private-body', 'fake-key', 'Authorization', 'messages'):
                self.assertNotIn(private, saved)

    def run_cli(self, argv):
        with patch.object(sys, 'argv', ['deepseek_summary.py', *argv]), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main()

    def test_existing_or_invalid_destination_stops_before_credentials_and_request(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / 'existing.json'
            existing.write_text('keep me', encoding='utf-8')
            for path in (existing, Path(folder) / 'missing' / 'result.json'):
                with self.subTest(path=path), patch('deepseek_summary.read_config_api_key') as read, \
                     patch('deepseek_summary.request_completion') as request:
                    self.assertEqual(self.run_cli(['--output', str(path)]), 1)
                read.assert_not_called()
                request.assert_not_called()
            self.assertEqual(existing.read_text(), 'keep me')

    def test_cli_reserves_output_before_request_and_saves_success_or_failure(self):
        for failed in (False, True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'result.json'
                attempts = 0

                def fake_request(key, messages):
                    nonlocal attempts
                    self.assertTrue(output.exists())
                    attempts += 1
                    if attempts == 1:
                        return response(tool_message(), 'tool_calls')
                    if failed:
                        raise TimeoutError('private-error')
                    return response({'role': 'assistant', 'content':
                                     '{"progress":[],"blockers":[],"next_steps":[]}'}, 'stop')

                with patch('deepseek_summary.read_config_api_key', return_value='fake-key'), \
                     patch('deepseek_summary.request_completion', side_effect=fake_request):
                    self.assertEqual(self.run_cli(['--output', str(output)]), int(failed))
                result = json.loads(output.read_text())
                self.assertEqual(result['model_requests'], 2)
                self.assertEqual(result['tool_executions'], 1)
                self.assertEqual(result['status'], 'failed' if failed else 'succeeded')
                self.assertEqual(result['usage']['complete'], not failed)

    def test_default_cli_and_pre_request_configuration_failure(self):
        with patch('deepseek_summary.read_config_api_key', side_effect=SummaryError('本地配置无效。')), \
             patch('deepseek_summary.request_completion') as request, tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            self.assertEqual(self.run_cli([]), 1)
            self.assertEqual(self.run_cli(['--output', str(output)]), 1)
            result = json.loads(output.read_text())
        request.assert_not_called()
        self.assertEqual(result['model_requests'], 0)
        self.assertEqual(result['usage']['total_tokens'], 0)
        self.assertTrue(result['usage']['complete'])

    def test_default_cli_success_without_output(self):
        final = response({'role': 'assistant', 'content':
                          '{"progress":[],"blockers":[],"next_steps":[]}'}, 'stop')
        with patch('deepseek_summary.read_config_api_key', return_value='fake-key'), \
             patch('deepseek_summary.request_completion', side_effect=[response(tool_message(), 'tool_calls'), final]):
            self.assertEqual(self.run_cli([]), 0)

    def test_output_write_flush_or_close_failure_returns_nonzero(self):
        final = response({'role': 'assistant', 'content':
                          '{"progress":[],"blockers":[],"next_steps":[]}'}, 'stop')
        snapshot = load_projects()
        for failing_method in ('write', 'flush', 'close'):
            with self.subTest(method=failing_method), patch('deepseek_summary.Path.open') as opened, \
                 patch('deepseek_summary.load_projects', return_value=snapshot), \
                 patch('deepseek_summary.read_config_api_key', return_value='fake-key'), \
                 patch('deepseek_summary.request_completion', side_effect=[response(tool_message(), 'tool_calls'), final]):
                getattr(opened.return_value, failing_method).side_effect = OSError('private-path')
                self.assertEqual(self.run_cli(['--output', 'unused.json']), 1)


if __name__ == '__main__':
    unittest.main()

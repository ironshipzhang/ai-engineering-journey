"""Offline checks of collection mechanics; these do not grade model factual quality."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from deepseek_summary import SummaryError, request_completion
from evaluate_summary import CASES_PATH, evaluate, load_cases, main


def response(reason='stop', content='{"progress":[],"blockers":[],"next_steps":[]}'):
    return {'choices': [{'message': {'role': 'assistant', 'content': content}, 'finish_reason': reason}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}}


class EvaluationTests(unittest.TestCase):
    def test_dataset_has_unique_cases_and_review_rules(self):
        cases = load_cases()
        self.assertEqual(len(cases), 6)
        self.assertEqual(len({c['id'] for c in cases}), 6)
        self.assertTrue(all(c['unsupported_claims'] for c in cases))

    def test_collects_all_cases_without_sending_review_labels(self):
        cases = load_cases()
        with patch('evaluate_summary.request_completion', return_value=response()) as request, redirect_stdout(io.StringIO()):
            report = evaluate('fake-key', cases)
        self.assertEqual(request.call_count, 6)
        self.assertEqual(report['usage_totals'], [120, 60, 180])
        self.assertTrue(all(c['factual_review'] == 'pending' for c in report['cases']))
        self.assertTrue(all(c['error'] is None for c in report['cases']))
        for call, case in zip(request.call_args_list, cases):
            self.assertFalse(call.kwargs['with_tools'])
            self.assertEqual(call.args[1][1], {'role': 'user', 'content': case['status']})

    def test_invalid_summary_and_truncation_are_failures_with_usage(self):
        cases = load_cases()[:2]
        with patch('evaluate_summary.request_completion', side_effect=[response(content='{}'), response(reason='length')]), redirect_stdout(io.StringIO()):
            report = evaluate('fake-key', cases)
        self.assertEqual(report['usage_totals'], [40, 20, 60])
        self.assertTrue(all(c['summary'] is None and c['error'] for c in report['cases']))

    def test_failed_request_is_not_retried_and_other_case_is_collected(self):
        cases = load_cases()[:2]
        with patch('evaluate_summary.request_completion', side_effect=[TimeoutError(), response()]) as request, redirect_stdout(io.StringIO()):
            report = evaluate('fake-key', cases)
        self.assertEqual(request.call_count, 2)
        self.assertIsNone(report['cases'][0]['usage'])
        self.assertIsNotNone(report['cases'][0]['error'])
        self.assertIsNotNone(report['cases'][1]['summary'])
        self.assertEqual(report['usage_totals'], [20, 10, 30])

    def test_bad_dataset_is_rejected_before_generation(self):
        cases = load_cases()
        for bad in ([], [cases[0], cases[0]], [{'id': 'incomplete'}]):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'cases.json'
                path.write_text(json.dumps(bad), encoding='utf-8')
                with self.assertRaises(SummaryError):
                    load_cases(path)

    def test_cli_uses_default_or_explicit_cases_path(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'result.json'
                selected = Path(folder) / 'custom.json' if explicit else CASES_PATH
                argv = ['evaluate_summary.py', '--output', str(output)]
                if explicit:
                    argv += ['--cases', str(selected)]
                report = {'cases': [], 'usage_totals': [0, 0, 0]}
                with patch.object(sys, 'argv', argv), \
                     patch('evaluate_summary.load_cases', return_value=[]) as load, \
                     patch('evaluate_summary.read_config_api_key', return_value='fake-key'), \
                     patch('evaluate_summary.evaluate', return_value=report) as collect, \
                     redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                load.assert_called_once_with(selected)
                collect.assert_called_once_with('fake-key', [])
                self.assertEqual(json.loads(output.read_text()), report)

    def test_summary_only_transport_keeps_limits_and_disables_tools(self):
        with patch('deepseek_summary.urlopen') as send:
            send.return_value.__enter__.return_value = io.StringIO('{}')
            request_completion('fake-key', [], with_tools=False)
        payload = json.loads(send.call_args.args[0].data)
        self.assertNotIn('tools', payload)
        self.assertNotIn('tool_choice', payload)
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertEqual(payload['max_tokens'], 800)
        self.assertEqual(send.call_args.kwargs['timeout'], 30)


if __name__ == '__main__':
    unittest.main()

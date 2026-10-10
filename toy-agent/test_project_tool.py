"""Offline checks of execution boundaries and the two-request conversation."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import socket
import unittest
from unittest.mock import patch

from deepseek_summary import (
    SummaryError, get_project, request_completion, run_project_summary, validate_tool_call,
)


def tool_message():
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call_test", "type": "function", "function": {
            "name": "get_project", "arguments": '{"project_id":"xingqiao"}',
        },
    }]}


def response(message, reason, counts=(10, 5, 15)):
    return {"choices": [{"message": message, "finish_reason": reason}],
            "usage": dict(zip(("prompt_tokens", "completion_tokens", "total_tokens"), counts))}


class ProjectToolTests(unittest.TestCase):
    def run_with_responses(self, responses):
        captured = []
        def fake_request(key, messages, *, with_tool):
            captured.append((deepcopy(messages), with_tool))
            item = responses[len(captured) - 1]
            if isinstance(item, Exception):
                raise item
            return item
        output = io.StringIO()
        with patch('deepseek_summary.request_completion', side_effect=fake_request), redirect_stdout(output):
            run_project_summary('fake-key')
        return captured, output.getvalue()

    def test_valid_flow_binds_result_and_keeps_data_out_of_first_request(self):
        summary = {"progress": ["接口完成"], "blockers": ["迁移失败"], "next_steps": ["修复迁移"]}
        captured, output = self.run_with_responses([
            response(tool_message(), 'tool_calls'),
            response({"role": "assistant", "content": json.dumps(summary)}, 'stop', (20, 8, 28)),
        ])
        self.assertEqual(len(captured), 2)
        first, second = captured
        self.assertTrue(first[1])
        self.assertNotIn('数据库迁移失败', json.dumps(first[0], ensure_ascii=False))
        self.assertFalse(second[1])
        self.assertEqual([m['role'] for m in second[0]], ['system', 'user', 'assistant', 'tool'])
        call = second[0][2]['tool_calls'][0]
        result = second[0][3]
        self.assertEqual(result['tool_call_id'], call['id'])
        self.assertEqual(json.loads(result['content']), get_project('xingqiao'))
        self.assertIn('总计=43', output)
        self.assertIn('结构化摘要', output)

    def test_invalid_calls_stop_before_execution_and_second_request(self):
        cases = []
        for calls in (None, [], [tool_message()['tool_calls'][0]] * 2, [None]):
            msg = tool_message(); msg['tool_calls'] = calls; cases.append(msg)
        for field, value in [('id', ''), ('id', 2), ('type', 'other'), ('function', None)]:
            msg = tool_message(); msg['tool_calls'][0][field] = value; cases.append(msg)
        msg = tool_message(); msg['tool_calls'][0]['function']['name'] = 'delete_project'; cases.append(msg)
        for args in (None, {}, '{', '[]', '{}', '{"project_id":1}', '{"project_id":null}',
                     '{"project_id":" "}', '{"project_id":"xingqiao","extra":true}'):
            msg = tool_message(); msg['tool_calls'][0]['function']['arguments'] = args; cases.append(msg)
        for msg in cases:
            with self.subTest(message=msg), patch('deepseek_summary.get_project') as execute, \
                 patch('deepseek_summary.request_completion', return_value=response(msg, 'tool_calls')) as request, \
                 redirect_stdout(io.StringIO()), self.assertRaises(SummaryError):
                run_project_summary('fake-key')
            execute.assert_not_called()
            self.assertEqual(request.call_count, 1)

    def test_unknown_project_stops_before_second_request(self):
        msg = tool_message()
        msg['tool_calls'][0]['function']['arguments'] = '{"project_id":"unknown"}'
        with patch('deepseek_summary.request_completion', return_value=response(msg, 'tool_calls')) as request, \
             redirect_stdout(io.StringIO()), self.assertRaisesRegex(SummaryError, '项目不存在'):
            run_project_summary('fake-key')
        self.assertEqual(request.call_count, 1)

    def test_wrong_first_finish_reason_is_rejected(self):
        for reason in ('stop', 'length', 'content_filter'):
            with self.subTest(reason=reason), self.assertRaises(SummaryError):
                validate_tool_call(tool_message(), reason)

    def test_final_summary_still_requires_valid_structure_and_finish(self):
        for content, reason in [('{}', 'stop'), ('not json', 'stop'),
                                ('{"progress":[],"blockers":[],"next_steps":[]}', 'length')]:
            with self.subTest(content=content, reason=reason), self.assertRaises(SummaryError):
                self.run_with_responses([response(tool_message(), 'tool_calls'),
                    response({"role": "assistant", "content": content}, reason)])

    def test_second_timeout_keeps_first_usage(self):
        output = io.StringIO()
        with patch('deepseek_summary.request_completion', side_effect=[
                response(tool_message(), 'tool_calls'), socket.timeout()]) as request, \
             redirect_stdout(output), self.assertRaises(socket.timeout):
            run_project_summary('fake-key')
        self.assertEqual(request.call_count, 2)
        self.assertIn('工具调用请求 Token 用量', output.getvalue())
        self.assertNotIn('结构化摘要', output.getvalue())

    def test_transport_bounds_and_phase_specific_payloads(self):
        for with_tool in (True, False):
            with self.subTest(with_tool=with_tool), patch('deepseek_summary.urlopen') as send:
                send.return_value.__enter__.return_value = io.StringIO('{}')
                request_completion('fake-key', [], with_tool=with_tool)
                req = send.call_args.args[0]
                payload = json.loads(req.data)
                self.assertEqual(send.call_args.kwargs['timeout'], 30)
                self.assertEqual(payload['max_tokens'], 400)
                self.assertEqual(payload['thinking'], {'type': 'disabled'})
                self.assertFalse(payload['stream'])
                if with_tool:
                    self.assertEqual(payload['tools'][0]['function']['name'], 'get_project')
                    self.assertEqual(payload['tool_choice']['function']['name'], 'get_project')
                    self.assertNotIn('response_format', payload)
                else:
                    self.assertNotIn('tools', payload)
                    self.assertEqual(payload['response_format'], {'type': 'json_object'})


if __name__ == '__main__':
    unittest.main()

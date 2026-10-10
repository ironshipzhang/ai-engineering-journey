"""Offline checks of execution boundaries and the bounded Agent Loop."""

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
        def fake_request(key, messages):
            captured.append(deepcopy(messages))
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
        self.assertNotIn('数据库迁移失败', json.dumps(first, ensure_ascii=False))
        self.assertEqual([m['role'] for m in second], ['system', 'user', 'assistant', 'tool'])
        call = second[2]['tool_calls'][0]
        result = second[3]
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
        self.assertIn('第 1 轮 Token 用量', output.getvalue())
        self.assertNotIn('结构化摘要', output.getvalue())

    def test_transport_always_offers_tool_with_json_without_forced_choice(self):
        with patch('deepseek_summary.urlopen') as send:
            send.return_value.__enter__.return_value = io.StringIO('{}')
            request_completion('fake-key', [])
            payload = json.loads(send.call_args.args[0].data)
            self.assertEqual(send.call_args.kwargs['timeout'], 30)
            self.assertEqual(payload['max_tokens'], 400)
            self.assertEqual(payload['thinking'], {'type': 'disabled'})
            self.assertFalse(payload['stream'])
            self.assertEqual(payload['tools'][0]['function']['name'], 'get_project')
            self.assertNotIn('tool_choice', payload)
            self.assertEqual(payload['response_format'], {'type': 'json_object'})

    def test_repeated_arguments_reuse_success_but_bind_current_call_id(self):
        second = tool_message()
        second['tool_calls'][0]['id'] = 'call_second'
        second['tool_calls'][0]['function']['arguments'] = '{ "project_id" : "xingqiao" }'
        final = response({'role': 'assistant', 'content': '{"progress":[],"blockers":[],"next_steps":[]}'}, 'stop')
        with patch('deepseek_summary.get_project', wraps=get_project) as execute:
            captured, output = self.run_with_responses([
                response(tool_message(), 'tool_calls'), response(second, 'tool_calls'), final,
            ])
        execute.assert_called_once_with('xingqiao')
        self.assertEqual(len(captured), 3)
        self.assertEqual(captured[2][-1]['tool_call_id'], 'call_second')
        self.assertEqual(captured[2][-3]['tool_call_id'], 'call_test')
        self.assertEqual(captured[2][-1]['content'], captured[2][-3]['content'])
        self.assertIn('复用', output)
        self.assertIn('总计=45', output)

    def test_direct_answer_without_data_is_rejected_even_if_valid_json(self):
        answer = response({'role': 'assistant', 'content': '{"progress":[],"blockers":[],"next_steps":[]}'}, 'stop')
        with patch('deepseek_summary.request_completion', return_value=answer) as request, \
             patch('deepseek_summary.get_project') as execute, redirect_stdout(io.StringIO()), \
             self.assertRaisesRegex(SummaryError, '尚未成功取得项目数据'):
            run_project_summary('fake-key')
        request.assert_called_once()
        execute.assert_not_called()

    def test_limit_ends_after_five_requests_without_sixth_request(self):
        responses = []
        for index in range(5):
            message = tool_message()
            message['tool_calls'][0]['id'] = f'call_{index}'
            responses.append(response(message, 'tool_calls'))
        output = io.StringIO()
        with patch('deepseek_summary.request_completion', side_effect=responses) as request, \
             patch('deepseek_summary.get_project', wraps=get_project) as execute, \
             redirect_stdout(output), self.assertRaisesRegex(SummaryError, '5 次模型请求上限'):
            run_project_summary('fake-key')
        self.assertEqual(request.call_count, 5)
        execute.assert_called_once()
        self.assertIn('总计=75', output.getvalue())
        self.assertNotIn('结构化摘要', output.getvalue())

    def test_final_answer_on_fifth_request_is_accepted(self):
        responses = [response(tool_message(), 'tool_calls') for _ in range(4)]
        responses.append(response({'role': 'assistant', 'content': '{"progress":[],"blockers":[],"next_steps":[]}'}, 'stop'))
        captured, output = self.run_with_responses(responses)
        self.assertEqual(len(captured), 5)
        self.assertIn('结构化摘要', output)

    def test_fifth_request_does_not_execute_a_new_tool(self):
        messages = [tool_message() for _ in range(5)]
        messages[-1]['tool_calls'][0]['function']['arguments'] = '{"project_id":"another"}'
        with patch('deepseek_summary.request_completion', side_effect=[response(m, 'tool_calls') for m in messages]) as request, \
             patch('deepseek_summary.get_project', wraps=get_project) as execute, \
             redirect_stdout(io.StringIO()), self.assertRaisesRegex(SummaryError, '上限'):
            run_project_summary('fake-key')
        self.assertEqual(request.call_count, 5)
        execute.assert_called_once_with('xingqiao')

    def test_cache_is_task_local_and_failure_is_not_reused_in_next_task(self):
        first = response(tool_message(), 'tool_calls')
        final = response({'role': 'assistant', 'content': '{"progress":[],"blockers":[],"next_steps":[]}'}, 'stop')
        with patch('deepseek_summary.get_project', side_effect=[SummaryError('工具失败'), get_project('xingqiao'), get_project('xingqiao')]) as execute:
            with self.assertRaisesRegex(SummaryError, '工具失败'):
                self.run_with_responses([first])
            self.run_with_responses([first, final])
            self.run_with_responses([first, final])
        self.assertEqual(execute.call_count, 3)

    def test_truncated_or_abnormal_round_does_not_execute_or_continue(self):
        for reason in ('length', 'content_filter', 'aborted'):
            with self.subTest(reason=reason), \
                 patch('deepseek_summary.request_completion', return_value=response(tool_message(), reason)) as request, \
                 patch('deepseek_summary.get_project') as execute, \
                 redirect_stdout(io.StringIO()), self.assertRaises(SummaryError):
                run_project_summary('fake-key')
            request.assert_called_once()
            execute.assert_not_called()

    def test_stop_with_tool_call_is_rejected(self):
        with self.assertRaisesRegex(SummaryError, '不一致'):
            self.run_with_responses([response(tool_message(), 'tool_calls'), response(tool_message(), 'stop')])


if __name__ == '__main__':
    unittest.main()

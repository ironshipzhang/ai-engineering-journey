"""Offline batch admission, serial execution, message binding and request limits."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import deepseek_summary as agent
from test_project_tool import response
from test_tool_registry import call, FINAL
import test_tool_registry as registry_checks
import test_run_result as result_checks


def batch(*responses):
    calls = [deepcopy(item['choices'][0]['message']['tool_calls'][0]) for item in responses]
    return response({'role': 'assistant', 'content': None, 'tool_calls': calls}, 'tool_calls')


class ToolBatchTests(unittest.TestCase):
    def run_script(self, script, task='issues'):
        return registry_checks.ToolRegistryTests().run_script(script, task=task)

    def test_two_tools_in_either_order_complete_in_two_requests_and_bind_messages(self):
        for names in (('get_project', 'list_project_issues'), ('list_project_issues', 'get_project')):
            with self.subTest(names=names):
                first = batch(call(names[0], call_id='first'), call(names[1], call_id='second'))
                result, captured = self.run_script([first, FINAL])
                self.assertEqual(result['status'], 'succeeded')
                self.assertEqual((result['model_requests'], result['tool_executions'], result['cache_hits']), (2, 2, 0))
                self.assertEqual([e['tool_call_count'] for e in result['trace'] if e['event'] == 'model_request'], [2, 0])
                messages = captured[1]
                self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'tool', 'tool'])
                self.assertEqual(messages[2]['tool_calls'], first['choices'][0]['message']['tool_calls'])
                self.assertEqual([m['tool_call_id'] for m in messages[3:]], ['first', 'second'])
                snapshot = agent.load_projects()
                expected = {'get_project': agent.get_project('xingqiao', snapshot),
                            'list_project_issues': agent.list_project_issues('xingqiao', snapshot)}
                self.assertEqual([json.loads(m['content']) for m in messages[3:]], [expected[name] for name in names])
                self.assertEqual([e['tool_name'] for e in result['trace'] if e['event'] == 'tool_execution'], list(names))

    def test_invalid_second_call_prevents_execution_of_the_entire_batch(self):
        valid_second = call('list_project_issues', call_id='second')['choices'][0]['message']['tool_calls'][0]
        invalid = [None, {**valid_second, 'type': 'other'}, {**valid_second, 'id': ''},
                   {**valid_second, 'id': 2}, {**valid_second, 'function': None},
                   {**valid_second, 'function': {'name': 2, 'arguments': '{}'}},
                   {**valid_second, 'function': {'name': 'unregistered-private', 'arguments': '{}'}}]
        for arguments in (None, {}, '{', '[]', '{}', '{"project_id":1}', '{"project_id":null}',
                          '{"project_id":" "}', '{"project_id":"xingqiao","extra":true}',
                          '{"project_id":"yunfan"}', '{"project_id":" xingqiao"}'):
            invalid.append({**valid_second, 'function': {'name': 'list_project_issues', 'arguments': arguments}})
        for second in invalid:
            payload = batch(call('get_project', call_id='first'), call('list_project_issues', call_id='second'))
            payload['choices'][0]['message']['tool_calls'][1] = second
            with self.subTest(second=second), patch.object(agent, 'get_project') as overview, \
                 patch.object(agent, 'list_project_issues') as issues:
                result, captured = self.run_script([payload])
            overview.assert_not_called()
            issues.assert_not_called()
            self.assertEqual(result['model_requests'], 1)
            self.assertEqual(len(captured), 1)
            self.assertEqual((result['tool_executions'], result['cache_hits']), (0, 0))
            self.assertEqual(result['usage']['total_tokens'], 15)
            self.assertEqual(result['trace'][-1]['stage'], 'tool_validation')
            self.assertEqual(result['trace'][0]['tool_call_count'], 2)
            self.assertEqual([e['event'] for e in result['trace']], ['model_request', 'failure'])
            self.assertNotIn('unregistered-private', json.dumps(result))
            self.assertNotIn('parameters', result['trace'][-1])

    def test_empty_three_calls_duplicate_ids_and_non_arrays_are_rejected(self):
        valid = batch(call('get_project', call_id='first'), call('list_project_issues', call_id='second'))
        pair = valid['choices'][0]['message']['tool_calls']
        duplicate = deepcopy(pair)
        duplicate[1]['id'] = duplicate[0]['id']
        for calls in ([], pair + [deepcopy(pair[0])], duplicate, None, {}, 'private-sentinel'):
            payload = deepcopy(valid)
            payload['choices'][0]['message']['tool_calls'] = calls
            with self.subTest(calls=calls), patch.object(agent, 'get_project') as overview, \
                 patch.object(agent, 'list_project_issues') as issues:
                result, captured = self.run_script([payload])
            overview.assert_not_called()
            issues.assert_not_called()
            self.assertEqual(len(captured), 1)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['tool_executions'], 0)
            self.assertEqual(result['trace'][-1]['stage'], 'tool_validation')
            self.assertEqual(result['trace'][0]['tool_call_count'], len(calls) if isinstance(calls, list) else None)
            self.assertNotIn('private-sentinel', json.dumps(result))

    def test_same_tool_in_batch_reuses_success_with_distinct_current_ids(self):
        for name in agent.TOOL_REGISTRY:
            with self.subTest(name=name), patch.object(agent, name, wraps=getattr(agent, name)) as execute:
                result, captured = self.run_script([
                    batch(call(name, call_id='first'), call(name, call_id='cached',
                          arguments='{ "project_id" : "xingqiao" }')),
                    call('list_project_issues' if name == 'get_project' else 'get_project', call_id='other'), FINAL,
                ])
            execute.assert_called_once()
            self.assertEqual(result['status'], 'succeeded')
            self.assertEqual((result['model_requests'], result['tool_executions'], result['cache_hits']), (3, 2, 1))
            messages = captured[1]
            self.assertEqual([m['tool_call_id'] for m in messages[-2:]], ['first', 'cached'])
            self.assertEqual(messages[-2]['content'], messages[-1]['content'])
            self.assertEqual(result['trace'][2]['event'], 'cache_hit')
            self.assertEqual(result['trace'][2]['call_id'], 'cached')

    def test_second_execution_failure_retains_first_success_and_stops(self):
        for error in (agent.SummaryError('工具失败'), RuntimeError('private-sentinel')):
            with self.subTest(error=type(error)), patch.object(agent, 'get_project', wraps=agent.get_project) as overview, \
                 patch.object(agent, 'list_project_issues', side_effect=error) as issues:
                result, captured = self.run_script([
                    batch(call('get_project', call_id='first'), call('list_project_issues', call_id='failed')),
                ])
            overview.assert_called_once()
            issues.assert_called_once()
            self.assertEqual(len(captured), 1)
            self.assertEqual(result['status'], 'failed')
            self.assertIsNone(result['summary'])
            self.assertEqual((result['model_requests'], result['tool_executions'], result['cache_hits']), (1, 2, 0))
            self.assertEqual([e['event'] for e in result['trace']],
                             ['model_request', 'tool_execution', 'tool_execution', 'failure'])
            self.assertEqual(result['trace'][1]['status'], 'succeeded')
            self.assertEqual(result['trace'][2]['status'], 'failed')
            self.assertEqual(result['trace'][-1]['stage'], 'tool_execution')
            self.assertEqual(result['trace'][-1]['call_id'], 'failed')
            self.assertEqual(result['usage']['total_tokens'], 15)
            self.assertTrue(result['usage']['complete'])
            self.assertNotIn('private-sentinel', json.dumps(result))

    def test_first_execution_failure_does_not_execute_second(self):
        with patch.object(agent, 'get_project', side_effect=agent.SummaryError('工具失败')) as overview, \
             patch.object(agent, 'list_project_issues') as issues:
            result, captured = self.run_script([
                batch(call('get_project', call_id='failed'), call('list_project_issues', call_id='not_started')),
            ])
        overview.assert_called_once()
        issues.assert_not_called()
        self.assertEqual(len(captured), 1)
        self.assertEqual(result['tool_executions'], 1)
        self.assertEqual(result['trace'][-1]['call_id'], 'failed')
        self.assertEqual([e['event'] for e in result['trace']], ['model_request', 'tool_execution', 'failure'])

    def test_batch_failure_retains_previous_success_and_cache_events(self):
        with patch.object(agent, 'list_project_issues', side_effect=agent.SummaryError('工具失败')):
            result, captured = self.run_script([
                batch(call('get_project', call_id='first'), call('get_project', call_id='cached_1')),
                batch(call('get_project', call_id='cached_2'), call('list_project_issues', call_id='failed')),
            ])
        self.assertEqual(len(captured), 2)
        self.assertEqual((result['model_requests'], result['tool_executions'], result['cache_hits']), (2, 2, 2))
        self.assertEqual([e['event'] for e in result['trace']],
                         ['model_request', 'tool_execution', 'cache_hit', 'model_request', 'cache_hit', 'tool_execution', 'failure'])
        self.assertEqual(result['usage']['total_tokens'], 30)
        self.assertEqual(result['trace'][-1]['call_id'], 'failed')

    def test_fifth_round_refuses_entire_batch_even_if_first_item_is_cached(self):
        script = [call('get_project', call_id=f'round_{i}') for i in range(1, 5)]
        script.append(batch(call('get_project', call_id='cached'), call('list_project_issues', call_id='new')))
        with patch.object(agent, 'get_project', wraps=agent.get_project) as overview, \
             patch.object(agent, 'list_project_issues') as issues:
            result, captured = self.run_script(script)
        overview.assert_called_once()
        issues.assert_not_called()
        self.assertEqual(len(captured), 5)
        self.assertEqual((result['model_requests'], result['tool_executions'], result['cache_hits']), (5, 1, 3))
        self.assertEqual(result['usage']['total_tokens'], 75)
        self.assertEqual(result['trace'][-2]['tool_call_count'], 2)
        self.assertEqual(result['trace'][-1]['stage'], 'request_limit')
        self.assertEqual([item['call_id'] for item in result['trace'][-1]['tool_calls']], ['cached', 'new'])
        self.assertFalse(any(e['event'] in ('tool_execution', 'cache_hit') and e['request_number'] == 5
                             for e in result['trace']))

    def test_fifth_round_final_answer_after_batch_success_is_accepted(self):
        result, captured = self.run_script([
            batch(call('get_project', call_id='first'), call('list_project_issues', call_id='second')),
            *[call('get_project', call_id=f'cached_{i}') for i in range(3)], FINAL,
        ])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(captured), 5)
        self.assertEqual((result['model_requests'], result['tool_executions'], result['cache_hits']), (5, 2, 3))

    def test_timeout_after_successful_batch_keeps_known_usage_and_events(self):
        with patch.object(agent, 'request_completion', side_effect=[
                batch(call('get_project', call_id='first'), call('list_project_issues', call_id='second')),
                TimeoutError('private-sentinel')]) as request:
            result = agent.run_project_summary('fake-key', task='issues')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result['model_requests'], 2)
        self.assertEqual(result['tool_executions'], 2)
        self.assertEqual(result['usage']['total_tokens'], 15)
        self.assertFalse(result['usage']['complete'])
        self.assertEqual([e['event'] for e in result['trace']],
                         ['model_request', 'tool_execution', 'tool_execution', 'model_request', 'failure'])
        self.assertIsNone(result['trace'][-2]['tool_call_count'])
        self.assertNotIn('private-sentinel', json.dumps(result))

    def test_cli_saves_batch_success_and_partial_execution_failure(self):
        for failed in (False, True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'result.json'
                script = [batch(call('get_project', call_id='first'), call('list_project_issues', call_id='second')), FINAL]
                execute = agent.list_project_issues
                if failed:
                    def execute(project_id, snapshot):
                        raise agent.SummaryError('工具失败')
                with patch.object(agent, 'read_config_api_key', return_value='fake-key'), \
                     patch.object(agent, 'list_project_issues', side_effect=execute), \
                     patch.object(agent, 'request_completion', side_effect=script) as request:
                    self.assertEqual(result_checks.RunResultTests().run_cli(['--task', 'issues', '--output', str(path)]), int(failed))
                result = json.loads(path.read_text())
                self.assertEqual(result['status'], 'failed' if failed else 'succeeded')
                self.assertEqual(result['model_requests'], 1 if failed else 2)
                self.assertEqual(request.call_count, result['model_requests'])
                self.assertEqual(result['trace'][0]['tool_call_count'], 2)
                self.assertEqual(result['tool_executions'], 2)
                self.assertEqual(result['trace'][1]['status'], 'succeeded')


if __name__ == '__main__':
    unittest.main()

"""Task D controls with scripted responses; no real credentials or model calls."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import deepseek_summary as agent
from test_project_tool import response, tool_message


FINAL = response({'role': 'assistant', 'content': json.dumps({
    'progress': [], 'blockers': [], 'next_steps': []})}, 'stop')


def call(name, project_id='xingqiao', call_id='call_test', arguments=None):
    message = tool_message()
    invocation = message['tool_calls'][0]
    invocation['id'] = call_id
    invocation['function'] = {'name': name, 'arguments': arguments if arguments is not None
                              else json.dumps({'project_id': project_id})}
    return response(message, 'tool_calls')


class ToolRegistryTests(unittest.TestCase):
    def run_script(self, script, project_id='xingqiao', task='summary', on_request=None):
        captured = []

        def request(key, messages):
            captured.append(deepcopy(messages))
            if on_request:
                on_request(len(captured))
            return script[len(captured) - 1]

        with patch.object(agent, 'request_completion', side_effect=request):
            result = agent.run_project_summary('fake-key', project_id, task)
        return result, captured

    def test_both_projects_and_tool_responsibilities(self):
        snapshot = agent.load_projects()
        for project_id in ('xingqiao', 'yunfan'):
            with self.subTest(project_id=project_id):
                result, captured = self.run_script([
                    call('get_project', project_id), call('list_project_issues', project_id), FINAL,
                ], project_id, 'issues')
                self.assertEqual(result['status'], 'succeeded')
                self.assertEqual(result['tool_executions'], 2)
                overview = json.loads(captured[1][-1]['content'])
                issues = json.loads(captured[2][-1]['content'])
                self.assertEqual(overview, agent.get_project(project_id, snapshot))
                self.assertEqual(set(overview), {'project_id', 'name', 'status'})
                self.assertEqual(issues, agent.list_project_issues(project_id, snapshot))
                self.assertEqual(set(issues), {'project_id', 'issues'})
        self.assertNotEqual(snapshot['xingqiao']['status'], snapshot['yunfan']['status'])
        self.assertEqual(agent.list_project_issues('yunfan', snapshot)['issues'], [])

    def test_issues_completion_is_independent_of_order(self):
        for names in (('get_project', 'list_project_issues'), ('list_project_issues', 'get_project')):
            with self.subTest(names=names):
                result, captured = self.run_script([call(name) for name in names] + [FINAL], task='issues')
                self.assertEqual(result['status'], 'succeeded')
                self.assertEqual(result['model_requests'], 3)
                self.assertEqual([e['tool_name'] for e in result['trace'] if e['event'] == 'tool_execution'], list(names))
                self.assertNotIn('数据库迁移失败', json.dumps(captured[0], ensure_ascii=False))

    def test_final_answer_requires_each_tasks_successful_results(self):
        for task, names in (('summary', []), ('summary', ['list_project_issues']),
                            ('issues', []), ('issues', ['get_project']), ('issues', ['list_project_issues'])):
            with self.subTest(task=task, names=names):
                result, captured = self.run_script([call(name) for name in names] + [FINAL], task=task)
                self.assertEqual(result['status'], 'failed')
                self.assertIsNone(result['summary'])
                self.assertEqual(result['trace'][-1]['stage'], 'summary_validation')
                self.assertEqual(len(captured), len(names) + 1)  # No automatic missing call.

    def test_invalid_parameters_and_wrong_target_never_execute_either_tool(self):
        for name in agent.TOOL_REGISTRY:
            for arguments in ('{', '[]', '{}', '{"project_id":1}', '{"project_id":null}',
                              '{"project_id":" "}', '{"project_id":"xingqiao","extra":true}',
                              '{"project_id":"yunfan"}', '{"project_id":" xingqiao"}'):
                with self.subTest(name=name, arguments=arguments), \
                     patch.object(agent, 'get_project') as overview, \
                     patch.object(agent, 'list_project_issues') as issues:
                    result, captured = self.run_script([call(name, arguments=arguments)])
                overview.assert_not_called()
                issues.assert_not_called()
                self.assertEqual(result['tool_executions'], 0)
                self.assertEqual(result['trace'][-1]['stage'], 'tool_validation')
                self.assertEqual(len(captured), 1)
        with patch.object(agent, 'get_project') as overview, patch.object(agent, 'list_project_issues') as issues:
            result, _ = self.run_script([call('delete_project')])
        overview.assert_not_called()
        issues.assert_not_called()
        self.assertEqual(result['trace'][-1]['stage'], 'tool_validation')

    def test_unknown_project_is_failure_for_both_tools(self):
        for name in agent.TOOL_REGISTRY:
            with self.subTest(name=name):
                result, captured = self.run_script([call(name, 'unknown')], 'unknown', 'issues')
                self.assertEqual(result['status'], 'failed')
                self.assertIn('项目不存在', result['error']['message'])
                self.assertEqual(result['tool_executions'], 1)
                self.assertEqual(result['trace'][1]['status'], 'failed')
                self.assertEqual(result['trace'][-1]['stage'], 'tool_execution')
                self.assertEqual(len(captured), 1)

    def test_cache_separates_tools_and_binds_current_ids(self):
        result, captured = self.run_script([
            call('list_project_issues', call_id='issues_1'),
            call('get_project', call_id='project_1'),
            call('list_project_issues', call_id='issues_2', arguments='{ "project_id" : "xingqiao" }'),
            call('get_project', call_id='project_2'), FINAL,
        ], task='issues')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual((result['model_requests'], result['tool_executions'], result['cache_hits']), (5, 2, 2))
        self.assertEqual(captured[3][-1]['tool_call_id'], 'issues_2')
        self.assertEqual(captured[4][-1]['tool_call_id'], 'project_2')
        self.assertEqual(captured[1][-1]['content'], captured[3][-1]['content'])
        self.assertEqual(captured[2][-1]['content'], captured[4][-1]['content'])
        self.assertNotEqual(captured[3][-1]['content'], captured[4][-1]['content'])
        output = io.StringIO()
        with redirect_stdout(output):
            agent.display_run_result(result)
        self.assertIn('list_project_issues', output.getvalue())
        self.assertIn('参数=', output.getvalue())

    def test_registry_is_schema_validation_and_execution_source(self):
        validations, executions = [], []
        original = agent.TOOL_REGISTRY['get_project']

        def validate(params, target):
            validations.append((params, target))
            original.validate(params, target)

        def execute(params, snapshot):
            executions.append(params)
            return original.execute(params, snapshot)

        registration = replace(original, schema=agent.project_tool_schema('test_overview', '测试注册入口'),
                               validate=validate, execute=execute)
        with patch.dict(agent.TOOL_REGISTRY, {'test_overview': registration}), \
             patch.object(agent, 'urlopen') as transport:
            transport.return_value.__enter__.return_value = io.StringIO('{}')
            agent.request_completion('fake-key', [])
            schemas = json.loads(transport.call_args.args[0].data)['tools']
            self.assertIn(registration.schema, schemas)
            # A registry-only addition is dispatched without changing Loop.
            result, _ = self.run_script([call('test_overview'), call('get_project'), FINAL])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(validations, [({'project_id': 'xingqiao'}, 'xingqiao')])
        self.assertEqual(executions, [{'project_id': 'xingqiao'}])

    def test_tool_failure_retains_prior_trace_and_usage_without_retry(self):
        for error in (OSError('private-sentinel'), RuntimeError('private-sentinel')):
            with self.subTest(error=type(error)), patch.object(agent, 'list_project_issues', side_effect=error):
                result, captured = self.run_script([call('get_project'), call('list_project_issues')], task='issues')
            self.assertEqual(len(captured), 2)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['tool_executions'], 2)
            self.assertEqual(result['usage']['total_tokens'], 30)
            self.assertTrue(result['usage']['complete'])
            self.assertEqual([e['event'] for e in result['trace']],
                             ['model_request', 'tool_execution', 'model_request', 'tool_execution', 'failure'])
            self.assertEqual(result['trace'][-1]['tool_name'], 'list_project_issues')
            self.assertNotIn('private-sentinel', json.dumps(result))

    def test_invalid_task_inputs_fail_before_data_loading_or_request(self):
        for project_id, task in (('', 'summary'), (' ', 'issues'), (None, 'summary'),
                                 ('xingqiao', 'other'), ('xingqiao', [])):
            with self.subTest(project_id=project_id, task=task), \
                 patch.object(agent, 'load_projects') as load, \
                 patch.object(agent, 'request_completion') as request:
                result = agent.run_project_summary('fake-key', project_id, task)
            load.assert_not_called()
            request.assert_not_called()
            self.assertEqual(result['trace'][-1]['stage'], 'task_validation')
            self.assertEqual(result['model_requests'], 0)

    def test_cli_explicit_inputs_and_saved_trace(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'issues.json'
            with patch.object(sys, 'argv', ['agent', '--project-id', 'yunfan', '--task', 'issues', '--output', str(output)]), \
                 patch.object(agent, 'read_config_api_key', return_value='fake-key'), \
                 patch.object(agent, 'request_completion', side_effect=[
                     call('list_project_issues', 'yunfan'), call('get_project', 'yunfan'), FINAL]), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(agent.main(), 0)
            result = json.loads(output.read_text())
        self.assertEqual(result['tool_executions'], 2)
        self.assertEqual(result['trace'][1]['parameters'], {'project_id': 'yunfan'})


class ProjectDataTests(unittest.TestCase):
    def test_data_path_is_independent_of_working_directory(self):
        previous = Path.cwd()
        expected = agent.load_projects()
        try:
            with tempfile.TemporaryDirectory() as folder:
                os.chdir(folder)
                self.assertEqual(agent.load_projects(), expected)
        finally:
            os.chdir(previous)

    def test_file_changes_apply_next_task_but_not_mid_task(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'projects.json'
            projects = list(agent.load_projects().values())
            path.write_text(json.dumps(projects), encoding='utf-8')

            def edit_file(request_number):
                if request_number == 1:
                    projects[0]['status'] = '更新概况'
                    projects[0]['issues'] = []
                    path.write_text(json.dumps(projects), encoding='utf-8')

            runner = ToolRegistryTests()
            with patch.object(agent, 'PROJECTS_PATH', path), patch.object(agent, 'load_projects', wraps=agent.load_projects) as load:
                first, messages = runner.run_script([call('get_project'), call('list_project_issues'), FINAL],
                                                    task='issues', on_request=edit_file)
                second, updated = runner.run_script([call('get_project'), call('list_project_issues'), FINAL], task='issues')
            self.assertEqual(load.call_count, 2)
            self.assertEqual(first['status'], 'succeeded')
            self.assertEqual(second['status'], 'succeeded')
            self.assertNotEqual(json.loads(messages[1][-1]['content'])['status'], '更新概况')
            self.assertTrue(json.loads(messages[2][-1]['content'])['issues'])
            self.assertEqual(json.loads(updated[1][-1]['content'])['status'], '更新概况')
            self.assertEqual(json.loads(updated[2][-1]['content'])['issues'], [])

    def test_missing_corrupt_and_unreadable_files_fail_before_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'projects.json'
            for content, hint in ((None, '不存在'), (b'{', 'UTF-8 JSON'), (b'\xff', 'UTF-8 JSON')):
                with self.subTest(content=content), patch.object(agent, 'PROJECTS_PATH', path), \
                     patch.object(agent, 'request_completion') as request:
                    if content is not None:
                        path.write_bytes(content)
                    result = agent.run_project_summary('fake-key')
                request.assert_not_called()
                self.assertEqual(result['trace'][-1]['stage'], 'data_loading')
                self.assertIn(hint, result['error']['message'])
                self.assertEqual(result['model_requests'], 0)
                self.assertTrue(result['usage']['complete'])
            with patch.object(Path, 'read_text', side_effect=PermissionError('private-sentinel')):
                with self.assertRaisesRegex(agent.SummaryError, '权限'):
                    agent.load_projects(path)

    def test_invalid_data_shapes_and_duplicate_ids_are_rejected(self):
        project = list(agent.load_projects().values())[0]
        invalid = [None, {}, [], [None], [{**project, 'extra': 1}],
                   [{**project, 'project_id': ''}], [{**project, 'name': 1}],
                   [{**project, 'status': ' '}], [{**project, 'issues': None}],
                   [project, project], [{**project, 'issues': [None]}],
                   [{**project, 'issues': [{}]}],
                   [{**project, 'issues': [{**project['issues'][0], 'id': ''}]}],
                   [{**project, 'issues': [project['issues'][0]] * 2}]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'projects.json'
            for data in invalid:
                with self.subTest(data=data), patch.object(agent, 'PROJECTS_PATH', path), \
                     patch.object(agent, 'request_completion') as request:
                    path.write_text(json.dumps(data), encoding='utf-8')
                    result = agent.run_project_summary('fake-key')
                request.assert_not_called()
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['trace'][-1]['stage'], 'data_loading')

    def test_cli_saves_data_loading_failure_with_zero_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'failed.json'
            with patch.object(sys, 'argv', ['agent', '--output', str(output)]), \
                 patch.object(agent, 'PROJECTS_PATH', Path(folder) / 'missing.json'), \
                 patch.object(agent, 'read_config_api_key', return_value='fake-key'), \
                 patch.object(agent, 'request_completion') as request, \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(agent.main(), 1)
            result = json.loads(output.read_text())
        request.assert_not_called()
        self.assertEqual(result['trace'][-1]['stage'], 'data_loading')
        self.assertEqual(result['model_requests'], 0)


if __name__ == '__main__':
    unittest.main()

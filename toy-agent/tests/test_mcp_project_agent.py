"""F2 fake model responses; the mcp success path uses a real local subprocess."""
from contextlib import asynccontextmanager, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import dashscope_embedding as wire
import deepseek_summary as business
import grounded_answer as generation
import mcp_project_agent as agent
import project_mcp_client as mcp
import project_mcp_contract as contract

KEY = 'fake-f-secret'
SUMMARY = {'progress': ['fixture'], 'blockers': [], 'next_steps': []}


def route():
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
        'tool_calls': [{'id': 'call-f-1', 'index': 0, 'type': 'function', 'function': {
            'name': 'get_project', 'arguments': '{"project_id":"xingqiao"}'}}]}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


def final():
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
        'content': json.dumps(SUMMARY)}}],
        'usage': {'prompt_tokens': 20, 'completion_tokens': 6, 'total_tokens': 26}}


def reply(value, status=200): return wire.Reply(status, json.dumps(value).encode())


class AgentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / 'fake.toml'
        self.config.write_text(f'[model]\napi_key="{KEY}"\n')  # deliberately no embedding
        self.data = self.root / 'projects.json'
        self.project = {'project_id': 'xingqiao', 'name': 'fixture', 'status': 'original', 'issues': []}
        self.data.write_text(json.dumps([self.project]))
        self.responses = [reply(route()), reply(final())]
        self.sent = []
        def model(key, messages, **kwargs):
            self.assertEqual(key, KEY)
            self.sent.append((deepcopy(messages), deepcopy(kwargs)))
            response = self.responses.pop(0)
            if isinstance(response, Exception): raise response
            return response
        self.patch = patch.object(generation, 'request_answer', side_effect=model)
        self.model = self.patch.start()
        self.addCleanup(self.patch.stop)
        for module, name in ((wire, 'read_embedding_config'), (wire, 'request_embeddings'),
                             (generation, 'build_opener'), (business, 'request_completion')):
            p = patch.object(module, name, side_effect=AssertionError('No network or embedding allowed'))
            blocked = p.start()
            self.addCleanup(p.stop)
            self.addCleanup(blocked.assert_not_called)

    def run_agent(self, **kwargs):
        options = dict(config_path=self.config, data_path=self.data)
        options.update(kwargs)
        return agent.run_agent(**options)

    def assert_failure(self, record, stage, requests, tools):
        self.assertEqual(record['status'], 'failed', record)
        self.assertIsNone(record['summary'])
        self.assertEqual(record['error']['stage'], stage)
        self.assertEqual(record['model_requests'], requests)
        self.assertEqual(record['tool_executions'], tools)
        self.assertNotIn(KEY, json.dumps(record))

    def test_direct_and_real_mcp_round_trip_same_business_data_ids_budget(self):
        records = []
        registry = deepcopy(business.TOOL_REGISTRY)
        for mode in ('direct', 'mcp'):
            self.responses = [reply(route()), reply(final())]
            self.sent.clear()
            output = self.root / f'{mode}.json'
            record = self.run_agent(transport_name=mode, output=output)
            records.append(record)
            self.assertEqual(json.loads(output.read_text()), record)
            self.assertEqual(record['status'], 'succeeded', record)
            self.assertEqual(record['summary'], SUMMARY)
            self.assertEqual((record['model_requests'], record['tool_executions']), (2, 1))
            self.assertEqual(record['usage']['total_tokens'], 41)
            self.assertTrue(record['usage']['complete'])
            self.assertEqual(record['semantic_review'], 'not_performed')
            first, second = self.sent
            self.assertEqual([t['function']['name'] for t in first[1]['tools']], ['get_project'])
            self.assertEqual(second[1], {})
            self.assertEqual([m['role'] for m in second[0]], ['system', 'user', 'assistant', 'tool'])
            assistant, tool = second[0][-2:]
            self.assertEqual(assistant['tool_calls'][0]['id'], tool['tool_call_id'])
            self.assertEqual(tool['tool_call_id'], 'call-f-1')
            self.assertNotIn('index', assistant['tool_calls'][0])
            self.assertEqual(json.loads(tool['content']), {k: self.project[k] for k in ('project_id', 'name', 'status')})
            self.assertTrue(record['tool_exchange']['sent_to_model'])
            self.assertNotIn(KEY, output.read_text())
        self.assertEqual(records[0]['tool_exchange'], records[1]['tool_exchange'])
        self.assertEqual(business.TOOL_REGISTRY, registry)
        self.assertEqual([e['event'] for e in records[1]['trace']], [
            'mcp_prepare', 'mcp_discovery', 'model_request', 'tool_validation', 'tool_execution',
            'mcp_call', 'model_request', 'mcp_cleanup', 'completed'])

    def test_illegal_model_calls_reject_without_business_execution(self):
        for change in ('target', 'tool', 'duplicate', 'extra', 'type', 'id', 'blankid', 'many',
                       'indexbool', 'indexvalue', 'indexfloat', 'indexextra', 'role', 'content',
                       'legacy', 'finish', 'length', 'none', 'choices'):
            value = route()
            choice = value['choices'][0]
            message = choice['message']
            call = message['tool_calls'][0]
            if change == 'target': call['function']['arguments'] = '{"project_id":"yunfan"}'
            elif change == 'tool': call['function']['name'] = 'list_project_issues'
            elif change == 'duplicate': call['function']['arguments'] = '{"project_id":"xingqiao","project_id":"xingqiao"}'
            elif change == 'extra': call['function']['arguments'] = '{"project_id":"xingqiao","other":true}'
            elif change == 'type': call['function']['arguments'] = '{"project_id":true}'
            elif change == 'id': call['id'] = KEY + '\n'
            elif change == 'blankid': call['id'] = ''
            elif change == 'many': message['tool_calls'].append(deepcopy(call))
            elif change == 'indexbool': call['index'] = True
            elif change == 'indexvalue': call['index'] = 1
            elif change == 'indexfloat': call['index'] = 0.0
            elif change == 'indexextra': call['other'] = KEY
            elif change == 'role': message['role'] = 'system'
            elif change == 'content': message['content'] = {KEY: KEY}
            elif change == 'legacy': message['function_call'] = {}
            elif change == 'finish': choice['finish_reason'] = 'stop'
            elif change == 'length': choice['finish_reason'] = 'length'
            elif change == 'none': value = final()
            else: value['choices'] = []
            self.responses = [reply(value)]
            with self.subTest(change=change), patch.object(contract, 'query') as query:
                record = self.run_agent()
                self.assert_failure(record, 'tool_validation', 1, 0)
                query.assert_not_called()
                self.assertEqual(record['usage']['total_tokens'], 26 if change == 'none' else 15)

    def test_bad_final_summary_and_repeated_tool_no_third_request(self):
        for change in ('repeat', 'length', 'extra', 'missing', 'duplicate', 'blank', 'type', 'legacy', 'role',
                       'malformed_calls_dict', 'malformed_calls_bool'):
            value = final()
            message = value['choices'][0]['message']
            if change == 'repeat': value = route()
            elif change == 'length': value['choices'][0]['finish_reason'] = 'length'
            elif change == 'extra': message['content'] = json.dumps({**SUMMARY, 'extra': []})
            elif change == 'missing': message['content'] = '{}'
            elif change == 'duplicate': message['content'] = '{"progress":[],"progress":[],"blockers":[],"next_steps":[]}'
            elif change == 'blank': message['content'] = json.dumps({**SUMMARY, 'progress': [' ']})
            elif change == 'type': message['content'] = json.dumps({**SUMMARY, 'progress': 'a'})
            elif change == 'legacy': message['function_call'] = {}
            elif change == 'malformed_calls_dict': message['tool_calls'] = {}
            elif change == 'malformed_calls_bool': message['tool_calls'] = False
            else: message['role'] = 'system'
            self.responses = [reply(route()), reply(value)]
            with self.subTest(change=change): self.assert_failure(self.run_agent(), 'summary_validation', 2, 1)

    def test_network_http_malformed_partial_and_missing_usage(self):
        for phase in (0, 1):
            for kind in ('timeout', 'http', 'nonjson', 'shape'):
                bad = (TimeoutError(KEY) if kind == 'timeout' else reply({'usage': final()['usage']}, 429)
                       if kind == 'http' else wire.Reply(200, KEY.encode()) if kind == 'nonjson'
                       else reply({'choices': [], 'usage': final()['usage']}))
                self.responses = ([reply(route())] if phase else []) + [bad]
                stage = ('answer_request' if phase else 'routing_request') if kind != 'shape' else (
                    'summary_validation' if phase else 'tool_validation')
                with self.subTest(phase=phase, kind=kind):
                    record = self.run_agent()
                    self.assert_failure(record, stage, phase + 1, phase)
                    self.assertEqual(record['usage']['total_tokens'], (15 if phase else 0) + (26 if kind in ('http', 'shape') else 0))
                    self.assertEqual(record['usage']['complete'], kind in ('http', 'shape'))
        for missing in (0, 1, 2):
            values = [route(), final()]
            for index in range(2):
                if missing == index or missing == 2: del values[index]['usage']
            self.responses = [reply(v) for v in values]
            record = self.run_agent()
            self.assertEqual(record['status'], 'succeeded')
            self.assertFalse(record['usage']['complete'])
            self.assertEqual(record['usage']['total_tokens'], [26, 15, 0][missing])

    def test_input_config_project_and_messages_preflight_zero_requests(self):
        for target in ('', None, True, 'unknown', '\ud800', '中' * 6000):
            with self.subTest(target=repr(target)[:40]):
                record = self.run_agent(project_id=target)
                self.assertEqual(record['status'], 'failed')
                self.assertEqual(record['model_requests'], 0)
        original = self.config.read_text()
        for content in ('[invalid', '[other]\nvalue=1', '[model]\napi_key="fake-中文"', '[model]\napi_key="fake key"'):
            self.config.write_text(content)
            self.assert_failure(self.run_agent(), 'configuration', 0, 0)
        self.config.write_text(original)
        self.project['status'] = '中' * 6000
        self.data.write_text(json.dumps([self.project]))
        self.assert_failure(self.run_agent(), 'project_preflight', 0, 0)
        self.model.assert_not_called()

    def test_discovery_failure_before_model_request_and_cleanup_after_summary_failure(self):
        @asynccontextmanager
        async def broken(*args, **kwargs):
            raise mcp.MCPFailure('mcp_discovery', 'invalid_schema')
            yield
        with patch.object(mcp, 'connect', broken):
            self.assert_failure(self.run_agent(transport_name='mcp'), 'mcp_discovery', 0, 0)
        self.model.assert_not_called()
        self.responses = [reply(route()), reply(route())]
        record = self.run_agent(transport_name='mcp')
        self.assert_failure(record, 'summary_validation', 2, 1)
        self.assertEqual(record['trace'][-1], {'event': 'mcp_cleanup', 'status': 'succeeded'})

    def test_real_discovery_schema_failure_prevents_model(self):
        from mcp import StdioServerParameters
        params = StdioServerParameters(command=str(mcp.PYTHON), args=[
            str(Path(__file__).with_name('mcp_fault_server.py').resolve()),
            'schema', str(self.root / 'pid')], cwd=str(self.root))
        with patch.object(mcp, 'server_parameters', return_value=params):
            self.assert_failure(self.run_agent(transport_name='mcp'), 'mcp_discovery', 0, 0)
        self.model.assert_not_called()

    def test_real_body_failure_then_cleanup_failure_preserves_both(self):
        self.responses = [reply(route()), reply(route())]
        record = self.run_agent(transport_name='mcp', cleanup_timeout=0)
        self.assert_failure(record, 'mcp_cleanup', 2, 1)
        self.assertEqual(record['prior_error']['stage'], 'summary_validation')
        self.assertEqual(record['usage']['total_tokens'], 30)

    def test_business_failure_keeps_first_usage_no_compensation(self):
        with patch.object(contract, 'query', side_effect=ValueError(KEY)):
            record = self.run_agent()
        self.assert_failure(record, 'tool_execution', 1, 1)
        self.assertEqual(record['usage']['total_tokens'], 15)
        self.model.assert_called_once()

    def test_real_mcp_cleanup_deadline_failure_invalidates_summary(self):
        # Tiny reporting deadline: the SDK must finish/reap, then report failure.
        record = self.run_agent(transport_name='mcp', cleanup_timeout=0)
        self.assert_failure(record, 'mcp_cleanup', 2, 1)
        self.assertEqual(record['usage']['total_tokens'], 41)
        self.assertEqual(record['trace'][-2]['event'], 'mcp_cleanup')

    def test_context_oversize_not_truncated_second_request_prevented(self):
        value = route()
        value['choices'][0]['message']['content'] = '中' * 6000
        self.responses = [reply(value)]
        record = self.run_agent()
        self.assert_failure(record, 'answer_context', 1, 1)
        self.assertFalse(record['tool_exchange']['sent_to_model'])
        self.model.assert_called_once()

    def test_output_reservation_and_write_flush_close_failures(self):
        output = self.root / 'existing.json'
        output.write_text('keep')
        for path in (output, self.root / 'missing/result.json'):
            self.assert_failure(self.run_agent(output=path), 'output', 0, 0)
        self.assertEqual(output.read_text(), 'keep')
        self.model.assert_not_called()
        original_open = Path.open
        for operation in ('write', 'flush', 'close'):
            output = self.root / f'{operation}.json'
            class Broken:
                def __init__(self, handle): self.handle = handle
                def __enter__(self): return self
                def __exit__(self, *args):
                    self.handle.close()
                    if operation == 'close': raise OSError(KEY)
                def write(self, text):
                    if operation == 'write': raise OSError(KEY)
                    return self.handle.write(text)
                def flush(self):
                    if operation == 'flush': raise OSError(KEY)
                    self.handle.flush()
            def opening(path, *args, **kwargs):
                handle = original_open(path, *args, **kwargs)
                return Broken(handle) if path == output and args and args[0] == 'x' else handle
            self.responses = [reply(route()), reply(final())]
            with patch.object(Path, 'open', opening):
                self.assert_failure(self.run_agent(output=output), 'output', 2, 1)

    def test_cli_default_direct_and_summary_only(self):
        output = self.root / 'cli.json'
        with redirect_stdout(io.StringIO()) as printed:
            code = agent.main(['--config', str(self.config), '--output', str(output)])
        self.assertEqual(code, 0)
        self.assertNotIn(KEY, printed.getvalue())
        self.assertEqual(json.loads(output.read_text())['transport'], 'direct')


if __name__ == '__main__': unittest.main()

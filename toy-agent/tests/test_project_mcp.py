"""F1: real SDK subprocess communication and application boundary tests."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import anyio
from mcp import StdioServerParameters, types

import deepseek_summary as business
import project_mcp_client as client
import project_mcp_contract as contract


class MCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'projects.json'
        self.original = [{'project_id': 'xingqiao', 'name': 'fixture', 'status': 'original', 'issues': []}]
        self.data.write_text(json.dumps(self.original))
        self.processes = []
        original = anyio.open_process
        async def observe(*args, **kwargs):
            self.assertEqual(args[0][0], str(client.PYTHON))
            process = await original(*args, **kwargs)
            self.processes.append(process)
            self.assertNotIn('FAKE_F_SECRET', kwargs['env'])
            self.assertNotIn('PYTHONPATH', kwargs['env'])
            return process
        self.patcher = patch.object(anyio, 'open_process', side_effect=observe)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def assert_reaped(self):
        self.assertTrue(self.processes)
        for process in self.processes:
            self.assertIsNotNone(process.returncode)
            with self.assertRaises(ProcessLookupError): os.kill(process.pid, 0)

    def fault(self, mode):
        return StdioServerParameters(command=str(client.PYTHON), args=[
            str(Path(__file__).with_name('mcp_fault_server.py').resolve()), mode, str(self.root / 'pid')],
            cwd=str(self.root))

    async def test_real_discovery_call_direct_equivalence_and_lifetime_snapshot(self):
        trace = []
        params = client.server_parameters(self.data)
        params.cwd = str(self.root)
        with patch.dict(os.environ, {'FAKE_F_SECRET': 'fake'}):
            async with client.connect(trace, params=params) as connected:
                found = await connected.session.list_tools()
                self.assertEqual([t.name for t in found.tools], ['get_project'])
                expected = contract.query({'project_id': 'xingqiao'}, business.load_projects(self.data))
                self.assertEqual(await connected.get_project({'project_id': 'xingqiao'}), expected)
                self.original[0]['status'] = 'changed'
                self.data.write_text(json.dumps(self.original))
                self.assertEqual(await connected.get_project({'project_id': 'xingqiao'}), expected)
            async with client.connect([], data_path=self.data) as connected:
                self.assertEqual((await connected.get_project({'project_id': 'xingqiao'}))['status'], 'changed')
        self.assertEqual(trace[-1], {'event': 'mcp_cleanup', 'status': 'succeeded'})
        self.assertEqual(trace[0]['protocol_version'], '2025-11-25')
        self.assert_reaped()

    async def test_real_server_rejects_unknown_blank_type_missing_extra_and_tool(self):
        async with client.connect([], data_path=self.data) as connected:
            for params in ({'project_id': 'unknown'}, {'project_id': ''}, {'project_id': ' '},
                           {'project_id': 1}, {'project_id': True}, {},
                           {'project_id': 'xingqiao', 'extra': True}):
                result = await connected.session.call_tool('get_project', params)
                self.assertTrue(result.is_error)
                with self.assertRaises(client.MCPFailure): client.unpack(result, 'xingqiao')
            self.assertTrue((await connected.session.call_tool('unknown', {'project_id': 'xingqiao'})).is_error)
        self.assert_reaped()

    async def test_real_timeouts_exit_schema_protocol_and_invalid_result_reap(self):
        for mode, expected in [('startup', 'mcp_prepare'), ('exit', 'mcp_prepare'),
                               ('discovery', 'mcp_discovery'), ('schema', 'mcp_discovery'),
                               ('call', 'mcp_call'), ('call_exit', 'mcp_call'),
                               ('protocol', 'mcp_call'), ('invalid', 'mcp_call')]:
            with self.subTest(mode=mode):
                trace = []
                start = time.monotonic()
                with self.assertRaises(client.MCPFailure) as caught:
                    async with client.connect(trace, params=self.fault(mode), timeout=1.5) as connected:
                        await connected.get_project({'project_id': 'xingqiao'})
                self.assertEqual(caught.exception.stage, expected)
                self.assertLess(time.monotonic() - start, 9)
                self.assertEqual(trace[-1]['event'], 'mcp_cleanup')
                self.assert_reaped()

    async def test_real_cancel_and_stubborn_process_forced_reap(self):
        for mode in ('call', 'stubborn'):
            trace = []
            async def work():
                async with client.connect(trace, params=self.fault(mode), timeout=10) as connected:
                    await connected.get_project({'project_id': 'xingqiao'})
            task = asyncio.create_task(work())
            while not (self.root / 'pid').exists(): await asyncio.sleep(.02)
            if mode == 'call':
                while not any(e['event'] == 'mcp_call' for e in trace): await asyncio.sleep(.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assert_reaped()
            self.assertEqual(trace[-1]['status'], 'succeeded')
            (self.root / 'pid').unlink()

    async def test_default_data_path_from_foreign_cwd_and_missing_startup(self):
        params = client.server_parameters()
        params.cwd = str(self.root)
        async with client.connect([], params=params) as connected:
            actual = await connected.get_project({'project_id': 'xingqiao'})
            self.assertEqual(actual, business.get_project('xingqiao', business.load_projects()))
        self.assert_reaped()
        params = client.server_parameters(self.root / 'absent.json')
        with self.assertRaises(client.MCPFailure) as error:
            async with client.connect([], params=params): pass
        self.assertEqual(error.exception.stage, 'mcp_prepare')
        self.assert_reaped()

    async def test_secret_not_in_real_server_environment(self):
        with patch.dict(os.environ, {'FAKE_F_SECRET': 'fake-key'}):
            async with client.connect([], params=self.fault('secret')) as connected:
                self.assertEqual((await connected.get_project({'project_id': 'xingqiao'}))['status'], 'False')
        self.assert_reaped()

    def test_result_and_schema_rejections(self):
        data = {'project_id': 'xingqiao', 'name': 'name', 'status': 'ok'}
        good = types.CallToolResult(structured_content=data,
            content=[types.TextContent(type='text', text=json.dumps(data))])
        self.assertEqual(client.unpack(good, 'xingqiao'), data)
        for change in ('missing', 'conflict', 'text', 'extra', 'empty', 'duplicate', 'type', 'error'):
            result = deepcopy(good)
            if change == 'missing': result.structured_content = None
            elif change == 'conflict': result.structured_content['status'] = 'other'
            elif change == 'text': result.content[0].text = 'error text'
            elif change == 'extra': result.content.append(types.TextContent(type='text', text='extra'))
            elif change == 'empty': result.content = []
            elif change == 'duplicate': result.content[0].text = '{"project_id":"a","project_id":"b"}'
            elif change == 'type': result.content = [types.ImageContent(type='image', data='AA==', mime_type='image/png')]
            else: result.is_error = True
            with self.subTest(change=change), self.assertRaises(client.MCPFailure): client.unpack(result, 'xingqiao')
        good_tool = types.Tool(name='get_project', description=contract.DESCRIPTION,
                              input_schema=contract.INPUT_SCHEMA, output_schema=contract.OUTPUT_SCHEMA)
        for change in ('name', 'description', 'input', 'output', 'many', 'page'):
            found = types.ListToolsResult(tools=[deepcopy(good_tool)])
            if change == 'name': found.tools[0].name = 'other'
            elif change == 'description': found.tools[0].description = ''
            elif change == 'input': found.tools[0].input_schema = {}
            elif change == 'output': found.tools[0].output_schema = {}
            elif change == 'many': found.tools.append(good_tool)
            else: found.next_cursor = 'more'
            with self.subTest(change=change), self.assertRaises(contract.ContractError): client.checked_discovery(found)


if __name__ == '__main__': unittest.main()

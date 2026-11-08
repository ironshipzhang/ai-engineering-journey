"""Offline subprocess fixture, never used by the production CLI."""
import asyncio
import os
from pathlib import Path
import signal
import sys

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

# Scripts launched from a non-repository cwd still find the actual project modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import project_mcp_contract as contract


async def main():
    mode, pid_path = sys.argv[1:]
    Path(pid_path).write_text(str(os.getpid()))
    if mode == 'exit': return
    if mode in ('startup', 'stubborn'):
        if mode == 'stubborn': signal.signal(signal.SIGTERM, signal.SIG_IGN)
        await asyncio.sleep(60)
        return

    async def listing(ctx, params):
        if mode == 'discovery': await asyncio.sleep(60)
        schema = dict(contract.INPUT_SCHEMA)
        if mode == 'schema': schema['additionalProperties'] = True
        return types.ListToolsResult(tools=[types.Tool(name='get_project', description=contract.DESCRIPTION,
            input_schema=schema, output_schema=contract.OUTPUT_SCHEMA)])

    async def calling(ctx, params):
        if mode == 'call': await asyncio.sleep(60)
        if mode == 'call_exit': os._exit(3)
        if mode == 'secret':
            data = {'project_id': 'xingqiao', 'name': 'fixture', 'status': str('FAKE_F_SECRET' in os.environ)}
            return types.CallToolResult(structured_content=data,
                content=[types.TextContent(type='text', text=__import__('json').dumps(data))])
        if mode == 'protocol': raise ValueError('fake-secret-do-not-print')
        return types.CallToolResult(content=[types.TextContent(type='text', text='invalid')])

    server = Server('fault', on_list_tools=listing, on_call_tool=calling)
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == '__main__':
    import logging
    logging.disable(logging.CRITICAL)
    asyncio.run(main())

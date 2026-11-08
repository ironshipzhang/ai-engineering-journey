"""F1: controlled local stdio server. stdout belongs exclusively to the SDK."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

import deepseek_summary as business
import project_mcp_contract as contract


def make_server(snapshot):
    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(
            name="get_project", description=contract.DESCRIPTION,
            input_schema=contract.INPUT_SCHEMA, output_schema=contract.OUTPUT_SCHEMA)])

    async def call_tool(ctx, params):
        try:
            contract.require(params.name == "get_project")
            data = contract.query(params.arguments, snapshot)
        except Exception:
            # Neither Pydantic details nor arbitrary input is reflected to the client.
            return types.CallToolResult(is_error=True, content=[types.TextContent(
                type="text", text="项目查询失败：参数无效或项目不存在。")])
        return types.CallToolResult(is_error=False, structured_content=data,
                                    content=[types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))])

    return Server("toy-project", version="1", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(data_path=None):
    snapshot = business.load_projects(data_path)  # exactly once per server lifetime
    server = make_server(snapshot)
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # Controlled local fixture path for offline testing; never a model tool parameter.
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)  # SDK diagnostics can contain request inputs
    try:
        asyncio.run(serve(args.data))
        return 0
    except Exception:
        print("项目 MCP Server 启动或协议运行失败。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

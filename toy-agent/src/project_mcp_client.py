"""F1 SDK stdio adapter. One session per run; no retry, reconnect or fallback."""
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import logging
import os
from pathlib import Path
import time

from mcp import ClientSession, StdioServerParameters, stdio_client, types

import prepare_corpus as corpus
import project_mcp_contract as contract

PYTHON = Path(__file__).absolute().parents[1] / ".venv" / "bin" / "python"
SERVER = Path(__file__).resolve().with_name("project_mcp_server.py")


class MCPFailure(Exception):
    def __init__(self, stage, category):
        self.stage, self.category = stage, category
        super().__init__("本地 MCP 操作失败；未重试或切换路径。")


def server_parameters(data_path=None):
    args = [str(SERVER)]
    if data_path is not None:
        args += ["--data", str(Path(data_path).resolve())]
    # SDK merges its small OS allowlist; no parent API keys, PYTHONPATH or dotenv.
    return StdioServerParameters(command=str(PYTHON), args=args,
                                 env={"PYTHONNOUSERSITE": "1"}, cwd=str(SERVER.parent))


def checked_discovery(found):
    contract.require(found.next_cursor is None and len(found.tools) == 1)
    tool = found.tools[0]
    contract.require(tool.name == "get_project" and tool.description == contract.DESCRIPTION)
    contract.require(tool.input_schema == contract.INPUT_SCHEMA and tool.output_schema == contract.OUTPUT_SCHEMA)
    return contract.MODEL_TOOL  # never forward a remote schema/description to the model


def unpack(result, target):
    if not isinstance(result, types.CallToolResult):
        raise MCPFailure("mcp_call", "result_type")
    if result.is_error:
        raise MCPFailure("mcp_tool", "tool_error")
    try:
        contract.require(len(result.content) == 1 and isinstance(result.content[0], types.TextContent))
        text = corpus.decode_json(result.content[0].text.encode("utf-8"), "MCP result")
        data = contract.project(result.structured_content, target)
        contract.require(contract.project(text, target) == data)
        return data
    except Exception:
        raise MCPFailure("mcp_result", "invalid_result") from None


class SafeSDKLogs(logging.Handler):
    """Discard SDK payload diagnostics; retain only the cleanup-survivor signal."""
    def __init__(self):
        super().__init__()
        self.cleanup_failed = False

    def emit(self, record):
        if record.name == "mcp.client.stdio" and record.msg == "MCP server process %d is still alive after the kill escalation; abandoning it":
            self.cleanup_failed = True


@asynccontextmanager
async def connect(trace, *, data_path=None, timeout=10, cleanup_timeout=10, params=None):
    stack = AsyncExitStack()
    sink = SafeSDKLogs()
    loggers = [logging.getLogger(name) for name in ("mcp", "client")]
    saved = [(logger.handlers[:], logger.propagate) for logger in loggers]
    for logger in loggers:
        logger.handlers, logger.propagate = [sink], False
    stage = "mcp_prepare"
    ready = False
    try:
        # asyncio timeout does not insert an AnyIO cancel scope across SDK task groups.
        with open(os.devnull, "w") as errors:
            try:
                async with asyncio.timeout(timeout):
                    streams = await stack.enter_async_context(stdio_client(params or server_parameters(data_path), errlog=errors))
                    session = await stack.enter_async_context(ClientSession(*streams, read_timeout_seconds=timeout))
                    initialized = await session.initialize()
                    contract.require(initialized.protocol_version == "2025-11-25"
                                     and initialized.capabilities.tools is not None)
                trace.append({"event": stage, "status": "succeeded", "protocol_version": initialized.protocol_version})
                stage = "mcp_discovery"
                async with asyncio.timeout(timeout):
                    checked_discovery(await session.list_tools())
                trace.append({"event": stage, "status": "succeeded", "tool": "get_project"})
                ready = True
                yield ProjectClient(session, trace, timeout)
            except Exception as error:
                if ready or isinstance(error, MCPFailure):
                    raise
                trace.append({"event": stage, "status": "failed"})
                raise MCPFailure(stage, "timeout" if isinstance(error, TimeoutError) else "protocol_or_contract") from None
            finally:
                started = time.monotonic()
                try:
                    # SDK shields its bounded shutdown: flush .5s, grace 2s, TERM 2s,
                    # KILL/reap 2s. Do not cancel it mid-cleanup or move it to another task.
                    await stack.aclose()
                    if sink.cleanup_failed or time.monotonic() - started > cleanup_timeout:
                        raise MCPFailure("mcp_cleanup", "cleanup_timeout")
                    trace.append({"event": "mcp_cleanup", "status": "succeeded"})
                except MCPFailure:
                    trace.append({"event": "mcp_cleanup", "status": "failed"})
                    raise
                except asyncio.CancelledError:
                    trace.append({"event": "mcp_cleanup", "status": "succeeded"})
                    raise
                except BaseException:
                    trace.append({"event": "mcp_cleanup", "status": "failed"})
                    raise MCPFailure("mcp_cleanup", "cleanup_failed") from None
    finally:
        for logger, (handlers, propagate) in zip(loggers, saved):
            logger.handlers, logger.propagate = handlers, propagate


class ProjectClient:
    def __init__(self, session, trace, timeout):
        self.session, self.trace, self.timeout = session, trace, timeout
        self.calls = 0

    async def get_project(self, params):
        target = contract.parameters(params)
        self.calls += 1
        # Local event number, deliberately not represented as the SDK's wire request ID.
        event = {"event": "mcp_call", "local_call_number": self.calls, "status": "failed"}
        self.trace.append(event)
        try:
            async with asyncio.timeout(self.timeout):
                result = await self.session.call_tool("get_project", params)
            data = unpack(result, target)
            event["status"] = "succeeded"
            return data
        except MCPFailure as error:
            event["category"] = error.category
            raise
        except Exception as error:
            category = "timeout" if isinstance(error, TimeoutError) else "protocol_error"
            event["category"] = category
            raise MCPFailure("mcp_call", category) from None

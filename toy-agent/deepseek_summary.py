"""Run a bounded read-only project Agent Loop using the Python standard library."""

import argparse
import json
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
MAX_TOKENS = 400
MAX_REQUESTS = 5
SUMMARY_FIELDS = ("progress", "blockers", "next_steps")
PROJECT_STATUS = """以下是虚构项目“星桥”的状态：
已完成：登录接口和项目列表接口已实现，12 个单元测试通过。
进行中：项目详情页面正在联调。
阻塞：测试环境数据库迁移失败，负责人小林正在排查。
下一步：修复迁移后完成联调，计划周五演示；演示时间存在延期风险。
"""


class SummaryError(Exception):
    """A safe, locally defined message suitable for terminal output."""


def read_api_key(path: Path) -> str:
    try:
        key = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise SummaryError("无法读取密钥文件；请检查文件是否存在、权限及 UTF-8 编码。尚未发送请求。") from None
    if not key:
        raise SummaryError("密钥文件为空；尚未发送请求。")
    if any(character.isspace() for character in key):
        raise SummaryError("密钥应为单行纯文本；尚未发送请求。")
    return key


SUMMARY_PROMPT = (
    "只依据提供的项目状态，用中文生成简短摘要，不要编造信息。"
    "只返回 JSON 对象，不附带说明或 Markdown。"
    "必须且仅包含 progress、blockers、next_steps 三个字段；"
    "每个值是字符串数组，每项必须是非空字符串，没有对应信息时用空数组 []。"
    "progress 包含已完成和进行中的进展，blockers 包含阻塞项及风险，"
    "next_steps 包含下一步行动。"
    '格式示例：{"progress":["接口已完成"],"blockers":[],"next_steps":["完成联调"]}'
)
GET_PROJECT_TOOL = {
    "type": "function",
    "function": {
        "name": "get_project",
        "description": "按项目 ID 查询虚构项目状态，只读。",
        "parameters": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "项目 ID，例如 xingqiao"}},
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
}


def get_project(project_id: str) -> dict[str, str]:
    """Read fixed fictional data; no database or write operation is involved."""
    if project_id != "xingqiao":
        raise SummaryError("项目不存在；任务结束，不自动重试。")
    return {"project_id": project_id, "name": "星桥", "status": PROJECT_STATUS}


def request_completion(api_key: str, messages: list[dict]) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }
    # With tools present, omitting tool_choice defaults to auto.
    payload["tools"] = [GET_PROJECT_TOOL]
    payload["response_format"] = {"type": "json_object"}
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def inspect_response(response: dict, stage: str) -> tuple[dict, str, list[int]]:
    """Record usage before interpreting the model's requested action."""
    try:
        choice = response["choices"][0]
        message = choice["message"]
        reason = choice["finish_reason"]
        counts = [response["usage"][name] for name in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError
        if not isinstance(reason, str) or any(type(count) is not int or count < 0 for count in counts):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise SummaryError("响应格式异常：缺少有效消息、结束原因或 token 用量。") from None
    print(f"{stage} Token 用量：输入={counts[0]}，输出={counts[1]}，总计={counts[2]}")
    print(f"结束原因：{reason}；输出上限：{MAX_TOKENS} tokens")
    return message, reason, counts


def validate_tool_call(message: dict, reason: str) -> dict:
    if reason == "length":
        raise SummaryError("工具调用达到 token 上限，可能被截断；不执行工具。")
    if reason != "tool_calls":
        raise SummaryError("模型未正常提出工具调用；不执行工具。")
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        raise SummaryError("必须恰好提出一次工具调用；不执行工具。")
    call = calls[0]
    if not isinstance(call, dict) or call.get("type") != "function":
        raise SummaryError("工具调用类型必须为 function。")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise SummaryError("工具调用缺少有效 ID。")
    function = call.get("function")
    if not isinstance(function, dict) or function.get("name") != "get_project":
        raise SummaryError("只允许调用 get_project。")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise SummaryError("工具参数必须是 JSON 字符串。")
    try:
        params = json.loads(arguments)
    except json.JSONDecodeError:
        raise SummaryError("工具参数不是有效 JSON。") from None
    if not isinstance(params, dict) or set(params) != {"project_id"}:
        raise SummaryError("工具参数必须且仅包含 project_id。")
    if not isinstance(params["project_id"], str) or not params["project_id"].strip():
        raise SummaryError("project_id 必须是非空字符串。")
    # Normalize only protocol fields; never dynamically resolve a model-supplied name.
    return {"id": call_id, "type": "function", "function": {
        "name": "get_project", "arguments": arguments,
    }}


def run_project_summary(api_key: str) -> None:
    messages = [
        {"role": "system", "content": SUMMARY_PROMPT + (
            "需要项目数据时使用 get_project，每轮最多调用一次。"
            "只有成功取得项目数据后才能生成最终摘要；已有数据时避免重复查询。"
        )},
        {"role": "user", "content": "请查询项目 ID 为 xingqiao 的虚构项目，并总结项目状态。"},
    ]
    # Task-local success cache: JSON formatting and call IDs are not cache keys.
    successful_results: dict[str, dict[str, str]] = {}
    totals = [0, 0, 0]
    for request_number in range(1, MAX_REQUESTS + 1):
        response = request_completion(api_key, messages)
        message, reason, counts = inspect_response(response, f"第 {request_number} 轮")
        totals = [a + b for a, b in zip(totals, counts)]
        print(f"累计 Token 用量：输入={totals[0]}，输出={totals[1]}，总计={totals[2]}")
        if reason == "stop":
            if message.get("tool_calls"):
                raise SummaryError("结束原因与工具调用不一致；任务结束。")
            if not successful_results:
                raise SummaryError("尚未成功取得项目数据；不接受最终摘要。")
            display_summary(message, reason)
            return
        # Reject truncation, abnormal finish reasons and invalid calls before execution.
        call = validate_tool_call(message, reason)
        if request_number == MAX_REQUESTS:
            raise SummaryError(f"已达到 {MAX_REQUESTS} 次模型请求上限，仍需工具调用；不执行工具，任务结束。")
        params = json.loads(call["function"]["arguments"])
        project_id = params["project_id"]
        print(f"模型提出工具调用：get_project；ID={call['id']}；参数={json.dumps(params, ensure_ascii=False)}")
        if project_id in successful_results:
            result = successful_results[project_id]
            print("复用本任务内成功的 get_project 结果。")
        else:
            # An exception exits the task before storing anything: failures are never cached.
            result = get_project(project_id)
            successful_results[project_id] = result
            print("本地只读 get_project 执行成功。")
        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": [call]})
        messages.append({"role": "tool", "tool_call_id": call["id"],
                         "content": json.dumps(result, ensure_ascii=False)})


def parse_summary(content: str) -> dict[str, list[str]]:
    """Validate structure only; factual correctness requires separate evaluation."""
    try:
        summary = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        raise SummaryError("摘要不是有效 JSON。") from None
    if not isinstance(summary, dict):
        raise SummaryError("摘要必须是 JSON 对象。")
    for field in SUMMARY_FIELDS:
        if field not in summary:
            raise SummaryError(f"摘要缺少必填字段：{field}。")
        values = summary[field]
        if not isinstance(values, list):
            raise SummaryError(f"摘要字段 {field} 必须是字符串数组，允许空数组 []。")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise SummaryError(f"摘要字段 {field} 的每个元素必须是非空字符串。")
    if set(summary) != set(SUMMARY_FIELDS):
        raise SummaryError("摘要包含约定之外的字段。")
    return summary


def display_response(response: dict) -> None:
    message, reason, _ = inspect_response(response, "摘要请求")
    display_summary(message, reason)


def display_summary(message: dict, reason: str) -> None:
    if reason == "length":
        raise SummaryError("摘要达到 token 上限，可能被截断；不作为有效摘要使用。")
    if reason != "stop":
        raise SummaryError("生成未正常结束；请检查结束原因。")
    if message.get("tool_calls"):
        raise SummaryError("摘要阶段不允许再次调用工具。")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SummaryError("响应缺少有效摘要。")
    summary = parse_summary(content)
    print("结构化摘要：")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True, help="仓库外的单行密钥文件")
    args = parser.parse_args()
    try:
        api_key = read_api_key(args.key_file)
        run_project_summary(api_key)
    except HTTPError as error:
        hints = {400: "请求参数无效", 401: "认证失败", 402: "余额不足", 422: "请求参数无法处理", 429: "请求限流", 500: "服务内部错误", 503: "服务繁忙"}
        print(f"错误：HTTP {error.code}，{hints.get(error.code, 'API 请求失败')}；未自动重试。", file=sys.stderr)
        error.close()
        return 1
    except (URLError, TimeoutError, socket.timeout):
        print("错误：网络连接失败或超时；未自动重试。超时不代表服务端未处理请求。", file=sys.stderr)
        return 1
    except SummaryError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    except (ValueError, OSError):
        # Do not expose raw exceptions: remote responses may contain sensitive data.
        print("错误：密钥文件无效或响应无法解析；请检查文件配置和 API 响应结构。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

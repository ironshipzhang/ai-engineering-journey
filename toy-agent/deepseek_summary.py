"""Run a bounded read-only project Agent Loop using the Python standard library."""

import argparse
import json
from pathlib import Path
import socket
import sys
import tomllib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
MAX_TOKENS = 800
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


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "local.toml"


def read_config_api_key(path: Path = DEFAULT_CONFIG_PATH) -> str:
    """Read only the API key; never expose TOML contents or parser diagnostics."""
    try:
        with path.open("rb") as source:
            config = tomllib.load(source)
    except FileNotFoundError:
        raise SummaryError("配置文件不存在；请复制 config.example.toml 到 config/local.toml 并填写 model.api_key，或指定 --config。尚未发送请求。") from None
    except (tomllib.TOMLDecodeError, UnicodeError):
        raise SummaryError("配置文件不是有效的 UTF-8 TOML；请检查格式。尚未发送请求。") from None
    except OSError:
        raise SummaryError("无法读取配置文件；请检查路径及权限。尚未发送请求。") from None
    model = config.get("model")
    if not isinstance(model, dict) or "api_key" not in model:
        raise SummaryError("配置缺少 model.api_key；尚未发送请求。")
    key = model["api_key"]
    if not isinstance(key, str):
        raise SummaryError("model.api_key 必须是字符串；尚未发送请求。")
    if not key.strip():
        raise SummaryError("model.api_key 不能为空；尚未发送请求。")
    if key.strip() == "YOUR_API_KEY":
        raise SummaryError("model.api_key 仍是示例占位符；请填写真实密钥。尚未发送请求。")
    if any(character.isspace() for character in key):
        raise SummaryError("model.api_key 不得包含空白字符；尚未发送请求。")
    return key


SUMMARY_PROMPT = (
    "只依据提供的项目状态，用中文生成简短摘要，不要编造信息。"
    "只返回 JSON 对象，不附带说明或 Markdown。"
    "必须且仅包含 progress、blockers、next_steps 三个字段；"
    "每个值是字符串数组，每项必须是非空字符串，没有对应信息时用空数组 []。"
    "progress 包含已完成和进行中的进展，区分已完成与尚在进行。"
    "blockers 同时包含当前仍有效的阻塞和原文明确的风险，不把已解除阻塞当作当前阻塞。"
    "原文说没有其他阻塞，不等于没有已知风险；仍须保留原文明示的风险。"
    "排查进展、原因是否定位须与对应阻塞合写在同一个数组元素中，不单独列排查项。"
    "next_steps 包含下一步行动及原文明确的计划，不因计划存在风险或条件而省略。"
    "计划须保留原文的前提、时间和不确定性；条件尚未满足时不能写成已满足，"
    "计划、可能或时间未确认不能改写成确定承诺。"
    "计划归入 next_steps；计划对应的明确风险也必须归入 blockers，不能只写在 next_steps。"
    "同一事实可以按不同用途在两个字段中表达，不应为避免重复而遗漏风险。"
    "只记录原文明示的风险，不把普通条件计划一律推断为风险。"
    "不补充原文没有的事实、负责人、日期、原因或解决办法。"
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


def request_completion(api_key: str, messages: list[dict], *, with_tools: bool = True) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }
    # With tools present, omitting tool_choice defaults to auto.
    if with_tools:
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


def empty_run_result() -> dict:
    return {"status": "failed", "summary": None, "error": None,
            "model_requests": 0,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                      "complete": True},
            "tool_executions": 0, "cache_hits": 0, "trace": []}


def known_usage(response) -> dict | None:
    """Usage can remain valid even when the response message is malformed."""
    names = ("prompt_tokens", "completion_tokens", "total_tokens")
    if not isinstance(response, dict) or not isinstance(response.get("usage"), dict):
        return None
    values = [response["usage"].get(name) for name in names]
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return dict(zip(names, values))


def safe_error(error: Exception, stage: str) -> dict:
    if isinstance(error, HTTPError):
        hints = {400: "请求参数无效", 401: "认证失败", 402: "余额不足", 422: "请求参数无法处理",
                 429: "请求限流", 500: "服务内部错误", 503: "服务繁忙"}
        message = f"HTTP {error.code}，{hints.get(error.code, 'API 请求失败')}；未自动重试。"
        error.close()
        category = "http_error"
    elif isinstance(error, (URLError, TimeoutError, socket.timeout)):
        category = "network_error"
        message = "网络连接失败或超时；未自动重试。超时不代表服务端未处理请求。"
    elif isinstance(error, SummaryError):
        category, message = stage, str(error)
    else:
        category, message = stage, "本地操作失败或响应无法解析；未自动重试。"
    return {"category": category, "message": message}


def record_failure(result: dict, error: Exception, stage: str, request_number: int,
                   tool: dict | None = None) -> dict:
    result["error"] = safe_error(error, stage)
    result["trace"].append({"event": "failure", "request_number": request_number,
                            "stage": stage, "error": result["error"], **(tool or {})})
    return result


def run_project_summary(api_key: str) -> dict:
    """Return execution/structure status, not a factual-quality verdict; never print."""
    messages = [
        {"role": "system", "content": SUMMARY_PROMPT + (
            "需要项目数据时使用 get_project，每轮最多调用一次。"
            "只有成功取得项目数据后才能生成最终摘要；已有数据时避免重复查询。"
        )},
        {"role": "user", "content": "请查询项目 ID 为 xingqiao 的虚构项目，并总结项目状态。"},
    ]
    successful_results: dict[str, dict[str, str]] = {}
    result = empty_run_result()
    for request_number in range(1, MAX_REQUESTS + 1):
        result["model_requests"] += 1
        event = {"event": "model_request", "request_number": request_number,
                 "finish_reason": None, "usage": None}
        result["trace"].append(event)
        stage = "request"
        tool = None
        try:
            response = request_completion(api_key, messages)
            counts = known_usage(response)
            event["usage"] = counts
            if counts is not None:
                for name, count in counts.items():
                    result["usage"][name] += count
            else:
                result["usage"]["complete"] = False
            stage = "response_validation"
            # Extract only validated metadata; no remote payload is persisted.
            try:
                choice = response["choices"][0]
                message, reason = choice["message"], choice["finish_reason"]
                if isinstance(reason, str):
                    event["finish_reason"] = reason
                if (not isinstance(message, dict) or message.get("role") != "assistant"
                        or not isinstance(reason, str) or counts is None):
                    raise ValueError
            except (KeyError, IndexError, TypeError, ValueError):
                raise SummaryError("响应格式异常：缺少有效消息、结束原因或 token 用量。") from None
            if reason == "stop":
                stage = "summary_validation"
                if message.get("tool_calls"):
                    raise SummaryError("结束原因与工具调用不一致；任务结束。")
                if not successful_results:
                    raise SummaryError("尚未成功取得项目数据；不接受最终摘要。")
                result["summary"] = parse_summary(message.get("content"))
                result["status"] = "succeeded"
                return result
            stage = "tool_validation"
            call = validate_tool_call(message, reason)
            params = json.loads(call["function"]["arguments"])
            tool = {"tool_name": "get_project", "call_id": call["id"], "parameters": params}
            stage = "request_limit"
            if request_number == MAX_REQUESTS:
                raise SummaryError(f"已达到 {MAX_REQUESTS} 次模型请求上限，仍需工具调用；不执行工具，任务结束。")
            project_id = params["project_id"]
            if project_id in successful_results:
                data = successful_results[project_id]
                result["cache_hits"] += 1
                result["trace"].append({"event": "cache_hit", "request_number": request_number, **tool})
            else:
                stage = "tool_execution"
                result["tool_executions"] += 1
                execution = {"event": "tool_execution", "request_number": request_number,
                             "status": "failed", **tool}
                result["trace"].append(execution)
                data = get_project(project_id)
                successful_results[project_id] = data
                execution["status"] = "succeeded"
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": [call]})
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(data, ensure_ascii=False)})
        except (SummaryError, HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
            if event["usage"] is None:
                result["usage"]["complete"] = False
            return record_failure(result, error, stage, request_number, tool)


def display_run_result(result: dict) -> None:
    for event in result["trace"]:
        if event["event"] == "model_request":
            print(f"第 {event['request_number']} 轮 Token 用量：{event['usage']}；结束原因：{event['finish_reason']}")
        elif event["event"] == "tool_execution":
            print(f"本地只读 get_project 执行状态：{event['status']}；ID={event['call_id']}；"
                  f"参数={json.dumps(event['parameters'], ensure_ascii=False)}")
        elif event["event"] == "cache_hit":
            print(f"复用本任务内成功的 get_project 结果；ID={event['call_id']}。")
    usage = result["usage"]
    print(f"累计已知 Token 用量：输入={usage['prompt_tokens']}，输出={usage['completion_tokens']}，"
          f"总计={usage['total_tokens']}；用量完整={usage['complete']}")
    if result["status"] == "succeeded":
        print("结构化摘要：")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(f"错误：{result['error']['message']}", file=sys.stderr)


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


def display_summary(message: dict, reason: str) -> dict[str, list[str]]:
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
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="TOML 配置路径，默认仓库根目录 config/local.toml")
    parser.add_argument("--output", type=Path, help="新建结果 JSON 文件，拒绝覆盖")
    args = parser.parse_args()
    output = None
    try:
        # Reserve before reading credentials or attempting a paid request.
        if args.output is not None:
            output = args.output.open("x", encoding="utf-8")
        try:
            api_key = read_config_api_key(args.config)
            result = run_project_summary(api_key)
        except SummaryError as error:
            result = record_failure(empty_run_result(), error, "configuration", 0)
        display_run_result(result)
        if output is not None:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            output.close()
            output = None
        return int(result["status"] != "succeeded")
    except (OSError, ValueError):
        print("错误：无法新建或保存结果文件；请检查路径、权限及已有文件。", file=sys.stderr)
        return 1
    finally:
        if output is not None:
            try:
                output.close()
            except OSError:
                # Cleanup after a reported write failure; normal close is checked above.
                pass


if __name__ == "__main__":
    sys.exit(main())

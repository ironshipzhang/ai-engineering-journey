"""Make one bounded DeepSeek request using only the Python standard library."""

import argparse
import json
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
MAX_TOKENS = 200
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


def request_summary(api_key: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "只依据提供的项目状态，用中文生成不超过120字的摘要，涵盖进展、风险和下一步。不要编造信息。"},
            {"role": "user", "content": PROJECT_STATUS},
        ],
        "thinking": {"type": "disabled"},
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def display_response(response: dict) -> None:
    try:
        choice = response["choices"][0]
        content = choice["message"]["content"]
        reason = choice["finish_reason"]
        usage = response["usage"]
        counts = [usage[name] for name in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if not isinstance(content, str) or not content.strip():
            raise ValueError
        if not isinstance(reason, str) or any(type(count) is not int or count < 0 for count in counts):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise SummaryError("响应格式异常：缺少有效摘要、结束原因或 token 用量。") from None
    print(f"摘要：\n{content}")
    print(f"Token 用量：输入={counts[0]}，输出={counts[1]}，总计={counts[2]}")
    print(f"结束原因：{reason}；输出上限：{MAX_TOKENS} tokens")
    if reason == "length":
        print("提示：摘要达到 token 上限，可能被截断。", file=sys.stderr)
    elif reason != "stop":
        raise SummaryError("生成未正常结束；请检查结束原因。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True, help="仓库外的单行密钥文件")
    args = parser.parse_args()
    try:
        api_key = read_api_key(args.key_file)
        display_response(request_summary(api_key))
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

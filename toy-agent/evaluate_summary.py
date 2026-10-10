"""Collect summaries for a small factual-quality dataset; review meaning manually."""

import argparse
import json
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError, URLError

from deepseek_summary import (
    MAX_TOKENS, MODEL, SUMMARY_PROMPT, SummaryError, display_summary,
    inspect_response, read_api_key, request_completion,
)

CASES_PATH = Path(__file__).parent / 'evals' / 'project_summary_cases.json'


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    cases = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(cases, list) or not cases:
        raise SummaryError('评估集必须是非空数组。')
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {'id', 'status', 'required_facts', 'unsupported_claims'}:
            raise SummaryError('评估样例字段无效。')
        if any(not isinstance(case[field], str) or not case[field].strip() for field in ('id', 'status')):
            raise SummaryError('样例 ID 与状态必须是非空字符串。')
        if case['id'] in ids:
            raise SummaryError('样例 ID 不得重复。')
        ids.add(case['id'])
        facts = case['required_facts']
        if not isinstance(facts, dict) or set(facts) != {'progress', 'blockers', 'next_steps'}:
            raise SummaryError('必保留事实必须按摘要三个字段列出。')
        for values in [*facts.values(), case['unsupported_claims']]:
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise SummaryError('评估规则必须是非空字符串数组，允许空数组。')
    return cases


def evaluate(api_key: str, cases: list[dict]) -> dict:
    """One request per case, no tools or retries, no automatic semantic verdict."""
    report = {'model': MODEL, 'max_tokens': MAX_TOKENS, 'prompt': SUMMARY_PROMPT,
              'scope': 'summary_only', 'cases': [], 'usage_totals': [0, 0, 0]}
    for case in cases:
        entry = {**case, 'summary': None, 'usage': None, 'finish_reason': None,
                 'error': None, 'factual_review': 'pending'}
        report['cases'].append(entry)
        try:
            # Labels and review rules stay local; only the raw state is sent to the model.
            response = request_completion(api_key, [
                {'role': 'system', 'content': SUMMARY_PROMPT},
                {'role': 'user', 'content': case['status']},
            ], with_tools=False)
            message, reason, counts = inspect_response(response, case['id'])
            entry['usage'] = counts
            entry['finish_reason'] = reason
            report['usage_totals'] = [a + b for a, b in zip(report['usage_totals'], counts)]
            entry['summary'] = display_summary(message, reason)
        except HTTPError as error:
            entry['error'] = f'HTTP {error.code}；未自动重试。'
            error.close()
        except (URLError, TimeoutError, socket.timeout):
            entry['error'] = '网络失败或超时；用量可能未知，未自动重试。'
        except SummaryError as error:
            entry['error'] = str(error)
        except (ValueError, OSError):
            entry['error'] = '响应无法解析；未自动重试。'
        if entry['error']:
            print(f"{case['id']}：{entry['error']}")
        print(f"累计已知用量：{report['usage_totals']}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='新建 JSON 结果文件，拒绝覆盖已有文件')
    args = parser.parse_args()
    try:
        cases = load_cases()
        api_key = read_api_key(args.key_file)
        # Reserve the destination before spending tokens; never overwrite an earlier run.
        with args.output.open('x', encoding='utf-8') as output:
            report = evaluate(api_key, cases)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write('\n')
    except (SummaryError, OSError, ValueError):
        print('错误：请检查评估集、仓库外密钥及新建输出文件路径。', file=sys.stderr)
        return 1
    print(f'结果已保存：{args.output}；事实评审待逐条核对。')
    return int(any(case['error'] for case in report['cases']))


if __name__ == '__main__':
    sys.exit(main())

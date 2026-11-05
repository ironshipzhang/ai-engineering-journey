"""E2c: one query encoding attempt followed by checked E2b retrieval."""

import argparse
import json
from pathlib import Path
import sys
import time

import dashscope_embedding as embedding
import json_retrieval as retrieval
import prepare_corpus as corpus


class OutputError(Exception):
    """Safe output diagnostic, with the in-memory result when available."""

    def __init__(self, message: str, result: dict):
        super().__init__(message)
        self.result = result


ERRORS = {
    "input_validation": ("input_validation", "问题须为非空、可编码且未超限的文本；top-k 须为正整数"),
    "artifact_check": ("artifact_check", "资料或向量产物缺失、损坏、过期或关联不符；未请求"),
    "configuration": ("configuration", "embedding 配置缺失或无效；未请求"),
    "encoding_compatibility": ("encoding_incompatible", "问题配置与文档编码契约不兼容；未请求"),
    "request": ("network_error", "问题编码请求失败或超时；未重试，用量可能未知"),
    "response_validation": ("response_validation", "问题编码响应无效；停止检索，保留已知用量"),
    "retrieval": ("retrieval_failed", "编码后资料复查或检索失败；保留问题向量和已知用量，无候选结果"),
}


def new_result(question, top_k) -> dict:
    return {
        "artifact_type": "e2c_live_query_retrieval", "format_version": 1,
        "status": "failed", "error": None,
        "question": question if isinstance(question, str) else None,
        "top_k": top_k if type(top_k) is int else None,
        "question_processing": "verbatim", "e1_build_id": None,
        "vector_artifact_sha256": None, "encoding": None,
        "http_attempts": 0, "requests": [],
        "usage": {"known_total_tokens": 0, "complete": True},
        "query": None, "retrieval": None, "elapsed_seconds": 0,
    }


def execute_retrieval(result: dict, question: str, top_k: int, prepared: Path, artifact_path: Path,
                      knowledge: Path, max_chars: int, config_path: Path, endpoint: str | None,
                      *, check_generation_config=None) -> None:
    """Shared in-memory stage; callers must reserve output first. Never rebuilds documents.

    E2d supplies a local generation-config check so both configurations fail before encoding.
    The optional check must not send requests or publish output.
    """
    started = time.monotonic()
    stage = "input_validation"
    try:
        embedding.validate_texts([question], "query")
        retrieval.require(type(top_k) is int and top_k > 0, "top-k 必须为正整数")

        stage = "artifact_check"
        artifact = retrieval.load_checked(artifact_path, prepared, knowledge, max_chars)
        result["e1_build_id"] = artifact["e1_build_id"]
        result["vector_artifact_sha256"] = artifact["content_sha256"]

        stage = "configuration"
        config = embedding.read_embedding_config(config_path, endpoint)
        if check_generation_config is not None:
            check_generation_config()
        stage = "encoding_compatibility"
        contract = retrieval.encoding_contract(config.public())
        result["encoding"] = contract
        retrieval.require(contract == artifact["encoding"], "编码契约不兼容")

        stage = "request"
        event = {"attempt": 1, "text_type": "query", "input_count": 1,
                 "status": "failed", "http_status": None, "request_id": None,
                 "usage_tokens": None, "elapsed_seconds": 0}
        result["requests"].append(event)
        result["http_attempts"] = 1
        result["usage"]["complete"] = False
        request_started = time.monotonic()
        try:
            # One call site, no loops/retries/fallback. The client also disables retries/redirects.
            reply = embedding.request_embeddings(config, [question], "query")
            event["http_status"] = reply.status
            payload = embedding.parse_payload(reply)
            event["usage_tokens"] = embedding.known_usage(payload)
            event["request_id"] = embedding.safe_request_id(payload, reply.request_id, config.api_key)
            if event["usage_tokens"] is not None:
                result["usage"] = {"known_total_tokens": event["usage_tokens"], "complete": True}
            if reply.status != 200:
                result["error"] = {"stage": stage, "category": "http_error",
                                   "message": "问题编码 HTTP 请求失败；未重试，不执行检索"}
                return
            stage = "response_validation"
            vector = embedding.validate_vectors(payload, 1, config.dimension)[0]
            result["query"] = {"text": question, **vector}
            event["status"] = "succeeded"
        finally:
            event["elapsed_seconds"] = round(time.monotonic() - request_started, 6)

        stage = "retrieval"
        result["retrieval"] = retrieval.search(
            artifact, result["query"], contract, top_k, prepared=prepared,
            knowledge=knowledge, max_chars=max_chars)
        result["status"] = "succeeded"
    except Exception:
        # Never persist raw exceptions: paths, parser errors or transport diagnostics may echo secrets.
        category, message = ERRORS[stage]
        result["error"] = {"stage": stage, "category": category, "message": message}
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 6)


def run_query(question: str, prepared: Path, artifact_path: Path, output: Path, *,
              top_k: int = 3, config_path: Path = embedding.DEFAULT_CONFIG_PATH,
              endpoint: str | None = None, knowledge: Path = corpus.DEFAULT_KNOWLEDGE,
              max_chars: int = corpus.DEFAULT_MAX_CHARS) -> dict:
    """Return the saved run record; output errors raise without automatic retry.

    A failed workflow still returns a saved record. Only status=succeeded means retrieval succeeded.
    This function can call the paid API after all prechecks; tests must mock the transport.
    """
    result = new_result(question, top_k)
    try:
        handle = output.open("x", encoding="utf-8")
    except OSError:
        raise OutputError("无法独占预留输出；检查新文件名和父目录。未读取密钥、未请求。", result) from None
    try:
        with handle:
            execute_retrieval(result, question, top_k, prepared, artifact_path, knowledge, max_chars, config_path, endpoint)
            # Escaping also lets invalid Unicode inputs be recorded on a failed precheck.
            json.dump(result, handle, ensure_ascii=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
    except (OSError, ValueError):
        raise OutputError("结果保存失败，可能留下空或部分文件；可能已经计费，请勿自动重跑。", result) from None
    return result


def show_summary(result: dict) -> None:
    question = result["question"]
    # Preserve valid text; escape rejected surrogate code points for terminal display.
    display = question.encode("utf-8", errors="backslashreplace").decode("utf-8") if question is not None else "（输入类型无效）"
    print(f"问题：{display}\nstatus={result['status']} HTTP尝试={result['http_attempts']} "
          f"已知tokens={result['usage']['known_total_tokens']} 用量完整={result['usage']['complete']}")
    if result["error"]:
        error = result["error"]
        print(f"{error['stage']} / {error['category']}：{error['message']}", file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="E2c 新问题检索（会联网计费，最多一次 query 请求）")
    parser.add_argument("--question", required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--config", type=Path, default=embedding.DEFAULT_CONFIG_PATH)
    parser.add_argument("--endpoint", help="用户确认的完整原生地址；不猜测地域、不写回配置")
    parser.add_argument("--knowledge", type=Path, default=corpus.DEFAULT_KNOWLEDGE)
    parser.add_argument("--max-chars", type=int, default=corpus.DEFAULT_MAX_CHARS)
    args = parser.parse_args(argv)
    try:
        result = run_query(args.question, args.prepared, args.artifact, args.output,
                           top_k=args.top_k, config_path=args.config, endpoint=args.endpoint,
                           knowledge=args.knowledge, max_chars=args.max_chars)
    except OutputError as exc:
        show_summary(exc.result)
        print(str(exc), file=sys.stderr)
        return 1
    show_summary(result)
    if result["retrieval"] is not None:
        retrieval.show_result(result["retrieval"])
    print("运行记录已保存；请结合 status 判断流程是否成功。")
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())

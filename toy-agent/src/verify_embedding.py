"""E2a controlled encoding validation, not a vector index or retrieval pipeline."""

import argparse
import json
from pathlib import Path
import sys
import time

import prepare_corpus as corpus
import dashscope_embedding as embedding


MAX_REQUESTS = 3
QUESTION = "数据库迁移失败后，重跑前需要检查什么？"


def new_result() -> dict:
    return {"artifact_type": "e2a_embedding_validation", "format_version": 1,
            "status": "failed", "error": None, "encoding": None, "e1_build_id": None,
            "http_attempts": 0, "usage": {"known_total_tokens": 0, "complete": True},
            "requests": [], "documents": [], "query": None, "elapsed_seconds": 0}


def run_validation(config_path: Path, prepared: Path, knowledge: Path, endpoint: str | None = None,
                   max_chars: int = corpus.DEFAULT_MAX_CHARS) -> dict:
    result = new_result()
    started = time.monotonic()
    stage = "corpus_check"
    try:
        manifest = corpus.check(knowledge, prepared, max_chars)
        reread_manifest, data = corpus.validate_artifact(prepared / "corpus")
        if manifest != reread_manifest:
            raise corpus.CorpusError("检查后构建发生变化")
        chunks = json.loads(data)
        result["e1_build_id"] = manifest["build_id"]
        stage = "configuration"
        config = embedding.read_embedding_config(config_path, endpoint)
        result["encoding"] = config.public()
        # Reserve one of the three attempts for the query even if the corpus has grown.
        selected = chunks[:embedding.BATCH_SIZE * (MAX_REQUESTS - 1)]
        result["selection"] = {"available_chunks": len(chunks), "selected_chunks": len(selected),
                               "limited_sample": len(selected) != len(chunks)}
        batches = [("document", selected[i:i + embedding.BATCH_SIZE], i)
                   for i in range(0, len(selected), embedding.BATCH_SIZE)]
        batches.append(("query", [{"text": QUESTION}], 0))
        stage = "input_validation"
        # Validate all local inputs before consuming any of the request budget.
        for text_type, items, _ in batches:
            embedding.validate_texts([item["text"] for item in items], text_type)
        for text_type, items, offset in batches:
            if result["http_attempts"] >= MAX_REQUESTS:
                raise embedding.EmbeddingError("request_limit", "达到 3 次请求尝试上限")
            event = {"attempt": result["http_attempts"] + 1, "text_type": text_type,
                     "input_count": len(items), "status": "failed", "usage_tokens": None,
                     "request_id": None, "http_status": None, "elapsed_seconds": 0,
                     "input_ids": [item["chunk_id"] for item in items] if text_type == "document" else ["question-001"]}
            result["http_attempts"] += 1
            result["requests"].append(event)
            request_started = time.monotonic()
            stage = "request"
            try:
                reply = embedding.request_embeddings(config, [item["text"] for item in items], text_type)
                payload = embedding.parse_payload(reply)
                event["http_status"] = reply.status
                event["usage_tokens"] = embedding.known_usage(payload)
                event["request_id"] = embedding.safe_request_id(payload, reply.request_id, config.api_key)
                if reply.status != 200:
                    raise embedding.EmbeddingError("http_error", "embedding HTTP 请求失败；停止后续请求，未重试")
                stage = "response_validation"
                vectors = embedding.validate_vectors(payload, len(items), config.dimension)
                if text_type == "document":
                    for local_index, (item, vector) in enumerate(zip(items, vectors)):
                        result["documents"].append({"chunk_id": item["chunk_id"], "document_id": item["document_id"],
                            "source_path": item["source_path"], "source": item["source"],
                            "input_row": offset + local_index, "attempt": event["attempt"], **vector})
                else:
                    result["query"] = {"id": "question-001", "text": QUESTION,
                                       "attempt": event["attempt"], **vectors[0]}
                event["status"] = "succeeded"
            finally:
                event["elapsed_seconds"] = round(time.monotonic() - request_started, 6)
                if event["usage_tokens"] is None:
                    result["usage"]["complete"] = False
                else:
                    result["usage"]["known_total_tokens"] += event["usage_tokens"]
        result["status"] = "succeeded"
    except corpus.CorpusError:
        result["error"] = {"stage": stage, "category": "corpus_check",
                           "message": "E1 资料过期、损坏或不可读；未进行编码，请先检查/重新准备"}
    except embedding.EmbeddingError as exc:
        result["error"] = {"stage": stage, "category": exc.category, "message": str(exc)}
    except Exception:
        # No exception text: transport/parser diagnostics may contain credentials or payloads.
        result["error"] = {"stage": stage, "category": "unexpected_error", "message": "本地编码验证异常；停止后续请求"}
    result["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="最多 3 次百炼请求的 E2a 编码验证（会联网计费）")
    parser.add_argument("--config", type=Path, default=embedding.DEFAULT_CONFIG_PATH)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, default=corpus.DEFAULT_KNOWLEDGE)
    parser.add_argument("--endpoint", help="已确认的完整原生 HTTP 地址；覆盖配置 endpoint，不修改配置文件")
    parser.add_argument("--max-chars", type=int, default=corpus.DEFAULT_MAX_CHARS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        # Exclusive reservation precedes reading credentials and all HTTP attempts.
        with args.output.open("x", encoding="utf-8") as handle:
            result = run_validation(args.config, args.prepared, args.knowledge, args.endpoint, args.max_chars)
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
    except (OSError, ValueError):
        print("输出预留或保存失败；拒绝覆盖，写入失败可能留下部分文件。请勿直接重复付费验证。", file=sys.stderr)
        return 1
    print(f"status={result['status']} HTTP尝试={result['http_attempts']} "
          f"文档向量={len(result['documents'])} 问题向量={int(result['query'] is not None)} "
          f"已知tokens={result['usage']['known_total_tokens']} 用量完整={result['usage']['complete']}")
    if result["error"]:
        print(result["error"]["message"], file=sys.stderr)
    print("结果是编码接入验证，不是完整向量索引，不代表检索质量通过。")
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())

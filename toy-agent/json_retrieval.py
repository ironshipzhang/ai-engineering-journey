"""E2b: offline JSON corpus import, freshness checks and exact cosine retrieval."""

import argparse
from copy import deepcopy
import math
from pathlib import Path
import sys

import prepare_corpus as corpus
from dashscope_embedding import DIMENSIONS, EmbeddingError, validate_endpoint, validate_vector

ARTIFACT_TYPE = "e2b_json_vectors"
FORMAT_VERSION = 1
CONTRACT_FIXED = {
    "provider": "dashscope", "model": "text-embedding-v4",
    "interface": "dashscope-native-sync", "output_type": "dense",
    "document_text_type": "document", "query_text_type": "query",
    "prefix": None, "instruct": None, "document_input": "E1 chunk.text verbatim",
    "normalization": "none",
}
CONTRACT_KEYS = set(CONTRACT_FIXED) | {"dimension", "endpoint"}
NOTICE = "仅为候选证据；余弦分数不是答案正确率，不代表证据足够。"


class RetrievalError(Exception):
    """Invalid import, artifact, encoding contract or query."""


def require(condition, message):
    if not condition:
        raise RetrievalError(message)


def encoding_contract(metadata: dict) -> dict:
    """Explicit semantic projection; runtime settings and usage are not compatibility keys."""
    require(isinstance(metadata, dict) and CONTRACT_KEYS <= metadata.keys(), "编码契约字段缺失")
    for key, expected in CONTRACT_FIXED.items():
        require(metadata[key] == expected, f"不支持的编码契约：{key}")
    dimension = metadata["dimension"]
    require(type(dimension) is int and dimension in DIMENSIONS, "编码维度无效")
    validate_endpoint(metadata["endpoint"])
    # Endpoint is retained AND conservatively compared; no cross-workspace equivalence guess.
    return {key: deepcopy(metadata[key]) for key in sorted(CONTRACT_KEYS)}


def read_json(path: Path):
    return corpus.decode_json(corpus.read_bytes(path), path.name)


def checked_corpus(prepared: Path, knowledge: Path, max_chars: int) -> tuple[dict, list]:
    manifest = corpus.check(knowledge, prepared, max_chars)
    reread, raw = corpus.validate_artifact(prepared / "corpus")
    require(manifest == reread, "检查期间 E1 构建发生变化")
    return manifest, corpus.decode_json(raw, "chunks.json")


def successful_record(record: dict) -> dict:
    require(isinstance(record, dict), "E2a 记录必须是对象")
    require(record.get("artifact_type") == "e2a_embedding_validation"
            and type(record.get("format_version")) is int and record["format_version"] == 1,
            "E2a 类型或格式版本无效")
    require(record.get("status") == "succeeded" and record.get("error") is None,
            "只接受成功的 E2a 记录")
    return encoding_contract(record.get("encoding"))


def validate_coverage(record: dict, manifest: dict, chunks: list) -> dict:
    contract = successful_record(record)
    require(record.get("e1_build_id") == manifest["build_id"], "E2a 与 E1 build_id 不匹配")
    selection = record.get("selection")
    require(isinstance(selection, dict) and selection.get("limited_sample") is False,
            "不接受缺失范围信息或 limited_sample")
    for key in ("available_chunks", "selected_chunks"):
        require(type(selection.get(key)) is int and selection[key] == len(chunks), "E2a 必须覆盖完整 corpus")
    rows = record.get("documents")
    require(isinstance(rows, list) and len(rows) == len(chunks), "文档向量数量不完整")
    expected = {chunk["chunk_id"]: (i, chunk) for i, chunk in enumerate(chunks)}
    seen = set()
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("chunk_id"), str), "文档向量记录无效")
        cid = row["chunk_id"]
        require(cid in expected and cid not in seen, "chunk_id 缺失、重复或额外")
        seen.add(cid)
        index, chunk = expected[cid]
        require(type(row.get("input_row")) is int and row["input_row"] == index, "E2a 输入行映射不符")
        for key in ("document_id", "source_path", "source"):
            require(corpus.json_bytes(row.get(key)) == corpus.json_bytes(chunk[key]), "E2a 原文来源映射不符")
        validate_vector(row.get("vector"), contract["dimension"])
    return contract


def seal(body: dict) -> dict:
    """SHA-256 covers canonical JSON of every field except this checksum itself."""
    return {**body, "content_sha256": corpus.sha256(corpus.json_bytes(body))}


def validate_artifact(artifact: dict) -> dict:
    require(isinstance(artifact, dict) and set(artifact) == {
        "artifact_type", "format_version", "e1_build_id", "encoding", "provenance",
        "documents", "content_sha256"}, "向量产物结构无效")
    require(artifact["artifact_type"] == ARTIFACT_TYPE
            and type(artifact["format_version"]) is int and artifact["format_version"] == FORMAT_VERSION,
            "向量产物类型或版本不支持")
    body = {k: v for k, v in artifact.items() if k != "content_sha256"}
    require(corpus.sha256(corpus.json_bytes(body)) == artifact["content_sha256"], "向量产物完整性检查失败")
    contract = encoding_contract(artifact["encoding"])
    require(set(artifact["encoding"]) == CONTRACT_KEYS, "编码契约混入未知字段")
    rows = artifact["documents"]
    require(isinstance(rows, list) and bool(rows), "向量产物没有文档")
    ids = set()
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("chunk_id"), str), "片段记录无效")
        require(row["chunk_id"] not in ids, "向量产物 chunk_id 重复")
        ids.add(row["chunk_id"])
        validate_vector(row.get("vector"), contract["dimension"])
    return contract


def check_artifact(artifact: dict, prepared: Path, knowledge: Path = corpus.DEFAULT_KNOWLEDGE,
                   max_chars: int = corpus.DEFAULT_MAX_CHARS) -> dict:
    validate_artifact(artifact)
    manifest, chunks = checked_corpus(prepared, knowledge, max_chars)
    require(artifact["e1_build_id"] == manifest["build_id"], "向量产物与当前 E1 构建不匹配；需要重建")
    rows = artifact["documents"]
    require(len(rows) == len(chunks), "向量产物未完整覆盖当前 E1")
    expected = {c["chunk_id"]: c for c in chunks}
    for row in rows:
        source = {key: value for key, value in row.items() if key != "vector"}
        require(corpus.json_bytes(source) == corpus.json_bytes(expected.get(row["chunk_id"])),
                "向量产物原文、来源或片段标识与 E1 不符")
    return artifact


def write_new(path: Path, value: dict) -> None:
    # Serialize completely first. A partial interrupted write cannot pass checksum/JSON validation.
    data = corpus.json_bytes(value)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except OSError:
        raise RetrievalError("输出已存在或写入失败；拒绝覆盖，可能留下不可用的部分文件") from None


def build(record_path: Path, prepared: Path, output: Path,
          knowledge: Path = corpus.DEFAULT_KNOWLEDGE, max_chars: int = corpus.DEFAULT_MAX_CHARS) -> dict:
    require(not output.exists() and not output.is_symlink(), "输出已存在，拒绝覆盖")
    manifest, chunks = checked_corpus(prepared, knowledge, max_chars)
    raw = corpus.read_bytes(record_path)
    record = corpus.decode_json(raw, "E2a")
    contract = validate_coverage(record, manifest, chunks)
    vectors = {row["chunk_id"]: row["vector"] for row in record["documents"]}
    artifact = seal({
        "artifact_type": ARTIFACT_TYPE, "format_version": FORMAT_VERSION,
        "e1_build_id": manifest["build_id"], "encoding": contract,
        "provenance": {"e2a_record_sha256": corpus.sha256(raw),
                       "endpoint_policy": "exact-match", "query_input": "E2a query.text verbatim"},
        "documents": [{**deepcopy(chunk), "vector": deepcopy(vectors[chunk["chunk_id"]])} for chunk in chunks],
    })
    # Recheck current inputs before writing; no filesystem-lock guarantee.
    check_artifact(artifact, prepared, knowledge, max_chars)
    write_new(output, artifact)
    return artifact


def load_checked(path: Path, prepared: Path, knowledge: Path = corpus.DEFAULT_KNOWLEDGE,
                 max_chars: int = corpus.DEFAULT_MAX_CHARS) -> dict:
    return check_artifact(read_json(path), prepared, knowledge, max_chars)


def import_query(record_path: Path) -> tuple[dict, dict]:
    record = read_json(record_path)
    contract = successful_record(record)
    query = record.get("query")
    require(isinstance(query, dict) and isinstance(query.get("text"), str)
            and bool(query["text"].strip()), "E2a 缺少已编码问题及真实文本")
    validate_vector(query.get("vector"), contract["dimension"])
    # No CLI text override: display the text that belongs to this saved vector.
    return {"text": query["text"], "vector": query["vector"]}, contract


def rank_vectors(documents: list, query_vector: list, dimension: int, top_k: int) -> list:
    """Pure exact cosine ranking. Divide before multiplication to avoid product overflow."""
    require(type(top_k) is int and top_k > 0, "top-k 必须是正整数")
    query_norm = validate_vector(query_vector, dimension)
    ranked = []
    for document in documents:
        vector = document["vector"]
        norm = validate_vector(vector, dimension)
        score = math.fsum((a / query_norm) * (b / norm) for a, b in zip(query_vector, vector))
        score = max(-1.0, min(1.0, score))  # Clamp floating-point roundoff only.
        ranked.append({**deepcopy({k: v for k, v in document.items() if k != "vector"}), "score": score})
    ranked.sort(key=lambda row: (-row["score"], row["chunk_id"]))
    return [{"rank": i + 1, **row} for i, row in enumerate(ranked[:top_k])]


def search(artifact: dict, query: dict, query_encoding: dict, top_k: int, *, prepared: Path,
           knowledge: Path = corpus.DEFAULT_KNOWLEDGE, max_chars: int = corpus.DEFAULT_MAX_CHARS) -> dict:
    """Public checked entry point; never reads config or performs network requests."""
    check_artifact(artifact, prepared, knowledge, max_chars)
    contract = encoding_contract(query_encoding)
    require(contract == artifact["encoding"], "问题与文档编码契约不兼容")
    require(isinstance(query, dict) and isinstance(query.get("text"), str)
            and bool(query["text"].strip()), "问题文本缺失")
    hits = rank_vectors(artifact["documents"], query.get("vector"), contract["dimension"], top_k)
    return {"artifact_type": "e2b_retrieval_result", "format_version": 1,
            "e1_build_id": artifact["e1_build_id"], "vector_artifact_sha256": artifact["content_sha256"],
            "encoding": contract, "question": query["text"], "metric": "cosine",
            "tie_break": "chunk_id ascending", "requested_top_k": top_k, "returned_count": len(hits),
            "evidence_status": "candidates_only", "notice": NOTICE, "hits": hits}


def show_result(result: dict) -> None:
    print(f"问题：{result['question']}\n返回 {result['returned_count']} 个候选片段。{NOTICE}")
    for hit in result["hits"]:
        source = hit["source"]
        print(f"\n#{hit['rank']} cosine={hit['score']:.8f} chunk_id={hit['chunk_id']}\n"
              f"{hit['title']} v{hit['version']} / " + " > ".join(s["title"] for s in hit["section"]))
        print(f"来源：{hit['source_path']}:{source['start_line']}-{source['end_line']}")
        print(hit["text"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="E2b 离线 JSON 构建/检查/检索；不读取密钥，不调用 API")
    subs = parser.add_subparsers(dest="operation", required=True)
    for name in ("build", "check", "search"):
        sub = subs.add_parser(name)
        sub.add_argument("--prepared", type=Path, required=True)
        sub.add_argument("--knowledge", type=Path, default=corpus.DEFAULT_KNOWLEDGE)
        sub.add_argument("--max-chars", type=int, default=corpus.DEFAULT_MAX_CHARS)
        if name == "build":
            sub.add_argument("--record", type=Path, required=True)
            sub.add_argument("--output", type=Path, required=True)
        else:
            sub.add_argument("--artifact", type=Path, required=True)
        if name == "search":
            sub.add_argument("--query-record", type=Path, required=True)
            sub.add_argument("--top-k", type=int, default=3)
            sub.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "build":
            artifact = build(args.record, args.prepared, args.output, args.knowledge, args.max_chars)
            print(f"构建完成：{len(artifact['documents'])} 个文档向量；sha256={artifact['content_sha256']}")
        elif args.operation == "check":
            artifact = load_checked(args.artifact, args.prepared, args.knowledge, args.max_chars)
            print(f"输入匹配、向量产物完整：{len(artifact['documents'])} 个片段；不代表检索质量通过。")
        else:
            artifact = read_json(args.artifact)
            query, contract = import_query(args.query_record)
            result = search(artifact, query, contract, args.top_k, prepared=args.prepared,
                            knowledge=args.knowledge, max_chars=args.max_chars)
            if args.output is not None:
                write_new(args.output, result)
            show_result(result)
    except corpus.RebuildRequired as exc:
        print(f"需要重建：{exc}", file=sys.stderr)
        return 2
    except (RetrievalError, corpus.CorpusError, EmbeddingError, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, (RetrievalError, corpus.CorpusError, EmbeddingError)) else "本地文件或数据格式无效"
        print(f"{args.operation} 失败：{message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

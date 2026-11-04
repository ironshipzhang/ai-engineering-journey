"""E1 only: deterministic Markdown source slices, manifests and offline checks."""

import argparse
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile

from markdown_it import MarkdownIt


DEFAULT_KNOWLEDGE = Path(__file__).resolve().parent.parent / "knowledge"
FORMAT_VERSION = 1
DEFAULT_MAX_CHARS = 1200
ARTIFACT_TYPE = "e1_prepared_corpus"


class CorpusError(Exception):
    """Invalid/unreadable input, incomplete artifact, or failed preparation."""


class RebuildRequired(CorpusError):
    """Valid artifact whose inputs or processing configuration have changed."""


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(path: Path) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise CorpusError(f"不是普通文件或文件缺失：{path.name}")
        return path.read_bytes()
    except OSError as exc:
        raise CorpusError(f"无法读取文件：{path.name}") from exc


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复 JSON 字段")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"非标准 JSON 常量：{value}")


def decode_json(data: bytes, label: str):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise CorpusError(f"无效 JSON：{label}") from exc


def processing_config(max_chars: int) -> dict:
    if type(max_chars) is not int or max_chars < 1:
        raise CorpusError("max-chars 必须是正整数")
    return {
        "rule_version": "heading-source-slices-v1",
        "component": "markdown-it-py", "component_version": version("markdown-it-py"),
        "mdurl_version": version("mdurl"), "preset": "commonmark",
        "heading_levels": [1, 2, 3, 4, 5, 6], "top_level_only": True,
        "max_chars": max_chars, "size_unit": "unicode_code_points",
        "overlap_chars": 0, "oversize": "fail", "text": "verbatim_markdown",
        "encoding": "utf-8", "newlines": "LF_or_CRLF",
    }


@dataclass
class Snapshot:
    inputs: dict
    texts: dict[str, str]


def load_snapshot(knowledge: Path) -> Snapshot:
    """The explicit catalog defines membership; unlisted files are not corpus inputs."""
    knowledge = knowledge.resolve()
    raw_catalog = read_bytes(knowledge / "catalog.json")
    catalog = decode_json(raw_catalog, "catalog.json")
    if not isinstance(catalog, list) or not catalog:
        raise CorpusError("目录必须是非空文档数组")
    ids, paths, documents, texts = set(), set(), [], {}
    for entry in catalog:
        if (not isinstance(entry, dict)
                or set(entry) != {"document_id", "title", "version", "path"}
                or any(not isinstance(v, str) or not v.strip() for v in entry.values())):
            raise CorpusError("文档目录字段无效")
        doc_id, relative = entry["document_id"], entry["path"]
        path = PurePosixPath(relative)
        if (not re.fullmatch(r"[a-z0-9][a-z0-9-]*", doc_id)
                or path.is_absolute() or path.suffix != ".md"
                or any(part in {"", ".", ".."} for part in relative.split("/"))
                or "\\" in relative):
            raise CorpusError("文档 ID 或相对 Markdown 路径无效")
        if doc_id in ids or relative in paths:
            raise CorpusError("文档 ID 或路径重复")
        source = knowledge.joinpath(*path.parts)
        if any(p.is_symlink() for p in [source, *source.parents] if p != knowledge
               and p.is_relative_to(knowledge)):
            raise CorpusError("来源路径不接受符号链接")
        data = read_bytes(source)
        try:
            text = data.decode("utf-8")
        except UnicodeError as exc:
            raise CorpusError(f"文档不是 UTF-8：{relative}") from exc
        if not text.strip() or "\x00" in text or "\r" in text.replace("\r\n", ""):
            raise CorpusError(f"文档为空或含不支持的 NUL/单独 CR：{relative}")
        ids.add(doc_id)
        paths.add(relative)
        texts[doc_id] = text
        documents.append({**entry, "sha256": sha256(data)})
    documents.sort(key=lambda d: d["document_id"])
    return Snapshot({"catalog_sha256": sha256(raw_catalog), "documents": documents}, texts)


def source_lines(text: str) -> list[str]:
    """Keep CRLF and Unicode separators intact; parser line maps use newline LF."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def build_chunks(snapshot: Snapshot, config: dict) -> list[dict]:
    parser = MarkdownIt(config["preset"])
    chunks = []
    for doc in snapshot.inputs["documents"]:
        text = snapshot.texts[doc["document_id"]]
        lines = source_lines(text)
        tokens = parser.parse(text)
        headings = []
        for i, token in enumerate(tokens):
            if token.type == "heading_open" and token.level == 0:
                headings.append((token.map[0], int(token.tag[1:]), tokens[i + 1].content))
        boundaries = sorted({0, len(lines), *(start for start, _, _ in headings)})
        heading_at = {start: (level, title) for start, level, title in headings}
        section = []
        for start, end in zip(boundaries, boundaries[1:]):
            if start in heading_at:
                level, title = heading_at[start]
                while section and section[-1]["level"] >= level:
                    section.pop()
                section.append({"level": level, "title": title, "line": start + 1})
            body = "".join(lines[start:end])
            if len(body) > config["max_chars"]:
                raise CorpusError(f"章节超过 {config['max_chars']} 字符：{doc['path']}:{start + 1}；"
                                  "请人工整理自包含章节，不截断或自动拆分")
            chunk = {
                "document_id": doc["document_id"], "title": doc["title"],
                "version": doc["version"], "source_path": doc["path"],
                "section": [dict(item) for item in section], "text": body,
                "source": {"start_line": start + 1, "end_line": end,
                           "line_convention": "1-based-inclusive", "document_sha256": doc["sha256"]},
            }
            chunk["chunk_id"] = sha256(json_bytes({"config": config, "chunk": chunk}))
            chunks.append(chunk)
    return chunks


def make_manifest(snapshot: Snapshot, config: dict, chunks: list[dict], data: bytes) -> dict:
    manifest = {
        "artifact_type": ARTIFACT_TYPE, "format_version": FORMAT_VERSION,
        "inputs": snapshot.inputs, "processing": config,
        "input_fingerprint": sha256(json_bytes({"inputs": snapshot.inputs, "processing": config})),
        "chunk_count": len(chunks),
        "chunks": {"file": "chunks.json", "sha256": sha256(data), "bytes": len(data)},
    }
    return {**manifest, "build_id": sha256(json_bytes(manifest))}


def validate_artifact(corpus: Path) -> tuple[dict, bytes]:
    """Checksums detect accidental corruption, not malicious coordinated rewriting."""
    manifest = decode_json(read_bytes(corpus / "manifest.json"), "manifest.json")
    expected_keys = {"artifact_type", "format_version", "inputs", "processing",
                     "input_fingerprint", "chunk_count", "chunks", "build_id"}
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise CorpusError("构建清单结构无效")
    unsigned = {k: v for k, v in manifest.items() if k != "build_id"}
    if (manifest["artifact_type"] != ARTIFACT_TYPE
            or type(manifest["format_version"]) is not int
            or manifest["format_version"] != FORMAT_VERSION
            or sha256(json_bytes(unsigned)) != manifest["build_id"]):
        raise CorpusError("构建清单类型、版本或完整性无效")
    descriptor = manifest["chunks"]
    if (not isinstance(descriptor, dict) or set(descriptor) != {"file", "sha256", "bytes"}
            or descriptor["file"] != "chunks.json"
            or type(descriptor["bytes"]) is not int
            or type(manifest["chunk_count"]) is not int or manifest["chunk_count"] < 1
            or not isinstance(manifest["inputs"], dict)
            or not isinstance(manifest["processing"], dict)):
        raise CorpusError("构建清单字段无效")
    fingerprint = sha256(json_bytes({"inputs": manifest["inputs"], "processing": manifest["processing"]}))
    if fingerprint != manifest["input_fingerprint"]:
        raise CorpusError("输入指纹损坏")
    data = read_bytes(corpus / "chunks.json")
    if len(data) != descriptor["bytes"] or sha256(data) != descriptor["sha256"]:
        raise CorpusError("片段产物完整性检查失败")
    chunks = decode_json(data, "chunks.json")
    if (not isinstance(chunks, list) or len(chunks) != manifest["chunk_count"]
            or any(not isinstance(c, dict) for c in chunks)):
        raise CorpusError("片段产物结构或数量无效")
    return manifest, data


def write_artifact(corpus: Path, snapshot: Snapshot, config: dict) -> dict:
    chunks = build_chunks(snapshot, config)
    data = json_bytes(chunks)
    manifest = make_manifest(snapshot, config, chunks, data)
    (corpus / "chunks.json").write_bytes(data)
    (corpus / "manifest.json").write_bytes(json_bytes(manifest))
    validate_artifact(corpus)
    return manifest


def prepare(knowledge: Path, output: Path, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    knowledge = knowledge.resolve()
    output = output.absolute()
    # Do not resolve the final component: a dangling output symlink must also fail.
    if output.exists() or output.is_symlink():
        raise CorpusError("输出目录已存在，拒绝覆盖；请使用新目录")
    if output.resolve().is_relative_to(knowledge):
        raise CorpusError("输出必须与知识资料目录分离")
    if not output.parent.is_dir():
        raise CorpusError("输出父目录不存在，请先创建父目录")
    config = processing_config(max_chars)
    snapshot = load_snapshot(knowledge)
    temporary = Path(tempfile.mkdtemp(prefix=".e1-prepare-", dir=output.parent))
    reserved = False
    try:
        manifest = write_artifact(temporary, snapshot, config)
        if load_snapshot(knowledge).inputs != snapshot.inputs:
            raise CorpusError("构建期间输入变化；未发布，请手动重新准备")
        # mkdir is exclusive, even if another writer creates an empty directory now.
        output.mkdir()
        reserved = True
        # Publish a complete inner directory in one same-filesystem rename.
        os.rename(temporary, output / "corpus")
        return manifest
    except OSError as exc:
        raise CorpusError("构建写入或发布失败；未发布可用构建") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if reserved and not (output / "corpus").exists():
            # Only our empty reservation; never recursively remove user output.
            output.rmdir()


def check(knowledge: Path, output: Path, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    manifest, data = validate_artifact(output / "corpus")
    snapshot = load_snapshot(knowledge)
    config = processing_config(max_chars)
    if snapshot.inputs != manifest["inputs"] or config != manifest["processing"]:
        raise RebuildRequired("资料、目录或处理配置变化，需要重建")
    # Small corpus: re-derive source slices to check source mappings and IDs too.
    if json_bytes(build_chunks(snapshot, config)) != data:
        raise CorpusError("片段内容、来源或标识与确定性构建结果不符")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="E1 prepared corpus；不执行 embedding 或模型调用")
    parser.add_argument("operation", choices=["prepare", "check"])
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--output", type=Path, required=True, help="新构建目录或待检查构建目录")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args(argv)
    try:
        operation = prepare if args.operation == "prepare" else check
        manifest = operation(args.knowledge, args.output, args.max_chars)
    except RebuildRequired as exc:
        print(f"需要重建：{exc}", file=sys.stderr)
        return 2
    except (CorpusError, OSError) as exc:
        message = str(exc) if isinstance(exc, CorpusError) else "本地文件操作失败"
        print(f"{args.operation} 失败：{message}", file=sys.stderr)
        return 1
    label = "准备完成" if args.operation == "prepare" else "输入匹配、产物完整"
    print(f"{label}：{len(manifest['inputs']['documents'])} 份文档，"
          f"{manifest['chunk_count']} 个片段；build_id={manifest['build_id']}")
    print("这是 E1 prepared corpus；不表示内容正确、检索有效或 RAG 已完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

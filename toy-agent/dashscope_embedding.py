"""Single-provider DashScope native synchronous embeddings; no retries or SDK."""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import tomllib
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config/local.toml"
API_PATH = "/api/v1/services/embeddings/text-embedding/text-embedding"
DIMENSIONS = {64, 128, 256, 512, 768, 1024, 1536, 2048}
BATCH_SIZE = 10
TIMEOUT_SECONDS = 30
# Conservative local admission policy, NOT a token count or tokenizer guarantee.
MAX_TEXT_BYTES = 8192
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class EmbeddingError(Exception):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class EmbeddingConfig:
    endpoint: str
    api_key: str = field(repr=False)
    dimension: int = 1024
    provider: str = "dashscope"
    model: str = "text-embedding-v4"

    def public(self) -> dict:
        return {"provider": self.provider, "model": self.model, "endpoint": self.endpoint,
                "dimension": self.dimension, "interface": "dashscope-native-sync",
                "output_type": "dense", "document_text_type": "document",
                "query_text_type": "query", "prefix": None, "instruct": None,
                "normalization": "none", "document_input": "E1 chunk.text verbatim",
                "batch_size": BATCH_SIZE, "timeout_seconds": TIMEOUT_SECONDS,
                "max_text_utf8_bytes": MAX_TEXT_BYTES, "exact_token_precheck": False,
                "retries": 0, "follow_redirects": False}


def validate_endpoint(endpoint) -> str:
    if not isinstance(endpoint, str) or any(c.isspace() for c in endpoint):
        raise EmbeddingError("configuration", "embedding.endpoint 必须是无空白的完整 HTTPS 地址")
    try:
        url = urlsplit(endpoint)
        host = url.hostname or ""
        valid_host = re.fullmatch(
            r"ws-[a-z0-9]+\.(?:cn-beijing|ap-southeast-1|cn-hongkong)\.maas\.aliyuncs\.com", host)
        if (url.scheme != "https" or not valid_host or url.netloc != host
                or url.path != API_PATH or url.query or url.fragment):
            raise ValueError()
    except ValueError:
        raise EmbeddingError("configuration", "需要已确认的百炼业务空间原生 embedding endpoint；不自动猜测或切换地址") from None
    return endpoint


def read_embedding_config(path: Path = DEFAULT_CONFIG_PATH, endpoint: str | None = None) -> EmbeddingConfig:
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, ValueError, UnicodeError):
        raise EmbeddingError("configuration", "无法读取有效的 UTF-8 TOML 配置；尚未请求") from None
    table = config.get("embedding")
    if not isinstance(table, dict):
        raise EmbeddingError("configuration", "缺少 embedding 配置表；尚未请求")
    if table.get("provider") != "dashscope" or table.get("model") != "text-embedding-v4":
        raise EmbeddingError("configuration", "本入口仅支持 dashscope / text-embedding-v4")
    key = table.get("api_key")
    if (not isinstance(key, str) or not key or not key.isascii()
            or any(not c.isprintable() or c.isspace() for c in key)
            or key.upper().startswith(("YOUR_", "REPLACE_"))
            or key.lower() in {"sk-xxx", "your-api-key", "<api_key>", "<redacted>"}):
        raise EmbeddingError("configuration", "embedding.api_key 缺失、无效或仍为占位符；尚未请求")
    selected = validate_endpoint(endpoint if endpoint is not None else table.get("endpoint"))
    if key in selected:
        raise EmbeddingError("configuration", "endpoint 不得包含认证信息")
    dimension = table.get("dimension", 1024)
    if type(dimension) is not int or dimension not in DIMENSIONS:
        raise EmbeddingError("configuration", "embedding.dimension 不是 v4 支持的维度")
    return EmbeddingConfig(selected, key, dimension)


def validate_texts(texts: list[str], text_type: str) -> None:
    if text_type not in {"query", "document"}:
        raise EmbeddingError("input_validation", "文本类型只能是 document 或 query")
    if not isinstance(texts, list) or not 1 <= len(texts) <= BATCH_SIZE:
        raise EmbeddingError("input_validation", "每批必须包含 1–10 条文本")
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("input_validation", "不接受空文本")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeError:
            raise EmbeddingError("input_validation", "文本无法编码为 UTF-8") from None
        if size > MAX_TEXT_BYTES:
            raise EmbeddingError("input_validation", "文本超过本地 8192 UTF-8 字节保护上限；不截断")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class Reply:
    status: int
    body: bytes = field(repr=False)
    request_id: str | None = None


def request_embeddings(config: EmbeddingConfig, texts: list[str], text_type: str) -> Reply:
    validate_texts(texts, text_type)
    payload = {"model": config.model, "input": {"texts": texts},
               "parameters": {"dimension": config.dimension, "text_type": text_type, "output_type": "dense"}}
    request = Request(config.endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": "Bearer " + config.api_key, "Content-Type": "application/json"},
                      method="POST")
    try:
        # urllib has no automatic request retry; redirect handler prevents extra attempts/key forwarding.
        try:
            response = build_opener(NoRedirect()).open(request, timeout=TIMEOUT_SECONDS)
        except HTTPError as error:
            response = error
        with response:
            return Reply(response.code, response.read(MAX_RESPONSE_BYTES + 1),
                         response.headers.get("X-Request-Id") or response.headers.get("X-Dashscope-Request-Id"))
    except (OSError, URLError, ValueError):
        raise EmbeddingError("network_error", "embedding 网络请求失败或超时；未重试，计费用量可能未知") from None


def parse_payload(reply: Reply):
    if len(reply.body) > MAX_RESPONSE_BYTES:
        return None
    try:
        return json.loads(reply.body)
    except (ValueError, UnicodeError):
        return None


def known_usage(payload) -> int | None:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    value = usage.get("total_tokens") if isinstance(usage, dict) else None
    return value if type(value) is int and value >= 0 else None


def safe_request_id(payload, header, key: str) -> str | None:
    candidate = payload.get("request_id", header) if isinstance(payload, dict) else header
    if (isinstance(candidate, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", candidate)
            and key not in candidate):
        return candidate
    return None


def validate_vector(vector, dimension: int) -> float:
    """Shared offline numeric validation; returns a freshly computed norm."""
    if not isinstance(vector, list) or len(vector) != dimension:
        raise EmbeddingError("response_validation", "返回向量维度不符")
    try:
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
            raise ValueError()
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise ValueError()
    except (ValueError, OverflowError):
        raise EmbeddingError("response_validation", "向量含非法数值或范数无效") from None
    return norm


def validate_vectors(payload, count: int, dimension: int) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("code") or payload.get("error"):
        raise EmbeddingError("response_validation", "embedding 响应不是成功结果")
    output = payload.get("output")
    rows = output.get("embeddings") if isinstance(output, dict) else None
    if not isinstance(rows, list) or len(rows) != count:
        raise EmbeddingError("response_validation", "返回向量数量与输入不一致")
    mapped = {}
    for row in rows:
        if not isinstance(row, dict):
            raise EmbeddingError("response_validation", "向量记录格式无效")
        # Native HTTP deployments use index; older native deployments use text_index.
        keys = [key for key in ("index", "text_index") if key in row]
        if len(keys) != 1:
            raise EmbeddingError("response_validation", "缺少或存在歧义的输入索引")
        index = row[keys[0]]
        if type(index) is not int or index not in range(count) or index in mapped:
            raise EmbeddingError("response_validation", "输入索引缺失、重复或越界")
        vector = row.get("embedding")
        norm = validate_vector(vector, dimension)
        mapped[index] = {"response_index": index, "response_index_field": keys[0],
                         "vector": vector, "norm": norm}
    return [mapped[i] for i in range(count)]

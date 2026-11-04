# E2b 交接：JSON 向量产物与独立检索

日期：2026-11-04。实现完成，待主会话复核。需求：[E2b 任务书](e2b-json-retrieval.md)。本轮全程离线，没有读取真实密钥、调用模型 API、重新编码、生成回答或接入 Agent。未提交/推送。

## 这次新增了哪一层

E1 保存“文档如何变成片段”；E2a 保存“片段如何完成一次远程编码验证”。E2b 把成功的文档向量与 E1 的正文、标题、章节、来源组合成可重复加载的检索产物，并提供检索入口：

```text
原始资料 + E1 构建 ──check──┐
                           ├→ build → 新的向量 JSON
成功全量 E2a 文档向量 ─────┘

向量 JSON + 当前资料/E1 ──完整性与过期检查──┐
                                           ├→ 精确余弦 → top-k 原文/来源
已有问题向量 + 编码契约 ──兼容性检查───────┘
```

生成模型尚未参与。检索只找到候选证据；没有自动判断证据足够，也没有把分数当作答案正确率。

## 代码与产物

- 新增 `toy-agent/json_retrieval.py`：build/check/search CLI；build、load_checked、search 为可调用接口，返回数据与 CLI 展示分离。search 接收内存产物、问题对象、编码元数据和 top-k，并在每次调用时核对当前 E1。
- 调整 `toy-agent/dashscope_embedding.py`：仅将既有单向量维度/有限值/非零范数校验抽成 validate_vector，E2a 原有响应校验和 E2b 共同使用。无传输、配置或编码行为变更。
- 新增 `toy-agent/test_json_retrieval.py`：16 项离线测试，不依赖个人 test-output；临时创建 E1、模拟 E2a，明确禁止配置读取和 API 调用。
- 无新依赖，不修改 pyproject.toml/uv.lock。

实际输出均在 Git 忽略目录：

| 文件 | 内容 |
| --- | --- |
| `test-output/e2b-vectors-20261104-001.json` | 15 个 1024 维文档向量、E1 原文与来源、编码契约及完整性摘要 |
| `test-output/e2b-top3-20261104-001.json` | 已有问题的 top-3 排名、余弦、原文、来源和检索配置 |

向量产物摘要为 `552457b9bc0b6610390f7ddb3b3d53966a9d6151c5855965f03bfd3a63ddfe00`。E1 build_id 仍为 `d6fe4d2da557d44234c820edd504de94d7f9195c6cb02ca595e0d2f565415912`。

## JSON 格式与可信边界

向量产物字段：

- artifact_type=`e2b_json_vectors`，format_version=1。
- e1_build_id：绑定来源构建。
- encoding：明确的兼容字段。
- provenance：导入 E2a 文件的字节 SHA-256、endpoint 比较策略和 E2a 问题原文处理说明。
- documents：每项保留完整 E1 chunk 字段及 vector。文本及来源从 E1 获取；通过 chunk_id 关联 E2a 向量，不假设记录列表顺序。
- content_sha256：覆盖除此字段自身之外的所有内容。采用 E1 json_bytes：UTF-8、sort_keys、indent=2、末尾换行、禁止 NaN。对象键排序和空白重排不影响语义摘要，文档数组顺序和数值表达改变会影响摘要。

build 不只信任 succeeded：重新检查全量标记及数量、唯一完整 ID 集合、全局 input_row、document_id/source_path/source、build_id 和实际向量。已有 norm 不参与计算，usage 缺失不影响向量可用性。这里只导入文档数据，不要求把 E2a 的运行用量和请求日志搬进检索产物。

check/search 校验摘要、向量数值与维度，再执行 E1 check，核对当前构建与每条完整正文/来源。即使为错误正文重新计算了摘要，正文仍不能通过与 E1 的逐条比对。产物可脱离 E2a 文档记录使用，但检查仍需要当前 E1 和原始资料；CLI 复用问题时仍需保存该问题的 E2a 记录。

SHA-256 是损坏检测，不是签名。E2a 记录本身无签名，无法证明一个合法数值向量确实由百炼为某段文本生成，也无法识别协调改写后的语义造假；本轮信任本地既有编码记录。没有模型内部版本证明。

## 编码兼容策略

| 字段 | 当前要求 |
| --- | --- |
| provider / model | dashscope / text-embedding-v4；不猜测跨模型兼容 |
| dimension | 已有 v4 支持维度之一，问题与文档一致；本次 1024 |
| interface / output_type | dashscope-native-sync / dense |
| document_text_type / query_text_type | document / query |
| prefix / instruct | 均为 null |
| document_input | E1 chunk.text verbatim |
| normalization | none，保存原始向量，不预归一化 |
| endpoint | 保留完整非敏感地址，当前保守要求完全一致 |

问题输入沿用 E2a 格式 1 的 query.text 原文，无额外清洗或前缀。CLI 没有 `--question` 覆盖参数；输出直接展示已存问题文本，不能把这个固定向量冒充任意新问题。函数调用者负责提供真正匹配的问题文本/向量，数值校验本身无法证明两者语义绑定。

运行时字段（批量、超时、重试、用量等）不属于编码兼容契约，不比较整个 public() 字典。endpoint 策略可能拒绝实际上兼容的不同空间，这是当前明确的保守选择。相同模型名下供应商未声明的内部更新无法被本地契约检测。

## 可执行命令

在仓库根目录执行。新建输出名字不能已存在；以下 `manual-001` 是供用户执行的新名字，本次实际演示使用上文带日期路径。

```bash
toy-agent/.venv/bin/python toy-agent/json_retrieval.py build \
  --prepared test-output/e1-20261028/build-001 \
  --record test-output/e2a-20261029-001.json \
  --output test-output/e2b-vectors-manual-001.json

toy-agent/.venv/bin/python toy-agent/json_retrieval.py check \
  --prepared test-output/e1-20261028/build-001 \
  --artifact test-output/e2b-vectors-manual-001.json

toy-agent/.venv/bin/python toy-agent/json_retrieval.py search \
  --prepared test-output/e1-20261028/build-001 \
  --artifact test-output/e2b-vectors-manual-001.json \
  --query-record test-output/e2a-20261029-001.json \
  --top-k 3 --output test-output/e2b-top3-manual-001.json

toy-agent/.venv/bin/python -m unittest discover -s toy-agent -p 'test_*.py'
```

search 可不带 --output，仅输出终端。check 不是 search 的手动前置步骤，search 自带检查。--knowledge/--max-chars 默认沿用 E1，须与当前构建一致。退出码：0 操作成功；2 E1 资料/切块配置已变，需要重建；1 其他失败，包括向量产物与 E1 build_id 不一致或编码不兼容。无自动重建、编码或继续用旧资料。

## 真实向量的离线观察

复用 2026-10-29 已有的 15 个文档和 1 个问题向量，未新增模型请求。build、check、search 均退出 0。问题：**数据库迁移失败后，重跑前需要检查什么？**

| 排名 | 余弦 | 章节 | 来源 |
| --- | ---: | --- | --- |
| 1 | 0.84009560 | 失败后重跑前的检查 | migration-guide.md:11–20 |
| 2 | 0.72438740 | 恢复与重新验证 | migration-guide.md:21–26 |
| 3 | 0.71418215 | 数据库相关检查 | post-release-checklist.md:17–22 |

人工逐条对照原文：第一名直接包含执行日志、迁移版本记录、是否部分执行，以及不能直接重跑的前提和例外，符合问题。第二名介绍恢复限制和重新验证，具有补充关联，但不是直接列出重跑前检查项。第三名讨论发布后的数据库检查、部分执行排查，主题相关，但原文明示不能替代发布前迁移验证，不能把它当作同等直接的回答依据。

这说明本例排序合理，也显示 top-k 返回的片段适用范围不同。未验证无答案问题、混淆问题、多问题召回或引用回答；没有据此设置相似度阈值。更不代表完整 RAG 已通过验收。

## 测试与简化边界

开工基线 103 项通过；实现后完整 **119 项通过（新增 16 项）**。新增覆盖全量确定性导入和逐条来源还原、失败/limited_sample/数量/ID/输入行/来源/build_id 拒绝、乱序按 ID 合并、非法向量与编码、未知用量、摘要覆盖、重算摘要后错误原文拒绝、资料/切块配置过期、损坏/缺失产物、查询兼容、原问题展示、手工余弦负分/同分/top-k、覆盖拒绝及模拟中途写入失败。E2a 的既有校验测试也通过。

- 使用 math.hypot 重算范数，按归一化分量的乘积求余弦，不修改存储向量；math.fsum 累加，浮点越界夹至 [-1,1]。手工小向量覆盖非单位输入，不依赖供应商的近似单位范数。
- top-k 必须正整数，超过文档数返回全部，结果记录请求数量与实际数量；同分按 chunk_id 升序。
- 当前全量读取 JSON、逐向量扫描、每次重新 E1 检查。没有数据库、ANN、reranker、混合检索、自动更新、增量编码或活动版本指针。
- 输出先序列化再独占创建，不覆盖；没有事务发布/fsync/锁。写入中断可能留下不完整文件，后续 JSON/摘要检查拒绝；模拟验证了失败，没有制造真实磁盘故障。
- 输入复查只保证读取快照，无法排除之后的外部修改；按项目约定顺序操作。供应商模型漂移、恶意协调改写和大规模性能未验证。

## 修改列表与复核交接

开工已有 `docs/PROGRESS.md` 修改和未跟踪的 `docs/tasks/e2b-json-retrieval.md`，保留原内容并标注状态演进。

本轮新增 json_retrieval.py、test_json_retrieval.py、本交接；修改 dashscope_embedding.py（仅共享校验抽取），更新 PROGRESS、SETUP、ARCHITECTURE、TOY_AGENT_ROADMAP、DECISIONS。未修改 E1 资料/代码、真实配置、依赖、Agent 协议或历史评估。运行产物被忽略，不提交到仓库。

请主会话复核 JSON 契约、完整导入、来源关联、显式编码字段及 endpoint 保守策略、余弦排序与失败行为，并独立离线回归。新问题编码、生成回答、更多效果验证及 E3 需要后续任务，不自动进入。当前无需要联网补采的受阻项。


## 主会话复核（2026-11-04）

结论：E2b 验收通过，无必要代码修正。独立完整离线回归 119 项通过；检查导入的 15 个向量逐条等于 E2a 数据，全部原文/来源与 E1 及来源文件行号切片一致。重新调用带检查的 search，结果与保存的 top-3 JSON 完全一致；另用直接点积与范数公式独立复算全部 15 个分数，前三排序及分数在浮点误差内一致。产物摘要与实现会话记录相符。未读取真实密钥、调用 API 或重新编码。

完整性、全量关联、来源/过期检查、显式编码兼容、非单位向量余弦、top-k 和输出拒绝覆盖符合任务书。校验和不认证向量语义，单问题观察不证明多问题检索效果；既有简化边界继续保留。

下一项 E2c 仅准备任务书：新问题编码后复用 E2b 检索，先完成离线验证；真实两问题、最多两次请求方案待用户确认。当前主会话没有实施 E2c、提交或推送。

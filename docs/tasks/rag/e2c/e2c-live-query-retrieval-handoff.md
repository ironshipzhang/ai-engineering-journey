# E2c 实施交接：新问题编码与独立检索

日期：2026-11-05。**离线实现完成，待主会话复核；真实验证未授权、未执行。** 需求依据：[E2c 任务书](e2c-live-query-retrieval.md)。未读取真实密钥、调用 API、重新编码文档、提交或推送。

## 本轮新增什么

E2b 能拿一个已有问题向量检索资料。E2c 新增的编排负责接收新问题，检查本地资料与配置，然后只编码这个问题，再交给 E2b 查资料。

```text
用户新问题 + 既有文档向量
  → 预留新输出文件
  → 问题/参数检查 → E1/E2b 产物检查 → 编码配置兼容检查
  → 单次百炼 query 编码
  → 取用量、校验响应向量
  → E2b search 再检查 E1 并返回候选
  → 保存单个运行 JSON，终端展示原文/分数/来源
```

本轮通过模拟传输验证这条程序链路，没有真实新问题的向量或检索效果结论。不是回答生成：程序只展示候选原文，没有 DeepSeek、Agent 工具或“证据足够”的自动判定。

## 文件与复用边界

新增：

- `toy-agent/src/live_query_retrieval.py`：可调用 run_query、内部流程编排、薄 CLI。
- `toy-agent/tests/test_live_query_retrieval.py`：18 项离线行为测试。
- 本交接。

直接复用既有能力，旧源码与测试未修改：

| 能力 | 复用位置 |
| --- | --- |
| 配置、文本长度、单次 HTTP、响应/向量校验、usage/request_id | dashscope_embedding.py |
| 资料/文档向量检查、编码契约、检索及候选展示 | json_retrieval.py |
| 原文与 prepared corpus 检查 | 由 E2b 调用 prepare_corpus.py |

没有新增依赖，不改配置、知识资料、文档向量、旧评估或 Agent 协议。使用现有客户端契约，本次没有更换模型、接口或参数；真实调用前的官方地域/限制/价格核实按任务书保留到获得授权后，不把旧费率或旧余额报告作为当前事实。

## 函数与调用顺序

公共函数：

```python
run_query(question, prepared, artifact_path, output,
          top_k=3, config_path=..., endpoint=None,
          knowledge=..., max_chars=1200) -> dict
```

函数本身包含输出预留，直接调用也不会绕过这一约束。正常流程失败仍返回已保存的结构化记录；预留或保存失败抛 OutputError，含安全说明和可用的内存结果。不要因函数返回记录就认为检索成功，要检查 status。

1. 用 x 模式独占创建必填输出文件，父目录不自动创建。失败时没有配置读取或请求。
2. 问题逐字使用，不 strip、不加前缀、不截断；拒绝空白、非字符串、无法 UTF-8 编码以及超过既有 8192 字节保护上限的输入。top-k 必须是正整数，拒绝 bool。
3. load_checked 校验向量摘要、完整来源、当前 E1 原文及 build_id。失败先于配置读取。
4. read_embedding_config 读取配置用于认证；只用 embedding 表，不调用生成模型、不写回配置。--endpoint 仅覆盖本次地址。
5. 从 config.public() 显式提取 E2b encoding_contract，与文档产物契约比较，包括 endpoint 完全一致。超时/批量/用量不参与兼容；不猜测其他地域。
6. 只有一个 request_embeddings 调用点，输入 `[question]`、text_type=query；最多一次尝试，无重试、健康检查或 fallback。
7. 先记录有效用量与合法请求 ID，再检查 HTTP/响应索引/数量/维度/数值/范数。无效响应不进入检索。
8. 调用 E2b search，不复制排序算法、不直接调用 rank_vectors。请求期间原文变化会在这次复查被拒绝，保留问题向量及用量但不返回旧候选。

继承每次网络操作 30 秒超时，不是流程总时限。运行中的文档产物是请求前加载的内存快照；search 复查其完整性与当前 E1，没有磁盘活动索引指针或并发文件锁。

## 运行记录与失败语义

artifact_type=`e2c_live_query_retrieval`，format_version=1。字段包括：

| 字段 | 含义 |
| --- | --- |
| status / error | 流程成功/失败；固定安全阶段、类别、说明 |
| question / top_k / question_processing | 原样问题和请求参数；处理方式 verbatim |
| e1_build_id / vector_artifact_sha256 | 已通过前检的来源构建及文档向量摘要 |
| encoding | 实际问题编码的非敏感契约；不含密钥 |
| http_attempts / requests | 最多一次尝试、HTTP 状态、编码状态、请求 ID、用量及耗时 |
| usage | 已知 total_tokens 合计与 complete 标记 |
| query | 校验通过的问题文本、向量、响应索引和重算范数；否则 null |
| retrieval | E2b 结构化候选结果；失败时 null |
| elapsed_seconds | 流程执行耗时，不含最终文件保存耗时 |

requests 的 succeeded 表示编码响应已校验，不代表后续检索一定成功。结果不复制全量文档向量，候选仍标记 candidates_only。

| 情况 | 请求次数 | 用量 | 向量/候选 |
| --- | ---: | --- | --- |
| 输入/资料/配置/兼容前检失败 | 0 | 0，complete=true | 无 |
| 请求失败且无有效 usage | 1 | 已知可为 0，complete=false；不能按零计费 | 无 |
| HTTP/向量失败但 usage 有效 | 1 | 保留有效用量 | 无候选，坏向量不保存 |
| 向量合法、usage 缺失 | 1 | complete=false | 可以检索成功 |
| 编码成功、资料复查失败 | 1 | 保留已知或未知状态 | 保留问题向量，无候选 |

不保存原始异常、认证头或错误正文；按阶段提供固定安全诊断，定位靠阶段、HTTP 状态、合法请求 ID 及资料检查命令。JSON 使用 Unicode 转义，因此拒绝的 surrogate 输入也能留下失败记录；解析后文本与原输入一致，正常中文在 CLI 直接展示，不刷完整向量。

结果在结束时写入并刷新/关闭，普通文件保存不是事务。保存失败由 OutputError/CLI 非零退出报告，与流程 status 分开；写入/刷新/关闭失败可能留下空、部分甚至已完整写出的文件，不能据文件存在认定保存成功。无 fsync、断点恢复或自动付费重跑。

## 可执行命令

仓库根目录，离线回归与 CLI 帮助可立即运行：

```bash
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'
toy-agent/.venv/bin/python toy-agent/src/live_query_retrieval.py --help
```

以下是**将来获得用户明确确认后**的付费单问题命令，本轮未执行：

```bash
mkdir -p test-output/rag/e2c
toy-agent/.venv/bin/python toy-agent/src/live_query_retrieval.py \
  --question '发现迁移部分执行或执行状态无法确认时，可以直接重跑原脚本吗？' \
  --prepared test-output/rag/e1/20261028/build-001 \
  --artifact test-output/rag/e2b/e2b-vectors-20261104-001.json \
  --endpoint https://ws-kicad9ful35400g7.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding \
  --top-k 3 --output test-output/rag/e2c/related-001.json
```

--config 默认根目录 config/local.toml；--output 必填且必须全新。CLI 退出 0 表示流程和保存均成功，流程/文件失败退出 1，argparse 参数解析失败退出 2。终端显示问题、状态、请求/用量、排名、分数和来源原文。

真实验证提案仍是任务书的两条问题、最多 2 次尝试，每条最多 256 UTF-8 字节、1024 维；首个请求/响应/保存失败就停止整个验证。程序只保证每次运行最多一次，不提供跨人工多次运行的总预算管理。第二条为范围外的差旅住宿问题；没有因为 task 或本文列出命令就获得执行授权。未来执行前核实官方资料及用户服务可用信息，未查询余额，不估算本轮不存在的真实费用。

## 离线结果与实际本地产物

- 开工工作区干净，基线 119 项通过；实现后完整 **137 项通过（新增 18 项）**。
- 新测试用临时 E1/E2b、假 TOML、模拟响应，禁止真实网络。覆盖输出先于配置、原样文本/单次 query、与 E2b search 一致、不执行 prepare/build、不修改文档向量、资料/产物/配置/兼容前检零请求、空/超长/非法 Unicode/top-k、HTTP/超时/非法响应/索引/向量、usage 已知/未知、编码期间原文变化、CLI 安全展示、写入/刷新/关闭失败。
- 成功链路只在模拟传输下验证，模拟向量不代表百炼语义效果。没有把旧问题向量冒充新问题结果。
- CLI --help 正常。另实际运行空问题前检，指定一个不会被读取的非真实配置路径，退出 1，保存 `test-output/rag/e2c/offline-input-rejected-20261105-001.json`。记录为 input_validation 失败、0 次 HTTP、0 tokens、complete=true、query/retrieval=null；这只是离线失败演示。
- 真实验证未执行，新问题向量质量、相关/范围外问题的实际排序、当前认证/余额/价格及供应商真实失败均未验证。磁盘失败为模拟，没有制造真实磁盘故障。

## 修改与主会话复核

新增源码、测试、本交接；更新 PROGRESS、SETUP、ARCHITECTURE、TOY_AGENT_ROADMAP 和任务索引。没有新增重要选型，复用既有契约，因此未另增 DECISIONS 条目。输出位于忽略的 test-output/rag/e2c/。旧源码、测试、资料、配置、依赖和历史记录未改；未提交/推送。

请主会话独立离线复核，重点核对请求前后两次检查、编码契约在请求前比较、单次请求上限、用量先于向量校验保存，以及流程/文件保存失败的区别。复核不调用 API。两问题真实验证仍待用户明确确认，不自动推进生成回答或 E3。


## 主会话离线复核（2026-11-05）

结论：E2c 离线实现复核通过，未发现必须修正的代码问题。主会话独立运行完整离线回归，137 项全部通过；检查新源码、18 项新测试及相关文档，确认输出先预留、请求前校验资料/产物/编码契约、单次 query 请求、usage 先于向量校验记录，以及 E2b 请求后复查与安全保存行为符合任务书。未修改源码或测试，保留已有工作区修改。

本地 offline-input-rejected-20261105-001.json 与报告一致：input_validation 失败，0 次 HTTP 尝试，已知 tokens=0 且 complete=true，query/retrieval 均为空。成功编码与检索仍仅由模拟传输验证，不能写成供应商真实验证通过。

本轮未读取真实密钥、调用 API、重新编码文档、提交、推送或推进后续阶段。真实验证仍待用户明确确认：相关与范围外各一条问题、各最多一次请求，合计最多两次尝试；任何运行失败即停止，不重试、不继续下一问题。待确认后再核实官方接口/地域/费率并执行，当前没有生成真实结果或费用。

## 用户授权后的真实验证（2026-11-05）

本节是离线实现与主会话复核之后的新记录；上文“未授权/未执行”描述当时状态，保留历史。用户本次明确授权按顺序验证两个固定问题，合计最多两次 HTTP 尝试；任一步失败停止、不重试。实际两题流程和保存均成功，第一题退出 0 且重读结果核对通过后才执行第二题。没有追加模型调用。

### 调用前核实与检查

2026-11-05 查阅官方 [同步接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api) 与 [v4 模型/价格](https://help.aliyun.com/zh/model-studio/text-embedding-v4)：北京业务空间原生 POST 地址为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding`；v4 每批最多 10 条、单条 8192 tokens、支持默认 1024 维，HTTP 的 text_type 放在 parameters。北京同步文本输入原价为 **¥0.5/百万 tokens**，未使用 Batch File 价格。

继续使用用户已确认的 ws-kicad9ful35400g7 北京 endpoint；本地 E1/E2b 预检通过，产物契约维度为 1024，两题分别 90、45 UTF-8 字节，均不超过本次 256 字节授权上限。实际 CLI 还在请求前重新检查资料及真实配置的编码兼容性。密钥只由程序读取用于 embedding 认证，未打印配置全文或密钥；没有健康检查、地域探测或余额查询。

### 实际结果与用量

| 问题 | HTTP 尝试/状态 | 已知 tokens | 用量完整 | 维度 | 流程耗时 | 估算费用（元） |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| 发现迁移部分执行或执行状态无法确认时，可以直接重跑原脚本吗？ | 1 / 200 | 20 | true | 1024 | 0.339 秒 | 0.000010 |
| 公司差旅报销的住宿标准是多少？ | 1 / 200 | 10 | true | 1024 | 0.309 秒 | 0.000005 |
| 合计 | 2 次 | 30 | 无未知用量 | — | — | 0.000015 |

费用按返回 total_tokens × 0.5 / 1,000,000 估算，**不是实际账单**；余额、免费额度抵扣、优惠及实际扣费均未核实。耗时来自程序记录，不含工具审批/调度和最终文件保存耗时。范数分别约 1.0000000688、1.0000000648；程序未自行归一化。

保存文件（Git 忽略，全新路径，未覆盖）：

- `test-output/rag/e2c/live-20261105-q1-001.json`
- `test-output/rag/e2c/live-20261105-q2-001.json`

请求 ID 分别为 `f8e73323-8209-9409-be4c-9a9ca74a802c`、`3acf18d6-f8be-92a3-a4df-109b2664ee5c`。两次 CLI 均退出 0，status=succeeded、error=null；已重读 JSON 核对 question/query.text/retrieval.question 完全一致，单次 query 请求、top-k=3、1024 维有限非零向量、完整用量。离线重算 E2b search 与保存结果完全一致，逐条按原文行号核对候选正文一致，无新 API 消耗。

### 候选观察，未生成回答

| 问题 | 排名 | 余弦 | 章节 | 来源 |
| --- | ---: | ---: | --- | --- |
| 迁移问题 | 1 | 0.83809894 | 失败后重跑前的检查 | migration-guide.md:11–20 |
| 迁移问题 | 2 | 0.72102279 | 执行前的记录 | migration-guide.md:5–10 |
| 迁移问题 | 3 | 0.68970790 | 恢复与重新验证 | migration-guide.md:21–26 |
| 差旅问题 | 1 | 0.30402284 | 发布范围与准备 | release-policy.md:5–10 |
| 差旅问题 | 2 | 0.30132682 | 排查交接 | migration-guide.md:27–29 |
| 差旅问题 | 3 | 0.29913419 | 应用验证与恢复准备 | release-policy.md:17–22 |

人工观察：迁移问题第一名直接保留“部分执行或无法确认状态时不得直接重跑”的条款和恢复/修复验证条件；其余两节涉及执行不确定性及恢复验证，属于补充关联。差旅问题的候选均讨论发布或数据库流程，没有住宿金额、地区/职级标准等依据，不能宣称资料中存在差旅住宿标准。检索程序只标记 candidates_only，不会自动识别范围外或断言有答案；本次没有临时调整分数阈值、提示词或资料。

### 本轮边界与交回

没有代码/测试改动，因此未重复执行已通过的 137 项完整回归；本轮新增验证是两次真实链路、保存记录检查和离线结果复算。旧模拟测试与真实观察分开，真实失败仍未故意触发。两条问题不能代表系统性语义效果评估，更没有验证生成回答或引用忠实度。

保留主会话新增离线复核及工作区既有修改，追加本节与进度，必要当前状态链接同步更新。未重新编码文档、调用 DeepSeek、接入 Agent 或生成回答；未提交、推送或推进下一阶段。真实请求预算已用完，交回主会话仅复核已有结果，不自动补跑。


## 主会话真实记录复核（2026-11-05）

结论：E2c 的两题真实记录复核通过。未重复调用 API、未读取真实密钥。逐项核对两份 live-20261105-q1/q2-001.json：每题 1 次 query HTTP 尝试、HTTP 200、1024 维有限非零向量，question/query.text/检索问题一致，用量完整且分别 20、10 tokens，合计 30。请求 ID 与实现会话记录一致；复用当前 E1/E2b 离线重算，全部检索字段与保存结果完全一致，6 条候选原文按来源文件行号还原一致。

迁移问题第一名确实包含“部分执行或无法确认状态时，不得直接重跑原脚本”的限制及先制定恢复/修复方案并验证的要求；差旅问题的三个候选仅讨论发布/迁移，不能支持住宿标准。认可交接的候选观察，不把检索成功说成可回答或引用回答已验证。此前 137 项离线复核仍为机制验证，真实失败、生成回答和引用忠实度尚未验证。

E2c 阶段验收通过；主会话准备 E2d 问答与引用任务书，由独立会话实施。未自动提交/推送、未实现 E2d 或进入 E3，E2 整体尚未完成。

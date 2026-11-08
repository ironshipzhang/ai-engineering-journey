# E3 实施交接：模型调用只读资料检索工具

日期：2026-11-08。**最新结论：主会话独立复核及用户最终确认通过，E3 和任务 E 的本轮范围验收完成。** 下文分节保留离线实施、真实失败、诊断及修正时的状态，以文末最终确认为准。 依据 [任务书](e3-retrieval-tool.md)。本轮未读取真实密钥、调用模型 API、重新编码文档、安装依赖或提交推送；不宣布 E3 或整个任务 E 验收完成。

最新状态（2026-11-08）：修正后的 199 项回归及 -004 两题真实样例已通过主会话独立复核，技术交接可接受，待用户最终内容确认。以下保留初始交接和失败/修正历史；主会话结论见文末。

## 目的与最小流程

E2d 是先检索再生成的固定流程；E3 在前面增加模型自主提出检索调用。只允许一个工具、一次往返，不扩展为通用 Loop：

```text
预留输出 → 本地检查 → DeepSeek（仅 search_knowledge，默认 auto）
  → 校验恰好一个调用、query 逐字一致 → Registry 分发
  → 单次问题编码 + E2b 检索 → 当前 S1–S3 原文证据
  → assistant.tool_calls + 对应 tool.tool_call_id
  → 复查 → DeepSeek（无工具，JSON 回答）
  → E2d 引用校验 → 最终复查 → 保存
```

首轮未提出检索时，completion_gate/retrieval_not_requested 失败，answer=null、零 embedding，不把它说成知识库没有答案。调用提议、校验和实际执行分别留痕；工具成功只表示取得候选，最终可以合理选择 insufficient_evidence。

## 文件与复用边界

- 新增 [retrieval_agent.py](../../../../toy-agent/src/retrieval_agent.py)：run_agent、独立单项 Registry、严格工具参数/协议校验、消息链、记录和薄 CLI。
- 新增 [test_retrieval_agent.py](../../../../toy-agent/tests/test_retrieval_agent.py)：25 项离线行为测试，独立临时资料/产物、假配置与模拟传输，不依赖个人 test-output。
- 小范围修改 [live_query_retrieval.py](../../../../toy-agent/src/live_query_retrieval.py)：将现有本地前检抽为 preflight_retrieval，原 execute_retrieval 调用它，顺序/错误阶段/输出结构保留；E3 在路由请求前完成同样检查，工具中仍复用完整编码检索阶段。
- 小范围修改 [grounded_answer.py](../../../../toy-agent/src/grounded_answer.py)：抽出同等规则的 read_generation_key；request_answer 增加仅关键字 tools=None，默认仍无工具，E2d 默认 payload 不变。
- 复用旧 ToolRegistration 类型，独立注册表关联 schema、校验及执行。旧项目 Registry/Agent 源码、摘要提示词、E2c/E2d 既有测试均未修改。没有复制向量/余弦/来源校验或在工具内调用生成。
- 更新 PROGRESS、SETUP、ARCHITECTURE、ROADMAP、任务索引与目录说明。本轮没有新增供应商或依赖；没有新选型决策，不另增 DECISIONS。前序阶段交接保留其历史停止点。

本轮检查了 [DeepSeek 官方 Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 与工具参数说明：提供 tools 时默认 auto，非思考工具消息通过 assistant/tool 关联；次轮不提供工具，沿用 JSON 对象输出。仅浏览公开文档，未发模型探测。当前费率、地域与真实接口组合的实际效果须在未来授权验证前再次核实，不把文档核实当作真实调用通过。

## 公共入口与运行

```python
run_agent(question, prepared, artifact_path, output, *,
          config_path=..., endpoint=None, knowledge=..., max_chars=1200) -> dict
```

调用函数与 CLI 都先独占预留输出，失败不读取配置或发请求。公共函数返回已保存记录；流程失败也保存，判断 status；预留或保存失败抛 E2c 的 OutputError，携带可用内存结果。CLI 成功退出 0，流程/保存失败退出 1，参数解析失败退出 2。命令均在仓库根目录：

```bash
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'
toy-agent/.venv/bin/python toy-agent/src/retrieval_agent.py --help
```

CLI 支持 --question、--prepared、--artifact、--output、--config、--endpoint、--knowledge、--max-chars；top-k 固定 3。付费命令示例见 [SETUP 的 E3 节](../../../SETUP.md)，本轮未执行。输出放 [test-output/rag/e3](../../../../test-output/rag/e3/)，全部 Git 忽略。

## 配置、消息与失败契约

两种配置和 E1/E2b/编码契约检查在首个模型请求前完成，包括 E2d 修复后的生成密钥非空可打印 ASCII 限制。初始 snapshot 保存 build_id/文档摘要/编码契约；工具执行前、检索后、次轮生成前、答案发布前继续核对当前原文及磁盘向量文件，变化/损坏停止，不自动重建。工具中重复本地前检是当前小规模 Toy 的有意简化，不是新的缓存平台。

模型只能提供 query，须与本次问题逐字一致；拒绝重复 JSON 键、额外参数、错类型、改写、未知工具、多调用、截断和 finish_reason 不一致。call_id 明确限制为 1–128 位 ASCII 字母/数字/下划线/连字符。合法首轮 assistant 文本及单调用保留一次，再追加对应 tool_call_id 的工具消息；附带自然语言不作为证据。第二轮 system 复用 E2d 回答契约并说明证据来自 tool，问题/原文不进入 system。次轮返回工具调用直接拒绝，不再执行。

两轮 messages 序列化上限各为 16 KiB UTF-8，包含消息链及完整原文，超出停止，不静默截断；这个既有保护不包含工具 schema，也不是精确 token/金额限制。资料注入测试仅验证消息边界和无命令能力，不证明真实攻击鲁棒性。

每次最多 2 次 DeepSeek + 1 次 query（含失败），非思考、非流式、每轮生成 800 输出 tokens、每次网络操作 30 秒；无重试、重定向、fallback、缓存、查询改写或隐藏生成。无工具执行时 embedding 子记录 status=failed 表示尚未完成，不意味着已经调用失败，需结合计数与 trace 判断。

运行类型 e3_retrieval_tool_run、格式 1。保存 question/status/error、initial_snapshot、generation 逐轮配置/请求/finish_reason/usage、embedding 子结果、本次 evidence、tool_call/call_id、tool_executions、tool_exchange、trace 及 answer/resolved_citations。tool_exchange 的 assistant/tool 内容与传给第二轮的一致，sent_to_model 只代表已发起尝试，不证明服务端收到。未复制全量文档向量或认证信息，不落盘原始异常、错误正文或非法调用参数。

DeepSeek 按轮记用量并按服务汇总，embedding 独立；有效 usage 先于协议校验保留，任一轮未知则 complete=false，后续已知用量不能抹除未知状态。response_received 仅表示收到可解析的 HTTP 200，validated 表示工具/回答校验通过；都不能当作语义支持证明。任何失败 answer=null，保留前序记录；最终检查通过后才发布有效回答，semantic_review 恒为 not_performed。

仍无跨网络文件锁，瞬时变化后恢复或检查后的修改可能不可见。保存为普通独占文件结束时一次写入；write/flush/close 失败安全报告非零，可能留下空/部分文件，不承诺事务/fsync/恢复，不自动重跑付费请求。

## 验证结果与轨迹样例

开工 Git 状态干净；既有 **168 项**通过。完成后完整 **193 项通过（168 + 25）**，旧测试未修改。新增覆盖正常消息链/ID/Registry 隔离、未检索门禁、非法调用零执行、两配置/资料/编码前检零请求、原文/有效磁盘向量运行期变化、次轮再要工具、两服务失败及未知用量、引用与资料不足、相反结论的语义边界、注入数据隔离、上下文超限、覆盖拒绝及保存失败。模拟测试不证明模型实际选择工具或内容正确。

从临时测试夹具实际执行成功模拟，摘录 trace（未发生真实请求，夹具产物已清理）：

```text
preflight: succeeded
 tool_proposal: proposed=true, call_count=1, validation=accepted
 tool_execution: search_knowledge, call_id=call-e3-001, succeeded
 completed: succeeded, call_id=call-e3-001
 ended: succeeded
```

模拟顺序为 generation → embedding → generation，记录尝试数分别为 2 和 1；最终为 insufficient_evidence，semantic_review=not_performed。另有 answered 引文存在但结论相反的模拟反例，仍仅通过可追溯性检查，没有自动语义通过。

CLI --help 正常；实际执行空问题离线前检，使用不存在且不读取的假配置路径，退出 1，生成/embedding/工具执行均 0：

```text
test-output/rag/e3/offline-input-rejected-20261108-001.json
status=failed, error.stage=input_validation
两阶段用量均为 0、complete=true；answer=null
trace: ended / failed / input_validation
```

该文件已存在，不覆盖重跑。没有本轮真实成功问答产物，没有使用旧 E2 结果冒充 E3 观察。

## 交回主会话与未验证项

请独立复核共享抽取是否保持 E2c/E2d 行为、前检与快照绑定、Registry 校验/实际执行分离、单次工具消息 ID、预算/未知用量，以及引用存在性与语义支持的区别。

真实模型是否选检索、是否逐字复制 query、两题实际引用/拒答、供应商失败与注入鲁棒性均未验证。相关题/差旅题各一轮的 **4 次 DeepSeek + 2 次 embedding** 仅为未授权提案，不能沿用 E2 旧预算；未来获授权后每题 ≤256 UTF-8 字节、1024 维、top-k=3，任一步失败停止，不补跑。第一题含保存和逐条内容核对通过后才能继续第二题。

本轮离线实现不代表 E3 或整个任务 E 已验收。未提交推送、不接 MCP、不推进下一阶段。

## 主会话离线复核及用户授权后的首次真实验证（2026-11-08）

以上“真实未授权/未执行”为实施交接时状态。其后用户明确要求在线测试；主会话独立运行完整离线回归 193 项全部通过，未发现阻止受控真实测试的问题。

首题实际发送 1 次 DeepSeek routing，HTTP 200、finish_reason=tool_calls，输入 495/输出 56/总计 551 tokens，用量完整。模型提出 1 个调用，但在 tool_validation 被拒绝。程序安全停止，工具执行/embedding 均为 0，没有回答；结果保存至 test-output/rag/e3/live-20261108-q1-001.json。

按照失败停止规则，未执行第二题，未重试或补跑。当前记录只有受控阶段，没有细分拒绝原因，无法判定具体哪项校验失败；不要猜测或直接放宽协议。需先由独立实现会话增加安全原因码及离线覆盖，后续真实复测另获明确确认。本轮不修改代码、不提交推送。

完整证据、保守费用估算及必要改进见 [主会话真实复核记录](e3-real-review-20261108.md)。结论：离线机制通过，E3 真实验收未通过，整个任务 E 不宣布完成。


## 工具调用拒绝原因码补充（2026-11-08，离线完成待复核）

用户确认先解释问题后授权本次改动。仅增强 E3 工具协议校验的诊断，不放宽任何原有规则，不改工具 schema、提示词、模型参数、共享传输或 E2 行为；没有真实复测。

`retrieval_agent.py` 新增 ToolValidationError 和固定原因码/说明允许列表。预期拒绝在 error.reason_code、最终 ended trace 中保留；若已创建 tool_proposal，也写入其 reason_code。CLI 通过安全说明及 trace 展示原因码。未分类的工具校验异常记录 validation_failed，不保存异常文字。原 artifact_type/format_version 保持，reason_code 为新增可选诊断字段；没有原因码的历史记录仍按原信息范围解读。

| reason_code | 拒绝含义 |
| --- | --- |
| response_shape_invalid | 路由响应缺少唯一有效 choice |
| message_shape_invalid | assistant 角色、内容类型或旧式调用协议不符合要求 |
| finish_reason_invalid | 非 tool_calls，包括截断或调用/结束原因不一致 |
| call_count_invalid | tool_calls 不是恰好一个调用 |
| call_shape_invalid | 调用或 function 对象缺失/多出字段、结构不符 |
| call_id_invalid | ID 值不符合既有字符/长度约束 |
| tool_type_invalid | type 不是 function |
| tool_name_invalid | 名称不属于本次注册表 |
| arguments_invalid | 参数 JSON（含重复键）、字段、文本类型/可编码性/长度不合法 |
| query_mismatch | 合法 query 文本与实际问题不逐字一致 |
| validation_failed | 未分类的工具校验异常，安全兜底 |

只记录首个触发的拒绝原因，不试图枚举或恢复全部非法字段。正常 stop 且未检索仍沿用 completion_gate/retrieval_not_requested，不改成工具参数错误；工具校验失败仍为 tool_validation、answer=null、零工具/embedding，不追加请求。合法模拟调用的接受行为保持。

离线测试验证例如改写 query 时得到 query_mismatch；这只是合成失败用例，不是对首次真实失败的归因。无效模型响应、ID、名称、参数及附带内容均不落盘或显示，代码只输出固定本地说明。对带有假凭据的非法值和异常做了输出安全断言，仍保留已知 routing 用量。

测试：新增 3 项（响应/消息结构原因、敏感非法值不泄露、未知异常兜底），并加强原非法调用用例以断言各类原因码、trace 和零执行。完整离线回归 **196 项通过（原 193 + 3）**，既有合法模拟流程及旧 Agent/E2c/E2d 测试仍通过。执行命令：

```bash
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'
```

本次保留全部工作区修改、真实复核记录及运行 JSON，没有读取真实密钥、调用模型、提交或推送。诊断改进无法恢复此前未保存的原始调用，因此首次真实 tool_validation 失败的具体原因仍未知；不宣称已修复真实兼容问题或通过 E3 验收。主会话先复核离线改动，后续真实复测方案及预算需用户重新明确授权，不能继续使用失败后剩余预算自动补跑。


## 原因码补充后的用户授权复测（2026-11-08，未通过）

用户本轮明确授权尝试在线测试。沿用原两题顺序与最多 4 次 DeepSeek + 2 次 embedding 的有界方案，按失败即停执行，不复用旧剩余预算。先完成 E1/E2b/维度/问题长度/新文件名前检，并核实官方接口与费率；没有探测或余额查询，配置仅在入口认证路径读取，不显示密钥。

迁移首题实际发送 1 次 DeepSeek routing，HTTP 200/tool_calls，输入 495、输出 56、共 551 tokens，用量完整；CLI 退出 1。新原因码 **call_shape_invalid** 记录在 error 及提议/结束 trace 中，表示调用或 function 对象的结构/字段集合不符。尚不能确定是哪层、缺失还是多余字段；不猜测具体字段，不把首次无原因码的失败倒推为同一原因。

结果保存并重读核对为 `test-output/rag/e3/live-20261108-q1-002.json`；工具/embedding 均为 0，没有次轮回答，answer=null、semantic_review=not_performed。已停止整个复测，第二题 -002 未生成，不重试或补跑。此次无源码/提示词或历史 JSON 修改，未重复回归；196 项仍为此前离线验证记录。

本次保守峰值未命中原价估算 $0.0002157，非账单；两次 E3 在线尝试累计 routing 2 次/1102 tokens、保守估算 $0.0004314，百炼零请求。官方来源、逐项记录和定位限制见 [真实验证复测节](e3-real-review-20261108.md)。

诊断能力已在真实记录中生效，但根因尚未细化，E3/任务 E 仍未通过真实验收。后续先确定受控结构诊断或协议兼容方案，新的修改和真实复测另行授权；不继续花剩余预算，不提交推送或推进后续阶段。

## 持续修正后的协议兼容与真实两题通过（2026-11-08）

用户明确授权“继续修改。直到真实在线测试通过。”本次先补受控结构详情，再依据真实差异作最小兼容调整，离线测试后真实运行。早前各轮停止点与未授权状态保留为历史，不再代表本节的后续授权。

### 根因与修正

- 198 项离线回归通过后，新增诊断运行 `live-20261108-q1-003.json`，1 次 routing/551 tokens，零工具/embedding。详情确认调用外层必需字段齐全，仅额外携带 `index:0`，触发原有 exact-fields 检查。不能将这一观察倒推成 -001/-002 原始调用的确定内容。
- `check_tool_fields` 仅保存固定对象层级、已知缺失字段和多字段标志，不保存未知名称或值。对 call 额外记录是否仅 index 及其值是否为整数 0，帮助安全定位。
- `checked_call` 现在允许调用外层可选 index，存在时须为整数 0（bool、浮点、非零、字符串和 null 均拒绝）；未知外层字段仍拒绝，function 字段与业务 query 参数仍严格。
- 校验后显式生成仅 id/type/function 的规范调用对象，移除传输 index，trace 记 transport_index_removed；工具、call_id、query 逐字绑定及引用规则不变，未改提示词或模型参数。新增安全原因码 call_index_invalid。
- 官方文档列出了流式 tool_call.index；非流式中该字段的存在是本次真实观察。此处为受控的供应商传输兼容，不声称非流式文档要求该字段，也不泛化接受任意多余字段。

最终 **199 项完整离线回归通过**（前次 196 + 本次 3）；新增/调整覆盖安全层级详情、index:0 的接受和规范化、非法 index 与未知额外字段拒绝。旧 Agent/E2c/E2d 测试保持通过，无新依赖。此次仅调整 E3 源码与测试；共享传输、原文、文档向量、真实配置及历史 JSON 未改。

### 成功链路与审阅

修正后文件为 `test-output/rag/e3/live-20261108-q1-004.json` 和 `live-20261108-q2-004.json`。首题完成保存及内容核对后才执行第二题；两题均 CLI 退出 0、status=succeeded，各 2 次 DeepSeek + 1 次 query 编码、一次 search_knowledge，1024 维、top-k=3。

| 问题 | DeepSeek 输入 / 输出 / 总 tokens | embedding tokens | 结果 |
| --- | --- | --- | --- |
| 迁移部分执行/状态不明能否直接重跑 | 2407 / 463 / 2870 | 20 | answered，5 条引用结论 |
| 差旅住宿标准 | 2170 / 105 / 2275 | 10 | insufficient_evidence，无编造标准 |
| 成功两题合计 | 4577 / 568 / 5145 | 30 | 均用量完整 |

重读结果并核对 query、消息 ID、工具结果/evidence、维度和用量；E2b 检索离线复算及原文行号切片完全一致。实现会话逐条比对迁移题五条 claim、quote 与完整段落，确认禁止直接重跑、先验证方案、不能单靠一项检查/无变更/客户端超时放行等条件保留。差旅题只声明本次资料不足，没有金额或公司无政策断言。本实现会话内容核对通过，仍待主会话复核及用户最终确认；原始 semantic_review=not_performed 不回填。

本次持续修正（-003 诊断及 -004 两题）实际 5 次 DeepSeek/5696 tokens + 2 次 embedding/30 tokens；E3 全部真实运行含 -001/-002 累计 7 次 DeepSeek/6798 tokens + 2 次 embedding/30 tokens。按峰值未命中原价保守估算，本次 DeepSeek $0.0022704、累计 $0.0027018，百炼 ¥0.000015；非账单，余额/缓存/优惠未查。完整逐轮表、五条内容核对与官方依据见 [真实复核最新节](e3-real-review-20261108.md)。

真实两题测试目标已达成，停止追加调用，交回主会话复核。不以两题外推通用准确率或生产可靠性，不自动提交推送或推进下一阶段。


## 主会话最终技术复核（2026-11-08）

独立完整回归 199 项通过，兼容修正及诊断范围合理，无必要代码修正项。已重读 -003 和两份 -004，验证规范化调用、逐字 query、消息 ID、两轮用量、1024 维、检索复算和来源切片，并逐条核对迁移题五项结论及差旅题拒答，均符合任务书。所有 E3 历史文件合计 7 次 DeepSeek/6798 tokens + 2 次 embedding/30 tokens，与交接一致。

结论：E3 技术交接与两题主会话内容审阅通过，用户最终确认尚待记录。详细证据见 [真实复核最新结论](e3-real-review-20261108.md)。本轮不重复联网、读取密钥、修改代码或历史产物、提交/推送或推进 MCP。


## 用户最终确认与任务 E 收尾（2026-11-08）

用户现已确认主会话复核后的两题结果符合预期，E3 技术实现、199 项独立完整回归和两题真实链路/内容验收完成；E1、E2a–E2d 的既有验收保留，任务 E 的既定学习范围正式关闭。199 项是主会话此前独立验证结果，本轮文档收尾不重复运行。

迁移题五项结论有完整原文支持，差旅题限定本次资料不足、不编造标准；程序引用存在性检查、主会话内容审阅和用户确认分别记录，原始 semantic_review 不改。index:0 根因依据为 -003，不回填早期失败。详见 [最终验收记录](e3-real-review-20261108.md) 与 [任务 E 总交接](../e-stage-handoff.md)。

失败、诊断、修正和用量记录全部保留。完成不代表通用准确率、自动语义核验、注入鲁棒性或生产可靠性达标，也未实施 MCP。Toy 继续 JSON，无新数据库/框架；后续阶段需另行选择授权。本轮只更新文档与路线 SVG，不改代码或历史产物、不调用 API、不提交推送。

# E2d 实施交接：依据检索资料生成回答与来源引用

日期：2026-11-05。**离线实现完成，待主会话复核；真实验证尚未授权或执行，E2 整体未宣布完成。** 本轮没有读取真实密钥、调用模型 API、重编码文档、安装依赖或修改旧摘要提示词/历史评估，也未提交或推送。

## 这一步补上什么

E2c 到“找到候选资料”为止；E2d 在同一次运行中继续把问题和候选资料交给生成模型，并核对回答的来源。固定顺序如下，不由 Agent 自主选择工具：

```text
用户问题 → 本地前检（含两种配置）→ 百炼只编码当前问题
        → E2b 检索 → 本次证据 S1/S2/S3 → 生成前复查
        → DeepSeek 根据证据给出逐条结论/资料不足
        → 引文存在性校验 → 最终资料复查 → 单个运行 JSON
```

证据表保留完整片段及 E1 来源，模型只选择本次 source_id 和逐字 quote。程序从本地证据表补齐文件、章节、行号和构建标识，不信任模型自报路径。它能检查“引文存在”，不能判断“结论被引文支持”；这一步仍须人工核对。即使 status=succeeded，也始终保存 semantic_review=not_performed。

## 修改与复用

- 新增 `toy-agent/src/grounded_answer.py`：公共 run_answer、独立资料问答提示词、证据表、无工具生成适配、严格解析与引用关联、两次磁盘复查及 CLI。
- 修改 `toy-agent/src/live_query_retrieval.py`：原内部执行函数更名为 execute_retrieval，供两个入口共用；增加可选的本地生成配置校验回调，在编码请求之前执行。E2c run_query/CLI 参数、输出结构和旧测试保持不变，没有临时中间文件。
- 新增 `toy-agent/tests/test_grounded_answer.py`：29 项离线测试，使用临时 corpus、合成 64 维向量及假配置。维度只是离线机制夹具，不能算真实 1024 维验收。
- 更新 PROGRESS、SETUP、ARCHITECTURE、路线、任务索引、README、PROJECT_STRUCTURE；本文件新增。任务书和前序讨论/复核记录保留。
- 沿用 E1 严格 JSON 解码、E2a 编码客户端、E2b load_checked/search、DeepSeek 安全密钥读取和用量解析。旧生成适配默认工具/重定向行为不满足本任务，因此新增小型独立 urllib 适配，不修改旧 Agent 路径。无新增依赖或锁文件变化。

## 运行记录如何读

类型 `e2d_grounded_answer`、格式 1。顶层 status 表示整个流程是否成功；error.stage 定位失败。answer 只在格式/引用及最终资料复查全部通过后赋值，否则为 null。

| 字段 | 作用 |
| --- | --- |
| question | 原样保留的问题 |
| embedding | E2c 阶段记录，含问题向量、E2b 候选、构建摘要、请求和用量；其 succeeded 只表示检索成功 |
| evidence | 本次 S1–S3 与原文、章节、行号、chunk_id、build_id、向量摘要的关联 |
| generation | 非敏感配置、提示词版本、请求次数/状态、三类 tokens 与 complete；messages_sent 表示已发起带该表的生成尝试 |
| answer | answered 的逐条 claims/citations，或 insufficient_evidence 的空 claims 与原因 |
| resolved_citations | 按 claim_index 关联的引文及本地可信来源 |
| semantic_review | 固定 not_performed；不能让模型给自己评审通过 |

evidence 在上下文构建时即保留；messages_sent=false 时并未发起生成，不应把表的存在说成已经发送。生成失败仍保留 embedding/候选/证据与已知用量，不保存原始错误正文或无效模型回答。无 usage 时 complete=false，不能当成免费。两供应商用量不混算，本轮没有实际费用估算。

## 关键取舍和失败边界

- top-k 固定 3；完整序列化 messages 最大 16 KiB UTF-8，超过就失败，不截短片段或丢掉限制条款。这不是精确 token 限额。普通问题入口继承 E2c 8192 字节限制；真实提案的 256 字节/1024 维仍须运行前核对。
- 生成使用现有 deepseek-flash/地址，禁用思考、流式和工具，JSON 对象模式，800 输出 tokens，30 秒网络操作超时；无重试、重定向、fallback 或自动修复。
- 只有 answered/insufficient_evidence；拒绝重复键、额外字段、空白内容、无引用结论、未知 ID、非逐字引文、非 assistant 文本、工具结果和非 stop 结束。资料不足是合法流程成功，但仍未做语义评审。
- 引文可以存在却支持不了结论。离线反例明确展示这种结果仍可通过结构校验，semantic_review 不变；不能宣传为自动事实核查。
- 问题和证据仅放在序列化 user 数据里；system 是固定可信规则，不执行模型/资料中的工具、代码或 URL。测试仅验证此消息边界与工具输出拒绝，不证明真实注入鲁棒性。
- 生成前后都重新从磁盘 load_checked，并与检索时的向量摘要/build_id 比较，覆盖原文变化、损坏以及有效但不同的向量文件替换。没有跨网络文件锁，无法保证发现瞬时修改后恢复或最后检查后的修改。
- 输出在读取配置前独占预留，拒绝覆盖，最后保存一次。写入/刷新/关闭失败非零退出，可能留下空/部分甚至已写出完整字节但关闭失败的文件；不是事务保存，不重跑付费请求。

## 验证结果与命令

在仓库根目录执行：

```bash
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'
toy-agent/.venv/bin/python toy-agent/src/grounded_answer.py --help
```

基线 137 项通过；完成后完整 **166 项通过（137 + 29）**。E2c 原 18 项测试未修改。新增覆盖两配置/资料/产物/兼容前检零请求、单次编码与生成、上下文上限、逐条引用严格校验、语义反例、资料注入数据边界、两阶段已知/未知用量、生成前后原文/向量变化、输出保存失败及无重试/重定向。

实际运行了以下**离线失败演示**，未读取该不存在的假配置路径，退出 1，两阶段 HTTP 尝试均为 0：

```bash
toy-agent/.venv/bin/python toy-agent/src/grounded_answer.py \
  --question '' \
  --prepared test-output/rag/e1/20261028/build-001 \
  --artifact test-output/rag/e2b/e2b-vectors-20261104-001.json \
  --config test-output/rag/e2d/not-a-real-config.toml \
  --output test-output/rag/e2d/offline-input-rejected-20261105-001.json
```

上述输出已经存在，不可直接覆盖重跑；需要演示时换新文件名。测试中的成功运行与保存只发生在临时目录且传输完全模拟，不是成功真实问答。联网命令参考 SETUP 的 E2d 节，**本轮未执行，也未获得真实授权**。

## 未验证与交回事项

尚未验证：当前真实 DeepSeek JSON/引用遵循情况、两题完整链路、生成内容及拒答范围、引用的语义支持、真实用量/费率/余额。也未测试真实网络故障或真实注入攻击。余额及账单未查询。

主会话复核离线代码和回归后，再由用户明确确认两题端到端提案：迁移重跑问题、差旅住宿标准问题；最多 2 次 embedding + 2 次生成，失败也计数。授权后才核实当前官方接口、地域、限制和费率；每题 ≤256 UTF-8 字节、1024 维、top-k=3。第一题含保存及人工 claim—quote—完整片段核对均成功后才能继续第二题；任何失败停止，不补跑。未经这些真实验收，不宣布 E2 最小范围完成，不进入 E3。

Git：保留开工时 README、ARCHITECTURE、PROGRESS、PROJECT_STRUCTURE、SETUP、ROADMAP、任务索引的修改，以及未跟踪的 E2c 源码/测试/交接和 E2d 任务书。本轮新增 grounded_answer.py、test_grounded_answer.py、本交接并窄改 E2c 复用函数；未回退前序修改。test-output/rag/e2d 已确认被忽略。没有自动提交或推送。


## 主会话离线复核（2026-11-05，待一项必要修正）

独立运行完整回归 166 项全部通过；另核对空问题本地 JSON，两阶段均 0 请求，answer=null、semantic_review=not_performed，与报告一致。现有 E2c 测试文件与此前主会话阅读的版本一致，本次 E2d 只抽取共享编排并增加配置前检回调。无真实密钥读取或 API 调用。

通过项：输出先独占预留；资料/编码兼容及两配置读取在请求前；每题单次 query/无工具生成且禁重定向重试；回答严格字段、重复键、正常结束、本次来源与逐字引文校验；semantic_review 不提升为语义通过；生成前后从磁盘 load_checked 并比较摘要/build_id；两阶段用量独立、坏回答保留有效用量、未知用量与保存失败分别记录。

必要修正 P2：grounded_answer.execute 的 check_generation_config 只调用旧 read_config_api_key，后者拒绝空值/空白/默认占位符，但接受非 ASCII 等本地可判定不适用于认证头的值。用临时 model.api_key=中文假密钥、合法假 embedding 配置复现：问题编码已经执行一次，真实生成适配在仅模拟 HTTP 头 Latin-1 编码时失败，最终落到 generation_request；正确行为应在 configuration 阶段失败，两阶段请求都为 0。所有传输均模拟，没有联网。

建议在 E2d 的生成配置前检对密钥增加非空可打印 ASCII（且无空白/控制字符）校验，报固定安全错误；不在本次修改旧 Agent/评估读取行为。补充非 ASCII 密钥和控制字符的假配置回归，断言两请求函数均未调用、零用量完整、配置阶段失败且不回显凭据。修正后重新完整回归并交主会话复核，本轮不直接修改代码。

当前结论：166 项既有回归通过，但 E2d 离线验收待上述前检修正，暂不进入真实验证。真实两题预算仍未授权；真实 JSON/引用遵循、内容支持与拒答范围、实际费用、供应商失败和注入鲁棒性均未验证。未提交、推送或进入 E3，E2 整体未完成。


## 生成密钥前检修正（2026-11-05，待再次复核）

针对上节 P2，仅修改 `grounded_answer.py` 的 check_generation_config：在旧安全读取器返回后，要求密钥非空且每个字符位于 ASCII `!`–`~`（0x21–0x7E）。这样拒绝非 ASCII、空白及控制字符，并在共享编排的 configuration 阶段、任何 embedding/生成请求之前失败。异常及运行诊断使用固定安全文字，不带凭据。旧 Agent/摘要评估读取器、E2c 源码及对外行为、所有提示词均未改；无新增依赖。

新增 2 项测试，使用临时 TOML，仅替换 model.api_key，embedding 假配置保持合法：

- 非 ASCII：中文和非 ASCII 字母。
- 控制字符及空白：通过 TOML 转义表示 NUL、ESC、DEL、制表符、换行，另覆盖普通空格。

各用例均断言 configuration 阶段失败、两请求函数未调用、两阶段 http_attempts=0/requests=[]、已知用量为 0 且 complete=true、answer=null、semantic_review=not_performed；保存记录与展示诊断不含测试凭据及其转义形式。既有合法配置的成功模拟流程继续通过。

实际执行完整离线回归：

```bash
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'
```

结果 **168 项通过（原 166 + 新增 2）**。本轮仅改上述源码、测试、PROGRESS 和本交接；保留工作区已有修改与主会话历史复核记录，未提交或推送。

未读取真实密钥、未调用任何模型 API。此校验只保证本地字符格式符合要求，不能证明密钥有效、账户权限或余额足够。真实端到端两题、引用语义支持及其他前述真实验收仍未授权/执行；交回主会话复核，不推进 E3，不宣布 E2 完成。


## 主会话修正复核（2026-11-05，通过）

已检查 E2d 独立前检及两项新增测试，并独立运行完整离线回归，168 项全部通过。非 ASCII、空白和控制字符现在在 configuration 阶段拒绝，测试覆盖两阶段零请求、零用量完整、answer=null 和安全诊断；既有合法配置模拟链路继续通过。此前 P2 已关闭，E2d 离线实现验收通过。

本轮只检查和维护复核记录，没有读取真实密钥、调用 API、修改源码/测试、提交或推送。下一步可在用户明确确认后执行原两题端到端提案，合计最多 2 次 embedding + 2 次生成，失败停止不补跑；当前仍未获真实调用授权。真实回答、拒答及引用语义支持尚未验收，E2 整体未完成。


## 用户确认后的真实验证（2026-11-05）

用户已明确确认原两题端到端方案，主会话顺序执行两题，合计 2 次问题编码 + 2 次生成，无重试或文档编码。两题 CLI/保存及格式引用检查均成功，分别为 answered 与 insufficient_evidence。embedding 合计 30 tokens，DeepSeek 合计输入 3296、输出 315、总计 3611 tokens，全部用量完整。原始结果在 test-output/rag/e2d/live-20261105-q1-001.json 与 live-20261105-q2-001.json。

主会话逐条核对迁移回答的三项结论、逐字引文及完整限制段落，均得到支持；差旅题拒答仅限定本次资料，未编造标准，符合候选原文。预算已用完，不追加请求。当前代码/原始 JSON 的 semantic_review=not_performed 保留，内容审阅独立记录在 [真实验证与内容审阅](e2d-real-review-20261105.md)，包含官方资料、估算费用、每条结论核对及未验证范围。审阅由主会话 AI 辅助完成，不能冒称用户逐条人工确认。

本轮最小链路及两题主会话审阅已完成，用户最终内容确认尚未记录，不以两个样例声称通用准确率通过。未修改源码或提示词、查询余额、提交/推送或进入 E3。


## E2 收尾确认（2026-11-05）

用户明确确认两题回答/引用与资料不足拒答符合预期，内容终验通过，授权提交推送。E2 本轮最小范围完成；168 项离线回归、真实两题与主会话语义核对已记录，不将其外推为通用准确率或生产验收，不进入 E3。真实预算用完，不追加调用；运行 JSON 保持原样，验收演进见 [真实验收记录](e2d-real-review-20261105.md)。

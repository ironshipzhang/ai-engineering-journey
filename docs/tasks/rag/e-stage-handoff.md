# 任务 E 阶段交接：E1–E3（最终验收完成）

更新日期：2026-11-08。**任务 E（E1、E2a–E2d、E3）的既定学习范围已通过主会话独立复核及用户最终确认，正式验收完成。** 完整 Toy Agent 尚未完成，MCP 等后续阶段仍待开展。本次仅文档收尾，不重复测试或真实请求。

## 阶段职责与当前链路

| 阶段 | 解决的问题与主要产物 | 任务 / 交接 |
| --- | --- | --- |
| E1 | 三份虚构资料切块，建立原文来源、确定性 ID 和构建清单；prepare/check 管理准备产物与变化检查，不生成向量 | [任务](e1/e1-corpus-preparation.md) / [交接](e1/e1-corpus-handoff.md) |
| E2a | 验证百炼远程编码，保存文档块和问题的向量及请求记录 | [任务](e2a/e2a-remote-embedding.md) / [交接](e2a/e2a-embedding-handoff.md) |
| E2b | 将已有文档向量与 E1 原文关联成可校验 JSON；用问题向量做余弦检索，返回候选、分数和来源 | [任务](e2b/e2b-json-retrieval.md) / [交接](e2b/e2b-json-retrieval-handoff.md) |
| E2c | 接收新问题，前检后只编码该问题，复用 E2b 检索；产物记录问题向量、候选与用量 | [任务](e2c/e2c-live-query-retrieval.md) / [交接](e2c/e2c-live-query-retrieval-handoff.md) |
| E2d | 将问题和候选资料交给 DeepSeek，生成逐条带引用的回答，或明确资料不足；保存完整问答记录 | [任务](e2d/e2d-grounded-answer.md) / [交接](e2d/e2d-grounded-answer-handoff.md) |
| E3 | 模型提出 search_knowledge 调用，宿主校验、执行检索并按调用 ID 回传证据，次轮生成引用回答 | [任务](e3/e3-retrieval-tool.md) / [交接](e3/e3-retrieval-tool-handoff.md) |

```text
资料侧：原文 → E1 切块/来源/构建清单 → E2a 编码 → E2b JSON 文档向量
固定流程（E2c/E2d）：新问题 → 前检 → 问题编码 → 检索 → 依据资料回答 → 引用校验/复查
工具流程（E3）：新问题 → 前检 → 模型提出调用 → Registry 校验
              → 问题编码/检索 → assistant/tool 消息回传原文证据
              → 模型引用回答/资料不足 → 引用校验/最终复查 → 保存
```

两种入口均复用未变化的文档向量。E3 只允许一个检索工具往返，模型提出请求、宿主决定是否执行；工具成功仅表示取得候选，相似度不等于正确率。模型未请求检索会安全失败，不接受无证据答案。

## 入口与产物在哪里

源码入口位于 [toy-agent/src](../../../toy-agent/src/)：

- [prepare_corpus.py](../../../toy-agent/src/prepare_corpus.py)：E1 prepare/check；原始资料在 [knowledge](../../../toy-agent/knowledge/)。
- [dashscope_embedding.py](../../../toy-agent/src/dashscope_embedding.py) / [verify_embedding.py](../../../toy-agent/src/verify_embedding.py)：编码客户端 / E2a 受控验证。
- [json_retrieval.py](../../../toy-agent/src/json_retrieval.py)：E2b build/check/search。
- [live_query_retrieval.py](../../../toy-agent/src/live_query_retrieval.py)：E2c run_query 及共享检索编排。
- [grounded_answer.py](../../../toy-agent/src/grounded_answer.py)：E2d run_answer / 问答 CLI。
- [retrieval_agent.py](../../../toy-agent/src/retrieval_agent.py)：E3 run_agent / 模型调用检索工具 CLI。

运行命令见 [SETUP](../../SETUP.md)，目录约定见 [PROJECT_STRUCTURE](../../PROJECT_STRUCTURE.md)，测试位于 [toy-agent/tests](../../../toy-agent/tests/)。本地产物全部由 Git 忽略，以下链接仅在拥有对应文件的本机有效：

| 位置 | 含义 |
| --- | --- |
| [E1 正常构建](../../../test-output/rag/e1/20261028/build-001/) | 15 个片段与构建清单；不使用故意损坏的 corrupt-copy |
| [E2a 编码记录](../../../test-output/rag/e2a/e2a-20261029-001.json) | 初次远程编码验证记录 |
| [E2b 文档向量](../../../test-output/rag/e2b/e2b-vectors-20261104-001.json) | 供后续复用的原文、向量、来源与校验信息 |
| [E2c 结果目录](../../../test-output/rag/e2c/) | 两题检索记录及离线前检失败示例 |
| [E2d 迁移题](../../../test-output/rag/e2d/live-20261105-q1-001.json) / [差旅题](../../../test-output/rag/e2d/live-20261105-q2-001.json) | 两次完整问答的原始记录 |
| [E3 迁移题](../../../test-output/rag/e3/live-20261108-q1-004.json) / [差旅题](../../../test-output/rag/e3/live-20261108-q2-004.json) | 模型提出工具、检索、消息回传与回答的完整成功记录 |
| [E3 结果目录](../../../test-output/rag/e3/) | 保留 -001/-002 早期失败、-003 受控诊断和离线示例 |

E2d JSON 包含问题、embedding 子记录（问题向量/检索候选/用量）、实际证据表、generation 请求与用量、answer 和 resolved_citations。迁移题为 answered，每条 claim 绑定 source_id 与逐字 quote，本地补齐来源；差旅题为 insufficient_evidence，claims 为空并解释资料不足。它们是单次运行记录，不是新增的文档向量库，也不重复保存全量文档向量。

E3 JSON 在此基础上记录初始快照、工具提议/校验/实际执行轨迹、call_id、规范化调用和 assistant/tool 消息交换；生成按 routing/answer 两轮记录，embedding 独立记用量。失败也留痕，不能将提议、执行、候选足够和回答受支持混为同一指标。

## 验收依据分层记录

1. **离线机制测试**：主会话此前独立完整回归 **199 项通过**（E2d 阶段为 168 项）。覆盖前检、工具协议、消息绑定、引用、变化检测、失败与用量等；本次文档收尾未重跑。
2. **真实运行**：E2d 两题固定问答通过；E3 修正后 -004 两题各两次 DeepSeek、一次问题编码与一次 search_knowledge，保存/引用校验通过。两阶段为不同调用批次，全部失败和诊断也保留。
3. **主会话内容核对**：E3 迁移题五条结论由完整原文支持，保留禁止直接重跑与验证前提；差旅题限定本次资料不足，无住宿标准编造。消息 ID/query、1024 维、检索复算和来源切片均独立核对一致。
4. **用户最终确认**：2026-11-08 用户确认上述结果符合预期，关闭 E3 及任务 E 本轮最小范围。E2 的 2026-11-05 验收与当时提交推送授权仍作为历史保留，本次不提交推送。

[E2d 两题验收](e2d/e2d-real-review-20261105.md) 与 [E3 真实复核/最终确认](e3/e3-real-review-20261108.md) 分别记录实际证据。程序只检查结构、引用来自本次证据表且引文逐字存在；主会话审阅与用户终验在文档中记录，原始 JSON 的 `semantic_review=not_performed` 不修改，不能说运行时自动验证了语义支持。

E3 的额外 `index:0` 由 -003 受控诊断确认；仅兼容该可选整数 0，校验后移除，业务参数保持严格。没有原始证据的 -001/-002 不倒推为同一根因。详见 [失败、诊断与修正过程](e3/e3-real-review-20261108.md)。

## 限制与停止点

两题通过不代表通用准确率。更多问法、部分可答或跨文档复杂问题、真实故障、注入鲁棒性及生产并发/恢复可靠性仍未验证。当前使用小规模 JSON、手动全量准备、快照检查和普通文件保存；没有生产级锁、事务恢复或自动更新承诺。历史实验、失败和修正记录均保留。

**任务 E 本轮既定学习范围已完成，完整 Toy Agent 尚未完成。** 下一计划项为最小 MCP，仍未开展；失败策略、端到端评估、CLI 演示收尾及可选探索保持原计划，需用户后续选择和授权，不自动推进。

## 状态演进

2026-11-05 初版只覆盖 E1–E2d，E2 已验收、E3 当时未开展；E2 实现提交推送为 `c453fa1`，阶段文档收尾为 `2ae5993`。2026-11-08 E3 经真实失败、安全诊断与最小兼容修正后完成两题真实链路，随后主会话独立复核及用户最终确认通过。本次补齐 E3 并同步最终状态，不删除前序实验或失败记录，不改功能代码、配置和历史产物，不读取密钥、调用模型、提交或推送。

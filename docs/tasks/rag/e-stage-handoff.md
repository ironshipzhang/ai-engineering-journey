# 任务 E 阶段交接：E1–E2d

日期：2026-11-05。**E1–E2d 已完成本轮约定范围，E2 已通过主会话复核与用户内容验收；任务 E 整体尚未完成，E3 未开展。** 实现已提交并推送：`c453fa1 — feat: complete E2 grounded document question answering`。本次仅整理文档，不重复测试或真实请求。

## 阶段职责与当前链路

| 阶段 | 解决的问题与主要产物 | 任务 / 交接 |
| --- | --- | --- |
| E1 | 三份虚构资料切块，建立原文来源、确定性 ID 和构建清单；prepare/check 管理准备产物与变化检查，不生成向量 | [任务](e1/e1-corpus-preparation.md) / [交接](e1/e1-corpus-handoff.md) |
| E2a | 验证百炼远程编码，保存文档块和问题的向量及请求记录 | [任务](e2a/e2a-remote-embedding.md) / [交接](e2a/e2a-embedding-handoff.md) |
| E2b | 将已有文档向量与 E1 原文关联成可校验 JSON；用问题向量做余弦检索，返回候选、分数和来源 | [任务](e2b/e2b-json-retrieval.md) / [交接](e2b/e2b-json-retrieval-handoff.md) |
| E2c | 接收新问题，前检后只编码该问题，复用 E2b 检索；产物记录问题向量、候选与用量 | [任务](e2c/e2c-live-query-retrieval.md) / [交接](e2c/e2c-live-query-retrieval-handoff.md) |
| E2d | 将问题和候选资料交给 DeepSeek，生成逐条带引用的回答，或明确资料不足；保存完整问答记录 | [任务](e2d/e2d-grounded-answer.md) / [交接](e2d/e2d-grounded-answer-handoff.md) |

```text
新问题 → 前检 → 问题编码 → 检索候选 → 本次证据表 S1–S3
      → 生成前复查 → 依据资料回答 → 引用校验 → 最终复查 → 保存结果
```

这是固定问答流程，复用未变化的文档向量，不由 Agent 决定是否检索。E2c 到“找到候选”为止，E2d 才组织回答；相似度不等于正确率，有候选也不代表足以回答。

## 入口与产物在哪里

源码入口位于 [toy-agent/src](../../../toy-agent/src/)：

- [prepare_corpus.py](../../../toy-agent/src/prepare_corpus.py)：E1 prepare/check；原始资料在 [knowledge](../../../toy-agent/knowledge/)。
- [dashscope_embedding.py](../../../toy-agent/src/dashscope_embedding.py) / [verify_embedding.py](../../../toy-agent/src/verify_embedding.py)：编码客户端 / E2a 受控验证。
- [json_retrieval.py](../../../toy-agent/src/json_retrieval.py)：E2b build/check/search。
- [live_query_retrieval.py](../../../toy-agent/src/live_query_retrieval.py)：E2c run_query 及共享检索编排。
- [grounded_answer.py](../../../toy-agent/src/grounded_answer.py)：E2d run_answer / 问答 CLI。

运行命令见 [SETUP](../../SETUP.md)，目录约定见 [PROJECT_STRUCTURE](../../PROJECT_STRUCTURE.md)，测试位于 [toy-agent/tests](../../../toy-agent/tests/)。本地产物全部由 Git 忽略，以下链接仅在拥有对应文件的本机有效：

| 位置 | 含义 |
| --- | --- |
| [E1 正常构建](../../../test-output/rag/e1/20261028/build-001/) | 15 个片段与构建清单；不使用故意损坏的 corrupt-copy |
| [E2a 编码记录](../../../test-output/rag/e2a/e2a-20261029-001.json) | 初次远程编码验证记录 |
| [E2b 文档向量](../../../test-output/rag/e2b/e2b-vectors-20261104-001.json) | 供后续复用的原文、向量、来源与校验信息 |
| [E2c 结果目录](../../../test-output/rag/e2c/) | 两题检索记录及离线前检失败示例 |
| [E2d 迁移题](../../../test-output/rag/e2d/live-20261105-q1-001.json) / [差旅题](../../../test-output/rag/e2d/live-20261105-q2-001.json) | 两次完整问答的原始记录 |

E2d JSON 包含问题、embedding 子记录（问题向量/检索候选/用量）、实际证据表、generation 请求与用量、answer 和 resolved_citations。迁移题为 answered，每条 claim 绑定 source_id 与逐字 quote，本地补齐来源；差旅题为 insufficient_evidence，claims 为空并解释资料不足。它们是单次运行记录，不是新增的文档向量库，也不重复保存全量文档向量。

## 验收依据分层记录

1. **离线机制测试**：完整回归 168 项通过，主会话独立复核。覆盖前检、格式/引用、变化检测、失败与用量等机制；生成密钥前检问题及修正过程保留在 [E2d 交接](e2d/e2d-grounded-answer-handoff.md)。本次文档收尾未重跑测试。
2. **两题真实运行**：新问题编码到生成、引用校验和保存均完成，共 2 次 embedding + 2 次生成，无重试或文档重编码；这与 E2c 早先仅检索的两次调用是不同批次。
3. **主会话逐条内容核对**：迁移题的结论保留“部分执行或状态无法确认”等限制，逐字引文及完整原文支持对应结论；差旅题限定为本次资料不足，没有编造住宿标准。该环节是主会话 AI 辅助内容审阅，不是程序自动语义核查。
4. **用户最终确认**：用户查看汇报后明确表示“符合预期”，完成本轮约定范围的内容终验，并授权当时的提交推送。

具体回答、逐条 claim—quote—完整原文核对、用量及用户最终确认见 [两题真实验收记录](e2d/e2d-real-review-20261105.md)。程序仅检查结构、来源属于本次证据表及引文逐字存在；不能由此证明结论正确。原始 JSON 的 `semantic_review=not_performed` 保持不变，后续审阅与用户确认记录在文档中，不回写成程序自动通过。

## 限制与停止点

两题通过不代表通用准确率。更多问法、部分可答或跨文档复杂问题、真实故障、注入鲁棒性及生产并发/恢复可靠性仍未验证。当前使用小规模 JSON、手动全量准备、快照检查和普通文件保存；没有生产级锁、事务恢复或自动更新承诺。历史实验、失败和修正记录均保留。

**E3 尚未开展，需用户后续选择和授权。** 今天不设计、不实现 E3，不新增其任务书。本次仅完成阶段交接，未读取真实密钥、调用模型、修改运行结果、提交或推送。

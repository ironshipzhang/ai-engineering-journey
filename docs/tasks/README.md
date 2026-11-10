# 任务索引

任务书描述授权范围，交接描述实际实现、验证和限制。历史记录按日期阅读，最新完成状态见 [PROGRESS](../PROGRESS.md)。

| 阶段 | 任务书 / 讨论 | 交接 |
| --- | --- | --- |
| C：运行结果与轨迹 | [任务说明](agent/run-result-and-trace.md) | 实现与验收记在说明及进度中 |
| D：多项目与注册表 | [任务及交接](agent/multi-project-registry.md) | 同左 |
| D2：双工具批次 | [任务及交接](agent/two-tool-batches.md) | 同左 |
| E：前序讨论 | [概念](rag/discussions/rag-design-discussion.md)、[场景与生命周期](rag/discussions/rag-scenario-and-lifecycle-discussion.md) | 保留讨论演进 |
| E1：资料准备 | [任务书](rag/e1/e1-corpus-preparation.md) | [交接](rag/e1/e1-corpus-handoff.md) |
| E2a：远程编码验证 | [任务书](rag/e2a/e2a-remote-embedding.md) | [交接](rag/e2a/e2a-embedding-handoff.md) |
| E2b：JSON 与独立检索 | [任务书](rag/e2b/e2b-json-retrieval.md) | [交接](rag/e2b/e2b-json-retrieval-handoff.md) |
| E2c：新问题编码与检索 | [任务书](rag/e2c/e2c-live-query-retrieval.md) | [离线实现及复核](rag/e2c/e2c-live-query-retrieval-handoff.md)，两题真实记录复核通过 |
| E2d：资料问答与引用 | [任务书](rag/e2d/e2d-grounded-answer.md)、[两题真实审阅](rag/e2d/e2d-real-review-20261105.md) | [实施与复核交接](rag/e2d/e2d-grounded-answer-handoff.md)，168 项回归及两题真实主会话审阅通过；用户已确认符合预期，E2 本轮最小范围完成 |
| E3：模型调用资料检索 | [任务书](rag/e3/e3-retrieval-tool.md)、[真实复核](rag/e3/e3-real-review-20261108.md) | [离线实施交接](rag/e3/e3-retrieval-tool-handoff.md)，最终回归 199 项通过；诊断及 index:0 修正后两题真实通过，主会话独立复核与用户最终确认均通过，E3 本轮范围完成，保留失败历史 |
| F：最小 MCP 接入 | [任务书](mcp/f-minimal-mcp.md) | [实现与验收交接](mcp/f-minimal-mcp-handoff.md)，2026-11-10 用户最终确认；独立 219 项回归、一次真实运行及内容复核通过，本轮范围完成 |

E1–E3 的职责、入口、产物及验收边界汇总见 [任务 E 阶段交接](rag/e-stage-handoff.md)。2026-11-08 用户最终确认，任务 E 的既定学习范围正式验收完成；任务 F 已通过主会话离线/在线复核及用户最终确认，既定学习范围完成；G/H/I 等后续阶段尚未开展。

源码、测试和本地结果位置见 [项目目录](../PROJECT_STRUCTURE.md)。2026-11-04 目录整理未启动 E2c；2026-11-05 离线实现状态见对应交接。

[E3 真实交互回顾](rag/e3-deepseek-interaction-walkthrough.md)：结合迁移与差旅两题，拆解两轮请求、工具消息、两层 JSON 与最终展示，便于学习复盘。

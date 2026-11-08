# 任务 F：一个只读项目工具的本地 MCP 接入

日期：2026-11-08。状态：主会话已完成设计与任务书，待独立实现；不是实现或验收报告。

## 目标与授权

用户已确认 E1–E3 完成，授权在新任务会话实现 F。先解释最小设计，再顺序完成 F1、F2；本轮可安装必要的公开依赖、阅读官方资料和运行本地测试，不读取真实密钥、不调用模型或 Embedding API。真实演示需先报告具体项目、任务与预算，待用户另行确认。不得自动提交、推送或进入失败策略等后续阶段。

理解 MCP Client 是宿主内部的通信组件；MCP Server 提供工具；DeepSeek 提出调用，宿主决定是否执行。MCP 统一发现、调用与结果封装，不替代各工具业务 schema、权限或结果有效性检查。

## 开始前阅读

- AGENTS.md、README.md、docs/PROGRESS.md、docs/PROJECT_STRUCTURE.md。
- docs/TOY_AGENT_ROADMAP.md、docs/tasks/agent/two-tool-batches.md。
- docs/tasks/rag/e3-deepseek-interaction-walkthrough.md、rag/e-stage-handoff.md（均相对 docs/tasks）。
- toy-agent/src/deepseek_summary.py：load_projects、get_project、参数校验、SUMMARY_PROMPT、结果与用量契约；以及对应测试。
- toy-agent/src/grounded_answer.py、retrieval_agent.py：配置前检、无重试/重定向的生成传输、输出预留、受控协议诊断及工具调用规范化；及相关测试。
- toy-agent/pyproject.toml、uv.lock。

保留已有工作区改动与历史产物，不重写旧实验和 E 验收记录。同一时间仅本会话修改工作区。

## 技术选择与核实

采用官方 Python MCP SDK、本地 stdio 传输，Python 继续使用 toy-agent/.venv；不自行实现 JSON-RPC、消息分帧或协议版本协商，不引入高层 Agent 框架。

主会话 2026-11-08 已查阅：

- 官方 SDK：https://github.com/modelcontextprotocol/python-sdk （MIT）。
- 官方 SDK 文档：https://py.sdk.modelcontextprotocol.io/ 。
- 包元数据：https://pypi.org/pypi/mcp/json 。
- 架构：https://modelcontextprotocol.io/docs/learn/architecture 。
- 客户端教程：https://modelcontextprotocol.io/docs/develop/build-client 。

实现前复核实际可安装稳定版本、该版本官方示例、Python 3.12/macOS arm64 兼容、许可证、直接/传递依赖及安装成本。不同文档版本的生命周期/API 可能不同：以锁定版本的文档和真实运行核对，不混用教程。记录所选版本、协议版本及来源；默认只安装必要 SDK，不默认添加 cli/Inspector/HTTP 服务开发额外依赖。依赖声明与 uv.lock 同步纳入管理。SDK 不兼容时先说明具体阻碍，不擅自升级 Python 或换高层框架。

## 最小架构

```text
用户输入 project_id + summary
  → 宿主：配置/输出前检，准备本次项目快照
  → direct：本地 get_project 适配器
    或 mcp：SDK Client → stdio Server → get_project
  → 相同业务结果校验
  → 按模型调用 ID 回传 tool 消息
  → DeepSeek 最终三字段摘要（本轮以假响应测试）
```

仅暴露 get_project(project_id)，不暴露 list_project_issues、search_knowledge、文件系统或任意命令。F 只支持 summary；保留旧入口、旧 Registry 的 D2 双工具行为、E2/E3 对外行为与提示词。不要为本任务重构整个项目。

建议增加独立的项目 MCP Server 模块、客户端适配模块和 F 演示入口，源码仍在 src、测试在 tests。具体文件命名由实现会话决定并在交接解释。允许小范围提取共享纯函数，前提是旧行为及测试保持。

## F1：先独立跑通真实本地协议

1. Server 复用 load_projects/get_project 的业务校验，不复制业务实现。启动时读取一次项目快照，整个 Server 生命周期复用；每个 F 运行启动一个 Server，运行结束关闭。direct 路径也每次运行读取一次快照。下一次运行才看到文件新内容；不做监听或热更新。
2. get_project 参数必须且仅有非空字符串 project_id；业务结果必须且仅有 project_id/name/status 三个非空字符串。未知项目为明确工具失败。单独调用 Server 时也拒绝额外字段和错误类型，不能只依赖宿主校验或 SDK 自动类型转换。
3. Client 按锁定 SDK 完成连接、能力/版本准备、tools/list、tools/call 与关闭；至少一次真实 SDK Client ↔ Server 子进程调用，不以 mock 通信代替本地集成测试。
4. 宿主仅接受名为 get_project 的预期工具并验证其描述/schema 满足本任务契约；不能把 Server 返回的全部工具直接开放给模型。发现不兼容 schema 时在模型请求前停止。
5. 明确 MCP 结果中的结构化数据/文本内容如何解包；成功只接受约定业务对象。工具错误标记、协议错误、非法/缺失/冲突数据分别失败，不把错误文字当正常项目状态，不静默丢弃未知类型后宣布成功。
6. 固定本机虚拟环境解释器与受控 Server 入口，按源码定位数据，使用参数数组启动，无 shell 拼接。Server 不读取或接收模型密钥；避免把父进程无关秘密环境变量传给子进程。Server stdout 仅协议消息，日志走 stderr，诊断不打印配置或完整环境。
7. 为启动/协议准备、发现、调用和关闭设置有界等待（建议各 10 秒，测试可注入更短值）；说明实际覆盖范围。正常、异常和取消都清理 Client、管道、子进程；有界退出失败时终止并回收受控子进程。不自动重连、重启、重试或 fallback 到 direct；SDK 自身行为须核对。

## F2：接入有界 Agent，并保留 direct 比较

独立 F 入口提供显式 direct/mcp 执行方式（建议 --transport direct|mcp，默认 direct），项目默认 xingqiao；只支持 summary。两种方式复用同一业务结果契约和新 F 编排，不把旧五轮 Loop 的所有能力扩展到 MCP。

每次运行最多两次 DeepSeek 请求、一次业务工具执行：

- 第一次只提供 get_project。模型可提出调用；必须恰好一个合法调用，参数 project_id 与用户目标逐字一致。未调用工具不得发布项目摘要，也不能断言项目不存在。
- 严格解析参数 JSON（含重复键拒绝）、工具名、字段/类型、调用 ID。复用已有受控 index:0 规范化经验，不复制过度严格的传输层字段相等问题；不扩大业务参数权限。未经校验不执行。
- 工具成功后追加 assistant 调用及对应 tool 消息，tool_call_id 与模型调用 ID 绑定。MCP 请求 ID 是另一层关联信息，不能替代模型 ID；若 SDK 无公开可用 ID，记录本地事件关联号，不编造 wire ID。
- 第二次请求不提供 tools，只接受正常 assistant/stop 和三字段摘要。字段必须且仅有 progress/blockers/next_steps，每项为非空字符串，数组可空；拒绝重复 JSON 键、额外字段、截断及再次工具调用。
- 复用 SUMMARY_PROMPT 的内容原则，不开展旧摘要样例调优。业务事实质量与结构成功仍分别判断。

复用已有安全配置前检、无重试/重定向的生成传输与必要响应处理；不要直接沿用旧入口较宽松的传输/密钥校验。输出预留、参数、配置与项目范围前检，以及 mcp 模式下的 Server/工具发现检查，都须先于首次模型请求。资料/向量不是 F 的前置条件，不读取 Embedding 配置或 E 产物。

保持当前模型、每次输出上限 800 tokens、网络操作 30 秒超时；整个流程不是 30 秒总超时。messages 设置并说明有界大小（沿用 16 KiB），不截断业务数据。配置/工具错误不会触发模型请求补偿或自动修复。

## 运行结果与输出

F 本地结果归档 test-output/mcp/f/；独立入口支持 --output，预留并拒绝覆盖，写入失败非零退出，不能为覆盖失败发起模型请求。无需为所有模式新增结果文件强制要求，但离线演示应保存一个安全样例。

结果至少包含：成功/失败、transport、project_id、summary、安全 error.stage/category、实际模型尝试数、实际业务工具调用数、已知 token 用量及完整性、有序 trace。mcp 模式区分协议准备、发现、调用、工具错误和清理事件；这些协议消息不算模型请求，也不算重复业务执行。

在请求发出前增加尝试计数；收到有效用量先保存，再判断响应是否可用。缺失用量不记为零且完整性为 false；失败保留此前已知记录。成功摘要后若清理失败，应明确运行失败及 summary 非有效发布状态，不静默报告全程成功。SDK/Pydantic 异常可能包含输入，转换为受控诊断，不能直接输出完整异常或原始响应。

## 离线验收

先基线回归，再实现与运行必要测试。199 项是此前主会话验证结果，不能代替本次实际运行。

- direct 与真实 stdio MCP 对同一静态测试数据返回相同业务对象；摘要不要求不同真实模型请求逐字一致。
- 发现工具、schema 检查、非默认 cwd、虚拟环境解释器与数据路径正确。
- Server 侧未知项目/空值/错类型/额外字段拒绝；宿主阻止目标项目不匹配、未知工具、重复键、非法 ID、多调用；拒绝时零业务执行。
- 启动、发现、调用超时及子进程异常；工具错误/畸形结果不当成功；所有路径有界清理。针对自有边界测试，不遍历 SDK 内部实现。
- 模型使用假配置/假响应，但 mcp 成功路径经过真实本地子进程，验证 assistant/tool ID 绑定、两次上限及结果回传，不调用公网模型。
- 未调用工具、第二次再调用工具、length、HTTP 错误、缺失用量、部分成功、输出覆盖与保存失败。
- 假密钥不传 Server、不出现在安全诊断；原 D2/E2/E3 回归保持。

完整离线回归从仓库根执行：

```bash
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'
```

本地子进程测试属于离线机制验证，不得描述为 DeepSeek 真实在线验证。

## 真实演示提案（本轮不执行）

离线通过后建议仅一题：xingqiao / summary，transport=mcp。最多 2 次 DeepSeek HTTP 尝试、1 次 get_project，无 Embedding、无重试、失败即停。每请求输出上限 800 tokens，使用现有 DeepSeek 配置。先由主会话复核，再由用户明确确认具体预算；不自动追加 direct 的付费比较或失败复测。

## 收尾与交接

- 新建同目录 f-minimal-mcp-handoff.md：版本/来源/协议与依赖、实际模块与入口、schema 映射、错误处理、超时及进程清理、测试结果、已知限制、真实演示提案。
- 简洁更新 PROGRESS、SETUP、ARCHITECTURE、任务索引；实际产生重要取舍时更新 DECISIONS，新增路径同步 PROJECT_STRUCTURE。路线/SVG 只标实际状态，不因离线通过宣称 F 真实验收完成。
- 执行 git diff --check，报告实际命令、结果与未验证范围。依赖及锁文件纳入 diff；不提交密钥、test-output 或环境文件。
- 完成离线实现后停止，交回主会话复核，不自动调用 API、提交/推送或推进下一阶段。

# 任务 D：实现与交接（2026-10-12）

> 本文保留任务 D 当时的单调用设计及验收事实。后续主会话已决定通过独立任务 D2 支持每轮 1～2 个调用，最新实现与真实验证见 [D2 交接](two-tool-batches.md)；下方旧失败的原始调用数量和名称仍未知。

任务 D 实现与离线机制验收已通过主会话复核；真实 summary 路径成功，真实 issues 目前只有调用数量拒绝记录，双工具成功验证尚未完成。此次仅整理交接，未提交、推送或开展任务 E。

## 最小设计与修改理由

- `toy-agent/data/projects.json` 保存两个虚构项目：xingqiao 有问题记录，yunfan 的 issues=[]。模块定位路径；每任务完整读取并校验一次，工具共用快照，下次运行重新读取。没有数据库或通用访问层。
- `TOOL_REGISTRY` 用 dict + 小型 dataclass 关联 schema、参数校验和执行适配函数。请求从 Registry 提取工具定义，Loop 按名称校验和分发，不写死单工具。
- get_project 只返回 ID、名称、概况；list_project_issues 只返回 ID、问题列表。模型参数都只有非空字符串 project_id；本地执行额外接收任务快照，快照不属于模型参数。
- CLI 增加 --project-id（默认 xingqiao）与 --task（summary / issues，默认 summary）。TASK_TOOLS 检查最终回答前必需的目标成功结果，模型决定顺序；不强制工具选择，不自动补调用。
- 缓存键是工具名与校验后参数的排序紧凑 JSON，工具间隔离、保留原始参数值；命中仍使用当前调用 ID。失败不缓存、不重试。保持五次请求上限、每轮一个工具及任务 C 的结果和保存边界。
- 新增 task_validation、data_loading 失败阶段；数据损坏不会伪装成空问题列表。工具意外异常也返回安全失败记录，保留已知用量与先前轨迹。

## 离线验证

```sh
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py' -v
```

实际结果：60 项测试通过，原 45 项保留核心断言并适配快照与新工具，新增 15 项。测试使用临时文件、假密钥和预设响应；未读取 config/local.toml 或其他真实密钥，不调用模型。

覆盖：默认 CLI 兼容；显式项目/任务及结果保存；两项目数据和工具返回职责；完整 Registry 定义/校验/执行来源；两个调用顺序；缺少必要结果拒绝；非法参数/未注册/越界不执行；未知项目失败；空 issues 成功；数据缺失/编码/JSON/结构/重复 ID 拒绝；启动目录无关；任务快照与下次更新；缓存隔离和当前 ID 绑定；工具失败保留事件与用量；第五轮不执行新工具、无第六轮；未知用量及输出预留/覆盖/写入/刷新/关闭边界。

## 两种模拟运行

以下摘要及 token 用量都是人为预设响应，用来验证流程、计数和展示。不是模型生成结果，不作内容质量验收。

| 任务 | 目标 | 状态 | 请求 | 执行 | 缓存命中 | 已知模拟 tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| summary | xingqiao | succeeded | 3 | 1 | 1 | 45，complete=true |
| issues | yunfan | succeeded | 3 | 2 | 0 | 45，complete=true |

summary 的轨迹：

```text
model_request #1 tool_calls
→ tool_execution get_project({project_id: xingqiao}) succeeded，ID=summary_1
→ model_request #2 tool_calls
→ cache_hit get_project({project_id: xingqiao})，ID=summary_cached
→ model_request #3 stop → 三字段摘要成功
```

模拟摘要包含接口完成与详情联调、迁移失败和小林排查、周五演示风险、修复后联调及计划。

issues 的轨迹（先问题、后概况）：

```text
model_request #1 tool_calls
→ tool_execution list_project_issues({project_id: yunfan}) succeeded，ID=issues_1，issues=[]
→ model_request #2 tool_calls
→ tool_execution get_project({project_id: yunfan}) succeeded，ID=issues_2
→ model_request #3 stop → 三字段摘要成功
```

模拟摘要包含导入导出已验证、手册正在编写、问题记录为空；blockers=[]；下一步为完成手册后内部试用，时间尚未确认。空问题记录没有被混同为不存在的项目。

本地完整模拟结果与终端展示保存在已忽略的 `test-output/agent/d/task-d-summary-simulated.json`、`test-output/agent/d/task-d-issues-simulated.json` 及同名 `.txt`；JSON 外层 source 明确标记预设离线响应，并包含项目、任务和完整 result。非空问题的 issues 任务、反向顺序、两个工具重复缓存由单元测试覆盖。

## 限制与主会话复核项

- 实现阶段只做离线验证；随后用户提供的真实 summary 成功、真实 issues 首轮调用数校验失败（见下方分项记录），尚无真实双工具成功运行或 issues 摘要质量验收；succeeded 仅代表取数条件、执行与结构校验通过，不能保证事实正确。共享 SUMMARY_PROMPT 内容质量规则及历史评估保持冻结。
- 整个数据文件一次校验，任何坏记录使本任务失败；status 为非空文本，不限制状态枚举。只用于小型虚构数据，未实现数据热更新、跨任务缓存、MCP、RAG、写操作或新依赖。
- summary 同时提供两个工具，允许模型额外查询目标项目问题，但概况仍是必要条件。模型不能切换项目，参数值不做去空白或大小写归一化。
- 原有网络、用量和保存限制保留：30 秒为每次网络操作超时，没有总时限或自动重试；未知计费不能当零；结果文件写入失败可留下部分内容。
- 主会话已复核实现与离线机制；调用策略的设计选择仍待主会话决定。此次不追加真实验收、不新增依赖或更改策略。
- Git 保持当前 main，代码/测试/六份指定文档及本交接文件未提交；历史 evals 与 EVALUATION.md 未改。完整改动以 `git status --short` 和 `git diff` 为准。

## 主会话复核：2026-10-12

- 检查 Git diff、数据文件、注册/校验/执行映射和测试，重跑 60 项离线测试全部通过，git diff --check 通过；没有发现阻碍任务 D 范围验收的问题。共享 SUMMARY_PROMPT、模型、API 地址和请求限制与 HEAD 一致。
- 每任务完整快照、两个工具不同职责、目标项目精确校验、TASK_TOOLS 完成条件、工具名与参数组成缓存键及当前调用 ID 绑定均符合要求。异常本地执行转为安全失败结果，保留事件与已知用量；未扩展成插件框架。
- 用户真实运行的 test-output/agent/d/d-summary-001.json 已核对：succeeded、两次请求、一次 get_project 执行、零缓存，输入 1672、输出 110、总计 1782 tokens，用量完整且与分轮记录一致。这验证新增双工具定义下的 summary 正常路径，不证明 list_project_issues 或 issues 双工具链路真实运行成功。
- 用户随后提供 test-output/agent/d/d-issues-001.json：failed，首轮 tool_calls 后在 tool_validation 因调用数不符合恰好一次要求而停止，零工具执行、零缓存，输入 761、输出 75、总计 836 tokens，用量完整。真实 issues 成功链路尚未跑通；这是调用数量约束的真实拒绝路径，不能记录为双工具成功。结果未保存原始调用列表，不能仅凭此文件确认调用数量或工具名称。
- 接受现有小规模取舍：整份坏数据使任务失败；未知目标项目在工具执行时失败，可能已产生一次模型请求；宽泛异常捕获保留安全结果，但不提供原始异常诊断。当前不要求为这些取舍增加机制或付费测试。
- 本次主会话未读取真实密钥、未调用模型、未改代码、未提交/推送或开展 E。仅补充复核记录。完整运行结果暂未额外保存 task / project_id 元数据，可由现有调用轨迹辨认，后续如需批量任务追踪再考虑扩展。


## 收尾：分项验收与待决策边界（2026-10-12）

### 1. 离线机制验收已通过

主会话确认并重跑 60 项离线测试全部通过，涵盖 Registry 校验/分发、两种任务的完成条件、两工具调用顺序、数据快照、成功缓存隔离、调用 ID 绑定及原有失败/用量/文件边界。预设模型响应只能证明程序控制符合当前设计，不能证明真实模型会按单调用要求完成任务。本次只核对已有记录，不重跑测试。

### 2. 真实 summary 路径已成功

本次重新核对 `test-output/agent/d/d-summary-001.json`：status=succeeded，2 次模型请求、1 次 get_project 执行、0 次缓存；输入 1672、输出 110、总计 1782 tokens，complete=true。

```text
model_request #1 tool_calls
→ tool_execution get_project succeeded
→ model_request #2 stop → 结构化摘要成功
```

这是提供两个工具定义时的真实 summary 正常路径，只要求并取得 get_project；没有执行 list_project_issues，不证明真实 issues 双工具任务成功，也不代替摘要内容质量验收。

### 3. 真实 issues 的调用数量拒绝路径已记录

本次重新核对 `test-output/agent/d/d-issues-001.json`：status=failed，summary=null；首轮 finish_reason=tool_calls，在 tool_validation 停止，错误为“必须恰好提出一次工具调用；不执行工具。”。1 次模型请求、0 次工具执行、0 次缓存；输入 761、输出 75、总计 836 tokens，complete=true。

```text
model_request #1 tool_calls
→ failure tool_validation：不符合恰好一次工具调用要求
→ 停止，未执行工具、未重试
```

保存结果没有原始 tool_calls 列表或实际数量。本次检查已有结果文件与本地保存的终端记录文件，只有模拟运行的 .txt，没有能证明该真实响应原始调用数量的安全终端记录。因此模型具体提出几个调用、哪些工具均保留未知；不能写成已确认两个调用，也不为确认它重新调用模型。

此前用户提供的 `d-yunfan-001.json` 与 `d-issues-002.json` 也在同一阶段失败；各记录 830 / 836 tokens，均为 1 次请求、0 次执行、0 次缓存、用量完整。这些文件也没有原始调用列表；每文件用量按保存值记录，不据此推断独立请求总数或合并账单。

校验在 Registry 名称查找及实际工具执行之前拒绝，当前失败记录不能证明工具分发、项目读取或完成条件存在故障。

此前查阅的 [DeepSeek Chat Completions 官方接口](https://api-docs.deepseek.com/api/create-chat-completion/)允许 auto 提出一个或多个工具调用；页面未列出 parallel_tool_calls 参数。该接口背景不证明这次响应具体包含多个调用，也不能证明添加某参数可强制单调用。本次未再联网查询或尝试参数。

### 4. 真实双工具成功验证尚未完成

当前没有已确认的真实 issues 成功记录；取得概况与问题列表、按任意顺序完成 Loop 的成功行为只在离线模拟中验证。summary 成功、调用数量拒绝被正确记录及 60 项测试通过，均不能补足该真实成功验证。

### 仍需主会话决定

- 继续维持每轮一个工具调用的设计边界。
- 或在独立任务中支持一轮多个工具调用。

两者是待主会话选择的设计方向，本次不自行选择、修改提示词或实现调用策略。若将来选择支持多个调用，需在独立任务明确整批准入、逐调用 ID 绑定、计数/缓存与第五轮边界；当前不删除调用数校验或只取第一项执行。

本次仅更新 `docs/PROGRESS.md` 与本交接文件，不记录密钥、请求头或原始敏感响应；未修改代码、提示词、历史评估或调用策略，未读取真实密钥、新增模型调用、提交、推送或开展 E。完成交接后停止。


## 后续设计决定：D2（2026-10-12）

主会话已明确选择在独立任务 D2 中允许每轮 1 或 2 个调用，整批校验后顺序执行，仍最多 5 次模型请求。D2 已实现并通过 71 项离线测试，一次真实 xingqiao / issues 成功：首轮两个工具按 get_project → list_project_issues 执行，次轮摘要，共 2024 tokens，保存为 test-output/agent/d2/d2-issues-001.json。完整交接见 [two-tool-batches.md](two-tool-batches.md)，待主会话复核；本补充不修改旧失败或历史验收事实。

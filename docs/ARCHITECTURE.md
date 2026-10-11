# 当前系统：有界只读 Agent Loop

入口为 `toy-agent/deepseek_summary.py`，仅使用 Python 标准库，无 Agent 框架或额外依赖。`hello.py` 独立用于检查 Python 环境。

## 数据流

```text
CLI 可选独占创建输出文件，从 TOML 本地配置读取密钥
  → Loop 初始化 messages、成功结果缓存与结构化结果
  → 最多 5 次模型请求，每轮提供 get_project + JSON 输出模式
  → 请求前计数并记录事件；独立提取已知用量，检查 finish_reason
      tool_calls → 校验单个调用 → 查询或复用成功结果
                 → 追加 assistant 调用与 tool 结果 → 下一轮
      stop       → 要求已成功取得项目数据 → 校验摘要 JSON → 返回 succeeded 结果
      其他       → 返回 failed 结果及此前轨迹
  → CLI 展示结果，可选写入 JSON；成功退出 0，失败或保存失败退出 1
```

- Loop 中的 `request_completion` 每轮发送 tools 和 response_format=json_object，省略 tool_choice（有工具时 API 默认 auto）。关闭思考、非流式，输出上限为每次 800 tokens；JSON 输出规则同时写入 system 提示。
- `validate_tool_call` 要求 tool_calls 正常结束、恰好一个 function 调用、非空 ID、工具名为 get_project；arguments 从 JSON 字符串解析，必须且仅包含非空字符串 project_id。
- `get_project` 仅支持 xingqiao，从代码内 PROJECT_STATUS 读取虚构项目状态，无写操作。模型提出调用，程序校验并显式执行。
- `run_project_summary` 的 MAX_REQUESTS=5 包含所有工具决策与最终摘要请求。第五次请求可正常提交摘要；若仍提出工具调用，校验后报超限，不执行工具、不发送第六次请求。

## 状态与缓存

messages、successful_results 和累计 token 用量均为本次函数调用的局部状态，不跨任务保存。每次模型请求重新发送所需对话历史，不依赖服务端对话 ID 保存历史。

成功缓存以解析后的 project_id 为键；因为只支持一个工具和一个参数，无需通用缓存系统。参数 JSON 的空格变化不影响缓存命中，参数值本身不做去空格或大小写归一化。函数成功返回后才写入缓存；工具失败立即终止，不缓存或重试。

缓存命中避免再次执行本地函数，但仍追加 assistant 调用记录与 tool 结果，用当前调用的 id / tool_call_id 对应。缓存不会节省该轮模型请求，也不会跳过参数校验或请求次数计数。

## 成功与失败边界

stop 响应不能携带工具调用；没有成功项目数据时，即使摘要 JSON 结构合法也拒绝展示。已有成功数据后继续使用 parse_summary 校验 progress、blockers、next_steps 三个字符串数组，允许空数组，拒绝缺字段、额外字段和空白元素。结构正确不能保证事实正确。

非法或多个调用、工具失败、length 截断、非正常结束和超限均立即终止，无自动重试。每轮用量及累计值在校验调用与摘要前记录，后续失败仍保留已确认用量；无有效用量的请求记录 null，累计 complete=false，未知不得当作零计费。每次网络操作为 30 秒超时，没有流程总时限。main 将已处理的错误转为退出码 1，不输出密钥或原始错误响应。

当前没有 MCP、RAG、写操作、跨任务缓存或持久化对话。测试与真实调用记录见 [SETUP.md](SETUP.md)，重要取舍见 [DECISIONS.md](DECISIONS.md)。

## 独立事实评估入口

`evaluate_summary.py` 读取 `evals/project_summary_cases.json`，逐条将状态和共享 SUMMARY_PROMPT 发给模型。request_completion 的 with_tools=False 仅用于这条评估路径；Loop 默认仍提供工具。每条样例一次模型请求，不进入 Loop。

有效摘要由共享 display_summary / parse_summary 校验后返回并写入新 JSON 文件，与原始状态、检查点、用量、错误和待评审标记一起保存。采集脚本不做语义评分；保存结果的 Codex 复核记录及尚未经用户逐条确认的说明见 [EVALUATION.md](EVALUATION.md)。

## 结构化运行结果与执行轨迹（2026-10-11）

run_project_summary 返回标准库 dict，不打印；已处理的失败返回 status=failed、summary=null 和安全 error。成功返回 status=succeeded、已校验 summary、error=null。succeeded 仅表示执行及结构校验通过，不能证明事实保留、字段归属或表达关联正确；当前候选的质量限制保持不变。

model_requests 在实际尝试请求前递增，包含网络失败的那次；tool_executions 在进入 get_project 前递增，包含工具失败，非法调用与第五轮拒绝不计入；cache_hits 仅计成功缓存复用。usage 的 prompt_tokens、completion_tokens、total_tokens 是累计已知值，complete 表示每次尝试的用量均有效；未发请求时零累计且 complete=true。消息异常但用量有效时仍保留用量；部分或非法用量整轮记 null，继续停止而不执行工具。

trace 按顺序保存 model_request（序号、结束原因、用量）、tool_execution（工具名、当前 ID、校验后参数、成功/失败）、cache_hit 和 failure（阶段、安全错误）。超限失败记录已校验调用的元数据但不产生执行或缓存事件；非法调用只记录校验失败，不持久化未经校验的参数。网络无响应仍有请求及失败事件。错误类别为 http_error、network_error 或失败阶段：configuration、request、response_validation、tool_validation、request_limit、tool_execution、summary_validation。

不保存密钥、请求头、原始错误响应、完整对话或内部推理；当前虚构参数可保存，将来接真实数据需另行设计脱敏。display_run_result 负责 CLI 展示；inspect_response、display_summary 等评估公共函数行为兼容。--output 用 x 模式在读取密钥及请求前预留位置，拒绝覆盖；执行失败结果也保存。保存不是事务操作，磁盘写入失败可能留下空文件或部分 JSON，CLI 返回非零，不自动删除或覆盖。

## 本地 TOML 配置

两个 CLI 共用 deepseek_summary.read_config_api_key，使用 Python 3.12 tomllib。DEFAULT_CONFIG_PATH 从脚本 __file__ 定位根目录 config/local.toml；--config 的显式相对路径保持按工作目录解析。只读取 model.api_key，不改变地址、模型、限制、提示词或 Loop/轨迹。

配置缺失、权限/编码/语法错误及字段无效均在联网前转为 SummaryError；不输出文件内容、密钥或 TOML 原始异常。Loop 在预留 --output 后读配置，失败仍保存 configuration 事件与零请求；评估入口读配置失败安全报错退出，不生成采集报告。配置为本地明文，/config/ 忽略规则不影响已跟踪文件。

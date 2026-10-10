# 当前系统：有界只读 Agent Loop

入口为 `toy-agent/deepseek_summary.py`，仅使用 Python 标准库，无 Agent 框架或额外依赖。`hello.py` 独立用于检查 Python 环境。

## 数据流

```text
读取仓库外密钥，初始化 messages、成功结果缓存与累计用量
  → 最多 5 次模型请求，每轮提供 get_project + JSON 输出模式
  → 记录本轮及累计用量，检查 finish_reason
      tool_calls → 校验单个调用 → 查询或复用成功结果
                 → 追加 assistant 调用与 tool 结果 → 下一轮
      stop       → 要求已成功取得项目数据 → 校验摘要 JSON → 展示并结束
      其他       → 明确失败并结束
```

- `request_completion` 每轮发送 tools 和 response_format=json_object，省略 tool_choice（有工具时 API 默认 auto）。关闭思考、非流式，输出上限为每次 400 tokens；JSON 输出规则同时写入 system 提示。
- `validate_tool_call` 要求 tool_calls 正常结束、恰好一个 function 调用、非空 ID、工具名为 get_project；arguments 从 JSON 字符串解析，必须且仅包含非空字符串 project_id。
- `get_project` 仅支持 xingqiao，从代码内 PROJECT_STATUS 读取虚构项目状态，无写操作。模型提出调用，程序校验并显式执行。
- `run_project_summary` 的 MAX_REQUESTS=5 包含所有工具决策与最终摘要请求。第五次请求可正常提交摘要；若仍提出工具调用，校验后报超限，不执行工具、不发送第六次请求。

## 状态与缓存

messages、successful_results 和累计 token 用量均为本次函数调用的局部状态，不跨任务保存。每次模型请求重新发送所需对话历史，不依赖服务端对话 ID 保存历史。

成功缓存以解析后的 project_id 为键；因为只支持一个工具和一个参数，无需通用缓存系统。参数 JSON 的空格变化不影响缓存命中，参数值本身不做去空格或大小写归一化。函数成功返回后才写入缓存；工具失败立即终止，不缓存或重试。

缓存命中避免再次执行本地函数，但仍追加 assistant 调用记录与 tool 结果，用当前调用的 id / tool_call_id 对应。缓存不会节省该轮模型请求，也不会跳过参数校验或请求次数计数。

## 成功与失败边界

stop 响应不能携带工具调用；没有成功项目数据时，即使摘要 JSON 结构合法也拒绝展示。已有成功数据后继续使用 parse_summary 校验 progress、blockers、next_steps 三个字符串数组，允许空数组，拒绝缺字段、额外字段和空白元素。结构正确不能保证事实正确。

非法或多个调用、工具失败、length 截断、非正常结束和超限均立即终止，无自动重试。每轮用量及累计值在校验调用与摘要前展示，后续失败仍保留已确认用量；无有效响应的请求用量无法本地确认。每次网络操作为 30 秒超时，没有流程总时限。main 将已处理的错误转为退出码 1，不输出密钥或原始错误响应。

当前没有 MCP、RAG、写操作、跨任务缓存或持久化对话。测试与真实调用记录见 [SETUP.md](SETUP.md)，重要取舍见 [DECISIONS.md](DECISIONS.md)。

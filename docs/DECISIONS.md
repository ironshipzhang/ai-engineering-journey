# 工程决策

## 2026-10-10：摘要结构由程序校验，缺字段不得补为空数组

- 约定：progress、blockers、next_steps 必填，值为字符串数组，可为空；元素必须是非空字符串。当前固定结构不接受额外字段。
- 原因：显式 [] 与未回答字段不同。自动补齐会掩盖模型遗漏，尤其可能把漏答阻塞项解释为没有阻塞项。
- 实现：请求使用 DeepSeek JSON 模式，Python 标准库解析后做本地校验；截断输出直接失败。
- 取舍：无需添加依赖，适合三个简单字段；结构复杂后再考虑 schema 校验库或模型端 schema 约束。
- 限制：JSON 语法和字段正确不保证事实正确，后者需要独立的内容评估。

## 2026-10-10：固定一次只读工具调用与两次模型请求

- 第一次请求声明 get_project(project_id: string)，指定 tool_choice 为 get_project，关闭思考；此阶段不启用摘要 JSON 模式。模型只接收查询意图和工具定义，不预先获得项目状态。
- 本地要求 finish_reason=tool_calls，恰好一个 function 调用，ID 非空，工具名为 get_project；arguments 必须是 JSON 字符串，仅包含非空字符串 project_id。随后显式调用 Python 函数，无动态函数查找或 eval。
- 仅支持虚构项目 xingqiao。非法调用或未知项目直接失败，不将错误送回模型修复，不重试。
- 第二次请求保留原对话，追加 assistant 工具调用与绑定相同 tool_call_id 的 tool 结果，不再提供 tools，启用现有摘要 JSON 模式与本地结构校验。
- 两次请求各保留 30 秒网络超时、400 输出 tokens 上限、用量与结束原因展示，均收到有效用量后显示合计。第二次请求失败时首次用量已展示；无响应的请求无法获知实际 token 用量。30 秒为每次网络操作超时，不是整个流程的总时限。
- 取舍：指定工具便于学习协议与执行边界，本次不验证模型自主选择工具的能力；固定流程没有通用 Agent Loop、MCP、RAG 或写操作。
- 官方接口参考：https://api-docs.deepseek.com/api/create-chat-completion/ （2026-10-10 查验）。

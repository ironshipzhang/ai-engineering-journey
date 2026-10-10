# 当前系统：一次只读工具调用与结构化摘要

入口为 `toy-agent/deepseek_summary.py`，仅使用 Python 标准库，无 Agent 框架或额外依赖。`hello.py` 独立用于检查 Python 环境。

## 固定数据流

```text
读取仓库外密钥
  → 第一次请求：system 规则 + user 查询意图 + tools / tool_choice
  → 记录用量，校验单个 get_project 调用
  → 本地 get_project("xingqiao") 返回虚构项目状态
  → 第二次请求：原消息 + assistant 调用记录 + tool 查询结果
  → 记录用量与两次合计，解析并校验摘要 JSON
  → 展示 progress / blockers / next_steps
```

- `request_completion` 负责 HTTP 请求；第一次指定 get_project，第二次不提供 tools，启用 JSON 输出模式。两次均关闭思考、非流式，每次最多输出 400 tokens。
- `validate_tool_call` 要求结束原因为 tool_calls、恰好一个 function 调用、非空 ID、工具名为 get_project；arguments 从 JSON 字符串解析，必须且仅包含非空字符串 project_id。
- `get_project` 显式执行本地只读查询，仅支持 xingqiao，数据来自代码内的 PROJECT_STATUS。模型只生成调用申请，程序控制执行；非法调用或未知项目直接失败。
- `run_project_summary` 按固定顺序组织两次请求，不使用循环。第二次请求重新发送所需上下文，不依靠服务端对话 ID 自动保存历史。

## 消息与关联

`system` 是程序设定的规则，`user` 是查询意图，`assistant` 记录模型提出的调用，`tool` 承载程序执行结果。assistant 调用的 id 与 tool 消息的 tool_call_id 相同；这个 ID 关联调用与结果，不代表整个对话。工具结果序列化为 JSON 字符串放入 content。

## 验证与失败边界

后续摘要须以 stop 结束，且必须仅含 progress、blockers、next_steps 三个字符串数组，允许空数组但拒绝空白元素。截断、再次调用工具或结构错误均不展示为有效摘要；结构校验不能保证事实正确。

每次网络操作设置 30 秒超时，无自动重试或流程总时限。已解析的响应用量会即时展示；第二次失败时首次用量仍保留，无响应请求的实际用量无法本地确认。错误由 main 转为退出码 1，密钥仅用于认证，不打印或写入仓库。

当前没有自主工具选择、多次工具调用、通用 Agent Loop、MCP、RAG、持久化对话或写操作。离线测试及已有真实调用记录见 [SETUP.md](SETUP.md)，重要取舍见 [DECISIONS.md](DECISIONS.md)。

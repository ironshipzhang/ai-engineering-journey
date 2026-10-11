# 最小开发环境：已完成

## 验收标准

1. Git 可运行，本目录是独立仓库。
2. Python 可运行，项目使用独立虚拟环境。
3. 一个最小 Python 程序实际运行成功。
4. 首次提交推送到用户的 GitHub 仓库。
5. 新任务会话能根据仓库文档了解进展和下一步。

## Apple Command Line Tools

终端执行：

```sh
xcode-select --install
```

在系统弹窗中完成安装，然后验证：

```sh
xcode-select -p
git --version
```

官方说明：https://developer.apple.com/documentation/xcode/installing-the-command-line-tools

## Python：已完成并验证

uv 0.12.22 和 Python 3.12.15 安装在项目内 .tools/，缓存位于 .cache/；这些机器相关文件被 .gitignore 排除。
toy-agent/.venv/ 是项目虚拟环境，toy-agent/uv.lock 记录依赖解析结果。

从项目根目录运行：

```sh
cd /Users/ironshipzhang/Documents/Codex/ai_engineer
env UV_CACHE_DIR="$PWD/.cache/uv" UV_PYTHON_INSTALL_DIR="$PWD/.tools/python" .tools/bin/uv run --project toy-agent toy-agent/hello.py
```

2026-10-02 实际输出：

```text
Toy Agent: Python environment is ready.
Python: 3.12.15
Architecture: arm64
Virtual environment: True
```

uv 管理 Python 版本、依赖与虚拟环境；虚拟环境隔离本项目的 Python 包。
hello.py 只用于验证环境，没有模型调用。

安装器报告 Python 动态库 install name 修补失败。当前程序运行正常，原生扩展构建未验证；需要时再检查。

## Git：本地初始化已完成

Apple Command Line Tools 和 Git 2.39.5 已验证，本项目已执行 git init -b main。
提交身份已按用户提供的信息设置在本仓库。初始提交包含最小文档、Python 配置和环境检查程序。
用户已提供仓库地址，origin 已配置为 git@github.com:ironshipzhang/ai-engineering-journey.git。
SSH 认证成功，首次推送已完成，main 跟踪 origin/main。

## VS Code：已安装

- VS Code 1.140.0，arm64，安装于 /Applications/Visual Studio Code.app。
- 已安装 Microsoft Python 扩展，以及自动安装的 Pylance、debugpy、Python Environments。
- 打开整个 ai_engineer 文件夹；.vscode/settings.json 默认解释器指向 toy-agent/.venv。
- 如需手动选择，使用 Cmd+Shift+P → Python: Select Interpreter，选择 toy-agent/.venv/bin/python。
- 打开 toy-agent/hello.py，使用 Python: Run Python File in Terminal；或在项目根目录终端执行 toy-agent/.venv/bin/python toy-agent/hello.py。
- 若想在终端使用 code 命令，使用 Cmd+Shift+P → Shell Command: Install 'code' command in PATH，然后重开终端。目前未修改系统 PATH。

用户已在 VS Code 实际运行 hello.py，输出验证虚拟环境已启用。

## SSH 认证：已完成（以下仅供首次配置参考）

当前设备无需重复生成密钥。用户已添加公钥；GitHub 官方 Ed25519 主机密钥已保存于 ~/.ssh/known_hosts，认证与推送均成功。

由用户在自己的终端操作，密钥和 passphrase 留在本机：

```sh
ssh-keygen -t ed25519 -C "ironshipzhang@gmail.com"
ssh-add --apple-use-keychain ~/.ssh/id_ed25519
pbcopy < ~/.ssh/id_ed25519.pub
```

生成时使用默认保存路径并自行设置 passphrase。
在 https://github.com/settings/keys 添加 Authentication Key，粘贴公钥。

随后执行 ssh -T git@github.com，首次连接核对 GitHub 官方主机指纹：
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints

成功认证的提示为 Hi ironshipzhang! You've successfully authenticated, but GitHub does not provide shell access.
这一成功测试的退出码可能仍为 1，应以提示内容判断。

## 后续模型访问

选择 DeepSeek 官方 API，初期模型使用 deepseek-flash，月度预算目标不超过 10 USD。
已于 2026-10-02 使用仓库外密钥完成一次真实调用，当前设备可以访问官方 API，认证和本次余额扣费条件满足；未查询账户余额或剩余额度。
当前两个入口默认读取仓库根目录 config/local.toml，使用 Python 3.12 标准库 tomllib，无新依赖。首次配置时在项目根目录执行（已有配置时保留原文件）：

```sh
umask 077
mkdir -p config
cp -n config.example.toml config/local.toml
chmod 600 config/local.toml
```

在本地编辑 config/local.toml，把 YOUR_API_KEY 换成真实密钥：

```toml
[model]
api_key = "YOUR_API_KEY"
```

config/local.toml 是本地明文文件；/config/ 被 Git 忽略，config.example.toml 只含占位符，可纳入版本控制。忽略规则不会移除已跟踪文件，已有跟踪需单独处理。本次已从原仓库外密钥迁移成功，权限为 0600，原密钥文件保留，无需重复复制。

运行当前工具调用与摘要流程（会联网）：

```sh
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py
```

脚本使用最多 5 次模型请求的简单 Agent Loop。已移除 --key-file；可用 --config 指定其他 TOML 路径。默认路径按脚本位置定位仓库根目录，不依赖启动目录；显式相对路径按启动时工作目录解析。例如：

```sh
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py --config ./config/local.toml --output test-output/run-002.json
```

输出文件名必须尚未存在。evaluate_summary.py 同样支持 --config；不传时使用相同默认配置。

1. 每轮 request_completion 发送当前 messages、get_project 工具定义与 response_format={"type":"json_object"}，省略 tool_choice，由模型自主选择工具调用或最终回答。
2. run_project_summary 返回结构化结果，记录每轮用量、结束原因和事件，并更新累计已知用量；CLI 由 display_run_result 展示。inspect_response 保留用于独立摘要评估。
3. tool_calls 分支由 validate_tool_call 校验工具名、类型、ID、调用数和参数；每轮只允许一个调用。首次成功查询存入任务内缓存，相同 project_id 后续复用，仍追加 assistant 与绑定当前 tool_call_id 的 tool 结果。
4. stop 分支必须已有成功项目数据，再调用原有 parse_summary 校验摘要。未查询数据的直接回答立即失败，不自动补发查询。
5. 最多 5 次模型请求；第五次若仍要求工具调用则终止，不执行该轮工具、不发送第六次请求；第五次有效最终摘要仍成功。

摘要必须且仅含 progress、blockers、next_steps；值必须为字符串数组，可为 []，元素不可是空白字符串。缺字段不自动补 []。
每次请求关闭思考、非流式、max_tokens=800、30 秒网络操作超时，无自动重试。整个流程不设置额外的总时限。
配置不存在、无法读取、TOML 无效、缺少 model.api_key、类型错误、空值、含空白或仍为示例占位符时联网前退出；非法调用、工具失败、超限、HTTP、网络和响应格式异常返回退出码 1，不打印密钥或原始错误响应。
工具调用须 tool_calls、最终摘要须 stop 正常结束；length 截断或其他结束原因直接失败。失败前已确认的每轮和累计用量保留于结果并在终端显示，未知轮次 usage=null、累计 complete=false，实际计费须查平台账单。

离线验证（不读取密钥、不调用模型）：

```sh
toy-agent/.venv/bin/python -m unittest discover -s toy-agent -p 'test_*.py' -v
```

历史记录（工具调用实现前）：2026-10-10，9 项测试通过；真实结构化调用输入 215、输出 67、总计 282 tokens，stop 正常结束。
格式校验不验证事实：即使 blockers=[] 合法，也仍需与原文对照，判断是否漏掉阻塞项。
缺少配置的验证命令（预期退出码 1）：

```sh
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py --config /private/tmp/nonexistent-agent-config.toml
```

2026-10-02 首次真实调用：输入 99、输出 54、总计 153 tokens，结束原因 `stop`。按缓存全部未命中的峰值费率估算上限约 $0.0000945；实际费用以平台账单为准。
2026-10-02 查验官方 Flash 每百万 token 价格：缓存命中输入峰值 $0.006 / 非峰值 $0.003，未命中输入 $0.30 / $0.15，输出 $1.20 / $0.60。价格页面支持文本摘要所需的非思考模式；首次真实调用验证当前本地网络可达，未单独核实其他地区的可用性。
预算目前是目标，尚未实现自动预算拦截。

官方入口：https://platform.deepseek.com/
价格与能力：https://api-docs.deepseek.com/quick_start/pricing/
价格查验日期：2026-10-02。具体费率以实际调用时官方页面为准。

## 历史验证：固定一次只读工具调用（2026-10-10）

- 16 项离线测试通过（原摘要校验 9 项 + 工具流程 7 项），不读取密钥、不联网。
- 真实执行成功，退出码 0：get_project 参数为 {"project_id":"xingqiao"}，本地只读函数执行一次。
- 首次：输入 448、输出 36、总计 484 tokens，finish_reason=tool_calls。
- 后续摘要：输入 335、输出 75、总计 410 tokens，finish_reason=stop。
- 合计：输入 783、输出 111、总计 894 tokens。以全部输入未命中的峰值价格估算费用上限约 $0.0003681，实际扣费以账单为准。
- 人工核对摘要：登录和列表接口完成、12 个测试通过、详情联调、数据库迁移失败、小林排查及演示延期风险均保留；下一步包括修复迁移和完成联调。
- 2026-10-10 再查验官方价格与能力：deepseek-flash 支持 Tool Calls 和 JSON Output；每百万 token 缓存命中输入 $0.006 / $0.003、未命中输入 $0.30 / $0.15、输出 $1.20 / $0.60（峰值 / 非峰值）。本地真实调用验证当前设备可达；未查询账户剩余额度或验证其他地区。
- 查验来源：https://api-docs.deepseek.com/quick_start/pricing/ 与 https://api-docs.deepseek.com/api/create-chat-completion/。
- 结构正确不能保证事实正确，本次只人工核对一个虚构项目，不宣称已建立内容评估集。

### Handoff 验证补充

- 文档交接时重新运行上述离线测试命令：16 项全部通过；未读取真实密钥、未重复执行付费调用。
- 用户提供的本地终端输出：首次输入 448、输出 36、总计 484 tokens，tool_calls；后续输入 335、输出 67、总计 402 tokens，stop；合计输入 783、输出 103、总计 886 tokens。该记录来自用户实际运行输出，不是本次离线测试生成。
- 对照代码内虚构数据，用户运行的摘要包含完成接口、12 个单元测试、详情联调、迁移失败、小林排查、演示延期风险和下一步计划。虚构数据中的“12 个单元测试”是项目状态文本，不是本仓库当前的 16 项测试数量。
- 未验证：真实 API 的非法调用、超时和 HTTP 失败场景；未建立事实质量评估集。当前超时测试通过模拟异常验证首次用量保留，不证明真实网络会在整个流程 30 秒内结束。

## 当前 Agent Loop 验证：2026-10-10

- 24 项离线测试通过（摘要校验 9 项、工具与 Loop 15 项），覆盖正常结束、重复参数结果复用与当前 ID 绑定、任务间缓存隔离、失败不重试、无数据直接回答拒绝、非法与多个调用、截断、第五轮正常结束、超限无第六次请求、累计用量和网络限制。
- 官方接口列出 tools 与 json_object 参数，工具默认 auto；文档未单独明确保证组合行为，本次用一次真实流程确认当前 deepseek-flash 非思考模式可同时使用。
- 真实运行退出码 0：第 1 轮输入 481、输出 41、总计 522 tokens，tool_calls；第 2 轮输入 635、输出 67、总计 702，stop；累计输入 1116、输出 108、总计 1224 tokens。
- 人工核对摘要：接口完成、12 个单元测试、详情联调、迁移失败、小林排查、延期风险及下一步计划均保留。文本中的“12 个单元测试”来自虚构数据，非本仓库测试数量。
- 按此前查验的全部输入未命中峰值费率估算费用上限约 $0.0004644；实际扣费以账单为准，未查询余额。
- 未验证：真实模型重复调用、直接回答、非法调用、超限或 HTTP 失败场景。这些控制路径以离线模拟验证，不为异常场景额外发送付费请求；事实质量仍只人工检查一个虚构项目。
- 接口查验来源：https://api-docs.deepseek.com/api/create-chat-completion/ 。

## 小型事实质量评估

新增独立评估入口 `toy-agent/evaluate_summary.py`，无新依赖；使用本地 TOML 配置，以 6 次模型请求采集摘要并保存新 JSON 文件。具体命令、首轮用量与复核标准见 [EVALUATION.md](EVALUATION.md)。原 Agent Loop 的运行命令保持不变。

首次六条评估阶段的离线验证共 30 项全部通过。真实评估 6 条结构全部通过、共 1392 tokens；事实质量由单独初评记录，不能由测试通过或脚本退出码判断。

## 指定评估集：2026-10-11

Evaluate 新增可选 --cases 参数；省略时仍使用 toy-agent/evals/project_summary_cases.json 的原六条样例，无新依赖。31 项离线测试通过，运行 Loop 的命令不变。

例如运行包含原六条与新增两条的组合集（会产生 8 次摘要请求费用，输出文件须不存在）：

```sh
toy-agent/.venv/bin/python toy-agent/evaluate_summary.py --cases toy-agent/evals/comparison_cases_20261011.json --output /private/tmp/project-summary-comparison-new.json
```

仅采集新增两条时，--cases 指向 toy-agent/evals/transfer_cases_20261011.json。脚本始终使用当前代码的共享 SUMMARY_PROMPT，没有历史提示词选择开关；本轮旧提示词的两条结果是在改词前采集，不能通过当前命令直接重现旧提示词。

本轮 10 次真实请求共 3477 tokens；逐条对照、退步与限制见 [EVALUATION.md](EVALUATION.md)，本次不再继续调用。

## 结构化运行结果与执行轨迹：2026-10-11

默认命令无需密钥参数，使用本地 TOML 配置；成功退出 0，执行或结构校验失败退出 1。可选保存完整结果（以下命令会联网，本轮未执行）：

```sh
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py --output /private/tmp/toy-agent-run-new.json
```

--output 目标须不存在，父目录须存在且可写；程序在读取密钥和请求前独占创建，失败运行也保存 JSON。已有文件或无效路径会在请求前退出；写入、刷新或关闭失败同样退出 1。写入并非事务操作，异常时可能留下空文件或部分 JSON，需要自行检查，不自动覆盖。

39 项离线测试全部通过，命令仍为上方 unittest discover；不读取真实密钥、不调用模型，不新增依赖。原有 31 项测试保留执行边界并适配返回契约，新增 8 项验证结果和 CLI 保存。提示词及历史评估数据未修改。

以下为测试替身产生的完整示例（首轮工具成功，第二轮超时），不是真实模型输出或账单：

```json
{
  "status": "failed",
  "summary": null,
  "error": {
    "category": "network_error",
    "message": "网络连接失败或超时；未自动重试。超时不代表服务端未处理请求。"
  },
  "model_requests": 2,
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15,
    "complete": false
  },
  "tool_executions": 1,
  "cache_hits": 0,
  "trace": [
    {
      "event": "model_request",
      "request_number": 1,
      "finish_reason": "tool_calls",
      "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15
      }
    },
    {
      "event": "tool_execution",
      "request_number": 1,
      "status": "succeeded",
      "tool_name": "get_project",
      "call_id": "call_test",
      "parameters": {
        "project_id": "xingqiao"
      }
    },
    {
      "event": "model_request",
      "request_number": 2,
      "finish_reason": null,
      "usage": null
    },
    {
      "event": "failure",
      "request_number": 2,
      "stage": "request",
      "error": {
        "category": "network_error",
        "message": "网络连接失败或超时；未自动重试。超时不代表服务端未处理请求。"
      }
    }
  ]
}
```

model_requests 包含失败的第二次尝试；tool_executions=1 包含实际进入函数的调用，cache_hits=0。网络失败的用量未知，complete=false；已知总计 15 不能当作整次运行总费用。无请求的配置失败可为零累计、complete=true。

trace 只保存请求、工具执行、缓存与失败的必要元数据，不保存密钥、请求头、原始错误响应、完整对话或内部推理；当前参数为虚构数据，后续真实参数需脱敏。succeeded 只表示执行及三字段结构校验成功，仍可能遗漏、编造或错字段；当前候选尚未通过 V2 内容质量验收。本轮真实网络行为与模型质量均未验证。

## TOML 配置迁移验证：2026-10-11

两个入口共用 read_config_api_key，移除 --key-file，增加 --config。45 项离线测试通过，包含默认路径独立于工作目录、显式绝对/相对路径、有效配置、缺失/权限/编码/语法/字段/类型/空值/占位符错误，以及两个入口配置失败不联网、不泄露内容。Loop 配置失败仍可保存 status=failed、configuration 事件和零请求结果；评估入口配置失败安全报错后退出，不创建评估输出。

仅迁移阶段读取原真实密钥并写入本地明文配置，未显示密钥、未删除原文件；测试使用虚构密钥与临时配置，未调用模型。已检查 local.toml 被 /config/ 忽略且未被跟踪，权限 0600；示例仅包含 YOUR_API_KEY。任务 D 尚未开始。

主会话复核：45 项离线测试全部通过；用户真实运行保存的 test-output/run-002.json 成功，两次请求、一次工具执行，累计 1582 tokens，用量完整且与分轮记录一致。正常配置读取及结果保存已真实验证，真实认证失败与异常配置仍仅离线验证。test-output/ 为本地运行产物，已被 Git 忽略，不影响 toy-agent/evals/ 历史评估记录。

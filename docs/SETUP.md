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
运行第一次调用（密钥文件必须是单行纯文本，不要复制进仓库）：

```sh
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py --key-file /Users/ironshipzhang/Documents/secret/deepseek.txt
```

脚本现在固定执行一次只读工具调用和后续摘要，共两次 `/chat/completions` 请求，仍使用 Python 标准库和同一运行命令。

1. `request_completion(..., with_tool=True)`：发送摘要规则、查询 xingqiao 的用户意图和 get_project 工具定义，指定 tool_choice；不把项目状态放入第一次请求。
2. `inspect_response` 记录首次用量和结束原因；`validate_tool_call` 校验调用数、类型、ID、工具名和参数结构。程序显式调用 `get_project` 查询本地虚构数据。未知项目或非法调用直接失败，不执行第二次请求。
3. `run_project_summary` 追加 assistant 调用消息，以及带相同 tool_call_id 的 tool 结果。结果通过 JSON 字符串作为 content 返回。
4. `request_completion(..., with_tool=False)` 不再提供工具，启用 response_format={"type":"json_object"}；第二次用量展示后计算两次合计，`display_summary` 调用原有 `parse_summary` 校验。

摘要必须且仅含 progress、blockers、next_steps；值必须为字符串数组，可为 []，元素不可是空白字符串。缺字段不自动补 []。
每次请求关闭思考、非流式、max_tokens=400、30 秒网络超时，无自动重试。整个流程不设置额外的总时限。
缺少、空或无法读取密钥时联网前退出；HTTP、网络和响应格式异常返回退出码 1，不打印密钥或原始错误响应。
首次须 tool_calls 正常结束，后续须 stop；length 截断直接失败。第二次失败时首次已展示的用量仍可用于排查，失败请求的实际计费情况须查平台账单。

离线验证（不读取密钥、不调用模型）：

```sh
toy-agent/.venv/bin/python -m unittest discover -s toy-agent -p 'test_*.py' -v
```

2026-10-10：9 项测试通过；真实结构化调用输入 215、输出 67、总计 282 tokens，stop 正常结束。
格式校验不验证事实：即使 blockers=[] 合法，也仍需与原文对照，判断是否漏掉阻塞项。
缺少密钥的验证命令（预期退出码 1）：

```sh
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py --key-file /private/tmp/nonexistent-deepseek-key-01a0fd07
```

本次真实调用：输入 99、输出 54、总计 153 tokens，结束原因 `stop`。按缓存全部未命中的峰值费率估算上限约 $0.0000945；实际费用以平台账单为准。
2026-10-02 查验官方 Flash 每百万 token 价格：缓存命中输入峰值 $0.006 / 非峰值 $0.003，未命中输入 $0.30 / $0.15，输出 $1.20 / $0.60。价格页面支持文本摘要所需的非思考模式；首次真实调用验证当前本地网络可达，未单独核实其他地区的可用性。
预算目前是目标，尚未实现自动预算拦截。

官方入口：https://platform.deepseek.com/
价格与能力：https://api-docs.deepseek.com/quick_start/pricing/
价格查验日期：2026-10-02。具体费率以实际调用时官方页面为准。

## 一次只读工具调用验证：2026-10-10

- 16 项离线测试通过（原摘要校验 9 项 + 工具流程 7 项），不读取密钥、不联网。
- 真实执行成功，退出码 0：get_project 参数为 {"project_id":"xingqiao"}，本地只读函数执行一次。
- 首次：输入 448、输出 36、总计 484 tokens，finish_reason=tool_calls。
- 后续摘要：输入 335、输出 75、总计 410 tokens，finish_reason=stop。
- 合计：输入 783、输出 111、总计 894 tokens。以全部输入未命中的峰值价格估算费用上限约 $0.0003681，实际扣费以账单为准。
- 人工核对摘要：登录和列表接口完成、12 个测试通过、详情联调、数据库迁移失败、小林排查及演示延期风险均保留；下一步包括修复迁移和完成联调。
- 2026-10-10 再查验官方价格与能力：deepseek-flash 支持 Tool Calls 和 JSON Output；每百万 token 缓存命中输入 $0.006 / $0.003、未命中输入 $0.30 / $0.15、输出 $1.20 / $0.60（峰值 / 非峰值）。本地真实调用验证当前设备可达；未查询账户剩余额度或验证其他地区。
- 查验来源：https://api-docs.deepseek.com/quick_start/pricing/ 与 https://api-docs.deepseek.com/api/create-chat-completion/。
- 结构正确不能保证事实正确，本次只人工核对一个虚构项目，不宣称已建立内容评估集。

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
账户、API 密钥和余额尚未配置；当前没有真实模型调用。
首次调用将限制输出，记录 token 用量，不启用无限循环或无限重试。
预算目前是目标，尚未实现自动预算拦截。

官方入口：https://platform.deepseek.com/
价格与能力：https://api-docs.deepseek.com/quick_start/pricing/
价格查验日期：2026-10-02。具体费率以实际调用时官方页面为准。

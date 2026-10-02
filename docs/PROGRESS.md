# 当前进度

更新时间：2026-10-02

## Done

- 明确求职方向、每天学习时间和预计投递窗口。
- 创建本地项目目录，保存最小协作原则与项目说明。
- 已在项目 .tools/ 中安装 uv 0.12.22 和 Python 3.12.15。
- 已创建 toy-agent/ 的无依赖 Python 项目与独立虚拟环境，实际运行 hello.py 成功（arm64，Virtual environment: True）。
- 已验证 Apple Command Line Tools 和 Git 2.39.5 可用，初始化本目录为独立 Git 仓库（main）。
- 已验证 .gitignore 排除 .venv、.tools、.cache、work 和 .env。
- 用户接受每月 10 USD 以内模型费用，选择 DeepSeek 官方 API 为起点；已核对官方 deepseek-flash 的价格和 JSON / Tool Calls 支持。
- 初始 Git 提交保存协作文档、Python 项目配置和已验证的环境检查程序。
- origin 已配置为用户提供的 SSH 地址 git@github.com:ironshipzhang/ai-engineering-journey.git。
- 已安装 VS Code 1.140.0 arm64 和 Microsoft Python 扩展及其依赖；已保存并验证 .vscode/ JSON 配置。
- 用户在 VS Code 运行 hello.py，输出确认使用项目虚拟环境，Python 3.12.15、arm64。
- GitHub SSH 认证成功，GitHub 官方 Ed25519 主机密钥已记录；首次推送成功，main 跟踪 origin/main。

## Current

- 最小开发环境任务已完成；尚未实现真实模型调用。

## Next

- 准备 DeepSeek 账户、API 密钥和余额。
- 下一任务：一次真实模型 API 调用，限制输出、记录 token 用量并验证失败处理；先讨论最小实现再编码。

## Open Questions

- DeepSeek 账户、API 密钥与余额尚未配置；尚未实现或执行真实模型调用。
- Python 安装器报告动态库 install name 修补失败；当前程序运行成功，原生扩展构建尚未验证，后续若需要构建再检查。

# 当前进度

更新时间：2026-10-02

## Done

- 明确求职方向、每天学习时间和预计投递窗口。
- 创建本地项目目录，保存最小协作原则与项目说明。
- 检查设备：Apple Silicon arm64；未发现 Apple Command Line Tools、uv、Homebrew 或 GitHub CLI。
- 已在项目 .tools/ 中安装 uv 0.12.22 和 Python 3.12.15。
- 已创建 toy-agent/ 的无依赖 Python 项目与独立虚拟环境，实际运行 hello.py 成功（arm64，Virtual environment: True）。
- 已验证 Apple Command Line Tools 和 Git 2.39.5 可用，初始化本目录为独立 Git 仓库（main）。
- 已验证 .gitignore 排除 .venv、.tools、.cache、work 和 .env。
- 用户接受每月 10 USD 以内模型费用，选择 DeepSeek 官方 API 为起点；已核对官方 deepseek-flash 的价格和 JSON / Tool Calls 支持。
- 初始 Git 提交保存协作文档、Python 项目配置和已验证的环境检查程序。

## Current

- 用户已确认提交身份与私有仓库方案；远程仓库和推送认证待完成。
- Python 环境已经验证；系统 /usr/bin/python3 不作为项目运行环境。

## Next

- 创建并关联 GitHub 私有仓库 ai-engineering-journey，完成首次推送。
- 在准备好模型访问条件后，完成首次真实模型 API 调用。

## Open Questions

- Git 提交身份已由用户确认并将仅设置在当前仓库；GitHub 仓库名 ai-engineering-journey、可见性 private 已确认。
- DeepSeek 账户、API 密钥与余额尚未配置；尚未实现或执行真实模型调用。
- Python 安装器报告动态库 install name 修补失败；当前程序运行成功，原生扩展构建尚未验证，后续若需要构建再检查。

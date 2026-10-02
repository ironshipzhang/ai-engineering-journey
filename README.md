# Ai Agent 转型

通过项目实践，在已有软件工程经验上积累 LLM Application / Agent Engineering 能力。

## 目标与范围

- 目标：2027 年 2–4 月开始投递 AI Application Engineer / AI-oriented SDE 等岗位。
- 时间：每天约 1–2 小时，包括工作日和周末。
- Toy Agent：理解模型调用、工具调用循环、状态、失败处理和最小评估。计划使用 Python。
- 后续工程项目：模拟 Product Operations 流程，逐步覆盖评估、权限、审批、可靠性和部署。
- Go 保留为已有后端优势；其他组件按真实需要引入。

## 会话协作

主会话负责方向、设计和任务选择；任务会话负责一个具体成果。会话通过仓库中的代码、验证结果和简短文档交接。初期顺序推进任务。

当前状态见 [docs/PROGRESS.md](docs/PROGRESS.md)。当前环境任务见 [docs/SETUP.md](docs/SETUP.md)。

本目录使用 Git（main），初始提交保存最小文档与已验证的 Python 环境检查程序。
origin 已配置为 git@github.com:ironshipzhang/ai-engineering-journey.git；SSH 认证和首次推送待完成。

使用 VS Code 打开整个仓库目录，Python 解释器配置为 toy-agent/.venv。

# Ai Agent 转型

通过项目实践，在已有软件工程经验上积累 LLM Application / Agent Engineering 能力。

## 目标与范围

- 目标：2027 年 2–4 月开始投递 AI Application Engineer / AI-oriented SDE 等岗位。
- 时间：每天约 1–2 小时，包括工作日和周末。
- Toy Agent：使用 Python 理解模型调用、工具调用循环、状态、失败处理和最小评估。
- 后续工程项目：模拟 Product Operations 流程，逐步覆盖评估、权限、审批、可靠性和部署。
- Go 保留为已有后端优势；其他组件按真实需要引入。

## 会话协作

主会话负责方向、设计、任务选择和学习回顾，也可更新相关文档；具体编码、测试和调试放到同项目目录下的任务会话。会话通过仓库中的代码、验证结果和简短文档交接。初期顺序推进任务。

当前状态见 [docs/PROGRESS.md](docs/PROGRESS.md)，环境与运行命令见 [docs/SETUP.md](docs/SETUP.md)。

## 当前成果

Toy Agent 已实现有界只读 Agent Loop：模型通过 get_project 查询虚构项目，程序校验并执行工具调用，复用本任务内成功结果，最后校验三字段结构化摘要；最多 5 次模型请求。

独立摘要评估已保存三轮输出与提示词迭代记录，31 项离线测试通过。主会话已按 V2 分别复核事实保留、字段归属和表达关联：当前候选八条关键事实均保留，但三条仍有字段问题，候选尚未通过质量验收。提示词与模型调用暂时冻结；评估只覆盖摘要环节，尚未验证完整 Loop 的多样例质量或多次生成稳定性。

阶段进度与后续建议见 [Toy Agent 进度图](docs/toy-agent-progress.svg)。下一项建议是完整 Loop 的结构化结果与执行轨迹记录，先用离线模拟验证；后续计划按验证结果逐项确定。

系统流程见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，评估记录与限制见 [docs/EVALUATION.md](docs/EVALUATION.md)，重要取舍见 [docs/DECISIONS.md](docs/DECISIONS.md)。

## 开发环境

本目录使用 Git（main），初始提交保存最小文档与已验证的 Python 环境检查程序。
origin 为 git@github.com:ironshipzhang/ai-engineering-journey.git；SSH 认证与首次推送已完成，main 跟踪 origin/main。

使用 VS Code 打开整个仓库目录，Python 解释器配置为 toy-agent/.venv。

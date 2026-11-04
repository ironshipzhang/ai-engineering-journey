# Ai Agent 转型

通过项目实践，在已有软件工程经验上积累 LLM Application / Agent Engineering 能力。

计划完成后作为学习项目开源，保留各阶段进度、讨论交接、设计取舍和实验记录，展示从最小实现到验证与修正的过程。历史记录按发生时的状态阅读，最新实现以代码、测试及当前进度为准；仓库公开与许可证将在后续确定。

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

Toy Agent 已实现有界只读 Agent Loop：用户选择项目与 summary / issues 任务，模型提出 get_project 或 list_project_issues 调用，Registry 校验并分发；任务内复用成功结果，最终校验必要取数与三字段结构化摘要，最多 5 次模型请求。虚构项目数据保存在 toy-agent/data/projects.json，每次任务读取一次快照。

内容评估练习已结束：已完成样例构造、批量采集、版本比较及三维评审，历史输出与结论保留在 EVALUATION.md，不再作为当前调优待办。

任务 C 已完成：Loop 返回结构化运行结果与执行轨迹，CLI 可展示或保存 JSON。39 项离线测试通过，正常真实运行与 --output 保存均已验证；异常路径通过离线模拟验证。

任务 D 与 D2 已通过主会话机制验收：每轮允许 1～2 个工具调用，整批校验后顺序执行，71 项离线测试通过；一次真实 issues 双工具链路成功。最新机制与验证见 [D2 交接](docs/tasks/two-tool-batches.md)。交接及模拟轨迹见 [任务 D 记录](docs/tasks/multi-project-registry.md)，完整路线见 [TOY_AGENT_ROADMAP.md](docs/TOY_AGENT_ROADMAP.md)。

E1 已完成并通过主会话验收：三份虚构资料经 markdown-it-py 生成有原文定位的片段，独立 prepare/check 提供确定性全量构建、输入变化与完整性检查。完整离线测试 88 项通过，正常构建包含 15 个片段；它是 prepared corpus，尚不包含 embedding、检索或问答。运行方法及边界见 [E1 交接](docs/tasks/e1-corpus-handoff.md)。

E2a 远程编码接入已通过主会话复核：百炼 text-embedding-v4 独立客户端完成 15 个文档和 1 个问题的 1024 维编码验证；完整离线回归 103 项通过。当前 JSON 是编码验证记录，正式向量产物与检索、问答尚未实现。详见 [E2a 交接](docs/tasks/e2a-embedding-handoff.md)。Toy 全程只用 JSON 保存原文关联、向量及元数据，不引入数据库服务；PostgreSQL 与 pgvector 留到正式求职项目。

默认运行（会联网）：`toy-agent/.venv/bin/python toy-agent/deepseek_summary.py`，等价于 `--project-id xingqiao --task summary`；问题摘要可用 `--project-id yunfan --task issues`，仍支持 `--config` 和 `--output`。

任务 C 的已完成实现范围见 [结果与执行轨迹任务说明](docs/tasks/run-result-and-trace.md)。

系统流程见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，评估记录与限制见 [docs/EVALUATION.md](docs/EVALUATION.md)，重要取舍见 [docs/DECISIONS.md](docs/DECISIONS.md)。

## 开发环境

本目录使用 Git（main），初始提交保存最小文档与已验证的 Python 环境检查程序。
origin 为 git@github.com:ironshipzhang/ai-engineering-journey.git；SSH 认证与首次推送已完成，main 跟踪 origin/main。

使用 VS Code 打开整个仓库目录，Python 解释器配置为 toy-agent/.venv。

模型入口默认读取 `config/local.toml`，不再需要 `--key-file`；可用 `--config` 指定其他路径。首次使用将 [config.example.toml](config.example.toml) 复制到该位置并在本地填写密钥，权限设为 0600，已有配置不覆盖；步骤见 [SETUP.md](docs/SETUP.md)。本地配置为明文且被 Git 忽略，示例不含真实密钥；忽略规则不会移除已跟踪文件。当前配置迁移已完成，45 项离线测试通过。

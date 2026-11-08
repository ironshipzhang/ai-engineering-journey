# 项目目录

更新时间：2026-11-08。2026-11-04 完成目录整理；后续阶段按相同结构归档。历史任务和实验保留，文档中的运行路径已更新为整理后的实际位置。

```text
ai_engineer/
├── AGENTS.md                 协作约定
├── README.md                 项目入口与当前成果
├── config.example.toml       无密钥配置示例
├── config/                   本地真实配置，Git 忽略
├── .vscode/                  解释器、源码分析与测试配置
├── toy-agent/
│   ├── pyproject.toml        Python 依赖声明
│   ├── uv.lock               依赖锁文件
│   ├── .venv/                虚拟环境，Git 忽略
│   ├── src/                  可运行脚本与业务模块
│   ├── tests/                离线 unittest 测试及其辅助函数
│   ├── data/                 虚构项目状态数据
│   ├── knowledge/            RAG 原始资料与 catalog
│   └── evals/
│       ├── cases/            纳入 Git 的评估输入样例
│       └── results/          纳入 Git 的历史评估结果
├── docs/
│   ├── PROGRESS.md           当前进度及历史记录
│   ├── SETUP.md              环境与运行命令
│   ├── ARCHITECTURE.md       实际架构与限制
│   ├── DECISIONS.md          重要取舍
│   ├── EVALUATION.md         历史内容评审
│   ├── TOY_AGENT_ROADMAP.md  完整路线
│   ├── PROJECT_STRUCTURE.md 本目录说明
│   ├── toy-agent-progress.svg
│   └── tasks/
│       ├── README.md         任务索引
│       ├── agent/            C、D、D2 任务与交接
│       ├── mcp/              F 的 MCP 任务书及离线实现交接
│       └── rag/
│           ├── e-stage-handoff.md  E1–E3 最终交接与验收边界
│           ├── e3-deepseek-interaction-walkthrough.md  两轮交互及 JSON 回顾
│           ├── discussions/  概念、场景及生命周期讨论
│           ├── e1/           E1 任务与交接
│           ├── e2a/          E2a 任务与交接
│           ├── e2b/          E2b 任务与交接
│           ├── e2c/          E2c 任务与交接
│           ├── e2d/          E2d 任务、实施交接与真实验收记录
│           └── e3/           E3 检索工具任务、实施交接与真实复核
└── test-output/              本地构建/运行结果，全部 Git 忽略
    ├── agent/
    │   ├── c/                run-001、run-002
    │   ├── d/                D 的真实及模拟结果
    │   └── d2/               D2 结果
    ├── mcp/f/               F 的本地验证与后续授权真实结果（按需创建）
    └── rag/
        ├── e1/20261028/      正常 build-001 与故意损坏的 corrupt-copy
        ├── e2a/             编码验证记录
        ├── e2b/             文档向量与已有问题检索结果
        ├── e2c/             新问题编码与检索结果
        ├── e2d/             资料问答结果与离线前检示例
        └── e3/              模型检索工具运行结果，保留失败诊断及成功两题
```

## 源码与测试

本轮保留简单脚本模块，不新增 Python 打包、安装或框架层。`src/` 下的模块仍可互相导入；从仓库根目录启动脚本时，Python 自动将脚本所在目录加入导入路径：

```bash
toy-agent/.venv/bin/python toy-agent/src/hello.py
toy-agent/.venv/bin/python toy-agent/src/json_retrieval.py --help
```

测试目录与源码目录分开后，运行 unittest 时需显式提供源码导入路径。以下命令在仓库根目录执行，只对这条命令设置 PYTHONPATH，不修改全局环境：

```bash
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'
```

VS Code 保持使用 `toy-agent/.venv`；`python.analysis.extraPaths` 指向 src。测试从仓库根目录发现 tests，通过 `.vscode/python.env` 设置相同 PYTHONPATH。这个文件只有导入路径，不能放密钥。默认配置、项目数据、知识资料及评估样例按源码所在位置定位，不依赖终端当前目录；用户传入的相对 CLI 路径仍相对于当前目录。

## 迁移约定

- 原 `toy-agent/*.py` 按职责移到 src 或 tests；数据、知识资料、虚拟环境和真实配置没有移动。
- 原 `toy-agent/evals/*.json` 按样例/结果分开，文件内容不改。
- 原扁平 `docs/tasks/` 按 Agent 与 RAG 阶段整理；同阶段任务书与交接放在一起。
- 本地 E1 构建、E2a 编码与 E2b 向量/检索 JSON 只移动位置，文件名（E1 日期目录除外）和文件字节保留，已有 build_id/摘要不变。corrupt-copy 仍是故意损坏的验证副本，不修复为正常构建。
- 过去聊天中的旧路径不会自动更新；后续命令以当前 SETUP 和任务书为准。不要为旧路径新建副本、兼容入口或符号链接，避免再次混放。
- 新任务书、交接、源码和输出按上述职责归档。输出目录仅在需要写入时创建；Git 不跟踪空目录或本地 test-output。

任务入口见 [任务索引](tasks/README.md)，实际命令见 [SETUP](SETUP.md)。

## 2026-11-08 F 新增入口

`toy-agent/src/` 新增 `project_mcp_contract.py`、`project_mcp_server.py`、`project_mcp_client.py` 和 `mcp_project_agent.py`；测试在 `toy-agent/tests/test_project_mcp.py`、`test_mcp_project_agent.py`，故障子进程夹具为同目录 `mcp_fault_server.py`。F 任务书及交接在 `docs/tasks/mcp/`，本地安全样例在忽略目录 `test-output/mcp/f/`。SDK 是依赖，不新增项目打包或服务部署。

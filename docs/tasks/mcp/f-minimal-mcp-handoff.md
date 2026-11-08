# F：最小 MCP 接入交接

日期：2026-11-08。F1/F2 离线实现完成，待主会话复核；没有真实 DeepSeek 验收，不进入下一阶段。任务范围见 [任务书](f-minimal-mcp.md)。

## 实现与阅读入口

- `toy-agent/src/project_mcp_contract.py`：输入、输出和允许工具的共享契约；`query` 委托已有 `deepseek_summary.load_projects/get_project` 业务，无项目查询副本。
- `toy-agent/src/project_mcp_server.py`：官方底层 Server，只注册 tools/list、tools/call 的 get_project；启动时读一次快照，不读配置或密钥。SDK 负责协议及生命周期。`--data` 仅为本地测试夹具路径，模型参数没有路径权限。
- `toy-agent/src/project_mcp_client.py`：受控解释器/Server 路径、SDK stdio ClientSession、显式 initialize、发现校验、结果解包与关闭。生产 CLI 不接收自定义命令、URL 或外部 Server。
- `toy-agent/src/mcp_project_agent.py`：独立 F 入口，默认 direct，可选 mcp；只允许 summary，默认 xingqiao。没有扩展旧五轮 Loop/Registry，也没有暴露 issues 或检索。
- `toy-agent/tests/test_project_mcp.py`：7 项测试，真实 SDK 子进程及边界；`mcp_fault_server.py` 为 tests 下独立故障夹具，不是生产服务。
- `toy-agent/tests/test_mcp_project_agent.py`：13 项测试，假模型、假配置；MCP 成功、发现失败和关闭失败等路径实际启动子进程。

旧 D2/E2/E3 的源码、测试、提示词与历史运行记录未改。F 复用 E3 的调用字段检查与 16 KiB messages 检查、E2d 的生成配置校验及禁止重试/重定向的 HTTP 传输，不读取 embedding 配置、向量或知识产物。

## 版本、来源、许可证与成本

实现前读取公开 PyPI 元数据，选定当时最新稳定版 **mcp==2.3.0**（2026-10-02 发布），不是预发布。官方包要求 Python >=3.10，本项目仍限定 >=3.12,<3.13。实际安装和子进程测试环境：Python 3.12.15、macOS 15.5 arm64。没有升级 Python，没有引入 Agent 框架；未安装 `[cli]`、Inspector、dotenv、typer 或 rich。

核对资料：

- [官方 SDK v2.3.0 README](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/README.md)、[MIT 许可证](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/LICENSE)。
- [官方 SDK 文档](https://py.sdk.modelcontextprotocol.io/)、[PyPI 版本元数据](https://pypi.org/pypi/mcp/2.3.0/json)。
- [v2.3.0 stdio 源码](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/client/stdio.py)、[ClientSession](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/client/session.py)、[底层 Server](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/lowlevel/server.py)。实现按本机锁定版本 API 核对，未照搬 v1 装饰器示例。
- [架构](https://modelcontextprotocol.io/docs/learn/architecture)、[客户端教程](https://modelcontextprotocol.io/docs/develop/build-client) 用于职责理解。教程中的模型 SDK、dotenv 与在线示例不属于本轮依赖和执行范围。

本轮使用 SDK 的 `ClientSession.initialize()`，实际协商并记录 **2025-11-25**。2.3.0 也支持 2026-07-28 的 discover 模式，但本轮不启用自动探测、降级或版本重试；仅接受已测握手版本。MCP Server 不知道模型调用 ID；SDK 内部维护协议请求 ID，项目记录 `local_call_number`，没有编造 wire ID。

`pyproject.toml` 精确固定 mcp；`uv.lock` 固定完整图及下载哈希。macOS 实际新增 28 个分发包，锁图共 33 个包（含项目与跨平台依赖），本机环境总计 30 个分发包。新增包的 RECORD 文件合计约 24.54 MiB（不等于下载量、RSS 或缓存占用）。uv 实际下载了 arm64 可用的二进制 wheel，未现场编译；其他系统未实跑。

以下为安装元数据中的版本/许可证清单。SDK 基础包没有 stdio-only extra，因此即使不启动 HTTP 服务，也须接受其 HTTP、ASGI、认证及原生扩展依赖。没有运行 uvicorn/HTTP 服务。

| 新增包 | 锁定版本 | 许可证元数据 |
| --- | --- | --- |
| mcp / mcp-types | 2.3.0 / 2.3.0 | MIT |
| anyio | 4.16.0 | MIT |
| httpx2 / httpcore2 | 2.16.0 / 2.16.0 | BSD-3-Clause |
| jsonschema / jsonschema-specifications | 4.26.0 / 2025.9.1 | MIT |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| pydantic / pydantic-core | 2.14.3 / 2.50.4 | MIT |
| pyjwt | 2.15.1 | MIT |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| cffi | 2.1.1 | MIT-0 |
| pycparser | 3.12 | BSD-3-Clause |
| python-multipart | 0.0.33 | Apache-2.0 |
| sse-starlette / starlette | 3.7.0 / 1.10.0 | BSD-3-Clause |
| uvicorn / click | 0.54.0 / 8.5.1 | BSD-3-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection / annotated-types | 0.4.5 / 0.8.0 | MIT |
| attrs / referencing / rpds-py | 26.1.0 / 0.37.0 / 2026.9.1 | MIT |
| h11 | 0.16.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| truststore | 0.10.5 | MIT |

Python 条件依赖按元数据处理：macOS 不安装 pywin32，cli/rich extras 不安装；SDK 的直接依赖与其进一步依赖的准确边以 uv.lock 为准。许可证清单用于依赖选择，不表示已为整个项目选择开源许可证。

## 业务与协议边界

输入严格为 `{project_id: 非空字符串}`，拒绝额外字段、空白值、整数和 bool。服务端直接校验原始 arguments 对象，无依赖 Pydantic 将字符串转数字等自动转换。未知工具或项目返回 `is_error=true` 的固定文字。项目文件与业务校验沿用旧实现。

输出严格为 project_id/name/status 三个非空字符串。Server 同时返回 structured_content 对象和单个 text JSON；Client 要求二者均存在、合法、一致且目标相符。错误标记、缺失/冲突数据、非 JSON 文本、额外内容块、未知内容类型都不能成为有效项目结果。SDK 还会按 output schema 校验；在业务解包前被 SDK 拒绝时分类为 mcp_call/protocol_error。工具错误为 mcp_tool/tool_error；本地解包失败为 mcp_result/invalid_result。

发现时只接受唯一 get_project、无分页、固定描述及完全相等的输入/输出 schema。然后给模型发送本地固定 schema，未将远端发现列表直接转交。这个严格策略只面向受控本地 Server：即使语义等价但表示不同的 schema 也会拒绝，不宣称通用 MCP 客户端兼容性。

每次 direct 运行读一次快照；每个 MCP Server 生命周期读一次并复用。MCP 宿主另读一次用于项目范围/大小前检，两进程之间没有文件系统事务。启动后文件变化不会热更新 Server；下次运行才读新快照。相同静态夹具的两路径业务对象已核对相等。宿主对已知项目做保守大小前检（包括 issues），不提前执行 get_project；最终 tool 内容仍在第二次请求前完整检查，绝不截断。启动间隙改文件可能导致本次服务端与宿主前检快照不同，不提供跨进程原子快照保证。

## F2 编排、计数与失败

输出文件先独占预留，然后依次检查输入/messages、生成配置、项目范围和大小；mcp 再启动、握手、发现。上述步骤失败时模型尝试数均为零。资料产物不是前提。

第一次请求仅提供 get_project。只接受唯一 function 调用、合法 ID、严格参数 JSON（含重复键拒绝）、固定名称与逐字目标绑定。可选 index 必须为整数 0，规范化后移除。合法后执行一次业务适配器；追加 assistant 和对应 tool 消息，用模型 ID 绑定 tool_call_id。第二次不提供 tools，只接受 assistant/stop 和严格三字段摘要；重复键、额外字段、空白元素、length 或再次调用均失败。摘要结构成功不等于内容质量通过，semantic_review 保持 not_performed。

最多 2 次模型 HTTP 尝试、1 次业务适配调用，无重试、自动重连、修复或 direct fallback。尝试计数在发出前增加，合法用量在解释 choice 前累计。缺失用量以 complete=false 表示未知，不将未知部分当免费；此前已知用量、调用和失败轨迹保留。tool_executions 表示宿主进入业务适配器的次数，含失败；MCP 超时/断连后无法确认远端是否已进入或完成业务函数，不宣称恰好一次交付。

沿用 deepseek-flash、800 输出 tokens、每次网络操作 30 秒，messages JSON 的 UTF-8 长度限 16 KiB。整个流程没有 30 秒总时限。MCP 协议准备/发现/调用事件不算模型请求或重复业务执行。

安全错误仅保存固定 stage/category/message，不输出 SDK/Pydantic/HTTP 原始异常、响应或环境。验证失败前的未信任模型调用不落盘；通过校验的 assistant/tool 往返保留用于复核。Server stderr 在宿主侧丢弃，SDK payload 日志也被抑制，仅识别锁定 SDK 的“终止后仍存活”警告并标记清理失败。代价是诊断细节较少，升级 SDK 时必须复核这个信号及关闭逻辑。此实现是顺序单运行入口，临时日志处理不面向同进程多 Agent 并发。

输出写入/flush/close 失败时退出非零，不补发请求。非事务保存可能留下空、部分或未可靠落盘的 JSON，须结合退出码判断；不会覆盖已有文件。

## 超时与回收的实际范围

启动（含 SDK 子进程启动、session 与 initialize）、发现、每次调用分别由 asyncio timeout 限制，默认各 10 秒；SDK session 同时有 10 秒读超时。它们是操作等待上限，不包含退出清理时间。测试对操作注入 1.5 秒短超时。

关闭在同一异步任务按栈退出，避免把 SDK 的 AnyIO task group 移到别的任务。锁定 SDK 提供取消屏蔽及逐步有界关闭：先关闭输入，等待退出，必要时向受控进程组发 TERM、KILL 并回收；其等待预算合计约 6.5 秒。项目的 cleanup_timeout 默认 10 秒是关闭完成后的超时判定阈值，**不是提前打断 SDK 清理的硬总时钟**，以免取消回收本身。超阈值、SDK 清理异常或存活警告都会让全程失败，成功摘要清空；若此前业务也失败，则保留 prior_error。

真实测试核对正常、工具失败、启动/发现/调用超时、异常退出、单次取消、忽略 SIGTERM 后强杀的 returncode 与 PID 不再存活。没有覆盖操作系统不可杀进程、重复原生 task.cancel、系统级资源耗尽或所有后代进程异常；不将本次验证推广为所有 OS 下绝对硬实时退出保证。

## 实际验证

从仓库根目录执行：

```sh
# 改动前：实际 199 项通过
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'

# F1：7 项；F2：13 项（包含真实子进程，假模型）
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_project_mcp.py' -v
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_mcp_project_agent.py' -v

# 实现后最终完整回归：219 项通过，21.153 秒
PYTHONPATH=toy-agent/src toy-agent/.venv/bin/python -m unittest discover -s toy-agent/tests -p 'test_*.py'

.tools/bin/uv sync --project toy-agent --locked --offline --cache-dir .cache/uv
# Resolved 33 packages / Checked 30 packages，未改锁文件
git diff --check
```

开发中取消清理曾错误转换 CancelledError，已修正并实测回收；后续保留业务失败后再清理时，旧测试对事件顺序的断言失败，改为失败事件在清理前、最终清理事件在后。失败过程未描述为通过；随后补充次轮 tool_calls 错误类型的拒绝断言，最终 219 项再次通过；上述 219 是修正后的完整实际结果。

覆盖还包括：foreign cwd、固定虚拟环境解释器、默认/夹具数据定位、服务端错误类型/空值/额外字段/未知项目拒绝、schema 拒绝先于模型请求、无关假秘密环境变量不传子进程、目标不符/非法 ID/多调用/重复键零业务执行、次轮无工具、HTTP/网络/非法响应、缺失用量、部分成功保留、超长上下文不截断、输出覆盖/写入/刷新/关闭失败、业务及清理双重失败。

安全样例为本机忽略文件 `test-output/mcp/f/offline-20261108-001.json`，已重读核对；外层明确标记 validation_mode=fake_model_real_local_stdio、paid_api_calls=0，内层成功、2 次假模型响应、1 次业务调用、已知假用量 41 tokens。摘要是固定 fixture 文本，没有语义验收含义。克隆仓库不保证存在该文件，测试会自行用临时夹具复现机制。

本轮没有读取 config/local.toml 或真实密钥，没有 DeepSeek/Embedding 请求，没有提交/推送。

## 待主会话复核的真实演示提案（未执行）

仅 **xingqiao / summary / mcp** 一次任务，先确认输出文件不存在；最多 2 次 DeepSeek HTTP 尝试、1 次 get_project，每请求最多 800 输出 tokens。无 embedding、无重试；任何失败立即停止，不追加 direct 比较或失败复测。

建议单次授权预算 **USD 0.02**。2026-11-08 查阅 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：Flash 峰值未命中输入 $0.30/百万、输出 $1.20/百万；仍支持 Tool Calls/JSON Output。按两次输入合计预留 50,000 tokens（含固定工具/schema 开销，属于预算估计，非本地 tokenizer 硬限制）、输出最多 1,600 tokens，估计 $0.01692；当前小项目通常远低于该保守预留。程序目前不提供美元预算硬拦截，实际扣费以账单为准，执行前须再核实价格与请求配置。不查询余额，不因离线通过推断认证或地区可用性。

以下命令仅供另行授权后使用，本轮没有执行：

```sh
mkdir -p test-output/mcp/f
toy-agent/.venv/bin/python toy-agent/src/mcp_project_agent.py --transport mcp --project-id xingqiao --task summary --output test-output/mcp/f/live-001.json
```

由主会话复核实现、计数、锁定版本和清理边界，再由用户确认真实任务及预算。真实运行后仍需单独对照项目原文检查摘要内容，不以结构成功代替内容验收。

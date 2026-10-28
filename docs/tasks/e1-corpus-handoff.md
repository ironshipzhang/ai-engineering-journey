# E1 实施交接：资料、切块与来源构建清单

日期：2026-10-28。E1 已通过主会话复核；未实施 E2/E3。下文保留实现会话交接时的运行与 Git 状态，后续验收见文末。需求依据：[E1 任务书](e1-corpus-preparation.md)。

## 先看整体：E1 在系统中负责什么

E1 把人维护的文档加工成可供后续编码的资料片段，并提供检查这些产物是否完整、是否仍对应当前资料的能力。它是独立的离线数据准备路径，尚未接入现有 Agent Loop。

```text
原始资料：knowledge/ 中的三份 Markdown + catalog.json
                         │
                 用户手动执行 prepare
                         │
               校验 → 切块 → 添加来源
                         │
              临时构建 → 校验与输入复查
                         │
               发布到新的构建目录
                         │
         ┌───────────────┴────────────────┐
     chunks.json                    manifest.json
   片段文本及其来源               构建依据与完整性记录
         └───────────────┬────────────────┘
                 用户手动执行 check
                         │
       与当前资料/规则比较，并检查产物是否完整
```

原始文档是内容依据；chunks.json 与 manifest.json 是可重新生成的派生数据。manifest 可以理解为本次构建的清单和校验记录。当前产物没有向量，也没有检索或回答能力。

| 本轮能力 | 体现在哪里 | 解决的问题 |
| --- | --- | --- |
| 切块 | chunks.json 中各片段的 text | 将文档按章节组织成后续可编码的单位，保留步骤与条件 |
| 来源 | 每片段的文档身份、版本、章节、行区间和原文指纹 | 能回到对应版本的原文核对片段 |
| 生命周期的 E1 部分 | prepare、check 和 manifest.json | 创建完整构建，发现过期或损坏，支持用户重新准备 |

## prepare 与 check：职责和执行时机

prepare 是写入操作：根据全部当前资料生成一个新构建，默认拒绝覆盖旧目录。发布之前，程序自动校验临时产物并复查输入，避免正常异常路径留下可被视为成功的半成品。prepare 成功不依赖用户事后再运行一次 check 才算完成。

check 是只读检查操作：先检查已有产物完整性，再检查资料和规则是否变化；匹配时重现片段以核对来源与标识。当前 E1 由用户手动运行，可以紧接 prepare 验证，也可以之后随时运行。没有后台监听或定时检查。

例如上午 prepare 成功生成 build-001，下午修改迁移手册，晚上再 check build-001，就会提示需要重建。用户随后用新输出目录手动执行 prepare；check 本身不修改资料或自动修复。

| check 结果 | 当前 E1 的行为 | 后续 E2 计划中的处理（未实现） |
| --- | --- | --- |
| 输入匹配、产物完整 | 报告成功，退出 0 | 继续检索及生成回答 |
| 文档、目录或处理配置变化 | 提示重建，退出 2 | 停止本次问答，提示用户手动准备 |
| 缺失、不可读或损坏 | 报告检查失败，退出 1 | 停止本次问答，不调用生成模型 |

E2 的已确认设计是由问答程序在每次检索之前自动接入检查能力，不要求模型判断是否需要检查，也不要求用户每次手动运行 CLI。具体接入代码尚未实现；向量产物及其兼容性检查还需要 E2 设计，不能认为当前 check 已经覆盖未来向量索引。prepare 仍由用户明确触发，不因提问而自动重建。E3 再接模型可调用的检索工具，重建不纳入当前只读工具范围。

## 两个本地产物目录与损坏示例

本次 `test-output/e1-20261028/` 下的两个目录用途不同：

- `build-001/` 是正常构建，包含 3 份文档生成的 15 个片段。
- `corrupt-copy/` 是专门复制并修改的故障验证样本，不是正常的第二版，也不是 prepare 日常必需的产物。只把副本中的 chunks.json 改成了 `[]` 加换行，保留原 manifest；原构建没有受影响。

正常清单记录 chunks.json 为 18692 字节并保存其 SHA-256。坏副本实际只有 3 字节，实际指纹也与记录不符，check 因此报告完整性失败。即使文件大小不变，内容改动仍可通过指纹差异发现。检查无法仅据此判断损坏原因，也不提供防恶意协调篡改的认证。

检测后程序停止并返回 1，不修复、不删除、不覆盖。实际使用中，可排查原因后从原始资料生成一个新构建；本次坏副本仅用于演示，无需修复。用户已讨论并理解该流程，本会话提供了以下手动命令；未收到用户终端输出，不能记作用户实跑验证：

```sh
toy-agent/.venv/bin/python toy-agent/prepare_corpus.py check --output test-output/e1-20261028/corrupt-copy
echo $?
```

预期先显示“check 失败：片段产物完整性检查失败”，随后退出码为 1。下文本地验证结果来自实现会话实际运行。

下面保留组件、字段与测试细节，供主会话在理解上述数据流后逐项复核。本次补充只调整交接说明，不改变代码或已有验证结果。

## 组件选择与证据

本轮只比较两个候选，2026-10-28 查阅官方资料后选择 markdown-it-py：

| 候选 | 核实事实与适用性 | 本轮取舍 |
| --- | --- | --- |
| markdown-it-py 4.2.0 | MIT，Python >=3.10；发布页包含 4.2.0，锁文件记录 2026-05-07 上传；基础仅依赖 mdurl。Token 提供行 map，可由标题边界取原文。 | 采用。解析器负责 Markdown 结构，项目负责章节分组与来源/生命周期契约；不使用渲染结果冒充原文。 |
| langchain-text-splitters 1.1.3 / MarkdownHeaderTextSplitter | MIT，Python >=3.10,<4，声明 3.12 支持；PyPI 记录 2026-10-02 发布。可保留标题元数据；默认剥离标题并处理空白，不提供本任务所需的精确原文行定位。 | 未安装。其直接依赖 langchain-core，后者还依赖 langsmith、httpx、pydantic 等；比本次原文分节需要的依赖面大。适合已有该生态且可接受重组文本的应用。 |

官方依据：

- [markdown-it-py 使用说明](https://markdown-it-py.readthedocs.io/en/latest/using.html)、[Token API](https://markdown-it-py.readthedocs.io/en/latest/api/markdown_it.token.html)、[项目元数据与依赖](https://raw.githubusercontent.com/executablebooks/markdown-it-py/master/pyproject.toml)、[发布记录](https://github.com/executablebooks/markdown-it-py/releases)、[MIT 许可](https://raw.githubusercontent.com/executablebooks/markdown-it-py/v4.2.0/LICENSE)。
- [LangChain 标题切分文档](https://docs.langchain.com/oss/python/integrations/splitters/markdown_header_metadata_splitter)、[实现源码](https://raw.githubusercontent.com/langchain-ai/langchain/master/libs/text-splitters/langchain_text_splitters/markdown.py)、[PyPI 元数据与发布](https://pypi.org/project/langchain-text-splitters/)、[拆分包依赖](https://raw.githubusercontent.com/langchain-ai/langchain/master/libs/text-splitters/pyproject.toml)、[core 依赖](https://raw.githubusercontent.com/langchain-ai/langchain/master/libs/core/pyproject.toml)。

维护判断基于公开发布记录，不保证未来维护。所选包与 mdurl 均为 `py3-none-any` wheel，无本地扩展编译；锁定下载量合计约 102 KB。已在本机 Python 3.12.15、arm64 安装并实际解析和测试；未安装另一个候选或验证其完整传递依赖的设备兼容。mdurl 0.1.2 无运行时依赖，[许可含 MIT 风格声明及原始 URL 实现声明](https://raw.githubusercontent.com/executablebooks/mdurl/master/LICENSE)。

依赖变更：pyproject.toml 增加 `markdown-it-py==4.2.0`；uv.lock 锁定该包及 mdurl 0.1.2。首次安装因沙箱 DNS 失败，之后经工具审批联网安装普通依赖；无模型下载、付费服务或密钥读取。

## 文件布局与运行命令

```text
toy-agent/knowledge/catalog.json             文档身份、标题、版本、相对路径
toy-agent/knowledge/release-policy.md        发布规范，887 个汉字
toy-agent/knowledge/migration-guide.md       迁移手册，901 个汉字
toy-agent/knowledge/post-release-checklist.md 发布后检查，893 个汉字
toy-agent/prepare_corpus.py                  独立 prepare/check
toy-agent/test_prepare_corpus.py             17 项 E1 离线测试
<新输出目录>/corpus/chunks.json               片段原文及来源
<新输出目录>/corpus/manifest.json             指纹、配置、数量、完整性记录
```

从项目根目录运行（`user-001` 须不存在；重复准备使用新目录）：

```sh
cd /Users/ironshipzhang/Documents/Codex/ai_engineer
# 本机已安装；其他环境按锁文件同步，可能下载普通依赖。
.tools/bin/uv sync --project toy-agent --locked --cache-dir .cache/uv
mkdir -p test-output/e1
toy-agent/.venv/bin/python toy-agent/prepare_corpus.py prepare --output test-output/e1/user-001
toy-agent/.venv/bin/python toy-agent/prepare_corpus.py check --output test-output/e1/user-001
toy-agent/.venv/bin/python -m unittest discover -s toy-agent -p 'test_*.py' -v
```

默认资料目录按脚本定位；可用 `--knowledge` 指定另一个含 catalog.json 的虚构资料目录。prepare/check 支持相同的 `--max-chars`（默认 1200）。源文件、目录、脚本、测试和锁文件需版本控制；运行产物位于已忽略的 test-output/，未修改忽略规则。

## 切块、来源与清单契约

- 按 commonmark 解析出的顶层 h1–h6 标题起始行切分；列表、引用、围栏代码中的标题不成为边界。保留每节完整原文及标题前内容，不渲染、不清洗、不重排。
- 大小单位为 Python 字符串的 Unicode 码点，包括 Markdown 和换行，非 token。默认最多 1200、重叠 0；超长节/段落/代码不继续细切，明确失败，要求人工整理自包含节。不是检索效果调优参数。
- 支持 UTF-8、LF/CRLF；拒绝空文档、NUL 和单独 CR。源码位置为 1 起始、两端包含的行区间，精确对应保存指纹的原始文档；section 中祖先标题带级别及行号，重复标题与文本可区分。
- 祖先正文没有重复注入子节，内联标题元数据可能保留 Markdown。链接引用和跨节条件不会自动展开；作者需使关键前提、步骤与例外同节。E2 仍需检查上下文是否足够，不将行号正确视为语义正确。
- chunk_id 是配置、身份/版本、原文位置和文本等的 SHA-256。manifest 记录 `e1_prepared_corpus` / 格式 1、目录及文档 SHA-256、组件和规则版本/参数、片段数量、chunks.json 字节数和 SHA-256、input_fingerprint、build_id。无时间、假向量或 embedding 占位字段。

示例：`migration-guide` / 版本 1 / `migration-guide.md` 第 11–20 行为“失败后重跑前的检查”，chunk_id 为 `9b11f361b6786e791833d5e8d1c2e1fc1c2e5448b640e51d6057bfffedc6e8d6`。该片段共 375 字符，包含执行日志、迁移版本记录、是否部分执行以及不能直接重跑的条件。可核对：

```sh
sed -n '11,20p' toy-agent/knowledge/migration-guide.md
```

三个检查项和后续前提/例外保留在同一片段，测试也验证了这一点。资料明确常规发布验证要求，但没有给出足以回答紧急豁免及审批人的条款；这是人工核对的资料设计，不是模型回答质量验收。

## 本地运行与测试结果

| 验证 | 实际结果 |
| --- | --- |
| 修改前回归 | 原有 71 项离线测试通过 |
| E1 与完整回归 | 新增 17 项通过；完整 88 项通过，旧测试未修改 |
| prepare 至 test-output/e1-20261028/build-001 | 退出 0，3 份文档、15 个片段，chunks.json 18692 字节 |
| check 同一构建 | 退出 0，输入匹配、产物完整 |
| check 改用 --max-chars 1300 | 退出 2，需重建 |
| prepare 再用已存在的 build-001 | 退出 1，拒绝覆盖，旧构建保留 |
| check 独立 corrupt-copy 副本（修改 chunks.json） | 退出 1，片段完整性失败；原构建不变 |

正常构建 build_id：`d6fe4d2da557d44234c820edd504de94d7f9195c6cb02ca595e0d2f565415912`。实际片段长度为 109–375 字符。确定性测试在两个不同目录生成相同字节及清单；每片段能按行区间还原，各文档片段拼接等于原文。

其他测试覆盖注册新增/删除与删除后重建、内容/目录元数据/目录格式变化、不可读和缺失资料、非法路径/重复目录项/编码、缺失和损坏产物、重复标题/代码/CRLF、超长失败、构建期间输入变化、输出竞争创建、部分写入及发布失败清理。权限、磁盘和构建中变化通过离线模拟，未制造真实磁盘故障。真实 API、embedding、检索质量和其他操作系统均未验证。

## 发布与检查的简化边界

prepare 先读取全部资料，临时写入并校验，再重读输入；变化则失败。最终独占创建输出容器，把完整临时目录同文件系统 rename 到其 corpus/。多一层目录用于避免覆盖已有空目录；check 只接受完整 corpus/。失败仅清理本次临时目录及自身空容器，不递归删除用户输出。

check 先查产物完整性，再比较输入与配置；匹配时重新切分小规模资料并核对原文/标识。目录文件定义成员：未登记文件忽略；删除需要同步删目录项，仍被引用的缺失文件是检查失败。连目录格式化也会改变字节指纹，是保守但可解释的重建策略。所有资料都删除后空目录清单被拒绝。

无通用锁、活动索引指针、自动更新、增量编码、重试或后台服务。最后复查不是文件系统事务，无法排除之后的外部改动或变化后恢复原值；使用者按项目约定顺序修改/准备。没有 fsync 或断电恢复承诺；强制终止可能留下临时或空预留目录，不能通过 check 冒充成功。摘要校验用于检测意外损坏，不提供对协调篡改的认证。

E1 已验证资料准备、确定性/来源、全量准备和独立变化/完整性检查。E2 的问答前检查接入、过期时阻止生成、embedding/存储/检索选型、引用回答契约与 E3 工具使用仍未实现。

## Git 与主会话复核

开始时已有 AGENTS.md、DECISIONS、PROGRESS、TOY_AGENT_ROADMAP 修改，以及未跟踪的 E1 任务书；本轮保留这些内容。另新增 knowledge/、prepare_corpus.py、test_prepare_corpus.py、本交接；更新 pyproject.toml/uv.lock、PROGRESS、SETUP、ARCHITECTURE、TOY_AGENT_ROADMAP、DECISIONS。前序讨论记录、Agent 代码/协议/配置、共享摘要提示词和旧评估数据未修改。

请主会话重点复核：整节上限失败策略、原文来源契约、显式目录成员与保守指纹、独占容器内发布的简化边界，以及资料中有答案/证据不足问题的依据。决定是否接受并提交 E1；未授权自动提交/推送或开展 E2。后续再核实 embedding 等方案，不据本次依赖选择推导 E2 已定型。

## 主会话验收与阶段结束：2026-10-28

- 独立运行完整回归，88 项通过，git diff --check 通过；未发现阻碍 E1 验收的必要代码修正。
- 正常 build-001 检查退出 0；max-chars 改为 1300 时退出 2；故意损坏的 corrupt-copy 退出 1，未将其视为正常构建失败。
- 在临时目录重新生成两份构建，清单、片段字节与 build-001 完全一致；核对三份文档的 15 个片段，来源行范围可还原原文，拼接等于原始内容。迁移重跑前检查与限制在第 11–20 行的同一片段内保留。
- 接受整节超限失败、目录显式定义成员、保守字节指纹及无文件锁/fsync 的 Toy 简化。E1 prepared corpus 与 E2 向量索引、问答前自动检查的边界明确；E2/E3 尚未实现或授权。
- 用户确认 E1 今日结束并授权提交、推送。项目计划完成后作为学习项目开源，阶段交接、进度与失败记录继续保留；不因阶段完成而删除学习过程。

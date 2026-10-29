# 当前系统：有界只读 Agent Loop

Agent 入口为 `toy-agent/deepseek_summary.py`，其执行路径仍仅使用 Python 标准库，无 Agent 框架。`hello.py` 独立用于检查 Python 环境。E1 的独立资料准备入口使用 markdown-it-py，未接入 Agent，见文末。

## 数据流

```text
CLI 可选独占创建输出文件，从 TOML 本地配置读取密钥
  → 校验项目/任务输入，读取并校验 projects.json，建立任务快照
  → Loop 初始化 messages、成功结果缓存与结构化结果
  → 最多 5 次模型请求，每轮从 Registry 提取两个工具 schema + JSON 输出模式
  → 请求前计数并记录事件；独立提取已知用量，检查 finish_reason
      tool_calls → 整批校验 1～2 个调用、ID 唯一、注册名称、参数及目标范围
                 → 未到第五轮：按返回顺序逐项执行或复用成功结果
                 → 全部成功：追加一条 assistant 批调用消息 + 对应 tool 结果 → 下一轮
      stop       → 检查本任务必需的目标项目工具结果 → 校验摘要 JSON → 返回 succeeded 结果
      其他       → 返回 failed 结果及此前轨迹
  → CLI 展示结果，可选写入 JSON；成功退出 0，失败或保存失败退出 1
```

- Loop 中的 `request_completion` 每轮发送 tools 和 response_format=json_object，省略 tool_choice（有工具时 API 默认 auto）。关闭思考、非流式，输出上限为每次 800 tokens；JSON 输出规则同时写入 system 提示。
- `validate_tool_calls` 要求 tool_calls 正常结束、数组含 1 或 2 个合法 function 调用；每项 ID 非空且本批内唯一，工具名称已注册；arguments 从 JSON 字符串解析，经注册项校验，必须且仅包含非空字符串 project_id，且与本次目标完全一致。整批通过前不执行任何工具；第二项无效也拒绝第一项。
- `TOOL_REGISTRY` 是名称到小型 dataclass 的显式 dict；每项关联模型 schema、参数校验函数和执行适配函数。request_completion 提取 schema，validate_tool_calls 查询注册项，Loop 按注册项执行；无 eval、动态导入、任意函数查找、自动发现或通用 schema 引擎。
- `get_project` 从快照返回 ID、名称和概况；`list_project_issues` 只返回 ID 和问题记录。二者均只读，模型输入不预装业务数据。
- CLI 默认 project_id=xingqiao、task=summary；TASK_TOOLS 声明任务完成条件。summary 需要 get_project 成功结果；issues 需要两个工具的成功结果，顺序不限。两个任务均提供两个工具；summary 允许额外查询目标项目的问题，但这不能代替概况查询。程序不强制 tool_choice，不补发缺失工具。
- `run_project_summary` 的 MAX_REQUESTS=5 包含所有工具决策与最终摘要请求。第五次请求可正常提交摘要；若仍提出工具调用，整批校验后报超限，不执行或复用任何一项工具、不发送第六次请求。

## 状态与缓存

messages、successful_results 和累计 token 用量均为本次函数调用的局部状态，不跨任务保存。每次模型请求重新发送所需对话历史，不依赖服务端对话 ID 保存历史。

成功缓存键为 (工具名, 校验后参数的排序紧凑 JSON)，两个工具结果相互隔离。参数 JSON 的空格变化不影响缓存命中，参数值本身不做去空格或大小写归一化。函数成功返回后才写入缓存；工具失败立即终止，不缓存或重试。

同批允许相同工具和参数、不同 ID；前项成功后，后项即可复用缓存。缓存命中避免再次执行本地函数，整批成功后仍追加 assistant 批调用记录与每项 tool 结果，用当前调用的 id / tool_call_id 对应。缓存不会节省该轮模型请求，也不会跳过参数校验或请求次数计数。

## 成功与失败边界

stop 响应不能携带工具调用；缺少该任务所需的任一目标项目成功结果时，即使摘要 JSON 结构合法也拒绝展示。所需数据齐全后继续使用 parse_summary 校验 progress、blockers、next_steps 三个字符串数组，允许空数组，拒绝缺字段、额外字段和空白元素。结构正确不能保证事实正确。

非法调用、空数组、超过两个调用、批内重复 ID、工具失败、length 截断、非正常结束和超限均立即终止，无自动重试。每轮用量及累计值在校验调用与摘要前记录，后续失败仍保留已确认用量；无有效用量的请求记录 null，累计 complete=false，未知不得当作零计费。每次网络操作为 30 秒超时，没有流程总时限。main 将已处理的错误转为退出码 1，不输出密钥或原始错误响应。

当前没有 MCP、RAG、写操作、跨任务缓存或持久化对话。测试与真实调用记录见 [SETUP.md](SETUP.md)，重要取舍见 [DECISIONS.md](DECISIONS.md)。

## 单轮批调用：顺序执行（D2）

多个调用来自同一模型响应，不代表本地并发。Loop 在整批校验和请求上限检查通过后，使用普通 for 循环逐个处理；前一个返回才处理下一个，没有异步、线程或并发调度。

全部成功后，只追加一条 role=assistant 消息，tool_calls 保留本批完整调用，再按顺序追加每个 role=tool 结果，各自绑定当前 ID。不会将同批拆成多个 assistant 消息；第二项可命中第一项刚写入的成功缓存。

执行中失败立即停止，不执行后续项、不发送下一次请求，也不把部分消息发给模型；此前成功执行和缓存事件仍保留。只读查询没有写入要撤销，不回滚已完成查询，不缓存失败、不重试。整批校验是执行准入，不能保证执行时两项都成功。

model_requests 按请求递增；一次响应有两个调用仍只算一次请求。tool_executions 按真正进入执行函数计数（失败的执行也算），cache_hits 按复用次数计数。第五轮若要求调用，整批连缓存也不处理；第五轮有效最终摘要可以成功。Registry、快照、目标范围和任务完成条件均保留。

## 外部数据快照

`PROJECTS_PATH` 按模块 __file__ 定位 `toy-agent/data/projects.json`，不依赖启动目录；每次 run_project_summary 在首次请求前读取并完整校验一次，两个工具共用该任务的快照。任务中途文件修改不影响已读取数据，下次任务重新读取；没有跨任务缓存或数据库层。

JSON 顶层为非空项目数组，每项严格含 project_id、name、status、issues；前三项为非空字符串，项目 ID 唯一。issues 必须是数组，允许 []；每条严格含非空字符串 id、title、status、description，问题 ID 在项目内唯一，status 保留文本而不限定枚举。

文件缺失、读取失败、UTF-8 / JSON 损坏或任何项目结构错误，在 data_loading 阶段停止，零模型请求、零工具执行、零已知用量且 complete=true；不会将损坏数据转成空列表。未知目标项目在实际工具执行时明确失败；越出目标项目的调用在 tool_validation 阶段拒绝，未执行工具。不输出解析器原始诊断或数据正文。意外本地工具异常也以安全错误保留已有记录并停止，无重试。

## 独立事实评估入口

`evaluate_summary.py` 读取 `evals/project_summary_cases.json`，逐条将状态和共享 SUMMARY_PROMPT 发给模型。request_completion 的 with_tools=False 仅用于这条评估路径；Loop 默认仍提供工具。每条样例一次模型请求，不进入 Loop。

有效摘要由共享 display_summary / parse_summary 校验后返回并写入新 JSON 文件，与原始状态、检查点、用量、错误和待评审标记一起保存。采集脚本不做语义评分；保存结果的 Codex 复核记录及尚未经用户逐条确认的说明见 [EVALUATION.md](EVALUATION.md)。

## 结构化运行结果与执行轨迹（2026-10-11）

run_project_summary 返回标准库 dict，不打印；已处理的失败返回 status=failed、summary=null 和安全 error。成功返回 status=succeeded、已校验 summary、error=null。succeeded 仅表示执行及结构校验通过，不能证明事实保留、字段归属或表达关联正确；当前候选的质量限制保持不变。

model_requests 在实际尝试请求前递增，包含网络失败的那次；tool_executions 在进入注册项执行函数前递增，包含工具失败，非法调用与第五轮拒绝不计入；cache_hits 仅计成功缓存复用。usage 的 prompt_tokens、completion_tokens、total_tokens 是累计已知值，complete 表示每次尝试的用量均有效；未发请求时零累计且 complete=true。消息异常但用量有效时仍保留用量；部分或非法用量整轮记 null，继续停止而不执行工具。

trace 按顺序保存 model_request（序号、结束原因、用量、tool_call_count）、tool_execution（工具名、当前 ID、校验后参数、成功/失败）、cache_hit 和 failure（阶段、安全错误）。tool_call_count 为响应中数组长度；未提供调用时为 0，无法取得有效消息或调用数组时为 null。即使数量超限，也可记录安全的数组长度；不保存未校验的工具名称或参数。第五轮超限失败保留整批已校验元数据：单项保持 tool_name / call_id / parameters，双项保存在 failure.tool_calls 列表；不产生执行或缓存事件。非法调用只记录校验失败，不持久化未经校验的参数。网络无响应仍有请求及失败事件。错误类别为 http_error、network_error 或失败阶段：configuration、task_validation、data_loading、request、response_validation、tool_validation、request_limit、tool_execution、summary_validation。

不保存密钥、请求头、原始错误响应、完整对话或内部推理；当前虚构参数可保存，将来接真实数据需另行设计脱敏。display_run_result 负责 CLI 展示；inspect_response、display_summary 等评估公共函数行为兼容。--output 用 x 模式在读取密钥及请求前预留位置，拒绝覆盖；执行失败结果也保存。保存不是事务操作，磁盘写入失败可能留下空文件或部分 JSON，CLI 返回非零，不自动删除或覆盖。

## 本地 TOML 配置

两个 CLI 共用 deepseek_summary.read_config_api_key，使用 Python 3.12 tomllib。DEFAULT_CONFIG_PATH 从脚本 __file__ 定位根目录 config/local.toml；--config 的显式相对路径保持按工作目录解析。只读取 model.api_key，不改变地址、模型、限制、提示词或 Loop/轨迹。

配置缺失、权限/编码/语法错误及字段无效均在联网前转为 SummaryError；不输出文件内容、密钥或 TOML 原始异常。Loop 在预留 --output 后读配置，失败仍保存 configuration 事件与零请求；评估入口读配置失败安全报错退出，不生成采集报告。配置为本地明文，/config/ 忽略规则不影响已跟踪文件。

## E1：独立 prepared corpus（2026-10-28）

`prepare_corpus.py` 不导入 Agent、不读取模型配置，只读取 `knowledge/catalog.json` 定义的当前资料集合。目录严格含 document_id、title、version、相对 Markdown path；ID/路径唯一，不允许越界或来源符号链接。未登记文件不属于资料集合；删除必须同步移除目录项，仍被引用但缺失的文档是读取失败。

markdown-it-py 4.2.0 以 commonmark 解析标题的行映射。项目按顶层容器中的 h1–h6 分节，保留从本标题到下一个标题之前的原文（含空白、Markdown、代码和步骤）；标题前导内容也保留。section 保存祖先标题、级别与标题行号，但不复制祖先正文。片段上限默认 1200 个 Unicode 码点，包括标记与换行；重叠 0。长章节、长段落或代码块若使整节超限，明确失败，要求人工整理自包含章节，不自动截断/拆分。列表、引用和代码块内部的标题不成为边界。

source 保存原始文档 SHA-256 和 1 起始两端包含的行区间；source_path 为目录相对路径；text 是原文切片，不是渲染或清洗结果。支持 UTF-8、LF/CRLF，拒绝空文档、NUL 与单独 CR。标题展示取自解析器 inline content，可包含内联 Markdown；不提供字节偏移、渲染 HTML 位置或语义完整性保证。跨章节引用仍可能需要 E2 上下文组织。

manifest 标记 `e1_prepared_corpus`、格式版本 1，记录目录原始字节指纹、排序的文档元数据与内容指纹、组件/规则版本和实际参数、片段数量及 chunks.json 字节数/SHA-256。chunk_id 哈希包含配置、文档身份/版本、来源定位及文本；重复标题/正文由位置区分。build_id 校验除自身之外的清单字段；输入指纹包含资料与处理配置。无时间字段、embedding 字段或假向量，相同输入/配置生成相同字节产物。

prepare 在输出父目录创建临时目录，写入并校验 chunks.json 和 manifest.json，再完整重读资料比对输入。变化则失败，不自动重试。完成后通过独占 mkdir 预留新的输出容器，将临时目录同文件系统 rename 为其中的 `corpus/`；消费者只有看到完整且校验通过的 `corpus/` 才能使用。已有输出容器（含空目录、文件、符号链接）拒绝覆盖；竞争者先创建目标时也不覆盖或清理对方。失败只清理本次临时目录及自身的空预留目录，无活动指针或通用锁。

check 先校验清单、片段字节和数量完整性，再读取当前资料和配置；不匹配返回需重建。匹配时重新生成原文切片比对产物，核验来源和 ID。退出 0 表示输入匹配且产物完整；2 表示需重建；1 表示缺失、读取/解析/完整性或准备失败。完整性不等于防恶意篡改签名；check 对小规模资料重新解析，不承诺大规模性能。

本地顺序操作约定下验证了发布前复查与目录可见性；没有输入文件锁，不能排除最后复查之后的外部修改或修改后恢复原值。没有 fsync 崩溃恢复保证，强制终止可能留下临时/空预留目录，check 不视其为成功。每次问答前调用检查、过期拒绝且无生成调用属于 E2，尚未集成。

## E2a：独立远程编码验证（2026-10-29）

```text
E1 原文 + prepared corpus
    → E1 check（变化/损坏则停止）
    → 读取独立 embedding 配置
    → 本地输入校验 → 文档分批编码（10 + 5）→ 问题编码（1）
    → 校验响应索引、数量、维度、有限值、非零范数
    → 保存编码验证 JSON（向量 + 来源映射 + 配置 + 请求轨迹 + 用量）
```

`verify_embedding.py` 负责运行约束和结果记录；`dashscope_embedding.py` 负责配置、百炼原生 HTTP 和响应校验。使用标准库 urllib，无新增依赖；不修改现有 Agent/DeepSeek 路径。模型为 text-embedding-v4，默认 1024 维，文档 text_type=document、问题 text_type=query，dense 输出，不加检索前缀、不自行归一化。endpoint 由用户确认的业务空间地址指定，不猜测地域；关闭重定向和自动重试，每次网络操作超时 30 秒，整次最多 3 个 HTTP 尝试。片段增加时最多取前 20 个并显式记录为样本，预留最后一次给问题。

输出文件在读取配置及联网前独占预留。失败停止后续请求，已成功批次保留，非法当前批次不进入向量结果；有效 usage 在向量校验前提取，无有效 usage 标记不完整，不能解释为零费用。只记录安全错误、非敏感配置和请求 ID，不保存密钥、认证头或原始错误正文。输出是普通 JSON 写入；磁盘失败或强制终止可能留下空/部分文件，无事务恢复或自动续跑。

本地保护上限为每条 8192 UTF-8 字节，比服务的 8192 tokens 限制更保守，但不是精确 token 计数；超过时直接失败，不截断。原生响应支持 index 或 text_index（每项必须且只能出现一个），按唯一完整索引恢复输入顺序；本次真实接口返回 text_index。E1 check 仅保证编码开始时读取的快照匹配，不给整个网络过程加文件锁。

2026-10-29 一次真实验证成功：15 + 1 个向量、1024 维、3 请求、1850 tokens。编码验证结果不是正式向量索引：embedding 配置与资料的长期兼容检查、持久化索引完整性、检索、问答前检查/过期拒绝、来源回答及 Agent 工具集成都留待后续任务。详见 [E2a 交接](tasks/e2a-embedding-handoff.md)。

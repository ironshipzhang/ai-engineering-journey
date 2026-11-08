# 当前系统：有界只读 Agent Loop

Agent 入口为 `toy-agent/src/deepseek_summary.py`，其执行路径仍仅使用 Python 标准库，无 Agent 框架。`hello.py` 独立用于检查 Python 环境。E1 的独立资料准备入口使用 markdown-it-py，未接入 Agent，见文末。

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

`evaluate_summary.py` 读取 `toy-agent/evals/cases/project_summary_cases.json`，逐条将状态和共享 SUMMARY_PROMPT 发给模型。request_completion 的 with_tools=False 仅用于这条评估路径；Loop 默认仍提供工具。每条样例一次模型请求，不进入 Loop。

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

2026-10-29 一次真实验证成功：15 + 1 个向量、1024 维、3 请求、1850 tokens。编码验证结果不是正式向量索引：embedding 配置与资料的长期兼容检查、持久化索引完整性、检索、问答前检查/过期拒绝、来源回答及 Agent 工具集成都留待后续任务。详见 [E2a 交接](tasks/rag/e2a/e2a-embedding-handoff.md)。

## E2b：JSON 文档向量产物与精确检索（2026-11-04）

```text
build：当前资料 + E1 check → 成功全量 E2a 文档向量 → 按 chunk_id 关联 E1 原文 → 带摘要的新 JSON
search：向量 JSON + 当前 E1 检查 + 已有问题向量/编码契约 → 精确余弦排序 → top-k 原文/分数/来源
```

`json_retrieval.py` 提供 build/check/search CLI 及函数。search 是带检查的公共检索入口；纯函数 rank_vectors 只负责算法，不能代替完整入口。向量数值校验抽为 dashscope_embedding.validate_vector，E2a/E2b 共用，不复制两套规则。无新依赖，没有真实配置读取或网络路径。

向量产物为单文件 `e2b_json_vectors` / 格式 1：e1_build_id、encoding、provenance、documents 和 content_sha256。documents 包含完整 E1 片段（原文、标题/版本/章节/来源/ID）及 vector。完整性摘要覆盖除 content_sha256 本身之外的全部字段，按 E1 json_bytes 的 UTF-8、键排序、2 空格缩进、末尾换行和禁止 NaN 规则序列化。摘要检测意外损坏，不认证来源、防恶意修改或验证向量确实由供应商编码；E2a 原始记录无签名，导入时记录其文件 SHA-256 供追溯。

编码契约显式提取 provider、model、dimension、interface、output_type、document_text_type、query_text_type、prefix、instruct、document_input、normalization、endpoint。当前仅支持已有 E2a 原生 v4 语义，endpoint 要求完全一致，是保守兼容策略，并不声称不同业务空间必然不兼容。query 输入逐字来自 E2a 格式 1 的 query.text，记录在 provenance。密钥不进入产物，批量/超时/历史用量不作为兼容字段；无法发现供应商在同模型名下未声明的更新。

build 检查成功标志之外的全量范围、ID 集合、输入行、来源、build_id 和实际向量；不相信记录 norm，允许未知 usage。写入前再次检查当前 E1。check/search 重新校验摘要和向量，并调用 E1 check，将每条原文/来源与 E1 逐条核对；不自动 prepare 或编码。产物可独立于 E2a 文档记录加载，但仍要求 E1 与当前知识资料用于过期检查。CLI 导入问题时保留其真实文本，没有改标签冒充新问题的参数；无法仅从数值证明文本与向量的语义绑定。

余弦按各向量的重算范数计算，不修改保存的原向量；先除范数再做乘积并用 math.fsum 求和，浮点舍入越界时限制在 [-1,1]。分数降序、同分 chunk_id 升序；top-k 正整数，超出返回全部。结果含 requested_top_k、returned_count、排名、原文、来源、构建摘要和编码契约，明确标记 candidates_only，无证据阈值、无生成回答。

输出使用独占文件创建，拒绝覆盖；先完成内存序列化再写。中断可能留下空/部分文件，不能通过后续 JSON/摘要/关联检查；没有原子发布、fsync、锁、活动版本指针或自动更新。检查只保证读取快照。全量读取、逐向量计算、逐次重验 E1 是当前 15 片段 Toy 的有意简化。详见 [E2b 交接](tasks/rag/e2b/e2b-json-retrieval-handoff.md)。

## 目录边界（2026-11-04）

源码位于 toy-agent/src，测试位于 toy-agent/tests；仍是简单脚本模块，执行脚本不需要安装本项目。默认配置定位到仓库 config/local.toml，数据和知识资料定位到 toy-agent/data 与 knowledge，评估输入定位到 toy-agent/evals/cases。以上路径按源码位置解析，用户传入 CLI 的相对路径仍按当前工作目录解释。测试通过显式 PYTHONPATH 导入 src，VS Code 使用同样的源码和测试目录。

任务书/交接与本地产物按阶段分别归档到 docs/tasks 与 test-output。迁移不改变 E1 片段的相对 source_path、build_id、编码契约或向量内容，因此无需重新 prepare/build/编码；已有产物仍须通过原完整性与资料检查。历史评估结果移到 evals/results 并保留原字节。详见 [项目目录](PROJECT_STRUCTURE.md)。

## E2c：新问题的单次编码与检索编排（2026-11-05）

```text
run_query(question, prepared, artifact_path, output, ...)
  → 独占预留输出（函数与 CLI 都不能绕过）
  → validate_texts / top-k 预检
  → E2b load_checked（当前 E1 + 文档向量完整性/来源/过期）
  → read_embedding_config → encoding_contract → 与产物契约完全一致
  → request_embeddings([question], "query")，最多一次
  → 提取 usage / request_id → 校验 HTTP 与向量
  → E2b search（再次检查 E1）
  → 单个 JSON 运行记录 + CLI 展示候选
```

`live_query_retrieval.py` 只编排既有 E2a 客户端和 E2b 公共 search，不复制余弦或绕过检查。没有 prepare/build、文档编码、生成或 Agent 工具调用。问题逐字发送并保存在 question/query.text/检索结果中；复用已有 8192 UTF-8 字节保护，不是精确 token 预算。endpoint 保守完全相同；运行参数不参与向量空间比较。密钥只在通过资料检查后由配置读取器用于认证，不写入结果。

运行记录类型 e2c_live_query_retrieval、格式 1，保存问题、top-k、E1 build_id、文档摘要、实际非敏感 encoding、最多一项 requests、用量、耗时、已验证 query 和 E2b retrieval。没有完整文档向量副本。前置失败是 0 请求、0 已知 tokens、complete=true；发起请求后先置用量不完整，取得有效 usage 才置 true。用量先于向量校验记录，非法向量仍保留已知费用依据。编码成功后检索失败保留 query，retrieval=null，status=failed。

所有流程异常按阶段输出固定安全诊断，不持久化原始异常、认证头或响应正文。输出在任何配置读取前以 x 模式预留；函数成功返回表示记录保存完成，流程是否成功看 status。输出预留/写入/刷新/关闭失败抛 OutputError（携带内存记录），CLI 退出 1。记录用 JSON Unicode 转义保存，以便无法 UTF-8 编码的问题也能留下失败记录；解析后文本不变，终端正常显示中文且不打印向量。

继承单次网络操作 30 秒超时、无重试/重定向，并非总流程时限。结果结束时才写入，非事务保存；中断可能留下空/部分文件，关闭失败也可能已写出完整字节，仍以保存失败处理。检查基于读取快照，没有文件锁，不能检测供应商未声明的模型变更。文档产物是请求前加载的快照，search 复查该快照及当前 E1，不跟踪磁盘上活动索引指针。真实验证截至本日未授权/未执行；137 项离线测试通过。详见 [E2c 交接](tasks/rag/e2c/e2c-live-query-retrieval-handoff.md)。

## E2d：固定检索后的资料问答（2026-11-05，离线实现）

```text
run_answer → 独占预留一个输出文件
  → E2c execute_retrieval：问题/E1/E2b/两种配置/编码兼容前检
  → 单次 query 编码 → E2b search（含 E1 复查）
  → S1–S3 证据表 → 完整 messages ≤16 KiB → 生成前磁盘快照复查
  → 单次 DeepSeek 无工具生成 → 先记录 usage，再检查 JSON/逐条引用
  → 最终磁盘快照复查 → 发布 answer 并保存单个运行 JSON
```

`grounded_answer.py` 负责证据、独立提示词、回答校验和薄 CLI。`live_query_retrieval.execute_retrieval` 从原内部函数更名为复用阶段，新增可选的本地生成配置检查回调，在任何编码请求前运行。两个公共入口均先预留输出；E2c 的参数、结果结构与既有测试保持不变。复用 E2b 检索及 E1 检查，不重新准备资料或编码文档。

生成复用现有 DeepSeek 安全密钥读取器和 known_usage；小型独立 urllib 适配器关闭重定向，不引入 SDK。地址/模型沿用现有常量，非思考、非流式、JSON 对象模式、800 输出 tokens、每次网络操作 30 秒；无工具、无重试/纠错/fallback。旧 SUMMARY_PROMPT、Agent 和评估路径未改。真实接口行为及当前费率仍须在后续授权运行前核实。

证据表按排名赋予本次 S1/S2/S3，包含原文、chunk_id、document_id、标题/版本/章节、相对路径、原文行号、build_id 和向量摘要。问题与表作为一个序列化 user 数据消息，只有固定规则进入 system。生成上下文不发送检索分数或密钥；保留完整片段，超过 messages 序列化 UTF-8 16 KiB 时停在 context 阶段。此保护不是精确 token 限额；提示词隔离不保证抵御所有注入。

回答只接受 answered 或 insufficient_evidence；前者每条 claim 必有本次 ID 和逐字连续引文，后者 claims=[] 并说明资料不足。使用 E1 严格 JSON 解码拒绝重复键及非标准常量；校验字段、类型、正常 stop 和无工具响应。本地 resolved_citations 由可信证据补齐，不信任模型生成的路径。引用存在性不等于语义支持；包括相反结论反例在内，semantic_review 均为 not_performed，CLI 只渲染通过校验且最终复查通过的回答。

记录类型 `e2d_grounded_answer`、格式 1：顶层 question/status/error、evidence、answer、resolved_citations、semantic_review；embedding 子记录复用 E2c 全部问题向量/检索/请求/用量字段（其 succeeded 仅指检索阶段成功），generation 保存非敏感配置/提示词版本、messages_sent、请求和三类 token 用量。失败也保留成功前序阶段。evidence 在上下文构造时保存，只有 messages_sent=true 才表示已发起包含该表的生成尝试，不能证明服务端已收到。无有效 usage 时 complete=false，不能解释为免费；两供应商用量不混算。

生成前后重新从磁盘 load_checked 并比较本次检索的内容摘要和 build_id，可发现运行期间原文变化或有效向量 JSON 被替换。最终复查失败 answer=null，保留合法响应的请求状态与已知用量。没有跨网络文件锁，瞬时修改再恢复或检查之后的变化仍可能不可见。输出独占创建、结束时一次保存，写入/刷新/关闭失败抛 OutputError 并退出 1，可能留空/部分文件，不重试付费请求；没有事务、fsync 或恢复承诺。

166 项离线回归通过，所有新增传输均模拟；未执行真实生成或人工内容验收，E2 未宣布完成。见 [交接](tasks/rag/e2d/e2d-grounded-answer-handoff.md)。


### 2026-11-05 E2d 后续真实验证状态

此前离线实施段落描述当时未授权状态；其后用户明确确认两题预算，主会话完成 2 次 embedding + 2 次生成，无重试。两题均流程/保存成功，分别给出原文支持的迁移限制及资料不足拒答；两阶段用量完整。原始 JSON 不改写 semantic_review，独立的逐条内容核对、官方费率估算与未验证范围见 [真实验证与主会话审阅](tasks/rag/e2d/e2d-real-review-20261105.md)。本轮未修改源码，沿用前检修正后的 168 项离线回归；用户逐条人工终验未记录，不自动进入 E3。

2026-11-05 后续用户已确认两题内容符合预期，E2 本轮最小范围收尾；前文未确认状态为过程记录。不增加调用或进入 E3。

## E3：单个检索工具往返（2026-11-08，离线实现待复核）

```text
run_agent → 独占预留输出 → preflight_retrieval（本地检查两配置/资料/编码兼容）
  → DeepSeek routing（只提供 search_knowledge，默认 auto）
  → 校验单个调用 → 核对初始磁盘快照 → Registry.execute
  → execute_retrieval：单次 query 编码 + E2b search → 再次核对快照
  → assistant.tool_calls + tool.tool_call_id（本次 evidence）
  → messages 大小检查 + 生成前磁盘复查
  → DeepSeek answer（不提供工具）→ E2d validate_answer → 最终磁盘复查
  → 保存单个运行记录
```

独立 `retrieval_agent.py` 复用旧 ToolRegistration 数据结构，维护自己的单项 TOOL_REGISTRY，不修改旧项目 Registry/摘要 Loop。注册项关联 schema、validate_query、search_knowledge；模型只能提供与实际问题逐字一致的 query，不能指定路径、top-k 或改写问题。call_id 采用 1–128 位 ASCII 字母/数字/下划线/连字符的明确本地约束。第一轮无合法调用停止；若正常 stop 且没有调用，completion_gate/retrieval_not_requested，零 embedding，不接受无依据回答。次轮再次要求工具直接拒绝，不执行、不追加请求。

E2c 前检抽为 preflight_retrieval，仍由原 execute_retrieval 调用；E3 在首次模型请求前调用它，在实际工具中仍复用完整 execute_retrieval，重复本地检查是当前小型 Toy 的简化。E2d 生成凭据检查抽为 read_generation_key；受控 request_answer 增加仅关键字 tools=None，默认 payload 无工具，保持 E2d 行为。E2c/E2d 既有测试及旧 Agent 源码/提示词未改，无依赖变化。

首轮 system 描述协议，question 在 user 数据。次轮固定 system 复用 E2d 回答契约并说明 evidence 位于 tool 数据，保留原 user 问题和合法 assistant 调用，只追加一条对应 tool 消息；首轮附带自然语言不作为结论或证据。两轮序列化 messages 都限制 16 KiB UTF-8，不截断；工具 schema 不计入这个既有 messages 限额。工具只返回 question/candidates_only/evidence，不返回文档向量、密钥或隐藏生成。提示词/消息隔离不等于真实注入鲁棒性验证。

每次最多 2 次 DeepSeek + 1 次 query 编码（失败也计数）。沿用非思考、非流式、JSON 对象、800 输出 tokens、每次网络操作 30 秒、无重试/重定向/fallback。接口参数已对照 [DeepSeek 官方 Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)：存在 tools 时默认 auto，次轮不提供 tools；没有发探测或真实模型请求。

记录类型 e3_retrieval_tool_run、格式 1。initial_snapshot 保存 build_id/向量摘要/编码契约；embedding 是 E2c 子记录，未执行时 status=failed 表示该阶段未完成，需结合请求数与 trace 判断；generation 含非敏感配置、逐轮阶段/HTTP/finish_reason/usage 与服务汇总。usage 先于工具/回答校验提取，任一轮缺失则汇总 complete=false，后续有效用量不能覆盖未知状态。response_received 只代表收到可解析的 HTTP 200，validated 表示对应工具/回答校验通过，不代表语义支持。

trace 区分 tool_proposal、参数 validation 和实际 tool_execution；tool_executions 包含失败的工具执行尝试。合法调用与 tool_exchange 保留 call_id，sent_to_model 仅表示已发起携带该结果的第二轮尝试，不证明服务端收到。无效原始参数/错误正文/异常不保存。失败停止，answer=null，保留已有向量、候选与用量；最终复查通过后才赋 answer，semantic_review 始终 not_performed。

快照在初始前检、工具执行前、检索后、最终生成前及答复前检查；重新读取磁盘向量产物，不只比较内存对象。检查无跨网络锁，仍不能保证发现瞬时修改后恢复或检查之后的变化。输出结束时写入，保存失败抛 OutputError/CLI 退出 1，可能留下空/部分文件，不承诺事务或恢复。

193 项离线回归通过（原 168 + E3 25），仅模拟传输；真实模型工具选择、两题内容及供应商失败仍未验证。见 [E3 交接](tasks/rag/e3/e3-retrieval-tool-handoff.md)。


### 2026-11-08 E3 拒绝原因诊断补充

首次真实调用在 tool_validation 被拒绝，旧记录不能细分原因。后续仅为 E3 增加固定本地原因码（error.reason_code、ended trace；存在 tool_proposal 时同步标记），分别覆盖响应/消息、finish_reason、调用数量/结构/ID/类型/名称、参数与 query 绑定；未知异常固定为 validation_failed。CLI 输出固定说明与原因码，不落盘非法值、原始响应或异常文字。正常未检索门禁及既有所有接受/拒绝规则、提示词、请求预算保持不变。新增可选诊断字段不回填旧 JSON，历史真实原因仍未知。196 项离线回归通过，真实复测未授权/未执行；原因码明细见 [E3 交接](tasks/rag/e3/e3-retrieval-tool-handoff.md)。

### 2026-11-08 E3 受控结构诊断与传输 index 规范化

用户后续授权持续修正直至真实测试通过。先增加仅含固定对象层级、已知必需字段缺失列表及多字段布尔标志的安全 details；-003 真实诊断确认调用外层只多了 index:0。现在仅兼容可选整数 0 的 index，未知额外字段和其余类型/值仍拒绝（call_index_invalid），校验后显式构造 id/type/function 并移除 index；trace 记录 transport_index_removed。function 字段、query、单工具/请求上限、提示词和共享 E2 行为保持。

官方文档在流式调用中列出 index，非流式实际携带该字段是本次观测；不泛化信任所有供应商额外字段。最终 199 项离线回归通过，-004 两题真实链路及实现会话内容核对通过。原始 JSON 审阅状态不回填，仍待主会话复核/用户终验；失败记录及原因码演进保留，详见 [E3 真实记录](tasks/rag/e3/e3-real-review-20261108.md)。


### 2026-11-08 任务 E 最终验收

主会话独立复核的 199 项回归及两份 E3 -004 真实结果/内容核对均通过，用户已最终确认，E1–E3 的本轮学习范围验收完成。前文离线/待确认状态为历史过程；原始 JSON 的 semantic_review=not_performed 保持不变，程序可追溯校验、主会话内容审阅与用户终验分别记录。不代表自动语义验证、通用准确率、注入鲁棒性、生产可靠性或 MCP 已验收，Toy 继续使用 JSON。见 [最终交接](tasks/rag/e-stage-handoff.md)。本次只改文档，未重复回归或模型调用。


## 2026-11-08 F：独立的项目 MCP 往返（离线完成）

新增 `mcp_project_agent.py`：输入/输出预留/安全生成配置/项目范围前检 → direct 本地适配器，或官方 SDK ClientSession → stdio Server → get_project → 共同结果契约 → 与模型调用 ID 对应的 tool 消息 → 第二次无工具生成 → 严格三字段摘要。最多两次模型尝试、一次业务调用，独立于旧五轮 Agent 与 E2/E3；无自动重试或 fallback。

业务仍由 deepseek_summary.load_projects/get_project 实现。Server 生命周期只读一次快照，下一次运行才看到文件更新；宿主另作范围及保守大小前检，没有跨进程原子快照。只暴露 get_project，发现时按固定描述与 schema 校验，向模型使用本地 schema。SDK 负责协议与 ID，模型 tool_call_id 与本地协议事件编号分别记录。成功结果须同时有一致的 structured_content 与单个 text JSON，错误/畸形/冲突数据不能变成项目状态。

锁定 mcp==2.3.0，显式 initialize 协议 2025-11-25，不使用自动版本探测。固定解释器与 Server 参数数组，无 shell；不传模型密钥，子进程仅继承 SDK 的 OS 环境允许列表。各协议操作默认 10 秒，SDK 关闭按有界等待与 TERM/KILL 回收；关闭超时阈值在清理完成后判断，失败会撤销有效摘要。此入口顺序运行，未设计多会话并发。

基线 199 / 最终 219 项离线测试通过，含真实子进程与假模型完整消息往返；尚无 F 的真实 DeepSeek 运行或内容验收。实现限制、用量计数与清理覆盖见 [F 交接](tasks/mcp/f-minimal-mcp-handoff.md)。

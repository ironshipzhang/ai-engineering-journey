# 任务 D2：每轮最多两个工具调用（2026-10-12）

已通过主会话实现与机制验收。任务 D 的旧失败原始调用数量/名称仍未知，未因 D2 新运行反推旧事实。后文保留子会话交接时的 Git 状态，最终状态见末尾主会话复核记录。

## 最小设计

- `validate_tool_calls` 返回 1 或 2 个已校验调用。执行前检查整批的 function 类型、非空且批内唯一的 ID、注册名称、JSON 参数、注册项参数规则和目标项目范围；任一不合法，整批不执行。
- Loop 使用普通 for 循环按模型顺序处理缓存或执行函数，前项结束才处理后项。一个模型响应包含多个调用，不等于本地并发；没有异步、线程或新依赖。
- 缓存仍使用工具名 + 校验后参数。相同工具/参数、不同 ID 合法；后项可复用前项成功结果，并绑定自己的当前 ID。
- 整批成功后追加一条 assistant 消息，包含全部 tool_calls，然后按顺序追加对应 tool 消息，每项用自己的 tool_call_id。不会拆成多条 assistant 消息。
- 执行时仍可能失败。首项失败不执行第二项；次项失败保留第一项成功和此前缓存/用量事件，立即停止、不再请求模型。只读查询没有写入需要撤销，因此不回滚；失败不缓存、不重试。整批校验是准入，执行不具有事务性。
- 模型请求计数按实际请求计；两调用仍只是一轮请求。tool_executions 按实际函数进入次数计（含执行失败），cache_hits 按实际复用次数计。第五轮若仍要求工具，整批不执行或复用，无第六轮；第五轮有效最终回答仍可成功。
- model_request 新增 tool_call_count，终端也显示。数组长度是安全诊断；非法名称/参数不保存。第五轮拒绝的双调用在 failure.tool_calls 中记录已校验的名称、ID 和参数；单调用失败元数据保持原字段。

## 保留边界

SUMMARY_PROMPT 内容质量规则、任务必需成功结果、Registry、数据快照、目标项目校验、模型/地址、800 输出 tokens、30 秒每次网络操作超时、配置和 JSON 保存行为保持不变。只修改工具使用说明中的旧调用数量限制。无新工具、依赖、并发、重试、自动评分或历史评估改动。

## 离线验证

先运行原测试：60 项全部通过。实现后完整回归：71 项全部通过，新增 11 项有意义的批次测试，未按提示词字面内容断言。

覆盖双工具同轮成功及顺序互换、整批消息与 ID 绑定、第二项非法时整批零执行、空数组/三个调用/重复 ID/非数组拒绝、同批相同调用缓存、首项及次项执行失败、此前缓存与成功轨迹保留、第五轮整批拒绝（包括不复用第一项缓存）、第五轮摘要成功、批次后超时保留已知用量、CLI 保存成功及部分执行失败。

原单调用、用量、安全错误、项目数据/范围和输出预留/覆盖/写入/刷新/关闭边界继续回归。git diff --check 通过；共享 SUMMARY_PROMPT、模型/地址/请求限制与 HEAD 一致。离线测试使用假密钥，不访问真实配置或模型。

## 唯一一次真实验证

经授权使用当前本地配置，运行一次 xingqiao / issues，输出预先确认不存在，CLI 独占创建：

```sh
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py --project-id xingqiao --task issues --output test-output/d2-issues-001.json
```

真实验证需要网络权限，按审批通道执行，未绕过限制。进程正常退出 0，无重试或第二次任务。结果 JSON 与终端核对一致，status=succeeded、error=null。

| 请求 | 结束原因 | 实际调用数 | 工具顺序与结果 | 输入 | 输出 | 总 tokens |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| 1 | tool_calls | 2 | get_project → list_project_issues，均执行成功 | 775 | 75 | 850 |
| 2 | stop | 0 | 最终三字段摘要 | 1078 | 96 | 1174 |

累计：model_requests=2、tool_executions=2、cache_hits=0；输入 1853、输出 171、总计 2024 tokens，complete=true。轨迹为 model_request → tool_execution → tool_execution → model_request。同轮两次执行均记 request_number=1，不能误算两次模型请求。

摘要包含接口完成与详情联调、已解决的登录提示问题、迁移失败及小林排查、原因未确认、演示延期风险和下一步计划。succeeded 表示取数/执行/结构通过，不宣称内容质量验收通过，也未新增内容评分或调词。

2026-10-12 重新查验 [DeepSeek 官方价格与能力](https://api-docs.deepseek.com/quick_start/pricing/)：Flash 支持 JSON Output / Tool Calls，峰值未命中输入 $0.30 / 百万 tokens、输出 $1.20 / 百万 tokens。本次按全部输入未命中的峰值费率估算上限约 $0.0007611；不是实际账单。未查询账户余额或剩余额度，未验证其他地区可用性。本次成功仅确认当前设备的这一次认证与网络访问。

仅程序读取本地配置用于认证，不输出/保存密钥、请求头、原始敏感响应或完整对话。输出路径在已忽略的 test-output/ 内，历史结果未覆盖。

## 用户测试命令

从项目根目录执行。以下两条为离线验证：

```sh
# 所有 71 项测试
toy-agent/.venv/bin/python -m unittest discover -s toy-agent -p 'test_*.py' -v

# 只运行新增 11 项批次测试
toy-agent/.venv/bin/python -m unittest discover -s toy-agent -p 'test_tool_batches.py' -v
```

以下为用户可手动执行的真实调用命令，不属于本轮自动追加验证；每次任务最多 5 次请求，模型也可以选择分轮调用：

```sh
# summary，只输出控制台
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py

# issues，只输出控制台
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py --project-id xingqiao --task issues

# 同时输出控制台并保存完整 JSON，输出文件名须尚不存在
mkdir -p test-output
toy-agent/.venv/bin/python toy-agent/deepseek_summary.py --project-id xingqiao --task issues --output test-output/d2-issues-user-001.json
```

可用 --project-id yunfan 测试空问题列表；--output 不覆盖文件，重复测试要换新文件名。默认本地配置读取方式和 --config 保持兼容。

## 限制与 Git 交接

- 仅一次真实 xingqiao / issues 同轮双工具成功，不保证每次模型都选对工具、调用数量或输出事实；反向顺序、同批缓存、云帆空列表及失败/第五轮场景只离线验证。
- 顺序执行可能留下部分成功的只读查询事件；不做事务、回滚、写操作或恢复。最多两调用的边界仍可被模型突破，此时整批拒绝。
- 每次网络操作超时不等于流程总时限；未知用量不算零计费，预算没有自动拦截。文件写入失败仍可留下部分 JSON。
- 当前 main 仍包含任务 D 和 D2 未提交改动。D2 新增 test_tool_batches.py 和本交接；修改执行/测试及 ARCHITECTURE、SETUP、PROGRESS、DECISIONS，并在 README 和原任务 D 交接标记新设计。完整文件状态以 git status --short 为准；未提交、推送或开展 E。
- 交回主会话复核实现、测试、计数与真实结果；本任务结束后不继续改词或追加运行。

## 主会话复核：2026-10-12

- 核对当前 Git diff 与批次测试，重跑 71 项离线测试全部通过，差异检查通过。整批校验先于执行、批内 ID 唯一、顺序执行、消息组织、缓存隔离及部分失败保留均符合 D2 要求；第五轮整批拒绝且不命中缓存，无第六次请求。
- 核对 d2-issues-001.json：首轮调用数 2，get_project 与 list_project_issues 同轮顺序成功；次轮 stop，调用数 0。两次请求、两次执行、零缓存，输入 1853、输出 171、总计 2024 tokens，分轮用量和完整性标记一致。
- 共享 SUMMARY_PROMPT、模型、API 地址、输出上限与请求次数限制与提交前 HEAD 一致。未追加模型调用、未读取真实配置、未修改代码或历史评估。
- 未发现阻碍本任务提交的问题，接受 D 与 D2 的当前实现并安排本地提交；不推送、不开展 E。真实成功只覆盖本次双工具任务，异常与其他顺序的验证范围仍以离线测试为准。

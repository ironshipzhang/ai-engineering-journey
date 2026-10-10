# 当前进度

更新时间：2026-10-10

## Done

- 明确求职方向、每天学习时间和预计投递窗口。
- 创建本地项目目录，保存最小协作原则与项目说明。
- 已在项目 .tools/ 中安装 uv 0.12.22 和 Python 3.12.15。
- 已创建 toy-agent/ 的无依赖 Python 项目与独立虚拟环境，实际运行 hello.py 成功（arm64，Virtual environment: True）。
- 已验证 Apple Command Line Tools 和 Git 2.39.5 可用，初始化本目录为独立 Git 仓库（main）。
- 已验证 .gitignore 排除 .venv、.tools、.cache、work 和 .env。
- 用户接受每月 10 USD 以内模型费用，选择 DeepSeek 官方 API 为起点；已核对官方 deepseek-flash 的价格和 JSON / Tool Calls 支持。
- 初始 Git 提交保存协作文档、Python 项目配置和已验证的环境检查程序。
- origin 已配置为用户提供的 SSH 地址 git@github.com:ironshipzhang/ai-engineering-journey.git。
- 已安装 VS Code 1.140.0 arm64 和 Microsoft Python 扩展及其依赖；已保存并验证 .vscode/ JSON 配置。
- 用户在 VS Code 运行 hello.py，输出确认使用项目虚拟环境，Python 3.12.15、arm64。
- GitHub SSH 认证成功，GitHub 官方 Ed25519 主机密钥已记录；首次推送成功，main 跟踪 origin/main。
- 新增 Python 标准库脚本 deepseek_summary.py，使用 deepseek-flash 对虚构“星桥”项目状态生成摘要；关闭思考、限制 200 输出 tokens、30 秒网络超时，无自动重试。
- 2026-10-02 真实调用成功：输入 99、输出 54、总计 153 tokens，finish_reason=stop；按全部输入未命中的峰值费率估算上限 $0.0000945，实际扣费以账单为准。
- 验证缺少和空密钥时退出码为 1 且不发送请求；验证异常响应被拒绝、length 截断提示正常。密钥仅从仓库外读取用于认证，未复制或输出。
- 已重新查验官方价格和接口能力；沙箱内网络失败，获准在沙箱外执行后真实调用成功。
- 2026-10-10：摘要改为 JSON 对象；progress、blockers、next_steps 必须存在且仅允许这三个字段，值为字符串数组，允许 []，拒绝空白字符串元素。
- 使用 DeepSeek json_object 模式，输出上限调为 400 tokens；本地解析与校验摘要，截断或非正常结束视为失败，不展示为有效摘要。
- 9 项离线单元测试通过，覆盖空数组、缺字段、错误类型、非法 JSON、额外字段和截断。
- 结构化摘要真实调用成功：输入 215、输出 67、总计 282 tokens，finish_reason=stop。人工对照原文确认包含数据库迁移失败和演示延期风险。

## Current

- 结构化摘要与本地格式校验已完成，运行和离线测试说明见 docs/SETUP.md。

## Next

- 回顾 JSON 语法、字段约定、事实正确性三者的区别；下一候选任务是单个只读工具调用，先讨论设计，不自动实现。

## Open Questions

- 未查询账户剩余额度；月度预算仍是目标，未实现自动预算拦截。HTTP 认证、余额、限流与服务错误已有处理分支，但未针对这些情况发送真实失败请求。
- 格式校验不能判断遗漏或编造；当前只人工核对一个固定输入，尚无事实质量评估集。
- Python 安装器报告动态库 install name 修补失败；当前程序运行成功，原生扩展构建尚未验证，后续若需要构建再检查。

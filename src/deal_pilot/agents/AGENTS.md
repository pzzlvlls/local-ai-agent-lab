# Agent 工厂

## 职责与入口

- `agent_factory.py` 定义组装流程；`main.py` 提供 `main_agent` 工厂及追踪包装。
- `retrieve_agent.py` 提供 `RetrieveAgentFactory`，名称为 `retrieve_agent`，导出 `factory` 与 `factory_with_trace`；后者已在 `langgraph.json` 注册为独立入口。
- `main_agent_state.py` 在 `DeepAgentState` 上增加 `turn_summary`，与轮次中间件保持一致。

## 创建流程

主 Agent 的 `factory()` 读取 Nacos AgentSpec → 创建模型 → 获取内置及 MCP 工具 → 获取子 Agent → 调用 `create_deep_agent()`。默认使用 `SandboxBackend`，有 Skill 时使用 `/shared/skills/{agent_name}` 路径。检索 Agent 覆盖 `factory()`，仅复用模型和工具加载方法，直接使用 LangChain `create_agent()`。

## 核心约束

- Agent 名称决定远程配置和 Skill 目录；不能只改本地属性而遗漏 Nacos 与调用方。
- 内置工具来自 `tools.get_tools()`。MCP 使用 `streamable_http` 和工具名前缀，禁用列表通过 `{mcp_name}_{tool_name}` 匹配；保持两边命名一致。
- 子 Agent 只从 `_AGENT_FACTORIES` 映射加载，当前只注册 `retrieve_agent`，模块必须导出异步 `factory`。未注册的远程名称当前会被忽略；是否启用仍由主 Agent 的远程 AgentSpec 决定。
- 子 Agent 使用 `CompiledSubAgent` 包装已创建的 runnable，避免把原始 AgentSpec 当成可运行图。父工厂读取子 Agent 描述时传入 `sync_skills=False`，是否同步 Skill 由各子工厂决定。
- 主 Agent 使用 `MainAgentState` 与 `turn_summary` 中间件；新增状态字段时同步检查写入方和消费者。
- 基类通过 `get_response_format() -> ResponseFormat[Any] | None` 提供结构化输出扩展点，默认返回 `None`，在 `create_agent()` 中作为 `response_format` 传给 `create_deep_agent`；主 Agent 当前沿用默认值。
- 检索 Agent 使用 LangChain 默认 `AgentState`，挂载 `retrieve_context` 并使用 `ToolStrategy(RetrieveResponse)`；读取配置时传入 `sync_skills=False`，不组装 Skill、子 Agent、沙箱后端或 Deep Agents 内置工具，也不挂载主 Agent 的 `turn_summary`。Nacos 中的 `skills`、`subagents` 不参与检索工厂组装；模型、提示词、内置工具和 MCP 配置仍生效。检索消息契约见 `../middlewares/AGENTS.md`。
- `retrieve_agent.py` 定义 Pydantic 输出模型：`RetrieveResponse` 的必填字段为 `status`（`answered`、`partial`、`unanswerable`）、`answer: str`（Markdown 正文）、`sources: list[Source]` 与 `gaps: list[str]`；每个 `Source` 必填 `title: str` 和 `url: str | None`，链接缺失时显式传 `None`。成功解析的对象由框架写入状态 `structured_response`，调用方应从该字段读取结构化结果。
- 来源实际采用、按文档去重、不编造链接，以及材料充足性判断等要求由字段描述和系统提示词引导；当前没有自定义校验器核验这些语义，不能把类型校验等同于回答有据可查。服务失败仍通过异常表达，不用 `unanswerable` 代替服务错误。
- 检索 Agent 的系统提示词来自 Nacos 的 `instruction_retrieve_agent/AGENTS__MD` 及关联 Prompt。`课件/34. 基于检索结果的内容生成.md` 提供提示词与字段说明示例，不由工厂读取，也不能据仓库文件推断远程资源已配置。提示词需区分普通用户 query 与 `retrieval_results` 参考材料，并约束空结果、来源引用和材料中指令的处理。
- `课件/35. 恢复图片展示.md` 在提示词示例中补充图片展示：读取本次图片检索结果的 `payload.bucket_name`、`payload.bucket_filename`，调用 `get_bucket_file_url` 后使用返回链接输出 Markdown 图片。工具已在本地内置注册表注册，仍需在 Nacos AgentSpec 的 `tools` 中显式选择并配置相应提示词；工厂不自动添加该工具，也不读取课件。工具参数和权限边界见 `../tools/AGENTS.md`，本地改动不代表远程配置或图片展示联调已完成。
- `课件/36. 格式化输出.md` 提供与 `RetrieveResponse` 配套的系统提示词示例，要求通过结构化输出工具返回结果，将正文、引用和图片放入 `answer`；`sources` 仅收录实际支持回答的文档，`gaps` 记录缺失信息或未解决冲突。课程目录 `课程内容.json` 已加入“格式化输出”；课件仍需人工配置到 Nacos，不由工厂自动加载。
- 工厂实例保留 `agent_config`，MCP 工具还有独立的 86400 秒缓存；涉及配置刷新或并发组装时检查共享状态与缓存影响，不假设 Nacos 更新立即生效。

## 修改指引

- 新增子 Agent：实现工厂模块和导出 → 注册 `_AGENT_FACTORIES` → 对齐远程 AgentSpec。只有需要对外暴露为独立图时才修改 `langgraph.json`。
- 优先通过 `get_backend`、`get_middlewares`、`get_state_schema`、`get_response_format` 等扩展点调整差异，公共组装流程留在基类。
- 保留 `factory_with_trace` 的服务入口契约；改导出时同步 `langgraph.json` 和追踪逻辑。

## 验证方式

`tests/units/test_retrieve_agent_factory.py` 使用真实本地 Agent 图和假模型，验证检索工具、结构化输出、主 Agent 委派，以及不组装 Skill、沙箱和自身子 Agent；HTTP Mock 验证配置读取可跳过 Skill 同步。`tests/units/test_run_agent.py` 覆盖父子图流事件适配。真实检索生成仍依赖 Nacos、Embedding、Milvus、模型及配置的其他服务，尚未进行本轮远程联调。行为变化按根目录命令选择适用的 Benchmark 数据集；不得将本地假模型检查称为真实 Agent 质量验证。

# Agent 工厂

## 职责与入口

- `agent_factory.py` 定义组装流程；`main.py` 提供 `main_agent` 工厂及追踪包装；`web.py` 提供 `web_agent` 子 Agent 工厂。
- `retrieve_agent.py` 提供 `RetrieveAgentFactory`，名称为 `retrieve_agent`，导出 `factory` 与 `factory_with_trace`；后者已在 `langgraph.json` 注册为独立入口。
- `main_agent_state.py` 在 `DeepAgentState` 上增加 `turn_summary`，与轮次中间件保持一致。

## 创建流程

`factory()` 读取 Nacos AgentSpec → 创建模型 → 获取内置及 MCP 工具 → 获取子 Agent → 调用 `create_agent()`。默认使用 `SandboxBackend`，有 Skill 时使用 `/shared/skills/{agent_name}` 路径。

## 核心约束

- Agent 名称决定远程配置和 Skill 目录；不能只改本地属性而遗漏 Nacos 与调用方。
- 内置工具来自 `tools.get_tools()`。MCP 使用 `streamable_http` 和工具名前缀，禁用列表通过 `{mcp_name}_{tool_name}` 匹配；保持两边命名一致。
- 子 Agent 只从 `_AGENT_FACTORIES` 映射加载，当前只注册 `web_agent`，模块必须导出异步 `factory`。未注册的远程名称当前会被忽略。
- 子 Agent 使用 `CompiledSubAgent` 包装已创建的 runnable，避免把原始 AgentSpec 当成可运行图。
- 主 Agent 使用 `MainAgentState` 与 `turn_summary` 中间件；新增状态字段时同步检查写入方和消费者。
- 检索 Agent 仅覆盖名称与 `get_middlewares()`，挂载 `retrieve_context`，沿用基类 `DeepAgentState`、后端及配置组装流程；不挂载主 Agent 的 `turn_summary`。检索消息契约见 `../middlewares/AGENTS.md`。
- 检索 Agent 的系统提示词来自 Nacos 的 `instruction_retrieve_agent/AGENTS__MD` 及关联 Prompt。`课件/34. 基于检索结果的内容生成.md` 提供提示词与字段说明示例，不由工厂读取，也不能据仓库文件推断远程资源已配置。提示词需区分普通用户 query 与 `retrieval_results` 参考材料，并约束空结果、来源引用和材料中指令的处理。
- `课件/35. 恢复图片展示.md` 在提示词示例中补充图片展示：读取本次图片检索结果的 `payload.bucket_name`、`payload.bucket_filename`，调用 `get_bucket_file_url` 后使用返回链接输出 Markdown 图片。工具已在本地内置注册表注册，仍需在 Nacos AgentSpec 的 `tools` 中显式选择并配置相应提示词；工厂不自动添加该工具，也不读取课件。工具参数和权限边界见 `../tools/AGENTS.md`，本地改动不代表远程配置或图片展示联调已完成。
- 工厂实例保留 `agent_config`，MCP 工具还有独立的 86400 秒缓存；涉及配置刷新或并发组装时检查共享状态与缓存影响，不假设 Nacos 更新立即生效。

## 修改指引

- 新增子 Agent：实现工厂模块和导出 → 注册 `_AGENT_FACTORIES` → 对齐远程 AgentSpec。只有需要对外暴露为独立图时才修改 `langgraph.json`。
- 优先通过 `get_backend`、`get_middlewares`、`get_state_schema` 等扩展点调整差异，公共组装流程留在基类。
- 保留 `factory_with_trace` 的服务入口契约；改导出时同步 `langgraph.json` 和追踪逻辑。

## 验证方式

目前没有专门的工厂单元测试或检索 Agent 场景测试。局部验证可使用受控配置和替代客户端检查组装；真实检索生成还依赖 Nacos、Embedding、Milvus、模型及按配置使用的沙箱等服务。检索 Agent 应覆盖有结果、空结果、连续轮次与检索失败的场景；本轮仅核对源码与指令，未进行真实服务联调。行为变化按根目录命令选择适用的 Benchmark 数据集；不得将组装检查称为真实 Agent 运行通过。

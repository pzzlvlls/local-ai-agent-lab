# Agent 工厂

## 职责与入口

- `agent_factory.py` 定义组装流程；`main.py` 提供 `main_agent` 工厂及追踪包装；`web.py` 提供 `web_agent` 子 Agent 工厂。
- `main_agent_state.py` 在 `DeepAgentState` 上增加 `turn_summary`，与轮次中间件保持一致。

## 创建流程

`factory()` 读取 Nacos AgentSpec → 创建模型 → 获取内置及 MCP 工具 → 获取子 Agent → 调用 `create_agent()`。默认使用 `SandboxBackend`，有 Skill 时使用 `/shared/skills/{agent_name}` 路径。

## 核心约束

- Agent 名称决定远程配置和 Skill 目录；不能只改本地属性而遗漏 Nacos 与调用方。
- 内置工具来自 `tools.get_tools()`。MCP 使用 `streamable_http` 和工具名前缀，禁用列表通过 `{mcp_name}_{tool_name}` 匹配；保持两边命名一致。
- 子 Agent 只从 `_AGENT_FACTORIES` 映射加载，当前只注册 `web_agent`，模块必须导出异步 `factory`。未注册的远程名称当前会被忽略。
- 子 Agent 使用 `CompiledSubAgent` 包装已创建的 runnable，避免把原始 AgentSpec 当成可运行图。
- 主 Agent 使用 `MainAgentState` 与 `turn_summary` 中间件；新增状态字段时同步检查写入方和消费者。
- 工厂实例保留 `agent_config`，MCP 工具还有独立的 86400 秒缓存；涉及配置刷新或并发组装时检查共享状态与缓存影响，不假设 Nacos 更新立即生效。

## 修改指引

- 新增子 Agent：实现工厂模块和导出 → 注册 `_AGENT_FACTORIES` → 对齐远程 AgentSpec。只有需要对外暴露为独立图时才修改 `langgraph.json`。
- 优先通过 `get_backend`、`get_middlewares`、`get_state_schema` 等扩展点调整差异，公共组装流程留在基类。
- 保留 `factory_with_trace` 的服务入口契约；改导出时同步 `langgraph.json` 和追踪逻辑。

## 验证方式

目前没有专门的工厂单元测试。局部验证可使用受控配置和替代客户端检查组装；真实验证依赖 Nacos、模型和沙箱。行为变化按根目录命令选择单个 Benchmark 数据集；不得将组装检查称为真实 Agent 运行通过。

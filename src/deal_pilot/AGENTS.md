# deal_pilot 包

## 职责与边界

这里实现 Agent 服务、认证、工具、配置、沙箱和评测。`__init__.py` 当前只有示例 `hello()`，不是服务启动入口，也不承担统一初始化。

## 主要调用关系

- `langgraph.json` → `agents/main.py:factory_with_trace` → `utils/trace_wrapper.py` → `AgentFactory.factory()`。
- 工厂读取 `config/nacos` 的 AgentSpec，组装模型、内置工具、MCP、子 Agent 和 Skill，交给 Deep Agents 创建运行图。
- 工具和后端从 `utils/shared.py` 获取认证用户与会话；`backends/sandbox_backend.py` 通过 `utils/sandbox.py` 连接或创建执行环境。
- `app` 接收 Langfuse Webhook；实验入口调用 `benchmarks`，评分由 `benchmarks/evaluators` 提供。
- `graphs` 保存手工构建的普通 LangGraph 图；当前将清理任务包装为可调度图，删除细节位于 `utils/cleanup_expired_traces.py`。

## 模块分工

- `agents` 负责组装，`tools` 负责模型可调用动作，`middlewares` 负责执行阶段状态处理。
- `graphs` 负责普通图的状态、节点和边连接；通过 LangChain 或 Deep Agents 创建的 Agent 图归属 `agents`，不要按是否有定时调度来区分两个目录。
- `config` 负责配置模型及获取，`security` 负责身份和授权；工具参数不能成为认证依据。
- `backends` 负责 Deep Agents 协议适配，公共沙箱连接逻辑放 `utils/sandbox.py`。
- `benchmarks` 负责实验编排，评分公式和结果 schema 放 `evaluators`，HTTP 处理放 `app`。
- `utils` 只保留被其他模块复用的能力，不作为新增业务逻辑的默认归宿。

## 修改与验证

- 调整身份、会话、模型或沙箱配置契约时，沿上述调用链检查受影响模块，不只修改单一函数。
- 注册名、远程 AgentSpec 名称和图导出名是不同层面的标识，改名时逐一核对引用。
- 阅读目标模块的 `AGENTS.md` 后再修改。跨模块改动同步维护局部指令，避免两处描述相互矛盾。

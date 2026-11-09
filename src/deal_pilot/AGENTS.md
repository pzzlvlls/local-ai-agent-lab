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
- `feishu/api` 通过官方 lark-oapi SDK、以应用身份读取知识库、Docx 与下载文档图片；完整同步 SDK 调用通过 asyncio.to_thread 隔离，直接复用 `config/feishu_settings.py`；没有接入 Agent 工具、结构化解析、索引或检索。
- `rag/structure/feishu_doc` 独立提供 `DocxBlock` 列表的原始关系校验和按标题层级构树；异步 `build_tree` 在完整树构建后按文档顺序串行调用图片处理占位函数，等待完成再返回；另有 Data URL、MinIO 私有图片上传及上下文提取辅助函数，尚未编排调用或接入模型识图。content 初始提取纯文本或图片 token，payload 保存代码语言或表格行列数、合并信息；尚未接入 Agent 或实现切分、索引及检索。
- `rag/loader/feishu_doc` 将已有标准树提取为 LangChain Documents；页面、标题、图片、表格和代码分别成文档，父文档保留正文和子文档占位引用。仅本地转换，不读取飞书、不重新构树或按长度切片。
- `utils` 只保留被其他模块复用的能力，不作为新增业务逻辑的默认归宿。

## 修改与验证

- 调整身份、会话、模型或沙箱配置契约时，沿上述调用链检查受影响模块，不只修改单一函数。
- 注册名、远程 AgentSpec 名称和图导出名是不同层面的标识，改名时逐一核对引用。
- 阅读目标模块的 `AGENTS.md` 后再修改。跨模块改动同步维护局部指令，避免两处描述相互矛盾。

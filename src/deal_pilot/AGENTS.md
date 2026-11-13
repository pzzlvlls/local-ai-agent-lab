# deal_pilot 包

## 职责与边界

这里实现 Agent 服务、认证、工具、配置、沙箱和评测。`__init__.py` 当前只有示例 `hello()`，不是服务启动入口，也不承担统一初始化。

## 主要调用关系

- `langgraph.json` → `agents/main.py:factory_with_trace` → `utils/trace_wrapper.py` → `AgentFactory.factory()`。
- 独立入口 `agents/retrieve_agent.py:factory_with_trace` 复用 `AgentFactory.factory()`，挂载 `middlewares/retrieve_context.py`；执行前读取 Nacos `rag_config.retriever` 并显式传给 `rag/retriever/feishu_doc/feishu_doc_retriever.py:search`，将检索结果追加到 messages 后交给模型，通过 `ToolStrategy(RetrieveResponse)` 返回结构化回答。当前未加入主 Agent 的子 Agent 注册表。
- 工厂读取 `config/nacos` 的 AgentSpec，组装模型、内置工具、MCP、子 Agent 和 Skill，交给 Deep Agents 创建运行图。
- 工具和后端从 `utils/shared.py` 获取认证用户与会话；`backends/sandbox_backend.py` 通过 `utils/sandbox.py` 连接或创建执行环境。
- `app` 接收 Langfuse Webhook；实验入口调用 `benchmarks`，按数据集名称选择 `EvalConfig`。当前 `retrieve` 任务显式调用 `retrieve_agent`，读取 `structured_response`，由 `benchmarks/evaluators` 对来源和回答评分。
- `graphs` 保存手工构建的普通 LangGraph 图；清理图调用 `utils/cleanup_expired_traces.py`，`feishu_doc_index` 通过追踪包装工厂注册为独立服务入口，分批调用单文档索引子图。

## 模块分工

- `agents` 负责组装，`tools` 负责模型可调用动作，`middlewares` 负责执行阶段状态处理。
- `graphs` 负责普通图的状态、节点和边连接；通过 LangChain 或 Deep Agents 创建的 Agent 图归属 `agents`，不要按是否有定时调度来区分两个目录。
- `config` 负责配置模型及获取，`security` 负责身份和授权；工具参数不能成为认证依据。
- `backends` 负责 Deep Agents 协议适配，公共沙箱连接逻辑放 `utils/sandbox.py`。
- `benchmarks` 负责数据集读取和实验编排；`evaluators` 保存任务配置、Agent 调用、来源指标公式及 LLM 回答评分模型与 Prompt 默认模板，HTTP 处理放 `app`。逐项阈值判定与报告由 `tests/benchmarks/test_benchmark.py` 完成，Langfuse 实验入口本身不判定回归是否达标。
- `feishu/api` 通过官方 lark-oapi SDK、以应用身份读取知识库、Docx 与下载文档图片；完整同步 SDK 调用通过 asyncio.to_thread 隔离，直接复用 `config/feishu_settings.py`；WikiAPI 和 DocxAPI 已由索引图调用，API 本身不承担解析、索引或检索，尚未注册为 Agent 工具。
- `rag/structure/feishu_doc` 独立提供 `DocxBlock` 列表的原始关系校验和按标题层级构树；异步 `build_tree` 在完整树构建后按文档顺序串行调用图片处理占位函数，等待完成再返回；另有 Data URL、MinIO 私有图片上传及上下文提取辅助函数，尚未编排调用或接入模型识图。content 初始提取纯文本或图片 token，payload 保存代码语言或表格行列数、合并信息；BlockNode 的 to_dict/from_dict 供索引图传递无循环引用的树形状态，本目录不承担切片、索引或检索。
- `rag/loader/feishu_doc` 将已有标准树提取为 LangChain Documents；页面、标题、图片、表格和代码分别成文档，父文档保留正文和子文档占位引用。仅本地转换，不读取飞书、不重新构树或按长度切片。
- `rag/splitter/feishu_doc` 对 loader 结果进一步切片：图片/代码不拆，表格首行表头加单行，页面/章节复用 LangChain 递归切分并保护占位符。切片新增序号与总数，block_id、parent_block_id 等保留来源结构含义；不执行向量化或入库。
- `rag/store/feishu_doc` 使用 PyMilvus 异步客户端显式初始化数据库、集合及稠密/稀疏索引；已有集合先同步可原地更新的 Schema（可空标量新增、VARCHAR 扩容），其他差异预检报错并保留数据；再比较稠密索引类型和度量，变化时释放集合、删除并重建稠密索引后重新加载。另有显式 `backfill_space_titles` 入口，从飞书读取知识空间名称并局部更新历史缺失标题。`get_store()` 首次调用先初始化，再按 Nacos Embedding 配置在线程中构造并缓存 LangChain Milvus 对象。连接配置来自 `config/milvus_settings.py`，索引配置和新集合向量维度来自 Nacos `rag_config`；索引图使用该对象比较版本、写入切片和删除旧版本实体，不在服务启动时自动入库。
- `rag/retriever/feishu_doc` 复用存储对象进行混合检索与重排，返回 `SearchResult(doc, score)`；中间件负责消息注入，Agent 工厂负责模型与远程提示词组装，检索器本身不生成回答。
- `utils` 只保留被其他模块复用的能力，不作为新增业务逻辑的默认归宿。

## 修改与验证

- 调整身份、会话、模型或沙箱配置契约时，沿上述调用链检查受影响模块，不只修改单一函数。
- 注册名、远程 AgentSpec 名称和图导出名是不同层面的标识，改名时逐一核对引用。
- 阅读目标模块的 `AGENTS.md` 后再修改。跨模块改动同步维护局部指令，避免两处描述相互矛盾。

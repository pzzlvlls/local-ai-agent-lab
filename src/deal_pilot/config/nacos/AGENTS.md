# Nacos 资源获取与同步

## 职责与入口

- `nacos_access_token.py` 获取登录令牌；`nacos_config.py` 读取通用 YAML 配置。
- `nacos_agent_spec.py` 读取 AgentSpec 并组装 Prompt、MCP 和 Skill；`nacos_schemas.py` 定义输出模型。
- `nacos_prompt.py` 读取并按给定顺序拼接 Prompt；`nacos_mcp.py` 解析 MCP 端点和禁用工具；`nacos_skill.py` 将 Skill 压缩包同步到共享卷。

## 关键契约

- 所有资源使用 `nacos_settings.namespace_id`。AgentSpec、Prompt、Skill 查询当前使用 `production` label；通用配置使用 `deal_pilot` group，当前 `ConfigName` 支持 `sandbox_config` 和 `rag_config`。
- AgentSpec 的 content 是 JSON；通用配置 content 是 YAML，使用 `yaml.safe_load` 后通过 Pydantic 校验，不将两种格式互换。
- `AgentModelConfig.thinking` 默认 `False`，`utils/create_model.py` 将其传为 `extra_body.enable_thinking`；远程 AgentSpec 显式提供的值优先。此默认值也用于未传模型配置的 LLM 评分器及 `RagImageParser.vl_model_config`，不代表图片识图已实现，也不证明各模型服务实际支持该参数。
- `RagConfig` 包含 `image_parser`、`embedding_model`、`splitter`、`store` 和 `retriever`；`MilvusCollection` 当前仅允许 `feishu_doc`。省略 `store` 时默认生成该集合的 `RagStoreConfig`，其中 `index_type="HNSW"`、`metric_type="COSINE"`，没有索引构建参数字段。显式传入的 `store` 不会自动补齐缺失集合，初始化直接读取 `store["feishu_doc"]`。新集合 Schema 的向量维度取 `embedding_model.dimensions`（默认 1024），已有集合不随配置自动迁移。
- `splitter: SplitterConfig` 默认 `chunk_size=1000`、`chunk_overlap=200`，由单文档索引图读取并显式传给 `split_feishu_doc`，长度单位为字符；这不同于切片函数直接调用时的 overlap 默认值 100。配置字段本身未加数值范围约束，合法性由切片函数检查。不要将 `embedding_model.chunk_size`（请求批量）与正文切片长度混用。
- `retriever: RetrieverConfig` 默认 `fetch_k=10`、`k=4`、`param=None`；`param` 类型为 `list[dict] | None`，用于按向量字段顺序传入各路检索参数，不再接受单个字典。当前存储的向量字段顺序为稠密、稀疏；配置模型不校验参数列表长度、字典内容或 k 的数值范围，需与检索调用一并核对。`reranker` 为 `RerankerConfig`，允许 `rrf`、`weighted`、`model`，默认 `rrf`、`params={}`；RRF/weighted 用于多路结果融合，model 用于模型重排，不将三者都描述为融合算法。
- `middlewares/retrieve_context.py` 和 `tools/milvus.py:milvus_search` 读取 `rag_config`，显式将 `retriever` 配置传给飞书检索器；检索器直接调用且未传 `config` 时仍新建默认 `RetrieverConfig()`，不会自行读取远程检索配置。远程旧配置若仍将 `retriever.param` 写成字典，会在 Pydantic 校验时失败；本地类型变更不代表已迁移 Nacos 配置。
- 系统指令来自资源 `instruction_{agent_name}/AGENTS__MD`，再拼接 `link_prompts`。这份远程指令服务于运行时 Agent，与仓库开发用 `AGENTS.md` 是不同内容，不自动上传仓库指令。
- MCP 当前取 `backendEndpoints` 的第一个端点；工具元数据中的 `enabled=false` 转为禁用列表。修改选端逻辑时同步工厂的工具名前缀规则。
- 当前业务码非零的降级分别为默认 AgentSpec、空 Prompt、缺失 MCP 或默认通用配置；不要把这种结果描述为成功读取远程配置。网络或解析错误也不等同于资源不存在。

## 缓存与共享资源

- 令牌通过进程内异步锁避免重复登录，使用单调时间并提前 30 秒到期；这不是跨进程锁。
- 配置、AgentSpec、Prompt 和 MCP 使用 `func_cache(ttl=nacos_settings.ttl, lazy=True)`：过期有旧值时先返回旧值再后台刷新，刷新失败保留旧值。
- `get_agent_spec` 会调用 `save_skills`，并非纯读操作。Skill 同步会先清理 `/shared/skills/{agent_name}`，再下载、解压到该目录；压缩包放在 `/shared/skill_zips/{agent_name}`。
- 只有共享维护沙箱可写共享卷。改 Skill 同步时检查并发刷新、路径引用和命令转义，不将清理范围扩大到其他 Agent 目录。
- 当前代码尚未提供 Skill 同步的原子替换或完整压缩包安全校验保证；不能把这些能力写成既有实现。

## 修改与验证

- 新资源类型同步 schema、查询参数和调用方；API 字段与版本以实际响应或官方文档为依据，不凭名称推断。
- 本地替代响应可验证组装、降级和缓存语义；真实验证需 Nacos，Skill 场景还需 OpenSandbox，且会写共享资源。
- `__main__` 示例可能访问远程服务或重写 Skill，不作为无副作用检查命令。当前没有专门的 Nacos 集成测试。

# 飞书文档 Milvus 存储

## Schema 与索引参数

- `schema.py:create_schema(dim: int) -> CollectionSchema` 同步构造 Schema；`index_params.py` 的 `create_dense_index_params(config: RagStoreConfig) -> IndexParams`、`create_sparse_index_params() -> IndexParams` 分别构造稠密、稀疏索引参数。这些工厂不连接 Milvus、不创建集合或索引、不写入数据。
- Schema 使用手动主键 `id: VARCHAR(64)`，对应飞书切片 `Document.id`；导出 Markdown 中的 `document_id` 是该 ID 的展示名称，不另设字段。`text` 上限为 2048 字节；切片预算按字符计量，图片/代码还可能整体保留，写入前须另核对 UTF-8 字节长度。
- 来源字段为 `space_id`、`node_id`、`node_title`、`obj_id`、`revision_id`，以及 `block_id`、`block_type`、`kind`、`payload`、`order`、`parent_document_id`、`title_path`、`references`。切片位置保存 `chunk_index`、`chunk_count` 和表格专用 `table_row_index`。`payload`、`title_path`、`references` 用 JSON 保留原结构；`parent_document_id`、`table_row_index` 可空。关系 ID 仍指向来源 `block_id`，不能改成切片主键含义。
- 开启动态字段；`dense` 为 `FLOAT_VECTOR`，维度由 `dim` 传入。`text` 开启中文分析器，`text_to_bm25` Function 从正文生成 `sparse` 稀疏向量。
- `DENSE_INDEX_NAME="dense_index"` 用于 `dense`，类型与度量来自 `RagStoreConfig`，当前没有传入构建参数。`SPARSE_INDEX_NAME="sparse_index"` 用于 `sparse`，固定 `SPARSE_INVERTED_INDEX/BM25`，遍历算法使用服务端默认值；当前没有标量索引。搜索时若显式指定度量，须与相应索引一致。

## 初始化及重建

- `init_store.py:await init_store() -> None` 读取 `get_config("rag_config", RagConfig)`，直接取 `store["feishu_doc"]`，使用 `milvus_settings.uri` 创建一个 `AsyncMilvusClient`。从默认数据库连接开始，目标 `db_name` 缺失则创建，再切换到目标数据库。
- 集合名固定为 `feishu_doc`。缺失时用 `create_schema(rag_config.embedding_model.dimensions)` 创建集合，依次创建 dense、sparse 索引，再加载集合。
- 已有集合只通过 `has_index_changed` 比较稠密索引；变化时调用 `drop_index`，重建稠密索引并重新加载。类型与度量未变时不做写操作，也不重新加载；不迁移 Schema/向量维度，不检查或补建稀疏索引，不比较构建参数。
- `await has_index_changed(config, collection_name, index_name, *, client) -> bool` 使用调用方客户端；集合不存在或 `describe_index` 返回 `None` 时返回 True，否则直接比较返回字典的 `index_type`、`metric_type`。不展开或归一化参数；SDK 抛出的索引缺失等异常原样传播，不能据此保证所有索引缺失情况都能自动重建。
- `await drop_index(collection_name, *, client) -> None` 先 `release_collection`，再按 `DENSE_INDEX_NAME` 删除稠密索引；不删除集合、实体或稀疏索引，不负责重建或重新加载。释放期间集合不可查询/检索；后续操作失败时不会自动恢复加载状态。
- 辅助函数不创建或关闭客户端；`init_store` 统一在 `finally` 中关闭。异常及取消不被捕获转换；已完成的数据库操作不回滚。初始化必须显式调用，尚未接入 Agent 或服务启动流程。

## LangChain 存储对象

- `get_store.py:await get_store()` 返回 `langchain_milvus.Milvus`。模块级 `_lock` 串行保护首次创建，成功后 `_store` 缓存同一对象；后续调用不重新初始化或刷新 Nacos 配置。初始化或构造失败时异常原样传播，缓存仍为空，已完成的数据库操作不回滚。
- 首次调用先 `await init_store()`，再读取 Nacos `rag_config`，使用 `create_embedding_model(config.embedding_model)` 创建 `OpenAIEmbeddings`。连接和数据库来自 `milvus_settings`，集合固定为 `feishu_doc`；字段映射为主键 `id`、正文 `text`、向量 `dense`/`sparse`，稀疏端使用 `BM25BuiltInFunction(text -> sparse)`。开启动态字段，`auto_id=False`、`drop_old=False`，不删除既有集合。
- 调用方可使用返回对象的 `aadd_documents`、`asimilarity_search` 等异步接口；当前没有从飞书加载、切片到入库的编排，也没有额外的业务写入/检索封装。使用已安装的 `langchain-milvus==0.4.0` 时，`aadd_documents` 不自动取 `Document.id`，须显式传入 `ids=[...]`；metadata 需包含 Schema 中的必填来源字段及切片字段，动态字段不能代替这些字段。
- 当前 `Milvus(...)` 构造包含同步联网调用，直接运行在 `get_store()` 所在的事件循环中，尚未做阻塞隔离；不能据函数为 async 就视为全程不阻塞。缓存对象持有同步及异步客户端，当前没有统一关闭或缓存重置入口；不要在使用期间关闭后继续复用缓存对象，也不要跨事件循环复用它。

## 验证边界

- 当前没有对应的存储单元测试或集成测试文件；源码与本地 SDK 参数构造不能证明真实 Milvus 行为。
- 需要真实验证时使用隔离临时数据库，分别核对首次创建、配置未变、稠密索引重建及数据/稀疏索引保留；Nacos 若使用 Mock，应单独注明，不能称为完整联调。
- 2026-10-22 已用真实 Nacos、Embedding 服务和 Milvus 手工验证 `get_store()`：隔离数据库 `deal_pilot_get_store_test_20261022_174056_f016a2` 中创建集合，3 个并发调用返回同一缓存对象；通过返回对象的 `aadd_documents(..., ids=...)` 写入 3 条数据，读回正文与全部测试 metadata 一致，稠密向量均为 1024 维，BM25 与混合检索均将退款样例排在首位。另一个进程也成功获取既有集合。测试数据保留，主键为 `get_store_test_20261022_174056_f016a2_1` 至 `_3`；此次未验证索引配置变更或故障恢复。
- BM25 Function 生成的 `sparse` 字段不允许通过 query 读回原始向量；验证时读回正文/元数据/稠密向量，并通过实际 BM25 搜索核对稀疏检索，不能要求 query 返回该字段。

# 飞书文档 Milvus 存储

## Schema 与索引参数

- `schema.py:create_schema(dim: int) -> CollectionSchema` 同步构造 Schema；`index_params.py` 的 `create_dense_index_params(config: RagStoreConfig) -> IndexParams`、`create_sparse_index_params() -> IndexParams` 分别构造稠密、稀疏索引参数。这些工厂不连接 Milvus、不创建集合或索引、不写入数据。
- Schema 使用手动主键 `id: VARCHAR(64)`，对应飞书切片 `Document.id`；导出 Markdown 中的 `document_id` 是该 ID 的展示名称，不另设字段。`text` 上限为 10000 字节；切片预算按字符计量，图片/代码还可能整体保留，写入前须另核对 UTF-8 字节长度。已有集合在调用初始化时自动比较并原地扩容此限制；缩小长度预检报错。
- 来源字段为 `space_id`、`space_title`、`node_token`、`node_title`、`obj_token`、`revision_id`、`url`、`parent_node_token`，以及 `block_id`、`block_type`、`kind`、`payload`、`order`、`parent_block_id`、`title_path`、`references`。切片位置保存 `chunk_index`、`chunk_count` 和表格专用 `table_row_index`。`payload`、`title_path`、`references` 用 JSON 保留原结构；`space_title: VARCHAR(300)`、`parent_node_token`、`parent_block_id`、`table_row_index` 可空。`space_title` 允许可空以支持历史集合原地新增，正常索引通过 WikiAPI.get_space 读取名称写入。已有集合不会由初始化自动迁移 nullable 属性。关系 ID 仍指向来源 `block_id`，不能改成切片主键含义。
- 开启动态字段；`dense` 为 `FLOAT_VECTOR`，维度由 `dim` 传入。`text` 开启中文分析器，`text_to_bm25` Function 从正文生成 `sparse` 稀疏向量。
- `DENSE_INDEX_NAME="dense_index"` 用于 `dense`，类型与度量来自 `RagStoreConfig`，当前没有传入构建参数。`SPARSE_INDEX_NAME="sparse_index"` 用于 `sparse`，固定 `SPARSE_INVERTED_INDEX/BM25`，遍历算法使用服务端默认值；当前没有标量索引。搜索时若显式指定度量，须与相应索引一致。

## 初始化及重建

- `init_store.py:await init_store() -> None` 读取 `get_config("rag_config", RagConfig)`，直接取 `store["feishu_doc"]`，使用 `milvus_settings.uri` 创建一个 `AsyncMilvusClient`。从默认数据库连接开始，目标 `db_name` 缺失则创建，再切换到目标数据库。
- 集合名固定为 `feishu_doc`。缺失时用 `create_schema(rag_config.embedding_model.dimensions)` 创建集合，依次创建 dense、sparse 索引，再加载集合。
- 已有集合先调用 `sync_schema(collection_name, schema, *, client) -> bool`：归一化 SDK 的布尔/数字/分析器及 Function 表示后比较配置与实际 Schema；全量预检通过后原地新增可空标量字段、扩容非主键 VARCHAR 的 max_length。无变化不写入，返回 False。字段删除、非空字段新增、类型/维度/nullable/分析器/Function/动态字段开关等不兼容差异抛 ValueError，不自动删库、删集合或重建数据；缩小长度也报错。服务端操作失败原样传播，已完成变更不回滚，再次初始化重新比较剩余差异。
- Schema 同步后通过 `has_index_changed` 比较稠密索引；变化时调用 `drop_index`，重建稠密索引并重新加载。类型与度量未变时不重建索引或重新加载；不检查或补建稀疏索引，不比较构建参数。
- `await has_index_changed(config, collection_name, index_name, *, client) -> bool` 使用调用方客户端；集合不存在或 `describe_index` 返回 `None` 时返回 True，否则直接比较返回字典的 `index_type`、`metric_type`。不展开或归一化参数；SDK 抛出的索引缺失等异常原样传播，不能据此保证所有索引缺失情况都能自动重建。
- `await drop_index(collection_name, *, client) -> None` 先 `release_collection`，再按 `DENSE_INDEX_NAME` 删除稠密索引；不删除集合、实体或稀疏索引，不负责重建或重新加载。释放期间集合不可查询/检索；后续操作失败时不会自动恢复加载状态。
- 辅助函数不创建或关闭客户端；`init_store` 统一在 `finally` 中关闭。异常及取消不被捕获转换；已完成的数据库操作不回滚。初始化必须显式调用，尚未接入 Agent 或服务启动流程。

## 历史标题回填

- `backfill_space_titles.py:backfill_space_titles(*, client, collection_name="feishu_doc", batch_size=500) -> int` 只查找 space_title 为 NULL 或空字符串的实体；每个空间在一次调用内通过 WikiAPI.get_space 读取一次名称。每批只发送 id、space_title，使用官方 `upsert(partial_update=True)` 保留正文、向量及其他字段，不调用 Embedding 服务。
- 使用 Strong 查询逐批收敛，不使用 offset 翻页；检查返回更新数量，并在上一批 ID 再次缺少标题时抛错防止无限重试。batch_size 为 1～1000。空间不存在、服务/权限错误、空名称或超出 300 UTF-8 字节时抛错；已经写入的批次保留，后续可重跑续填。不刷新已有非空标题，知识库重命名不在此次回填范围内。
- 调用前需完成 Schema 同步并暂停并发入库。显式执行 `uv run python -m deal_pilot.rag.store.feishu_doc.backfill_space_titles` 会按 Settings/Nacos 初始化并回填当前配置集合；导入模块不运行，不在每次 get_store 时自动回填。
- 设计决策：目标是保存历史数据并同步元数据；选定方案为兼容差异原地更新、不兼容差异报错、标题单独局部回填；原因是维度/类型等变化需要显式数据迁移且不能自动删数据；实现状态为已完成，真实验证见下方。

## LangChain 存储对象

- `get_store.py:await get_store()` 返回 `langchain_milvus.Milvus`。模块级 `_lock` 串行保护首次创建，成功后 `_store` 缓存同一对象；后续调用不重新初始化或刷新 Nacos 配置。初始化或构造失败时异常原样传播，缓存仍为空，已完成的数据库操作不回滚。
- 首次调用先 `await init_store()`，再读取 Nacos `rag_config`，使用 `create_embedding_model(config.embedding_model)` 创建 `OpenAIEmbeddings`。连接和数据库来自 `milvus_settings`，集合固定为 `feishu_doc`；字段映射为主键 `id`、正文 `text`、向量 `dense`/`sparse`，稀疏端使用 `BM25BuiltInFunction(text -> sparse)`。开启动态字段，`auto_id=False`、`drop_old=False`，不删除既有集合。
- 调用方可使用返回对象的 `aadd_documents`、`asimilarity_search` 等异步接口；飞书入库由 `graphs/feishu_doc_index/document_index` 编排，当前调用 `aupsert([str(chunk.id) for chunk in chunks], chunks)`，查询版本和删除旧实体也由该子图负责。使用已安装的 `langchain-milvus==0.4.0` 时，`aadd_documents` 不自动取 `Document.id`，须显式传入 `ids=[...]`；metadata 需包含 Schema 中的必填来源字段及切片字段，动态字段不能代替这些字段。
- `Milvus(...)` 构造包含同步联网调用，当前通过 `await asyncio.to_thread(Milvus, ...)` 隔离；缓存赋值发生在构造成功后。缓存对象持有同步及异步客户端，当前没有统一关闭或缓存重置入口；不要在使用期间关闭后继续复用缓存对象，也不要跨事件循环复用它。线程隔离不能据此视为整个 SDK 调用链都无阻塞。

## 验证边界

- 2026-10-23 已通过 `alter_collection_field` 将真实 `deal_pilot.feishu_doc` 集合的 `text.max_length` 从 2048 原地更新为 10000 字节；更新前后均为 195 条，主键、正文、node_token 与 revision_id 的排序摘要一致，集合 ID、已加载状态及 dense/sparse 索引名称未变。没有删除或重建集合，也未重跑索引图。
- 本地测试：`uv run pytest -q tests/units/test_feishu_doc_schema.py`，覆盖等价 Schema 无写入、字段新增/扩容、不可兼容差异在写入前失败、标题批次/缓存/错误传播及新文档 metadata。
- 真实 Milvus 测试：`MILVUS_INTEGRATION=1 uv run pytest -q tests/integrations/test_feishu_doc_schema.py`；只操作随机数据库，验证新集合、旧 Schema 同步、幂等、局部更新后已有字段/动态字段/向量保留、稠密索引重建及 BM25/稠密搜索，结束清理本次数据库。Nacos 与飞书标题来源使用 Mock，不调用模型。
- 2026-10-23 实际调用真实 Nacos、飞书 WikiAPI 与 Milvus 完成 `deal_pilot.feishu_doc` 标题回填：Strong 查询的有效实体为 206 条、6 个空间，全部已更新，缺失数为 0；再次回填为 0。更新前后所有显式可查询旧字段（含正文和稠密向量）的排序摘要相同，集合 ID、加载状态及 dense/sparse 索引名称未变；没有重跑索引图或重新向量化。BM25 sparse 不能直接 query，本次业务集合不声称比较原始 sparse 值。
- 2026-11-12 复核：`uv run python -m deal_pilot.rag.store.feishu_doc.backfill_space_titles` 首次执行时该集合 206 条切片的 `space_title` 均为空并全部更新，二次执行更新 0 条；Strong 查询缺失数为 0，6 个空间均有标题。执行后集合仍为 206 条，`text.max_length=10000`、`dense.dim=1024`，`dense_index`（HNSW/COSINE）与 `sparse_index`（BM25）状态为 Finished；未重跑索引图或调用 Embedding。此次执行前标题为空与 2026-10-23 的记录不一致，原因未核实，可能涉及数据卷恢复或集合重建。
- 需要真实验证时使用隔离临时数据库，分别核对首次创建、配置未变、稠密索引重建及数据/稀疏索引保留；Nacos 若使用 Mock，应单独注明，不能称为完整联调。
- 2026-10-22 已用真实 Nacos、Embedding 服务和 Milvus 手工验证 `get_store()`：隔离数据库 `deal_pilot_get_store_test_20261022_174056_f016a2` 中创建集合，3 个并发调用返回同一缓存对象；通过返回对象的 `aadd_documents(..., ids=...)` 写入 3 条数据，读回正文与全部测试 metadata 一致，稠密向量均为 1024 维，BM25 与混合检索均将退款样例排在首位。另一个进程也成功获取既有集合。测试数据保留，主键为 `get_store_test_20261022_174056_f016a2_1` 至 `_3`；此次未验证索引配置变更或故障恢复。
- BM25 Function 生成的 `sparse` 字段不允许通过 query 读回原始向量；验证时读回正文/元数据/稠密向量，并通过实际 BM25 搜索核对稀疏检索，不能要求 query 返回该字段。

# RAG 模块

- 当前 `structure/feishu_doc` 提供树节点、添加/移除节点方法，以及异步 `await build_tree(list[DocxBlock]) -> BlockNode`：校验原始块关系并按标题层级构树，提取纯文本或图片 token 到 content，payload 保存代码语言或表格行列数、合并信息，构树完成后按文档顺序遍历全部图片节点，逐张串行调用图片处理函数，等待完成再返回。图片入口当前仍为占位；已提供 Data URL、MinIO 私有图片上传、父链和同父兄弟上下文辅助函数，尚未编排调用。该目录不负责内容渲染。
- `loader/feishu_doc` 提供 `load_feishu_doc_structre(root, metadata=None) -> list[Document]`，按现成 children 结构提取页面、标题、图片、表格和代码文档；保留父正文、子引用及标题上下文，渲染 Markdown/HTML 并校验表格。输入不变，只使用现有依赖与本地计算；契约见下级指令。
- `splitter/feishu_doc` 提供 `split_feishu_doc(docs, *, chunk_size=1000, chunk_overlap=100)`：图片/代码不拆，表格第一行为表头并逐行切片，页面/章节按段落、句子与长度切分，保留目标 overlap 并保护完整占位符。长度固定按字符计量，完整标题也计入预算；切片 metadata 保留来源结构，新增 chunk_index/chunk_count，表格再加 table_row_index。输入不变，不读取飞书或调用模型。
- `store/feishu_doc` 提供 Milvus Schema、稠密/稀疏索引参数及异步 `init_store()`；按 Settings 和 Nacos `rag_config` 初始化数据库、集合与索引，已有集合仅在稠密索引类型或度量变化时重建该索引。新集合向量维度来自 `embedding_model.dimensions`，已有集合不迁移 Schema。具体契约见下级指令。
- `store/feishu_doc/get_store.py` 提供异步 `get_store()`，首次初始化后缓存返回 LangChain Milvus 对象；调用方可使用其异步文档写入和稠密/BM25 混合检索方法。Embedding 由 `embedding_model.py:create_embedding_model` 按 Nacos 配置创建 `OpenAIEmbeddings`，默认模型 `text-embedding`、请求批量 10、1024 维，连接及密钥依赖运行环境中的 OpenAI 配置。
- 飞书解析、切片和入库由 `graphs/feishu_doc_index` 编排：树以 `BlockNode.to_dict()` 结果保存在状态中，Loader 前用 `from_dict()` 还原；切片参数来自 Nacos `rag_config.splitter`，随后使用存储对象写入并清理旧版本实体。各 RAG 子模块仍不自行编排流程或在导入时入库，尚未接入 Agent。图片处理的实现边界见 `structure/feishu_doc/AGENTS.md`。
- 不将此目录名称或类型定义视为已有完整 RAG 能力；具体结构契约见下级指令。

# 单文档索引子图

## 结构与状态

- `graph.py` 使用 StateGraph(DocumentIndexState) 注册节点、版本条件路由及顺序边，导出编译后的 graph，不单独指定输入、输出 Schema；主图以 `{"node": WikiNode}` 调用。
- `state.py` 只定义 DocumentIndexState，包含 node、document、indexed_revision_id、needs_index、metadata、blocks、root、documents、chunks、written_chunk_count 和 status；不依赖父图状态或保存统计增量。
- root 使用 BlockNodeDict，只保存内容与 children；结构化节点在 build_tree 后调用 to_dict，Loader 前用 BlockNode.from_dict 重建引用，再调用 `load_feishu_doc_structre`。
- `nodes.py` 的全部业务节点已有函数体；`resource/feishu_doc_index/document_index` 中同名节点仍是教学占位，两者不能混为一谈。

## 流程与实际行为

获取文档元信息 → 版本比较 → 不需要索引则收尾；需要索引则依次执行：
构建 metadata → 读取正文 → 结构化 → Loader → Splitter → 写入切片 → 清理旧版本实体 → 收尾。

- fetch_document_version 用 node.obj_token 调用 DocxAPI.get_document。compare_versions 通过 `store.aclient.query` 按 `obj_token == document.document_id` 查询 revision_id，limit=1；无记录或第一条记录版本不同则需要索引。当前不按 node_token 隔离、不排序，也不检查所有切片是否完整；同文档被多个 Wiki 节点引用或混合版本时不能据此保证判断准确。
- metadata 保存 space_id、node_token、node_title、obj_token、parent_node_token、url 和本次读取的 revision_id。
- fetch_document_content 当前只调用 `list_blocks(document.document_id)`，没有传 document_revision_id，实际使用 API 默认的最新版本。不能按函数注释宣称正文固定为元信息版本；两次读取之间文档变化时没有一致性校验。
- structure_document、load_documents 复用现有构树与 Loader；图片处理入口仍为占位，没有在此补充模型识图流程。
- split_documents 读取 Nacos rag_config.splitter，显式传入 chunk_size、chunk_overlap；默认分别为 1000、200，单位为字符，与切片函数直接调用的 overlap 默认值 100 区分。
- create_new_index 调用 `store.aupsert([str(chunk.id) for chunk in chunks], chunks)`；成功返回 written_chunk_count=len(chunks)。主键来自现有切片 ID，不含版本后缀，新旧版本相同主键会被更新，不能将其描述为完整保留旧版本的原子替换。
- 仅在写入节点成功后进入 delete_old_index；indexed_revision_id 非 None 时，调用 `adelete(expr=...)` 删除同 obj_token 且 revision_id 不等于当前版本的实体。返回假值则抛 RuntimeError；首次查询无旧版本时跳过删除。不删除集合或 dense/sparse 索引结构，也不清理目录中已删除的文档。
- finish_document 以 written_chunk_count 是否存在决定 success 或 skipped，0 也算 success；子图返回完整状态，主图只累计文档统计。没有切片完整性复查、写入失败回滚或旧版本清理失败后的自动恢复。
- 子图节点不捕获业务异常，异常停止该文档后续节点，由主图的 Exception 边界转成失败记录；已完成的外部写入不撤回。保持构树、加载、切片、存储各模块的职责，不在此复制其实现。

## 验证边界

- 当前没有 `tests/units/test_feishu_doc_index.py`，也没有本子图的专门自动化测试。现有构树、Loader、Splitter 单元测试只覆盖各自本地能力，不能作为整条流水线验证。
- 本次只核对源码与指令，未执行真实索引或外部服务联调。后续验证需分别检查跳过、首次写入、版本更新、部分写入失败和旧版本清理失败，记录实际服务与数据范围；不能将构图或类型检查称为入库成功。

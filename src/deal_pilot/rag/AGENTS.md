# RAG 模块

- 当前 `structure/feishu_doc` 提供树节点、添加/移除节点方法，以及异步 `await build_tree(list[DocxBlock]) -> BlockNode`：校验原始块关系并按标题层级构树，提取纯文本或图片 token 到 content，payload 保存代码语言或表格行列数、合并信息，构树完成后按文档顺序遍历全部图片节点，逐张串行调用图片处理函数，等待完成再返回。图片入口当前仍为占位；已提供 Data URL、MinIO 私有图片上传、父链和同父兄弟上下文辅助函数，尚未编排调用。该目录不负责内容渲染。
- `loader/feishu_doc` 提供 `load_feishu_doc_structre(root, metadata=None) -> list[Document]`，按现成 children 结构提取页面、标题、图片、表格和代码文档；保留父正文、子引用及标题上下文，渲染 Markdown/HTML 并校验表格。输入不变，只使用现有依赖与本地计算；契约见下级指令。
- 尚未实现实际图片解析、长度切片、索引或检索，也未接入 Agent。
- 不将此目录名称或类型定义视为已有完整 RAG 能力；具体结构契约见下级指令。

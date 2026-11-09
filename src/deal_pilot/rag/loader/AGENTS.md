# 标准结构加载

- 目标：将已经标准化的来源树提取为 LangChain `Document`，为后续处理保留结构关系。
- 选定方案：按来源类型组织；当前 `feishu_doc` 复用 `structure/feishu_doc` 的 `BlockNode`、`BlockType` 和 `CodeLanguage`，不新增依赖。
- 原因：构树负责章节归属，loader 只沿有序 children 消费现成结构，不重新读取数据或改变树。
- 实现状态：已实现本地飞书树的结构提取、Markdown 正文及 HTML 表格渲染；不执行远程调用、长度切片、向量化、索引或检索，尚未接入 Agent。
- 飞书入口与局部验证见 `feishu_doc/AGENTS.md`。

# 飞书 Documents 进一步切片

- 入口：`split_feishu_doc(docs, *, chunk_size=1000, chunk_overlap=100) -> list[Document]`。输入为 loader 的结构 Documents，`id == metadata.block_id` 且 ID 唯一；不接受已加切片字段的输入，不修改原对象。配置要求整数 `chunk_size > 0`、`0 <= chunk_overlap < chunk_size`；长度固定按字符数计算，不提供自定义计量参数。
- 图片和代码原文整份保留，不受长度限制。页面和章节正文复用已有 `RecursiveCharacterTextSplitter`，按段落、句子、换行/空白、字符逐级兜底，保留分隔符；完整标题路径重复到每片并计入预算。overlap 为目标上限，实际受自然边界和占位符原子性约束；不跨来源 Document。
- `references.py` 将完整 document-ref 临时替换为不与正文冲突的单字符，长度计量前还原，切分后还原；原子占位符不会被拆开或泄漏临时字符。占位符超出正文预算或标题本身使正文无可用预算时明确报错。源 references 与实际占位符不一致时报错；图片/代码原文中的标签示例允许作为普通文字保留，不当成新增引用。输出 references 依当前正文中的首次出现顺序筛选、去重，包括 overlap、重复表头和跨行合并展开带入的引用。
- `table.py` 复用锁文件中已有 BeautifulSoup4（html.parser），读取 loader 的单张 HTML 表格，第一物理行固定为表头，每个数据物理行生成“表头＋该行”一片，不做表格 overlap。横向合并保留 colspan；纵向合并将原单元格内容展开到覆盖的各行并去除 rowspan，保证行片独立可读。校验 payload 中的原表尺寸、合并越界/重叠和缺失单元格；仅有表头的表格保留一片，`table_row_index=0`。表头加数据行连同标题超过预算时明确报错，不截断、不静默返回超限片。
- `Document.id`：单片保留来源 ID；多片使用 `<block_id>::chunk:<index>`，检查来源和输出 ID 冲突。`metadata.block_id/block_type/kind/payload/order/parent_document_id/title_path` 仍表示原结构，深拷贝保留；payload 不改成切片尺寸，order 不改成全局切片序号。仅新增 `chunk_index`、`chunk_count`，表格再加 `table_row_index`（原表行号，表头为 0，第一数据行为 1）；不新增重复的 source_document_id。预占字段冲突时报错。
- references.id 和 parent_document_id 保留原 block_id，表达来源结构关系；需要通过输出切片的 block_id 分组解析，不能假定总能按 Document.id 找到完整原文。函数不要求或执行原始 Documents 入库。
- 验证：`.venv/bin/python -m pytest -q tests/units/test_feishu_doc_splitter.py tests/units/test_feishu_doc_loader.py`；类型检查 `.venv/bin/pyright --pythonpath .venv/bin/python src/deal_pilot/rag/splitter tests/units/test_feishu_doc_splitter.py`。覆盖长度、overlap、完整引用、元数据独立、表格行与合并及非法输入；本地 JSON 导出不代表模型、真实飞书或向量库验证。
- 本地演示：`temp/export_feishu_doc_chunks.py` 消费上节课两份 `.documents.json`，以 500/50 字符配置导出至新目录 `temp/document_chunks/`，按来源分目录，每片为带 YAML metadata 的 Markdown；输出目录已存在时明确报错，不覆盖上次产物。

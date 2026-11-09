# 飞书标准树到 Documents

- 入口：`feishu_doc_loader.load_feishu_doc_structre(root: BlockNode, metadata: dict[str, Any] | None = None) -> list[Document]`，保留 `structre` 拼写；根必须为 PAGE。
- `extraction.py` 用显式栈做前序归属分配与后序内容组装，只沿 children 遍历，校验空/重复 ID、对象重复挂载及环；不使用 parent/prev/next，不修改输入。失败直接抛错，不返回部分结果。
- PAGE、HEADING_1–HEADING_9、IMAGE、TABLE、CODE 生成 Document，ID 直接用来源 block_id，输出与 order 为前序。其他类型在最近的上级文档内保留正文、格式和子引用，不改变文档归属；未知类型无自身文本时保留类型与 ID 标记。
- 子文档位置使用转义后的单行 `<document-ref id="..." kind="...">标签</document-ref>`；直接子引用按出现顺序记录 id/kind/placeholder。标题标签用来源标题，图片/表格/代码用类型标签，避免把完整子正文重复放入父文档。
- 内部 metadata 严格为 block_id、block_type（int）、kind、payload、order、parent_document_id、title_path、references；调用方字段冲突抛 ValueError。每份文档分别深拷贝外部 metadata 和来源 payload，标题路径及引用也各自独立。
- title_path 为非空页面/章节标题列表；图片、表格、代码继承所属路径。正文开头按路径深度输出 Markdown 标题，超过六层使用六级标题继续保留路径项；页面/标题自身不再次输出标题。
- `rendering.py` 保留段落、引用、列表、公式、分隔线和高亮（aside）；不恢复缺失的链接、待办状态或行内样式。代码原文保留，围栏长于正文最长连续反引号；已知语言由现有枚举生成名称，未知编号仅留在 payload。图片只读现有 content/payload，不下载或调用模型。
- `table.py` 使用 HTML td/tr 表达完整行列，不推断表头。children 必须是按行排列的 row_size * column_size 个 TABLE_CELL；尺寸为正整数。缺少 merge_info 表示无合并，存在时必须与单元格数相同，每项包含整数 row_span/col_span。合并起点跨度为正且不能越界/重叠；覆盖位置只能是 (1,1) 或 (0,0) 标记且渲染内容为空，否则抛 ValueError，不丢弃覆盖位置的正文或结构引用。普通文本转义，生成的引用标签保持原样。
- 单元测试：`.venv/bin/python -m pytest -q tests/units/test_feishu_doc_loader.py`，验证结构种类、归属、顺序、深树、引用转义、metadata 独立、代码围栏、表格合并与异常输入。类型检查：`.venv/bin/pyright --pythonpath .venv/bin/python src/deal_pilot/rag/loader tests/units/test_feishu_doc_loader.py`。
- `temp/BsEbwxwQPiDbH5kv9B2cDpa2nRh.documents.json` 与 `temp/QPmAwpxKoi46Q9kMKw6cQbavnod.documents.json` 是已有标准树的完整 Document 本地验证产物，含 id/page_content/metadata；同名 `.documents.md` 便于阅读。它们不是测试 fixture，也不代表本轮真实飞书、模型或存储验证。

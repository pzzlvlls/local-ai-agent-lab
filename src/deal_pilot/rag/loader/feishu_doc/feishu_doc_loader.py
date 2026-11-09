"""已标准化飞书树的结构提取入口。"""

from typing import Any

from langchain_core.documents import Document

from deal_pilot.rag.loader.feishu_doc.extraction import extract_documents
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode


def load_feishu_doc_structre(
    root: BlockNode, metadata: dict[str, Any] | None = None
) -> list[Document]:
    """一个结构节点生成一份 Document；只沿 children 提取，不修改输入。

    PAGE、标题、图片、表格、代码各自成文档；其他节点保留在最近的
    上级文档内。非法根、ID、树关系、表格或 metadata 冲突抛 ValueError。
    """
    return extract_documents(root, metadata)

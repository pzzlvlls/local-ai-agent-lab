"""单文档子图的处理中间状态及处理结果。"""

from typing import Literal, TypedDict

from langchain_core.documents import Document
from pydantic import JsonValue

from deal_pilot.feishu.api.models import DocxBlock, DocxDocument, WikiNode
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNodeDict


class DocumentIndexState(TypedDict, total=False):
    """各节点只返回自己更新的字段，字段类型在此定义。"""

    node: WikiNode
    """由主图调用子图时传入的飞书 node。"""
    document: DocxDocument
    """当前文档元信息，包含本次版本号 revision_id。"""
    indexed_revision_id: int | None
    """已建立索引的版本号；首次索引时为 None。"""
    needs_index: bool
    """版本对比得到的结果：是否需要索引。"""
    metadata: dict[str, JsonValue]
    blocks: list[DocxBlock]
    root: BlockNodeDict
    """结构化树的字典表示，不含父节点与兄弟的循环引用。"""
    documents: list[Document]
    chunks: list[Document]
    written_chunk_count: int
    status: Literal["success", "skipped"]
    """本次文档处理成功，或因版本未变化而跳过。"""

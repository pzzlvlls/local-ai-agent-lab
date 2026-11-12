"""按流程顺序排列的单文档节点；逐个填写函数体即可。"""

from typing import Literal

from deal_pilot.config.nacos.nacos_config import get_config
from deal_pilot.config.nacos.nacos_schemas import RagConfig
from deal_pilot.graphs.feishu_doc_index.document_index.state import (
    DocumentIndexState,
)
from deal_pilot.feishu.api import DocxAPI
from deal_pilot.rag.loader.feishu_doc.feishu_doc_loader import load_feishu_doc_structre
from deal_pilot.rag.store.feishu_doc.get_store import get_store, COLLECTION_NAME
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.tree_builder import build_tree
from deal_pilot.rag.splitter.feishu_doc.feishu_doc_splitter import split_feishu_doc


async def fetch_document_version(state: DocumentIndexState) -> DocumentIndexState:
    """根据 node 获取文档元信息，返回 {"document": DocxDocument}。"""
    node = state.get("node")
    docx = DocxAPI()
    assert node is not None
    doc = await docx.get_document(node.obj_token)
    assert doc is not None
    return {"document": doc}


async def compare_versions(state: DocumentIndexState) -> DocumentIndexState:
    """返回 indexed_revision_id（int | None）和 needs_index（bool）。"""
    doc = state.get("document")
    assert doc is not None
    store = await get_store()
    result = await store.aclient.query(
        collection_name=COLLECTION_NAME,
        filter=f'obj_token=="{doc.document_id}"',
        output_fields=["revision_id"],
        limit=1,
    )
    if len(result) == 0:
        return {"indexed_revision_id": None, "needs_index": True}
    indexed_revision_id = result[0]["revision_id"]
    return {
        "indexed_revision_id": indexed_revision_id,
        "needs_index": indexed_revision_id != doc.revision_id,
    }


def route_by_version(
    state: DocumentIndexState,
) -> Literal["build_metadata", "finish_document"]:
    """根据版本对比节点写入的 needs_index 选择是否继续索引。"""
    needs_index = state.get("needs_index")
    if needs_index:
        return "build_metadata"
    else:
        return "finish_document"


async def build_metadata(state: DocumentIndexState) -> DocumentIndexState:
    """根据 node 和 document 构建来源信息，返回 {"metadata": 字典}。"""
    doc = state.get("document")
    node = state.get("node")
    assert doc is not None
    assert node is not None
    return {
        "metadata": {
            "space_id": node.space_id,
            "node_token": node.node_token,
            "node_title": node.title,
            "obj_token": node.obj_token,
            "parent_node_token": node.parent_node_token,
            "url": node.url,
            "revision_id": doc.revision_id,
        }
    }


async def fetch_document_content(state: DocumentIndexState) -> DocumentIndexState:
    """按 document.revision_id 读取正文，返回 {"blocks": list[DocxBlock]}。"""
    docx = DocxAPI()
    doc = state.get("document")
    assert doc is not None
    blocks = await docx.list_blocks(doc.document_id)
    return {"blocks": blocks}


async def structure_document(state: DocumentIndexState) -> DocumentIndexState:
    """将 blocks 结构化，返回 {"root": 不含循环引用的树形字典}。"""
    blocks = state.get("blocks", [])
    root = await build_tree(blocks)
    root_dict = root.to_dict()
    return {"root": root_dict}


async def load_documents(state: DocumentIndexState) -> DocumentIndexState:
    """将 root 和 metadata 传给 Loader，返回 {"documents": list[Document]}。"""
    root_dict = state.get("root")
    assert root_dict is not None
    root = BlockNode.from_dict(root_dict)
    metadata = state.get("metadata", {})
    documents = load_feishu_doc_structre(root, metadata)
    return {"documents": documents}


async def split_documents(state: DocumentIndexState) -> DocumentIndexState:
    """将 documents 传给 Splitter，返回 {"chunks": list[Document]}。"""
    documents = state.get("documents", [])
    config = await get_config("rag_config", RagConfig)
    chunks = split_feishu_doc(
        documents,
        chunk_size=config.splitter.chunk_size,
        chunk_overlap=config.splitter.chunk_overlap,
    )
    return {"chunks": chunks}


async def create_new_index(state: DocumentIndexState) -> DocumentIndexState:
    """写入本次版本的全部 chunks，成功后返回 {"written_chunk_count": int}。"""
    store = await get_store()
    chunks = state.get("chunks", [])
    await store.aupsert([str(chunk.id) for chunk in chunks], chunks)
    return {"written_chunk_count": len(chunks)}


async def delete_old_index(state: DocumentIndexState) -> DocumentIndexState:
    """删除当前文档的旧版本索引，成功后返回空字典。"""
    store = await get_store()
    doc = state.get("document")
    assert doc is not None
    revision_id = state.get("indexed_revision_id")
    if revision_id is not None:
        success = await store.adelete(
            expr=f'obj_token=="{doc.document_id}" and revision_id!={doc.revision_id}'
        )
        if not success:
            raise RuntimeError(f"删除文档 {doc.title} 版本 {revision_id} 的索引失败")
    return {}


async def finish_document(state: DocumentIndexState) -> DocumentIndexState:
    """返回 {"status": "success"} 或 {"status": "skipped"}。"""
    written_chunk_count = state.get("written_chunk_count")
    if written_chunk_count is None:
        return {"status": "skipped"}
    return {"status": "success"}

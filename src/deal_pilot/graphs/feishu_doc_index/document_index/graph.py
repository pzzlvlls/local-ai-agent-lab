"""单文档索引子图，按课件流程依次连接节点。"""

from langgraph.graph import END, START, StateGraph

from deal_pilot.graphs.feishu_doc_index.document_index.nodes import (
    build_metadata,
    compare_versions,
    create_new_index,
    delete_old_index,
    fetch_document_content,
    fetch_document_version,
    finish_document,
    load_documents,
    route_by_version,
    split_documents,
    structure_document,
)
from deal_pilot.graphs.feishu_doc_index.document_index.state import (
    DocumentIndexState,
)

builder = StateGraph(DocumentIndexState)
builder.add_node("fetch_version", fetch_document_version)
builder.add_node("compare_versions", compare_versions)
builder.add_node("build_metadata", build_metadata)
builder.add_node("fetch_content", fetch_document_content)
builder.add_node("structure_document", structure_document)
builder.add_node("load_documents", load_documents)
builder.add_node("split_documents", split_documents)
builder.add_node("create_new_index", create_new_index)
builder.add_node("delete_old_index", delete_old_index)
builder.add_node("finish_document", finish_document)

builder.add_edge(START, "fetch_version")
builder.add_edge("fetch_version", "compare_versions")
builder.add_conditional_edges("compare_versions", route_by_version)
builder.add_edge("build_metadata", "fetch_content")
builder.add_edge("fetch_content", "structure_document")
builder.add_edge("structure_document", "load_documents")
builder.add_edge("load_documents", "split_documents")
builder.add_edge("split_documents", "create_new_index")
builder.add_edge("create_new_index", "delete_old_index")
builder.add_edge("delete_old_index", "finish_document")
builder.add_edge("finish_document", END)

graph = builder.compile(name="document_index")

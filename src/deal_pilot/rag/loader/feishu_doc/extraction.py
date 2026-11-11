"""沿 children 迭代校验、分配文档归属并组装 Document。"""

from copy import deepcopy
from dataclasses import dataclass
from html import escape
from typing import Any

from langchain_core.documents import Document

from deal_pilot.rag.loader.feishu_doc.rendering import render_node, title_prefix
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType


_INTERNAL_FIELDS = frozenset(
    {
        "block_id",
        "block_type",
        "kind",
        "payload",
        "order",
        "parent_block_id",
        "title_path",
        "references",
    }
)
_KINDS: dict[int, str] = {
    BlockType.PAGE: "page",
    BlockType.IMAGE: "image",
    BlockType.TABLE: "table",
    BlockType.CODE: "code",
    **{BlockType(value): "heading" for value in range(3, 12)},
}
_LABELS = {
    "page": "页面",
    "heading": "标题",
    "image": "图片",
    "table": "表格",
    "code": "代码",
}


def _escape_ref(value: str) -> str:
    # 单行标签不会因外层 Markdown 引用或列表缩进而改变实际 placeholder。
    return (
        escape(value, quote=True)
        .replace("\r", "&#13;")
        .replace("\n", "&#10;")
        .replace("\t", "&#9;")
    )


@dataclass(slots=True)
class _Frame:
    node: BlockNode
    owner: Document | None
    title_path: tuple[str, ...]
    html: bool
    exiting: bool = False
    document: Document | None = None
    placeholder: str = ""


def extract_documents(
    root: BlockNode, metadata: dict[str, Any] | None
) -> list[Document]:
    """前序创建文档与引用，后序渲染内容；不跟随反向或兄弟指针。"""
    if root.block_type != BlockType.PAGE:
        raise ValueError("root 必须为 PAGE 节点")
    extra = metadata if metadata is not None else {}
    conflicts = _INTERNAL_FIELDS.intersection(extra)
    if conflicts:
        raise ValueError(f"metadata 与内部字段冲突: {', '.join(sorted(conflicts))}")

    documents: list[Document] = []
    seen_objects: set[int] = set()
    active: set[int] = set()
    seen_ids: set[str] = set()
    # 只保存尚未被父节点消费的渲染片段，不复制整棵子树的正文缓存。
    fragments: dict[str, str] = {}
    pending = [_Frame(root, None, (), False)]
    while pending:
        frame = pending.pop()
        node = frame.node
        if frame.exiting:
            children = [fragments.pop(child.block_id) for child in node.children]
            content = render_node(node, children, frame.html)
            if frame.document is not None:
                prefix = title_prefix(frame.title_path)
                frame.document.page_content = "\n\n".join(
                    part for part in (prefix, content) if part
                )
                fragments[node.block_id] = frame.placeholder
            else:
                fragments[node.block_id] = content
            active.remove(id(node))
            continue

        _validate_node(node, seen_objects, active, seen_ids)
        active.add(id(node))
        kind = _KINDS.get(node.block_type)
        owner = frame.owner
        if kind is not None:
            if kind in {"page", "heading"} and node.content.strip():
                frame.title_path = (*frame.title_path, node.content)
            document = Document(
                id=node.block_id,
                page_content="",
                metadata={
                    **deepcopy(extra),
                    "block_id": node.block_id,
                    "block_type": int(node.block_type),
                    "kind": kind,
                    "payload": deepcopy(node.payload),
                    "order": len(documents),
                    "parent_block_id": owner.id if owner is not None else None,
                    "title_path": list(frame.title_path),
                    "references": [],
                },
            )
            documents.append(document)
            if owner is not None:
                label = (
                    node.content
                    if kind == "heading" and node.content.strip()
                    else _LABELS[kind]
                )
                placeholder = (
                    f'<document-ref id="{_escape_ref(node.block_id)}" '
                    f'kind="{_escape_ref(kind)}">{_escape_ref(label)}</document-ref>'
                )
                frame.placeholder = placeholder
                owner.metadata["references"].append(
                    {
                        "id": node.block_id,
                        "kind": kind,
                        "placeholder": placeholder,
                    }
                )
            frame.document = document
            owner = document
            # 每份文档独立渲染；表格单元格中的子代码等仍用自己的 Markdown。
            frame.html = kind == "table"

        frame.exiting = True
        pending.append(frame)
        children_html = frame.html or node.block_type == BlockType.CALLOUT
        pending.extend(
            _Frame(child, owner, frame.title_path, children_html)
            for child in reversed(node.children)
        )
    return documents


def _validate_node(
    node: BlockNode, seen_objects: set[int], active: set[int], seen_ids: set[str]
) -> None:
    if id(node) in active:
        raise ValueError(f"children 存在环: {node.block_id!r}")
    if id(node) in seen_objects:
        raise ValueError(f"节点重复挂载: {node.block_id!r}")
    if not isinstance(node.block_id, str) or not node.block_id.strip():
        raise ValueError("block_id 必须为非空字符串")
    if node.block_id in seen_ids:
        raise ValueError(f"重复 block_id: {node.block_id!r}")
    seen_objects.add(id(node))
    seen_ids.add(node.block_id)

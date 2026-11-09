"""将 loader 的结构 Documents 进一步切片；只做本地转换。"""

from copy import deepcopy

from langchain_core.documents import Document

from deal_pilot.rag.splitter.feishu_doc.references import ReferenceProtector
from deal_pilot.rag.splitter.feishu_doc.table import split_table
from deal_pilot.rag.splitter.feishu_doc.text import separate_title, split_text

_CHUNK_FIELDS = frozenset({"chunk_index", "chunk_count", "table_row_index"})


def split_feishu_doc(
    docs: list[Document],
    *,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
) -> list[Document]:
    """图片/代码不拆，表格按首行表头加单行切，正文按段落/句子切。

    长度统一按字符数计算；chunk_size 包括重复标题和还原后的完整占位符。
    图片/代码允许超出预算，表格行片或不可拆分占位符超限则抛出 ValueError。
    来源结构 metadata 深拷贝保留，仅筛选 references 并添加切片字段。
    """
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("chunk_size 必须为正整数")
    if type(chunk_overlap) is not int or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap 必须为非负整数且小于 chunk_size")
    source_ids: set[str] = set()
    for doc in docs:
        _validate_document(doc)
        if doc.id in source_ids:
            raise ValueError(f"重复 Document ID: {doc.id!r}")
        source_ids.add(doc.metadata["block_id"])

    chunks: list[Document] = []
    output_ids: set[str] = set()
    for doc in docs:
        kind = doc.metadata["kind"]
        protector = ReferenceProtector(
            doc.page_content,
            doc.metadata["references"],
            allow_literal_tags=kind in {"image", "code"},
        )
        row_indices: list[int] = []
        if kind in {"image", "code"}:
            contents = [doc.page_content]
        elif kind == "table":
            prefix, body = separate_title(doc.page_content, doc.metadata["title_path"])
            rows = split_table(protector.protect(body), doc.metadata["payload"])
            contents = [prefix + protector.restore(content) for content, _ in rows]
            row_indices = [index for _, index in rows]
            if any(len(content) > chunk_size for content in contents):
                raise ValueError(
                    f"表格 {doc.id!r} 的表头加单行长度超过 chunk_size，不能截断"
                )
        else:
            contents = split_text(
                doc.page_content,
                doc.metadata["title_path"],
                protector,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        for index, content in enumerate(contents):
            chunk_id = (
                doc.metadata["block_id"]
                if len(contents) == 1
                else f"{doc.id}::chunk:{index}"
            )
            if chunk_id in output_ids or (
                chunk_id != doc.id and chunk_id in source_ids
            ):
                raise ValueError(f"切片 ID 与来源或其他切片冲突: {chunk_id!r}")
            output_ids.add(chunk_id)
            metadata = deepcopy(doc.metadata)
            metadata.update(chunk_index=index, chunk_count=len(contents))
            metadata["references"] = protector.references_for(content)
            if row_indices:
                metadata["table_row_index"] = row_indices[index]
            chunks.append(
                Document(id=chunk_id, page_content=content, metadata=metadata)
            )
    return chunks


def _validate_document(doc: Document) -> None:
    block_id = doc.metadata.get("block_id")
    if not isinstance(block_id, str) or not block_id.strip() or doc.id != block_id:
        raise ValueError("来源 Document.id 必须等于非空 metadata.block_id")
    if doc.metadata.get("kind") not in {"page", "heading", "image", "table", "code"}:
        raise ValueError(f"不支持的 Document kind: {doc.metadata.get('kind')!r}")
    conflicts = _CHUNK_FIELDS.intersection(doc.metadata)
    if conflicts:
        raise ValueError(f"metadata 与切片字段冲突: {', '.join(sorted(conflicts))}")
    titles = doc.metadata.get("title_path")
    if not isinstance(titles, list) or any(
        not isinstance(title, str) for title in titles
    ):
        raise ValueError("title_path 必须为字符串列表")
    if not isinstance(doc.metadata.get("payload"), dict):
        raise ValueError("payload 必须为对象")
    references = doc.metadata.get("references")
    if not isinstance(references, list) or any(
        not isinstance(ref, dict)
        or any(
            not isinstance(ref.get(key), str) for key in ("id", "kind", "placeholder")
        )
        for ref in references
    ):
        raise ValueError("references 必须为包含 id、kind、placeholder 字符串的引用列表")

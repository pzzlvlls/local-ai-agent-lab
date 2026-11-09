from copy import deepcopy
from typing import Any

from bs4 import BeautifulSoup
from langchain_core.documents import Document
import pytest

from deal_pilot.rag.loader.feishu_doc.feishu_doc_loader import load_feishu_doc_structre
from deal_pilot.rag.loader.feishu_doc.rendering import title_prefix
from deal_pilot.rag.splitter.feishu_doc.feishu_doc_splitter import split_feishu_doc
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType


def document(
    body: str, kind: str = "heading", block_id: str = "section", *,
    titles: list[str] | None = None, references: list[dict[str, str]] | None = None,
    payload: dict[str, Any] | None = None,
) -> Document:
    path = titles if titles is not None else ["页面", "章节"]
    prefix = title_prefix(tuple(path))
    return Document(id=block_id, page_content="\n\n".join(p for p in (prefix, body) if p), metadata={
        "block_id": block_id, "block_type": {"heading": 3, "page": 1, "image": 27, "code": 14, "table": 31}[kind],
        "kind": kind, "payload": payload or {}, "order": 7,
        "parent_document_id": "parent", "title_path": path, "references": references or [],
        "source": {"tags": ["original"]},
    })


def reference(block_id: str = "child", label: str = "图片") -> dict[str, str]:
    return {"id": block_id, "kind": "image", "placeholder": f'<document-ref id="{block_id}" kind="image">{label}</document-ref>'}


def body_of(doc: Document) -> str:
    prefix = title_prefix(tuple(doc.metadata["title_path"]))
    return doc.page_content.removeprefix(prefix).removeprefix("\n\n")


def test_short_and_empty_documents_keep_ids_and_add_chunk_metadata() -> None:
    inputs = [document("短正文"), document("", "page", "empty", titles=[])]
    chunks = split_feishu_doc(inputs)
    assert [c.id for c in chunks] == ["section", "empty"]
    assert [c.page_content for c in chunks] == [d.page_content for d in inputs]
    assert all(c.metadata["chunk_index"] == 0 and c.metadata["chunk_count"] == 1 for c in chunks)
    assert all("source_document_id" not in c.metadata for c in chunks)


@pytest.mark.parametrize("kind", ["image", "code"])
def test_images_and_code_remain_whole_even_above_length_limit(kind: str) -> None:
    source = document("原文缩进\n    " * 200, kind)
    chunk, = split_feishu_doc([source], chunk_size=40, chunk_overlap=10)
    assert chunk.id == source.id and chunk.page_content == source.page_content
    assert len(chunk.page_content) > 40


@pytest.mark.parametrize("kind", ["image", "code"])
def test_atomic_documents_can_contain_literal_reference_examples(kind: str) -> None:
    source = document('示例：<document-ref id="example">标签</document-ref>\n不完整示例：<document-ref', kind)
    chunk, = split_feishu_doc([source])
    assert chunk.page_content == source.page_content
    assert chunk.metadata["references"] == []


@pytest.mark.parametrize("kind", ["page", "heading"])
def test_paragraph_boundaries_titles_order_and_stable_ids(kind: str) -> None:
    paragraphs = ["第一段内容。" * 3, "第二段内容。" * 3, "第三段内容。" * 3]
    source = document("\n\n".join(paragraphs), kind)
    chunks = split_feishu_doc([source], chunk_size=45, chunk_overlap=0)
    assert len(chunks) == 3
    assert "".join(body_of(c) for c in chunks) == body_of(source)
    assert [body_of(c).strip() for c in chunks] == paragraphs
    assert all(len(c.page_content) <= 45 for c in chunks)
    for index, chunk in enumerate(chunks):
        assert chunk.id == f"section::chunk:{index}"
        assert chunk.metadata["chunk_index"] == index
        assert chunk.metadata["chunk_count"] == 3
        assert chunk.metadata["block_id"] == "section"
        assert chunk.metadata["order"] == 7 and chunk.metadata["parent_document_id"] == "parent"
        assert chunk.page_content.startswith("# 页面\n\n## 章节\n\n")
    assert chunks == split_feishu_doc([source], chunk_size=45, chunk_overlap=0)


def test_long_paragraph_uses_sentence_boundaries_and_sentence_overlap() -> None:
    sentences = [f"这是第{i}句话。" for i in range(8)]
    chunks = split_feishu_doc([document("".join(sentences), titles=[])], chunk_size=24, chunk_overlap=8)
    assert len(chunks) > 1
    assert all(len(c.page_content) <= 24 and c.page_content.endswith("。") for c in chunks)
    assert all(s in "".join(c.page_content for c in chunks) for s in sentences)
    for left, right in zip(chunks, chunks[1:]):
        assert left.page_content.split("。")[-2] + "。" == right.page_content.split("。")[0] + "。"


def test_long_sentence_falls_back_without_losing_whitespace_or_unicode() -> None:
    text = "  " + "甲乙𠮷🙂" * 50 + "\n"
    chunks = split_feishu_doc([document(text, titles=[])], chunk_size=17, chunk_overlap=0)
    assert "".join(c.page_content for c in chunks) == text
    assert all(len(c.page_content) <= 17 for c in chunks)


def test_placeholders_are_atomic_and_overlap_references_follow_actual_content() -> None:
    ref = reference(label="图中\n说明")
    source = document("前文。" * 15 + ref["placeholder"] + "后文。" * 20, titles=[], references=[ref])
    chunks = split_feishu_doc([source], chunk_size=110, chunk_overlap=85)
    containing = [c for c in chunks if ref["placeholder"] in c.page_content]
    assert len(containing) >= 2
    assert len(containing) < len(chunks)
    for chunk in chunks:
        assert len(chunk.page_content) <= 110
        assert chunk.page_content.count("<document-ref") == chunk.page_content.count("</document-ref>")
        assert chunk.metadata["references"] == ([ref] if ref["placeholder"] in chunk.page_content else [])
        assert not any(0xF0000 <= ord(char) <= 0x10FFFD for char in chunk.page_content)


def test_placeholder_private_use_marker_collision_and_reference_order() -> None:
    a, b = reference("a"), reference("b")
    source = document(chr(0xF0000) + b["placeholder"] + a["placeholder"], titles=[], references=[a, b])
    chunk, = split_feishu_doc([source])
    assert chunk.page_content == source.page_content
    assert chunk.metadata["references"] == [b, a]
    long_source = document(source.page_content + "追加正文。" * 40, titles=[], references=[a, b])
    chunks = split_feishu_doc([long_source], chunk_size=100, chunk_overlap=0)
    assert "".join(c.page_content for c in chunks) == long_source.page_content
    assert [ref["id"] for c in chunks for ref in c.metadata["references"]] == ["b", "a"]


def test_oversize_placeholder_or_title_is_rejected_without_truncation() -> None:
    ref = reference(label="超长" * 80)
    with pytest.raises(ValueError, match="占位符"):
        split_feishu_doc([document(ref["placeholder"], titles=[], references=[ref])], chunk_size=100, chunk_overlap=10)
    with pytest.raises(ValueError, match="标题"):
        split_feishu_doc([document("正文" * 50, titles=["标题" * 40])], chunk_size=40, chunk_overlap=10)


def test_character_budget_counts_restored_placeholders_and_titles() -> None:
    ref = reference()
    source = document("中文句子。" * 20 + ref["placeholder"] + "更多正文。" * 20, references=[ref])
    chunks = split_feishu_doc([source], chunk_size=170, chunk_overlap=20)
    assert len(chunks) > 1 and all(len(c.page_content) <= 170 for c in chunks)
    assert any(ref["placeholder"] in c.page_content for c in chunks)


def test_table_first_row_is_repeated_and_each_chunk_has_one_data_row() -> None:
    ref = reference()
    table = f'<table><tr><td>姓名</td><td>角色</td></tr><tr><td>甲</td><td>{ref["placeholder"]}</td></tr><tr><td>乙</td><td>员工</td></tr></table>'
    source = document(table, "table", payload={"row_size": 3, "column_size": 2}, references=[ref])
    chunks = split_feishu_doc([source])
    assert len(chunks) == 2
    for index, chunk in enumerate(chunks):
        rows = BeautifulSoup(chunk.page_content, "html.parser").find_all("tr")
        assert len(rows) == 2
        assert rows[0].get_text("|", strip=True) == "姓名|角色"
        assert rows[1].find_all("td")[0].get_text() == ["甲", "乙"][index]
        assert chunk.metadata["table_row_index"] == index + 1
        assert chunk.metadata["payload"] == source.metadata["payload"]
    assert chunks[0].metadata["references"] == [ref]
    assert chunks[1].metadata["references"] == []


def test_table_rowspan_is_expanded_and_colspan_is_preserved() -> None:
    table = '<p>说明</p><table><tr><td colspan="2">分类</td><td>值</td></tr><tr><td rowspan="2">共有</td><td>A</td><td>1</td></tr><tr><td>B</td><td>2</td></tr></table>'
    chunks = split_feishu_doc([document(table, "table", payload={"row_size": 3, "column_size": 3})])
    assert len(chunks) == 2
    for chunk in chunks:
        soup = BeautifulSoup(chunk.page_content, "html.parser")
        assert soup.find_all("td")[0]["colspan"] == "2"
        assert all("rowspan" not in cell.attrs for cell in soup.find_all("td"))
        assert soup.find_all("tr")[1].find_all("td")[0].get_text() == "共有"
        assert "<p>说明</p>" in chunk.page_content


def test_table_repeated_header_references_preserve_exact_escaping() -> None:
    ref = reference("a&amp;b", "引用&#10;标题")
    table = f'<table><tr><td>{ref["placeholder"]}<br>列名 &amp; 单位</td></tr><tr><td>A</td></tr><tr><td>B</td></tr></table>'
    chunks = split_feishu_doc([document(table, "table", payload={"row_size": 3, "column_size": 1}, references=[ref])])
    assert all(ref["placeholder"] in c.page_content and c.metadata["references"] == [ref] for c in chunks)
    chunks[0].metadata["references"][0]["id"] = "changed"
    assert chunks[1].metadata["references"] == [ref]


def test_header_only_table_is_not_dropped_and_oversize_row_is_rejected() -> None:
    source = document('<table><tr><td>表头</td></tr></table>', "table", payload={"row_size": 1, "column_size": 1})
    chunk, = split_feishu_doc([source])
    assert chunk.id == source.id and chunk.metadata["table_row_index"] == 0
    with pytest.raises(ValueError, match="表格.*长度"):
        split_feishu_doc([source], chunk_size=20, chunk_overlap=0)


def test_metadata_is_deep_copied_and_input_is_not_mutated() -> None:
    source = document("甲。" * 100, payload={"nested": [1]})
    snapshot = deepcopy(source)
    chunks = split_feishu_doc([source], chunk_size=50, chunk_overlap=10)
    assert source == snapshot
    chunks[0].metadata["payload"]["nested"].append(2)
    chunks[0].metadata["source"]["tags"].append("changed")
    chunks[0].metadata["title_path"].append("changed")
    assert chunks[1].metadata["payload"] == {"nested": [1]}
    assert chunks[1].metadata["source"]["tags"] == ["original"]
    assert source == snapshot


@pytest.mark.parametrize("size,overlap", [(0, 0), (-1, 0), (10, -1), (10, 10), (10, 11), (True, 0), (10, False)])
def test_invalid_length_settings_are_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        split_feishu_doc([], chunk_size=size, chunk_overlap=overlap)


def test_invalid_inputs_and_chunk_metadata_conflicts_are_rejected() -> None:
    assert split_feishu_doc([]) == []
    with pytest.raises(ValueError, match="重复"):
        split_feishu_doc([document("a"), document("b")])
    bad = document("a")
    bad.id = "other"
    with pytest.raises(ValueError, match="block_id"):
        split_feishu_doc([bad])
    for field in ("chunk_index", "chunk_count", "table_row_index"):
        bad = document("a")
        bad.metadata[field] = 1
        with pytest.raises(ValueError, match=field):
            split_feishu_doc([bad])
    bad = document("a")
    bad.metadata["kind"] = "unknown"
    with pytest.raises(ValueError, match="kind"):
        split_feishu_doc([bad])


def test_broken_or_untracked_references_are_rejected() -> None:
    ref = reference()
    for source in (
        document(ref["placeholder"], references=[]),
        document("正文", references=[ref]),
        document('<document-ref id="broken">'),
    ):
        with pytest.raises(ValueError, match="引用|占位符"):
            split_feishu_doc([source])


@pytest.mark.parametrize("table,payload", [
    ('<table><tr><td rowspan="3">X</td></tr></table>', {"row_size": 1, "column_size": 1}),
    ('<table><tr><td colspan="2">X</td></tr></table>', {"row_size": 1, "column_size": 1}),
    ('<table><tr><td>X</td></tr></table>', {"row_size": 2, "column_size": 1}),
    ('<table><tr></tr></table>', {"row_size": 1, "column_size": 1}),
    ('not a table', {"row_size": 1, "column_size": 1}),
])
def test_invalid_table_structure_is_rejected(table: str, payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="表格"):
        split_feishu_doc([document(table, "table", payload=payload)])


def test_output_id_collisions_are_rejected() -> None:
    with pytest.raises(ValueError, match="ID.*冲突"):
        split_feishu_doc([document("正文。" * 100), document("短文", block_id="section::chunk:0")], chunk_size=80, chunk_overlap=10)


def test_loader_to_splitter_preserves_source_relations_without_original_documents() -> None:
    root = BlockNode("page", BlockType.PAGE, "页面")
    heading = BlockNode("heading", BlockType.HEADING_1, "章节")
    root.append(heading)
    heading.append(BlockNode("text", BlockType.TEXT, "正文句子。" * 100))
    table = BlockNode("table", BlockType.TABLE, "", {"row_size": 3, "column_size": 1})
    heading.append(table)
    for index, value in enumerate(["表头", "数据一", "数据二"]):
        table.append(BlockNode(f"cell-{index}", BlockType.TABLE_CELL, value))
    image = BlockNode("image", BlockType.IMAGE, "图片描述" * 200)
    table.children[1].append(image)
    inputs = load_feishu_doc_structre(root, {"tenant": "test"})
    snapshot = deepcopy(inputs)
    chunks = split_feishu_doc(inputs, chunk_size=200, chunk_overlap=30)
    assert inputs == snapshot
    by_block: dict[str, list[Document]] = {}
    for chunk in chunks:
        by_block.setdefault(chunk.metadata["block_id"], []).append(chunk)
        assert chunk.metadata["tenant"] == "test"
    assert len(by_block["heading"]) > 1 and len(by_block["table"]) == 2
    assert by_block["image"][0].metadata["parent_document_id"] == "table"
    assert by_block["image"][0].id == "image"
    for chunk in chunks:
        for ref in chunk.metadata["references"]:
            targets = by_block[ref["id"]]
            assert ref["placeholder"] in chunk.page_content
            assert all(target.metadata["parent_document_id"] == chunk.metadata["block_id"] for target in targets)

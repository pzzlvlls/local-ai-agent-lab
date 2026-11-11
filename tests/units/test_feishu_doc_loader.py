"""标准树到 Document 的本地契约测试，不调用飞书、模型或存储。"""

from copy import deepcopy
from html import escape
from html.parser import HTMLParser
import sys
from typing import Any

import pytest
from langchain_core.documents import Document

from deal_pilot.rag.loader.feishu_doc.feishu_doc_loader import load_feishu_doc_structre
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType
from deal_pilot.rag.structure.feishu_doc.code_language import CodeLanguage


FIELDS = {
    "block_id",
    "block_type",
    "kind",
    "payload",
    "order",
    "parent_block_id",
    "title_path",
    "references",
}


def node(
    block_id: str,
    block_type: int = BlockType.TEXT,
    content: str = "",
    *children: BlockNode,
    payload: dict[str, Any] | None = None,
) -> BlockNode:
    result = BlockNode(block_id, block_type, content, payload or {})
    for child in children:
        result.append(child)
    return result


def page(*children: BlockNode, title: str = "页面") -> BlockNode:
    return node("page", BlockType.PAGE, title, *children)


def table(
    rows: int = 2,
    columns: int = 2,
    merges: Any = None,
    cells: list[BlockNode] | None = None,
) -> BlockNode:
    payload: dict[str, Any] = {"row_size": rows, "column_size": columns}
    if merges is not None:
        payload["merge_info"] = merges
    return node(
        "table",
        BlockType.TABLE,
        "",
        *(
            cells
            if cells is not None
            else [
                node(f"cell-{i}", BlockType.TABLE_CELL) for i in range(rows * columns)
            ]
        ),
        payload=payload,
    )


def assert_references(documents: list[Document]) -> None:
    by_id = {doc.id: doc for doc in documents}
    assert len(by_id) == len(documents)
    for order, doc in enumerate(documents):
        assert isinstance(doc, Document)
        assert doc.metadata["order"] == order
        assert doc.metadata["block_id"] == doc.id
        assert type(doc.metadata["block_type"]) is int
        refs = doc.metadata["references"]
        positions = []
        for ref in refs:
            assert set(ref) == {"id", "kind", "placeholder"}
            target = by_id[ref["id"]]
            assert target.metadata["parent_block_id"] == doc.id
            assert target.metadata["kind"] == ref["kind"]
            assert doc.page_content.count(ref["placeholder"]) == 1
            positions.append(doc.page_content.index(ref["placeholder"]))
        assert positions == sorted(positions)
        if doc.metadata["parent_block_id"] is not None:
            parent = by_id[doc.metadata["parent_block_id"]]
            assert (
                sum(ref["id"] == doc.id for ref in parent.metadata["references"]) == 1
            )


def test_preorder_ownership_titles_and_no_body_duplication() -> None:
    image = node(
        "image", BlockType.IMAGE, "独立图片说明", payload={"location": {"key": "x"}}
    )
    root = page(
        node("intro", content="页面引言"),
        node(
            "h1",
            BlockType.HEADING_1,
            "章节",
            node("before", content="前方解释"),
            node("callout", BlockType.CALLOUT, "", image),
            node("after", content="后方解释"),
            node("h2", BlockType.HEADING_3, "小节", node("body", content="小节正文")),
        ),
        node("h3", BlockType.HEADING_1, "另一章"),
    )
    documents = load_feishu_doc_structre(root)
    assert [doc.id for doc in documents] == ["page", "h1", "image", "h2", "h3"]
    assert [doc.metadata["parent_block_id"] for doc in documents] == [
        None,
        "page",
        "h1",
        "h1",
        "page",
    ]
    assert [doc.metadata["title_path"] for doc in documents] == [
        ["页面"],
        ["页面", "章节"],
        ["页面", "章节"],
        ["页面", "章节", "小节"],
        ["页面", "另一章"],
    ]
    assert documents[2].page_content == "# 页面\n\n## 章节\n\n独立图片说明"
    assert documents[3].page_content == "# 页面\n\n## 章节\n\n### 小节\n\n小节正文"
    assert "独立图片说明" not in documents[1].page_content
    assert "小节正文" not in documents[1].page_content
    assert "前方解释" not in documents[2].page_content
    assert (
        documents[1].page_content.index("前方解释")
        < documents[1].page_content.index("<document-ref")
        < documents[1].page_content.index("后方解释")
    )
    assert documents[1].page_content.count("## 章节") == 1
    assert all(set(doc.metadata) == FIELDS for doc in documents)
    assert_references(documents)


@pytest.mark.parametrize("level", range(3, 12))
def test_all_heading_levels_and_empty_titles(level: int) -> None:
    documents = load_feishu_doc_structre(page(node("heading", level, "标题"), title=""))
    assert len(documents) == 2
    assert documents[0].metadata["title_path"] == []
    assert documents[1].metadata["title_path"] == ["标题"]
    assert documents[1].page_content == "# 标题"
    assert documents[1].metadata["kind"] == "heading"


def test_empty_documents_and_only_structural_children_are_retained() -> None:
    documents = load_feishu_doc_structre(
        page(node("heading", 3, "", node("image", 27)))
    )
    assert len(documents) == 3
    assert documents[1].metadata["title_path"] == ["页面"]
    assert "<document-ref" in documents[0].page_content
    assert "<document-ref" in documents[1].page_content
    assert_references(documents)


def test_nonstructural_formats_unknown_nodes_and_paragraph_boundaries() -> None:
    root = page(
        node(
            "h",
            3,
            "节",
            node("callout", 19, "", node("p", content="高亮正文")),
            node("quote", 34, "引用引言", node("q", 15, "引用正文\n第二行")),
            node("bullet", 12, "项目", node("nested", 13, "子项")),
            node("todo", 17, "待办"),
            node("formula", 16, "x < y"),
            node(
                "grid",
                24,
                "",
                node(
                    "column",
                    25,
                    "",
                    node("p2", content="段一"),
                    node("p3", content="段二"),
                ),
            ),
            node("future", 1234, "未来文本", node("future-child", content="内部正文")),
            node("unrenderable", 1235),
            node("divider", 22),
        )
    )
    documents = load_feishu_doc_structre(root)
    assert len(documents) == 2
    content = documents[1].page_content
    for text in (
        "高亮正文",
        "引用引言",
        "引用正文",
        "项目",
        "子项",
        "待办",
        "x < y",
        "未来文本",
        "内部正文",
        "1235",
        "unrenderable",
    ):
        assert text in content
    assert "<aside>" in content
    assert "> " in content
    assert "- 项目" in content and "1. 子项" in content
    assert "$$\nx < y\n$$" in content
    assert "段一\n\n段二" in content
    assert "[ ]" not in content and "[x]" not in content


def test_metadata_and_tree_remain_independent_and_unmodified() -> None:
    shared: dict[str, Any] = {"items": ["original"]}
    root = page(
        node("code", 14, "print(1)", payload={"language": 49, "shared": shared})
    )
    root.payload["shared"] = shared
    metadata = {"source": {"tags": ["a"]}, "shared": shared}
    snapshot = deepcopy(metadata)
    child = root.children[0]
    documents = load_feishu_doc_structre(root, metadata)
    assert metadata == snapshot
    assert root.children == [child] and child.parent is root
    assert root.payload["shared"] is shared
    assert (
        documents[0].metadata["payload"]["shared"]
        is not documents[0].metadata["shared"]
    )
    documents[0].metadata["source"]["tags"].append("b")
    documents[0].metadata["payload"]["shared"]["items"].append("changed")
    documents[0].metadata["references"][0]["id"] = "changed"
    documents[0].metadata["title_path"].append("changed")
    assert documents[1].metadata["source"] == snapshot["source"]
    assert (
        documents[1].metadata["payload"]["shared"] == shared == {"items": ["original"]}
    )
    assert documents[1].metadata["title_path"] == ["页面"]
    assert metadata == snapshot


@pytest.mark.parametrize("reserved", sorted(FIELDS))
def test_reserved_metadata_is_rejected(reserved: str) -> None:
    with pytest.raises(ValueError, match=reserved):
        load_feishu_doc_structre(page(), {reserved: None})


class RefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[dict[str, str | None]] = []
        self.labels: list[str] = []
        self.in_ref = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "document-ref":
            self.refs.append(dict(attrs))
            self.in_ref = True

    def handle_data(self, data: str) -> None:
        if self.in_ref:
            self.labels.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "document-ref":
            self.in_ref = False


def test_placeholder_attributes_and_label_are_escaped() -> None:
    block_id = "id\"<&'"
    title = '标题 <script> & "引号"'
    documents = load_feishu_doc_structre(page(node(block_id, 3, title)))
    placeholder = documents[0].metadata["references"][0]["placeholder"]
    parser = RefParser()
    parser.feed(placeholder)
    assert parser.refs == [{"id": block_id, "kind": "heading"}]
    assert "".join(parser.labels) == title
    assert "<script>" not in placeholder
    assert f'id="{escape(block_id, quote=True)}"' in placeholder
    assert_references(documents)


@pytest.mark.parametrize(
    "container_type", [BlockType.QUOTE_CONTAINER, BlockType.BULLET, BlockType.CALLOUT]
)
def test_multiline_reference_stays_exact_inside_formatted_containers(
    container_type: int,
) -> None:
    block_id = 'id\nwith\rtabs\t"'
    title = "标题\n第二行\r\n尾行"
    documents = load_feishu_doc_structre(
        page(node("container", container_type, "引言", node(block_id, 3, title)))
    )
    placeholder = documents[0].metadata["references"][0]["placeholder"]
    assert "\n" not in placeholder and "\r" not in placeholder
    parser = RefParser()
    parser.feed(placeholder)
    assert parser.refs[0]["id"] == block_id
    assert "".join(parser.labels) == title
    assert_references(documents)


def test_heading_inside_nonstructural_container_does_not_reassign_later_siblings() -> (
    None
):
    documents = load_feishu_doc_structre(
        page(
            node(
                "container",
                34,
                "",
                node("heading", 11, "内部章节", node("inside", 27, "内部图片")),
            ),
            node("outside", 27, "外部图片"),
        )
    )
    assert documents[2].metadata["title_path"] == ["页面", "内部章节"]
    assert documents[3].metadata["title_path"] == ["页面"]
    assert documents[3].metadata["parent_block_id"] == "page"
    assert_references(documents)


@pytest.mark.parametrize(
    "language, expected",
    [(CodeLanguage.PYTHON, "python"), (8, "csharp"), (1, ""), (9876, ""), (None, "")],
)
def test_code_language_and_safe_fence_preserve_original(
    language: int | None, expected: str
) -> None:
    source = '  print("hi")\n```\n`````\n\n  end'
    payload = {"language": language} if language is not None else {}
    documents = load_feishu_doc_structre(
        page(node("code", 14, source, payload=payload))
    )
    assert documents[1].page_content == f"# 页面\n\n``````{expected}\n{source}\n``````"
    assert documents[1].metadata["payload"] == payload


def test_code_trailing_newlines_and_structured_child() -> None:
    documents = load_feishu_doc_structre(
        page(node("code", 14, "a\n\n", node("image", 27, "图")))
    )
    assert "```\na\n\n```" in documents[1].page_content
    assert documents[2].metadata["parent_block_id"] == "code"
    assert documents[1].page_content.index("</document-ref>") > documents[
        1
    ].page_content.index("a\n\n```")


def test_table_html_preserves_empty_cells_text_and_no_default_header() -> None:
    source = table(
        cells=[node("a", 32, "<b>&"), node("b", 32), node("c", 32, "C"), node("d", 32)]
    )
    documents = load_feishu_doc_structre(page(source))
    content = documents[1].page_content
    assert content.count("<tr>") == 2 and content.count("<td") == 4
    assert "<td></td>" in content
    assert "&lt;b&gt;&amp;" in content and "<b>" not in content
    assert "<th" not in content


def test_table_children_extract_all_structural_kinds_at_original_positions() -> None:
    nested = table(1, 1)
    nested.block_id = "nested-table"
    nested.children[0].block_id = "nested-cell"
    source = table(
        1,
        1,
        cells=[
            node(
                "cell",
                32,
                "前文 <&>",
                node("image", 27, "图说明"),
                node("code", 14, "code"),
                node("h", 3, "单元格标题", node("p", content="标题正文"), nested),
                node("after", content="后文"),
            )
        ],
    )
    documents = load_feishu_doc_structre(page(source))
    assert [doc.id for doc in documents] == [
        "page",
        "table",
        "image",
        "code",
        "h",
        "nested-table",
    ]
    assert [doc.metadata["parent_block_id"] for doc in documents] == [
        None,
        "page",
        "table",
        "table",
        "table",
        "h",
    ]
    content = documents[1].page_content
    assert "前文 &lt;&amp;&gt;" in content
    assert "<document-ref" in content and "&lt;document-ref" not in content
    assert "标题正文" not in content
    assert documents[-1].metadata["title_path"] == ["页面", "单元格标题"]
    assert_references(documents)


@pytest.mark.parametrize("covered", [(1, 1), (0, 0)])
def test_merged_table_rowspan_colspan_and_covered_empty_text(
    covered: tuple[int, int],
) -> None:
    info = [{"row_span": 2, "col_span": 2}] + [
        {"row_span": covered[0], "col_span": covered[1]} for _ in range(3)
    ]
    source = table(merges=info)
    source.children[0].content = "合并内容"
    source.children[1].append(node("empty", content=""))
    content = load_feishu_doc_structre(page(source))[1].page_content
    assert '<td rowspan="2" colspan="2">' in content
    assert content.count("<td") == 1 and content.count("<tr>") == 2
    assert "合并内容" in content


@pytest.mark.parametrize(
    "field,value",
    [
        ("row_size", 0),
        ("column_size", -1),
        ("row_size", True),
        ("row_size", "2"),
        ("column_size", None),
        ("merge_info", []),
        ("merge_info", {}),
        ("merge_info", [None] * 4),
        ("merge_info", [{"row_span": 1}] * 4),
        ("merge_info", [{"row_span": 1, "col_span": True}] * 4),
        ("merge_info", [{"row_span": 0, "col_span": 0}] * 4),
        ("merge_info", [{"row_span": -1, "col_span": 1}] * 4),
        ("merge_info", [{"row_span": 3, "col_span": 1}] * 4),
        ("merge_info", [{"row_span": 1, "col_span": 3}] * 4),
    ],
)
def test_invalid_table_payload(field: str, value: Any) -> None:
    source = table()
    source.payload[field] = value
    with pytest.raises(ValueError, match="table"):
        load_feishu_doc_structre(page(source))


@pytest.mark.parametrize(
    "bad",
    [
        "missing-size",
        "cell-count",
        "cell-type",
        "overlap",
        "covered-text",
        "covered-image",
        "covered-descendant",
    ],
)
def test_invalid_table_layouts(bad: str) -> None:
    source = table()
    if bad == "missing-size":
        del source.payload["row_size"]
    elif bad == "cell-count":
        source.children.pop()
    elif bad == "cell-type":
        source.children[0].block_type = BlockType.TEXT
    else:
        merges: list[Any] = [{"row_span": 2, "col_span": 2}] + [
            {"row_span": 1, "col_span": 1} for _ in range(3)
        ]
        source.payload["merge_info"] = merges
        if bad == "overlap":
            merges[1] = {"row_span": 2, "col_span": 1}
        elif bad == "covered-text":
            source.children[1].content = "不可丢弃"
        elif bad == "covered-image":
            source.children[1].append(node("image", 27))
        else:
            source.children[1].append(
                node("container", 24, "", node("text", content="不可丢弃"))
            )
    with pytest.raises(ValueError, match="table"):
        load_feishu_doc_structre(page(source))


@pytest.mark.parametrize(
    "bad",
    [
        "non-page",
        "empty-id",
        "whitespace-id",
        "duplicate-id",
        "same-child",
        "shared-node",
        "cycle",
    ],
)
def test_invalid_trees(bad: str) -> None:
    root = page(node("a"), node("b"))
    if bad == "non-page":
        root.block_type = BlockType.HEADING_1
    elif bad == "empty-id":
        root.children[0].block_id = ""
    elif bad == "whitespace-id":
        root.block_id = "  "
    elif bad == "duplicate-id":
        root.children[1].block_id = "a"
    elif bad == "same-child":
        root.children.append(root.children[0])
    elif bad == "shared-node":
        root.children[1].children.append(root.children[0])
    else:
        root.children[0].children.append(root)
    with pytest.raises(ValueError):
        load_feishu_doc_structre(root)


def test_deep_children_traversal_ignores_other_links() -> None:
    root = page()
    current = root
    for i in range(sys.getrecursionlimit() + 100):
        child = node(f"container-{i}", BlockType.GRID)
        current.children.append(child)
        current = child
    current.children.extend(
        [node("text", content="深层正文"), node("image", 27, "深层图片")]
    )
    root.parent = root.prev = root.next = root
    documents = load_feishu_doc_structre(root)
    assert [doc.id for doc in documents] == ["page", "image"]
    assert "深层正文" in documents[0].page_content
    assert documents[1].metadata["parent_block_id"] == "page"
    assert_references(documents)

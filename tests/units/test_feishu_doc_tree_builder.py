"""使用内存块数据验证构树，无需飞书服务或图片下载。"""

import asyncio
from itertools import permutations
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import JsonValue

from deal_pilot.feishu.api.models import DocxBlock
from deal_pilot.rag.structure.feishu_doc import image_parser
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType
from deal_pilot.rag.structure.feishu_doc.code_language import CodeLanguage
from deal_pilot.rag.structure.feishu_doc.tree_builder import build_tree


@pytest.fixture(autouse=True)
def mock_image_parser(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    parser = AsyncMock(return_value=None)
    monkeypatch.setattr(image_parser, "parse_image_block", parser)
    return parser


def block(
    block_id: str,
    parent_id: str | None = None,
    children: list[str] | None = None,
    block_type: int = BlockType.TEXT,
    **data: JsonValue,
) -> DocxBlock:
    return DocxBlock(
        block_id=block_id,
        block_type=block_type,
        parent_id=parent_id,
        children=children or [],
        raw={
            "block_id": block_id,
            "block_type": block_type,
            "parent_id": parent_id,
            "children": list(children or []),
            **data,
        },
    )


def assert_links(root: BlockNode, expected_count: int) -> None:
    """全树检查对象唯一性、父子关系、双向兄弟引用及首尾边界。"""
    assert root.parent is root.prev is root.next is None
    seen: set[str] = set()
    pending = [root]
    while pending:
        node = pending.pop()
        assert node.block_id not in seen
        seen.add(node.block_id)
        for index, child in enumerate(node.children):
            assert child.parent is node
            assert child.prev is (node.children[index - 1] if index else None)
            assert child.next is (
                node.children[index + 1] if index + 1 < len(node.children) else None
            )
        pending.extend(node.children)
    assert len(seen) == expected_count


@pytest.mark.parametrize("parent_id", [None, ""])
def test_single_page(parent_id: str | None) -> None:
    source = block("doc", parent_id, block_type=BlockType.PAGE, page={"elements": []})
    root = asyncio.run(build_tree([source]))
    assert root.block_id == "doc"
    assert root.block_type is BlockType.PAGE
    assert root.content == ""
    assert root.payload == {}
    assert root.children == []
    assert_links(root, 1)


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_child_order_comes_from_children_not_input_order(order: tuple[int, ...]) -> None:
    sources = [
        block("doc", children=["b", "a"], block_type=BlockType.PAGE),
        block("a", "doc"),
        block("b", "doc"),
    ]
    root = asyncio.run(build_tree([sources[index] for index in order]))
    assert [child.block_id for child in root.children] == ["b", "a"]
    assert_links(root, 3)


def test_heading_collects_following_content_and_keeps_nested_tables_and_lists() -> None:
    sources = [
        block("doc", children=["heading", "text", "list", "table"], block_type=1),
        block("heading", "doc", block_type=3),
        block("text", "doc"),
        block("list", "doc", ["nested"], block_type=12),
        block("nested", "list", block_type=12),
        block("table", "doc", ["cell2", "cell1"], block_type=31),
        block("cell1", "table", ["paragraph"], block_type=32),
        block("paragraph", "cell1"),
        block("cell2", "table", block_type=32),
    ]
    root = asyncio.run(build_tree(list(reversed(sources))))
    assert [child.block_id for child in root.children] == ["heading"]
    heading = root.children[0]
    assert [child.block_id for child in heading.children] == ["text", "list", "table"]
    text, bullet, table = heading.children
    assert text.parent is heading
    assert bullet.children[0].block_id == "nested"
    assert [cell.block_id for cell in table.children] == ["cell2", "cell1"]
    assert table.children[1].children[0].block_id == "paragraph"
    assert_links(root, len(sources))


@pytest.mark.parametrize("block_type", [BlockType.UNDEFINED, 104])
def test_known_and_unknown_types_are_preserved(block_type: int) -> None:
    root = asyncio.run(build_tree([block("doc", children=["child"], block_type=1), block("child", "doc", block_type=block_type)]))
    child = root.children[0]
    assert child.block_type == block_type
    if block_type == BlockType.UNDEFINED:
        assert child.block_type is BlockType.UNDEFINED
    else:
        assert type(child.block_type) is int


def test_content_is_extracted_and_payloads_are_empty_and_independent() -> None:
    sources = [
        block("doc", children=["image", "text"], block_type=1),
        block("image", "doc", block_type=27, image={"token": "img-token", "width": 120}),
        block("text", "doc", text={"elements": [{"text_run": {"content": "原文"}}]}, extension={"values": [1, None]}),
    ]
    snapshot = [source.model_dump() for source in sources]
    root = asyncio.run(build_tree(sources))
    image, text = root.children
    assert image.content == "img-token"
    assert text.content == "原文"
    assert [source.model_dump() for source in sources] == snapshot
    assert all(node.payload == {} for node in (root, image, text))
    image.payload["custom"] = "changed"
    assert root.payload == text.payload == {}
    image.remove()
    assert [source.model_dump() for source in sources] == snapshot

    # 不同构树调用也不共享节点或 payload。
    other = asyncio.run(build_tree(sources))
    assert other is not root
    assert other.children[0].content == "img-token"
    assert other.children[0].payload == {}
    assert_links(other, 3)


def test_relationships_use_model_fields_instead_of_raw_fields() -> None:
    page = block("doc", children=["child"], block_type=1)
    page.raw["children"] = ["stale"]
    child = block("child", "doc")
    child.raw["parent_id"] = "stale"
    root = asyncio.run(build_tree([child, page]))
    assert root.children[0].block_id == "child"
    assert root.children[0].parent is root
    assert root.payload == {}
    assert page.raw["children"] == ["stale"]  # 不修改来源数据。


def test_deep_tree_does_not_require_python_recursion() -> None:
    count = 1500
    sources = [
        block(
            str(index),
            str(index - 1) if index else None,
            [str(index + 1)] if index + 1 < count else [],
            block_type=1 if index == 0 else 12,
        )
        for index in range(count)
    ]
    root = asyncio.run(build_tree(list(reversed(sources))))
    assert root.block_id == "0"
    assert_links(root, count)


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        ([], "至少需要一个"),
        ([block("")], "block_id 不能为空"),
        ([block("  ")], "block_id 不能为空"),
        ([block("doc"), block("doc")], "重复的 block_id"),
        ([block("doc"), block("other")], "只有一个根节点"),
        ([block("a", "b", ["b"]), block("b", "a", ["a"])], "只有一个根节点"),
        ([block("doc", children=["missing"])], "子块 'missing' 不存在"),
        ([block("doc"), block("child", "missing")], "父块 'missing' 不存在"),
        ([block("doc", children=["child", "child"]), block("child", "doc")], "重复引用"),
        ([block("doc", children=["a", "b"]), block("a", "doc", ["child"]), block("b", "doc", ["child"]), block("child", "a")], "重复引用"),
        ([block("doc", children=["a", "child"]), block("a", "doc"), block("child", "a")], "parent_id.*不一致"),
        ([block("doc"), block("child", "doc")], "未列在父块.*children 中"),
        ([block("doc", children=["doc"])], "parent_id.*不一致"),
        ([block("doc"), block("a", "a", ["a"])], "存在环"),
        ([block("doc"), block("a", "b", ["b"]), block("b", "a", ["a"])], "存在环"),
    ],
    ids=["empty", "empty-id", "blank-id", "duplicate-id", "multiple-roots", "no-root", "missing-child", "missing-parent", "duplicate-child", "multiple-parents", "parent-conflict", "unlisted-child", "root-self-reference", "detached-self-cycle", "detached-cycle"],
)
def test_invalid_tree_raises_without_modifying_input(sources: list[DocxBlock], message: str) -> None:
    snapshot = [source.model_dump() for source in sources]
    with pytest.raises(ValueError, match=message):
        asyncio.run(build_tree(sources))
    assert [source.model_dump() for source in sources] == snapshot


@pytest.mark.parametrize("image", [None, {}, {"token": None}, {"token": ""}, {"token": "  "}, {"token": 123}])
def test_image_requires_valid_token(image: JsonValue) -> None:
    sources = [block("doc", children=["image"]), block("image", "doc", block_type=27, image=image)]
    with pytest.raises(ValueError, match="图片块 'image'.*image.token"):
        asyncio.run(build_tree(sources))


@pytest.mark.parametrize(
    ("block_type", "field"),
    [(1, "page"), (2, "text")]
    + [(level + 2, f"heading{level}") for level in range(1, 10)]
    + [(12, "bullet"), (13, "ordered"), (14, "code"), (15, "quote"), (16, "equation"), (17, "todo")],
)
def test_all_text_block_fields_preserve_order_whitespace_and_newlines(block_type: int, field: str) -> None:
    source = block("doc", block_type=block_type)
    source.raw[field] = {
        "elements": [
            {"text_run": {"content": "  第一段", "text_element_style": {"bold": True}}},
            {"text_run": {"content": "\n第二段\t"}},
            {"text_run": {"content": ""}},
            {"text_run": {"content": "结尾  "}},
        ],
        "style": {"language": 49},
    }
    result = asyncio.run(build_tree([source]))
    assert result.content == "  第一段\n第二段\t结尾  "
    assert result.payload == ({"language": 49} if block_type == BlockType.CODE else {})


def test_inline_equation_and_document_or_link_title() -> None:
    source = block("doc", text={"elements": [
        {"text_run": {"content": "参考 "}},
        {"mention_doc": {"title": "文档标题", "url": "https://example.com/doc"}},
        {"text_run": {"content": "："}},
        {"equation": {"content": "a^2+b^2"}},
        {"link_preview": {"title": "链接标题", "url": "https://example.com/link"}},
        {"mention_doc": {"url": "https://example.com/fallback"}},
    ]})
    assert asyncio.run(build_tree([source])).content == "参考 文档标题：a^2+b^2链接标题https://example.com/fallback"


def test_container_content_does_not_repeat_child_text() -> None:
    root = asyncio.run(build_tree([
        block("doc", children=["container"], block_type=1, page={"elements": [{"text_run": {"content": "标题"}}]}),
        block("container", "doc", ["text"], block_type=19, callout={"emoji_id": "pushpin"}),
        block("text", "container", text={"elements": [{"text_run": {"content": "子节点正文"}}]}),
    ]))
    assert root.content == "标题"
    assert root.children[0].content == ""
    assert root.children[0].children[0].content == "子节点正文"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"text": None}, "text 必须为对象"),
        ({"text": {"elements": "wrong"}}, "elements 必须为列表"),
        ({"text": {"elements": [None]}}, "行内元素必须包含一个类型字段"),
        ({"text": {"elements": [{"text_run": None}]}}, "text_run 必须为对象"),
        ({"text": {"elements": [{"text_run": {"content": 123}}]}}, "缺少有效文本"),
        ({"text": {"elements": [{"mention_user": {"user_id": "user"}}]}}, "尚不支持的行内元素"),
    ],
)
def test_invalid_or_unsupported_inline_content_is_not_silently_dropped(data: dict[str, JsonValue], message: str) -> None:
    source = block("doc")
    source.raw.update(data)
    with pytest.raises(ValueError, match=message):
        asyncio.run(build_tree([source]))


def test_heading_sections_handle_peers_backtracking_and_skipped_levels() -> None:
    ids = ["intro", "h1", "a", "h3", "b", "h2", "c", "h2-peer", "h9", "d", "h1-peer", "e"]
    levels = {"h1": 1, "h3": 3, "h2": 2, "h2-peer": 2, "h9": 9, "h1-peer": 1}
    sources = [block("doc", children=ids, block_type=1)] + [
        block(block_id, "doc", block_type=levels[block_id] + 2 if block_id in levels else 2)
        for block_id in ids
    ]
    snapshot = [source.model_dump() for source in sources]
    root = asyncio.run(build_tree(list(reversed(sources))))
    expected_parents = {
        "intro": "doc", "h1": "doc", "a": "h1", "h3": "h1", "b": "h3",
        "h2": "h1", "c": "h2", "h2-peer": "h1", "h9": "h2-peer", "d": "h9",
        "h1-peer": "doc", "e": "h1-peer",
    }
    reading_order = []
    pending = list(reversed(root.children))
    while pending:
        node = pending.pop()
        assert node.parent is not None
        assert node.parent.block_id == expected_parents[node.block_id]
        reading_order.append(node.block_id)
        pending.extend(reversed(node.children))
    assert reading_order == ids
    assert [source.model_dump() for source in sources] == snapshot
    assert_links(root, len(sources))


@pytest.mark.parametrize("level", range(1, 10))
def test_initial_heading_at_any_level_needs_no_synthetic_parent(level: int) -> None:
    root = asyncio.run(build_tree([
        block("doc", children=["heading", "body"], block_type=1),
        block("heading", "doc", block_type=level + 2),
        block("body", "doc"),
    ]))
    assert [node.block_id for node in root.children] == ["heading"]
    assert root.children[0].children[0].block_id == "body"
    assert_links(root, 3)


def test_heading_scopes_do_not_cross_container_or_table_cell_boundaries() -> None:
    root = asyncio.run(build_tree([
        block("doc", children=["h1", "table", "outside", "peer"], block_type=1),
        block("h1", "doc", block_type=3),
        block("table", "doc", ["cell1", "cell2"], block_type=31),
        block("cell1", "table", ["cell-heading", "cell-body"], block_type=32),
        block("cell-heading", "cell1", block_type=3),
        block("cell-body", "cell1"),
        block("cell2", "table", ["second-body"], block_type=32),
        block("second-body", "cell2"),
        block("outside", "doc"),
        block("peer", "doc", block_type=3),
    ]))
    heading, peer = root.children
    table, outside = heading.children
    first, second = table.children
    assert outside.parent is heading
    assert peer.children == []
    assert first.children[0].block_id == "cell-heading"
    assert first.children[0].children[0].block_id == "cell-body"
    assert second.children[0].block_id == "second-body"
    assert_links(root, 10)


def test_heading_existing_children_come_before_absorbed_following_siblings() -> None:
    root = asyncio.run(build_tree([
        block("doc", children=["h1", "following"], block_type=1),
        block("h1", "doc", ["original"], block_type=3),
        block("original", "h1"),
        block("following", "doc"),
    ]))
    assert [node.block_id for node in root.children[0].children] == ["original", "following"]
    assert_links(root, 4)


@pytest.mark.parametrize("language", [49, 0, 1000])
def test_code_payload_contains_only_original_language(language: int) -> None:
    source = block("doc", block_type=14, code={
        "elements": [{"text_run": {"content": "a = 1\n"}}],
        "style": {"language": language, "wrap": True},
    })
    before = source.model_dump()
    root = asyncio.run(build_tree([source]))
    assert root.payload == {"language": language}
    if language == 49:
        assert root.payload["language"] is CodeLanguage.PYTHON
    else:
        assert type(root.payload["language"]) is int
    assert json.loads(json.dumps(root.payload)) == {"language": language}
    assert root.content == "a = 1\n"
    assert source.model_dump() == before


@pytest.mark.parametrize("style", [{}, {"language": None}])
def test_missing_code_language_is_not_invented(style: dict[str, JsonValue]) -> None:
    assert asyncio.run(build_tree([block("doc", block_type=14, code={"style": style})])).payload == {}


@pytest.mark.parametrize("style", [None, "wrong", {"language": "python"}, {"language": True}])
def test_invalid_code_language_structure_raises(style: JsonValue) -> None:
    with pytest.raises(ValueError, match="code.style"):
        asyncio.run(build_tree([block("doc", block_type=14, code={"style": style})]))


def test_table_payload_keeps_only_selected_properties_without_mutating_source() -> None:
    source = block("table", block_type=31, table={
        "cells": [],
        "property": {
            "column_size": 3,
            "row_size": 3,
            "column_width": [100, 100, 100],
            "merge_info": [{"col_span": 1, "row_span": 1} for _ in range(9)],
        },
    })
    before = source.model_dump()
    node = asyncio.run(build_tree([source]))
    assert node.payload == {
        "column_size": 3,
        "row_size": 3,
        "merge_info": [{"col_span": 1, "row_span": 1} for _ in range(9)],
    }
    assert node.content == ""
    assert source.model_dump() == before
    assert json.loads(json.dumps(node.payload)) == node.payload


def test_table_merge_info_is_copied_without_rewriting_spans_or_order() -> None:
    source = block("table", block_type=31, table={
        "property": {
            "column_size": 2,
            "row_size": 2,
            "merge_info": [
                {"col_span": 2, "row_span": 1},
                {"col_span": 1, "row_span": 1},
                {"col_span": 1, "row_span": 1},
                {"col_span": 1, "row_span": 1},
            ],
        },
    })
    before = source.model_dump()
    first = asyncio.run(build_tree([source]))
    second = asyncio.run(build_tree([source]))
    merges = first.payload["merge_info"]
    assert isinstance(merges, list)
    origin = merges[0]
    assert isinstance(origin, dict)
    assert origin == {"col_span": 2, "row_span": 1}
    origin["col_span"] = 1
    merges.pop()
    assert source.model_dump() == before
    assert second.payload["merge_info"] == [
        {"col_span": 2, "row_span": 1},
        {"col_span": 1, "row_span": 1},
        {"col_span": 1, "row_span": 1},
        {"col_span": 1, "row_span": 1},
    ]


@pytest.mark.parametrize("properties", [{}, {"row_size": 3}, {"merge_info": []}])
def test_missing_table_properties_are_not_invented(properties: dict[str, JsonValue]) -> None:
    source = block("table", block_type=31, table={"property": properties})
    assert asyncio.run(build_tree([source])).payload == properties


@pytest.mark.parametrize("table", [None, [], {"property": None}, {"property": "wrong"}])
def test_invalid_table_property_container_raises(table: JsonValue) -> None:
    with pytest.raises(ValueError, match="table.*必须为对象"):
        asyncio.run(build_tree([block("table", block_type=31, table=table)]))


def test_no_images_does_not_call_image_parser(mock_image_parser: AsyncMock) -> None:
    root = asyncio.run(build_tree([block("doc", block_type=1)]))
    assert root.block_id == "doc"
    mock_image_parser.assert_not_awaited()


def test_image_root_is_processed_in_place(mock_image_parser: AsyncMock) -> None:
    async def parse(node: BlockNode) -> None:
        assert node.content == "root-token"
        assert node.parent is None
        node.content = "图片内容"
        node.payload["processed"] = True

    mock_image_parser.side_effect = parse
    root = asyncio.run(build_tree([block("image", block_type=27, image={"token": "root-token"})]))
    mock_image_parser.assert_awaited_once_with(root)
    assert root.content == "图片内容"
    assert root.payload == {"processed": True}


def test_all_images_run_concurrently_after_complete_tree_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [
        block("doc", children=["heading", "image-a", "table", "image-c", "tail"], block_type=1),
        block("heading", "doc", block_type=3),
        block("image-a", "doc", block_type=27, image={"token": "token-a"}),
        block("table", "doc", ["cell"], block_type=31),
        block("cell", "table", ["image-b"], block_type=32),
        block("image-b", "cell", block_type=27, image={"token": "token-b"}),
        block("image-c", "doc", block_type=27, image={"token": "token-c"}),
        block("tail", "doc"),
    ]
    before = [source.model_dump() for source in sources]

    async def scenario() -> None:
        started: dict[str, BlockNode] = {}
        finished: set[str] = set()
        all_started = asyncio.Event()

        async def parse(node: BlockNode) -> None:
            root = node
            while root.parent is not None:
                root = root.parent
            assert_links(root, len(sources))
            assert root.children[0].block_id == "heading"
            assert [child.block_id for child in root.children[0].children] == [
                "image-a", "table", "image-c", "tail",
            ]
            assert node.block_id not in started
            started[node.block_id] = node
            if len(started) == 3:
                all_started.set()
            # 串行实现会停在这里；所有图片都开始处理后才允许任意一次结束。
            await all_started.wait()
            token = node.content
            node.content = f"processed-{node.block_id}"
            node.payload.update({"token": token, "processed": True})
            finished.add(node.block_id)

        monkeypatch.setattr(image_parser, "parse_image_block", parse)
        root = await asyncio.wait_for(build_tree(sources), timeout=2)
        assert set(started) == finished == {"image-a", "image-b", "image-c"}
        heading = root.children[0]
        images = [heading.children[0], heading.children[1].children[0].children[0], heading.children[2]]
        for node in images:
            assert node is started[node.block_id]
            assert node.content == f"processed-{node.block_id}"
            assert node.payload == {"token": f"token-{node.block_id[-1]}", "processed": True}
        assert_links(root, len(sources))

    asyncio.run(scenario())
    assert [source.model_dump() for source in sources] == before


@pytest.mark.parametrize("error", [RuntimeError("图片处理失败"), asyncio.CancelledError()])
def test_image_parser_errors_and_cancellation_propagate(error: BaseException, mock_image_parser: AsyncMock) -> None:
    mock_image_parser.side_effect = error
    with pytest.raises(type(error)) as captured:
        asyncio.run(build_tree([block("image", block_type=27, image={"token": "token"})]))
    assert captured.value is error
    mock_image_parser.assert_awaited_once()


def test_image_parser_is_not_started_when_tree_construction_fails(mock_image_parser: AsyncMock) -> None:
    sources = [
        block("doc", children=["valid", "invalid"], block_type=1),
        block("valid", "doc", block_type=27, image={"token": "valid-token"}),
        block("invalid", "doc", block_type=27),
    ]
    with pytest.raises(ValueError, match="图片块 'invalid'"):
        asyncio.run(build_tree(sources))
    mock_image_parser.assert_not_awaited()

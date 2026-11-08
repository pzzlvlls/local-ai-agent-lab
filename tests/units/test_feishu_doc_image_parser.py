"""图片辅助函数的上下文与编码契约，不连接 Nacos、飞书或 MinIO。"""

import asyncio
import base64
from unittest.mock import AsyncMock

import pytest

from deal_pilot.config.nacos.nacos_schemas import RagConfig, RagImageParser
from deal_pilot.rag.structure.feishu_doc import image_parser
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType


def node(content: str, kind: BlockType = BlockType.TEXT) -> BlockNode:
    return BlockNode(block_id=content, block_type=kind, content=content)


@pytest.mark.parametrize("data,mime", [(b"", "image/png"), (b"\x00\xff\x89", "image/jpeg")])
def test_generate_dataurl_preserves_mime_and_bytes(data, mime):
    result = image_parser._generate_dataurl(data, mime)
    prefix, encoded = result.split(",", 1)
    assert prefix == f"data:{mime};base64"
    assert base64.b64decode(encoded, validate=True) == data


@pytest.mark.parametrize("count,expected_prevs,expected_nexts", [
    (0, [], []),
    (1, ["前图已解析"], [""]),
    (3, ["较早正文", "", "前图已解析"], ["", "后文一", "后文二"]),
    (9, ["较早正文", "", "前图已解析"], ["", "后文一", "后文二"]),
])
def test_attachment_info_uses_parent_chain_and_sibling_rules(monkeypatch, count, expected_prevs, expected_nexts):
    config = AsyncMock(return_value=RagConfig(image_parser=RagImageParser(sibling_count=count)))
    monkeypatch.setattr(image_parser, "get_config", config)
    root = node("文档标题", BlockType.PAGE)
    empty_parent = node("")
    section = node("章节", BlockType.HEADING_1)
    root.append(node("父级前文"))
    root.append(empty_parent)
    root.append(node("父级后文"))
    empty_parent.append(section)
    current = node("当前token", BlockType.IMAGE)
    previous_image = node("前图已解析", BlockType.IMAGE)
    for sibling in [node("较早正文"), node(""), previous_image, current,
                    node("后图token", BlockType.IMAGE), node(""),
                    node("后图2token", BlockType.IMAGE), node("后文一"), node("后文二")]:
        section.append(sibling)
    before = [(child.content, child.parent, child.prev, child.next) for child in section.children]
    result = asyncio.run(image_parser._attachment_info(current))
    assert result.model_dump() == {
        "parent_trace": ["文档标题", "章节"], "prevs": expected_prevs, "nexts": expected_nexts,
    }
    assert [(child.content, child.parent, child.prev, child.next) for child in section.children] == before
    config.assert_awaited_once_with("rag_config", RagConfig)


def test_attachment_info_root_and_isolated_image_have_no_context(monkeypatch):
    monkeypatch.setattr(image_parser, "get_config", AsyncMock(return_value=RagConfig()))
    assert asyncio.run(image_parser._attachment_info(node("token", BlockType.IMAGE))).model_dump() == {
        "parent_trace": [], "prevs": [], "nexts": [],
    }


def test_attachment_info_rejects_negative_count(monkeypatch):
    monkeypatch.setattr(image_parser, "get_config", AsyncMock(return_value=RagConfig(
        image_parser=RagImageParser(sibling_count=-1),
    )))
    with pytest.raises(ValueError, match="sibling_count"):
        asyncio.run(image_parser._attachment_info(node("token", BlockType.IMAGE)))


@pytest.mark.parametrize("mime,block_id", [
    ("application/octet-stream", "block"), ("image/unknown-test-format", "block"),
    ("image/png", ""), ("image/png", "a/b"), ("image/png", "a\\b"),
    ("image/png", ".."), ("image/png", "a\x00b"),
])
def test_upload_minio_invalid_image_metadata_fails_before_external_calls(monkeypatch, mime, block_id):
    config = AsyncMock(side_effect=AssertionError("不应调用 Nacos"))
    monkeypatch.setattr(image_parser, "get_config", config)
    with pytest.raises(ValueError):
        asyncio.run(image_parser._upload_minio(b"data", mime, block_id))
    config.assert_not_awaited()

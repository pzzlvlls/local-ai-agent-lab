"""将完整的飞书 DocxBlock 列表构建为按标题层级组织的有序树。"""

from copy import deepcopy

from pydantic import JsonValue

from deal_pilot.feishu.api.models import DocxBlock
from deal_pilot.rag.structure.feishu_doc import image_parser
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType
from deal_pilot.rag.structure.feishu_doc.code_language import CodeLanguage


_TEXT_FIELDS: dict[int, str] = {
    BlockType.PAGE: "page",
    BlockType.TEXT: "text",
    **{level + 2: f"heading{level}" for level in range(1, 10)},
    BlockType.BULLET: "bullet",
    BlockType.ORDERED: "ordered",
    BlockType.CODE: "code",
    BlockType.QUOTE: "quote",
    BlockType.EQUATION: "equation",
    BlockType.TODO: "todo",
}


async def build_tree(blocks: list[DocxBlock]) -> BlockNode:
    """校验原始块关系，按标题层级组织内容并返回唯一根节点。

    输入须包含整棵树，列表本身可以乱序；根块的 parent_id 为 None 或
    空字符串。子节点顺序以 DocxBlock.children 为准，parent_id 必须与之
    一致。公共字段以 DocxBlock 属性为准，不从 raw 重读关系。
    每个原始父块的直接子列表独立按标题组织：低级标题挂到最近的高级
    标题下，同级或更高级标题结束当前章节，普通块归入最近的标题。
    保留容器及其内部结构，不跨容器重排，也不为跳级标题创建虚拟节点。

    已知类型转换为 BlockType，未知编号保留为 int。代码块 payload 保存
    原始 code.style.language 编号，表格保存 column_size、row_size、
    merge_info（仅保留来源中存在的字段），其他节点为空字典。
    文本块 content 为按 elements 顺序提取的本节点纯文本；图片 content
    保存 image.token；无自身文本的容器等节点为空字符串。
    完成整棵树后，只沿 children 按文档顺序收集全部图片节点，再串行调用
    image_parser.parse_image_block；该函数原地更新节点，等待当前图片完成
    再处理下一张，全部完成后返回根节点。图片处理的异常及取消向调用方传播。
    不修改输入，也不拼接子节点内容；图片处理行为由 image_parser 决定。

    空输入、空/重复 ID、非唯一根、缺失块、父子关系冲突、重复挂载、环、
    图片缺少有效 token、文本结构错误或行内元素尚不支持时抛出
    ValueError，不返回部分树。
    """
    ordered_blocks = _validate_tree(blocks)
    nodes: dict[str, BlockNode] = {}
    for block in ordered_blocks:
        try:
            block_type = BlockType(block.block_type)
        except ValueError:
            block_type = block.block_type

        nodes[block.block_id] = BlockNode(
            block_id=block.block_id,
            block_type=block_type,
            content=_get_content(block),
            payload=_get_payload(block),
        )

    # 自底向上挂载，每个原始子列表独立按标题层级组织。
    # 父节点此时尚未挂到祖先，避免扫描原始深树的整条祖先链。
    for block in reversed(ordered_blocks):
        _append_sections(nodes[block.block_id], [nodes[child_id] for child_id in block.children])
    root = nodes[ordered_blocks[0].block_id]
    images: list[BlockNode] = []
    pending = [root]
    while pending:
        node = pending.pop()
        if node.block_type == BlockType.IMAGE:
            images.append(node)
        pending.extend(reversed(node.children))
    for node in images:
        await image_parser.parse_image_block(node)
    return root


def _append_sections(parent: BlockNode, children: list[BlockNode]) -> None:
    """用标题栈组织一个来源子列表；节点初始脱离父节点，内部子树已构好。"""
    headings: list[BlockNode] = []
    for child in children:
        is_heading = BlockType.HEADING_1 <= child.block_type <= BlockType.HEADING_9
        if is_heading:
            while headings and headings[-1].block_type >= child.block_type:
                headings.pop()
        target = headings[-1] if headings else parent
        target.append(child)
        if is_heading:
            headings.append(child)


def _get_payload(block: DocxBlock) -> dict[str, JsonValue]:
    """提取代码语言或指定表格属性，其他扩展数据留给后续处理。"""
    if block.block_type == BlockType.TABLE:
        table = block.raw.get("table", {})
        if not isinstance(table, dict):
            raise ValueError(f"块 {block.block_id!r} 的 table 必须为对象")
        properties = table.get("property", {})
        if not isinstance(properties, dict):
            raise ValueError(f"表格块 {block.block_id!r} 的 table.property 必须为对象")
        return {
            name: deepcopy(properties[name])
            for name in ("column_size", "row_size", "merge_info")
            if name in properties
        }
    if block.block_type != BlockType.CODE:
        return {}
    code = block.raw.get("code", {})
    if not isinstance(code, dict):
        raise ValueError(f"块 {block.block_id!r} 的 code 必须为对象")
    style = code.get("style", {})
    if not isinstance(style, dict):
        raise ValueError(f"代码块 {block.block_id!r} 的 code.style 必须为对象")
    language = style.get("language")
    if language is None:
        return {}
    if type(language) is not int:
        raise ValueError(f"代码块 {block.block_id!r} 的 code.style.language 必须为整数")
    try:
        return {"language": CodeLanguage(language)}
    except ValueError:
        return {"language": language}


def _get_content(block: DocxBlock) -> str:
    """提取本节点内容；纯文本不附加 Markdown 标记或丢弃原有空白。"""
    if block.block_type == BlockType.IMAGE:
        image = block.raw.get("image")
        token = image.get("token") if isinstance(image, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"图片块 {block.block_id!r} 缺少有效的 image.token")
        return token

    field = _TEXT_FIELDS.get(block.block_type)
    if field is None:
        return ""
    data = block.raw.get(field, {})
    if not isinstance(data, dict):
        raise ValueError(f"块 {block.block_id!r} 的 {field} 必须为对象")
    elements = data.get("elements", [])
    if not isinstance(elements, list):
        raise ValueError(f"块 {block.block_id!r} 的 {field}.elements 必须为列表")

    parts: list[str] = []
    for element in elements:
        if not isinstance(element, dict) or len(element) != 1:
            raise ValueError(f"块 {block.block_id!r} 的行内元素必须包含一个类型字段")
        kind, value = next(iter(element.items()))
        if not isinstance(value, dict):
            raise ValueError(f"块 {block.block_id!r} 的 {kind} 必须为对象")
        if kind in {"text_run", "equation"}:
            content = value.get("content")
        elif kind in {"mention_doc", "link_preview"}:
            content = value.get("title") or value.get("url")
        else:
            raise ValueError(f"块 {block.block_id!r} 包含尚不支持的行内元素 {kind!r}")
        if not isinstance(content, str):
            raise ValueError(f"块 {block.block_id!r} 的 {kind} 缺少有效文本")
        parts.append(content)
    return "".join(parts)


def _validate_tree(blocks: list[DocxBlock]) -> list[DocxBlock]:
    """校验完整性，返回父块先于子块的遍历序列。"""
    if not blocks:
        raise ValueError("至少需要一个 DocxBlock")

    by_id: dict[str, DocxBlock] = {}
    for block in blocks:
        if not block.block_id.strip():
            raise ValueError("block_id 不能为空")
        if block.block_id in by_id:
            raise ValueError(f"重复的 block_id：{block.block_id!r}")
        by_id[block.block_id] = block

    roots = [block for block in blocks if not block.parent_id]
    if len(roots) != 1:
        raise ValueError(f"必须有且只有一个根节点，实际为 {len(roots)} 个")

    owners: dict[str, str] = {}
    for block in blocks:
        if block.parent_id and block.parent_id not in by_id:
            raise ValueError(f"块 {block.block_id!r} 的父块 {block.parent_id!r} 不存在")
        for child_id in block.children:
            if child_id not in by_id:
                raise ValueError(f"块 {block.block_id!r} 的子块 {child_id!r} 不存在")
            if child_id in owners:
                raise ValueError(f"子块 {child_id!r} 被重复引用")
            if by_id[child_id].parent_id != block.block_id:
                raise ValueError(
                    f"子块 {child_id!r} 的 parent_id 与父块 {block.block_id!r} 不一致"
                )
            owners[child_id] = block.block_id

    for block in blocks:
        if block.parent_id and block.block_id not in owners:
            raise ValueError(
                f"块 {block.block_id!r} 未列在父块 {block.parent_id!r} 的 children 中"
            )

    ordered: list[DocxBlock] = []
    pending = [roots[0]]
    while pending:
        block = pending.pop()
        ordered.append(block)
        pending.extend(by_id[child_id] for child_id in reversed(block.children))

    # 唯一入边及 parent_id 已校验。从无父块的根出发不可能进入环；
    # 若还有不可达块，它们必在一个或多个与根断开的有环分量中。
    if len(ordered) != len(blocks):
        reached = {block.block_id for block in ordered}
        unreachable_id = next(block.block_id for block in blocks if block.block_id not in reached)
        raise ValueError(f"存在环，块 {unreachable_id!r} 无法从根节点到达")
    return ordered

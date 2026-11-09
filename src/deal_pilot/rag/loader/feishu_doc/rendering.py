"""节点自身内容与非结构化容器的 Markdown / HTML 表达。"""

from html import escape
import re

from deal_pilot.rag.loader.feishu_doc.table import render_table
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType
from deal_pilot.rag.structure.feishu_doc.code_language import CodeLanguage


def title_prefix(title_path: tuple[str, ...]) -> str:
    """按路径深度输出 Markdown 标题；超过六层仍保留每项标题。"""
    return "\n\n".join(
        f"{'#' * min(depth, 6)} {title}"
        for depth, title in enumerate(title_path, 1)
    )


def _html_text(text: str) -> str:
    return escape(text, quote=False).replace("\n", "<br>\n")


def _code(node: BlockNode) -> str:
    language = node.payload.get("language")
    name = ""
    if isinstance(language, int) and not isinstance(language, bool):
        try:
            member = CodeLanguage(language)
        except ValueError:
            pass  # 未知编号只保留在 payload 中。
        else:
            aliases = {
                CodeLanguage.PLAIN_TEXT: "", CodeLanguage.C_SHARP: "csharp",
                CodeLanguage.COFFEE_SCRIPT: "coffeescript",
                CodeLanguage.OBJECTIVE_C: "objectivec",
                CodeLanguage.POWER_SHELL: "powershell",
                CodeLanguage.OPENGL_SHADING_LANGUAGE: "glsl",
            }
            name = aliases.get(member, member.name.lower().replace("_", "-"))
    longest = max((len(run) for run in re.findall(r"`+", node.content)), default=0)
    fence = "`" * max(3, longest + 1)
    ending = "" if node.content.endswith("\n") else "\n"
    return f"{fence}{name}\n{node.content}{ending}{fence}"


def render_node(node: BlockNode, children: list[str], html: bool) -> str:
    """children 已包含实际引用标签；只转义节点自身文本，不转义已渲染片段。"""
    block_type = node.block_type
    separator = "\n" if html else "\n\n"
    if block_type == BlockType.PAGE or BlockType.HEADING_1 <= block_type <= BlockType.HEADING_9:
        return separator.join(part for part in children if part)
    if block_type == BlockType.TABLE:
        own = f"<p>{_html_text(node.content)}</p>" if node.content else ""
        return "\n".join(part for part in (own, render_table(node, children)) if part)
    if block_type == BlockType.CODE:
        return "\n\n".join(part for part in (_code(node), *children) if part)

    own = _html_text(node.content) if html else node.content
    body = separator.join(part for part in (own, *children) if part)
    if block_type in {BlockType.QUOTE, BlockType.QUOTE_CONTAINER}:
        if not body:
            return ""
        if html:
            return f"<blockquote>{body}</blockquote>"
        return "\n".join(f"> {line}" for line in body.split("\n"))
    if block_type == BlockType.CALLOUT:
        own_html = f"<p>{_html_text(node.content)}</p>" if node.content else ""
        inner = "\n".join(part for part in (own_html, *children) if part)
        return f"<aside>{inner}</aside>" if inner else ""
    if block_type in {BlockType.BULLET, BlockType.ORDERED, BlockType.TODO}:
        if not body:
            return ""
        if html:
            tag = "ol" if block_type == BlockType.ORDERED else "ul"
            return f"<{tag}><li>{body}</li></{tag}>"
        marker = "1. " if block_type == BlockType.ORDERED else "- "
        return marker + body.replace("\n", "\n" + " " * len(marker))
    if block_type == BlockType.EQUATION:
        formula = f"$$\n{own}\n$$" if node.content else ""
        return separator.join(part for part in (formula, *children) if part)
    if block_type == BlockType.DIVIDER:
        return separator.join(part for part in (own, "<hr>" if html else "---", *children) if part)
    if block_type not in {
        BlockType.TEXT, BlockType.IMAGE, BlockType.GRID,
        BlockType.GRID_COLUMN, BlockType.TABLE_CELL,
    } and not node.content:
        marker = f"[block type={int(block_type)} id={node.block_id}]"
        body = separator.join(part for part in (_html_text(marker) if html else marker, *children) if part)
    if html and own and block_type in {BlockType.TEXT, BlockType.IMAGE, BlockType.TABLE_CELL}:
        return "\n".join(part for part in (f"<p>{own}</p>", *children) if part)
    return body

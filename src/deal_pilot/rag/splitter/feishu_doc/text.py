"""保留标题上下文，在占位符保护下复用 LangChain 递归切分。"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from deal_pilot.rag.loader.feishu_doc.rendering import title_prefix
from deal_pilot.rag.splitter.feishu_doc.references import ReferenceProtector


def separate_title(content: str, titles: list[str]) -> tuple[str, str]:
    prefix = title_prefix(tuple(titles))
    if not prefix:
        return "", content
    if content == prefix:
        return prefix, ""
    if not content.startswith(prefix + "\n\n"):
        raise ValueError("正文开头与 title_path 标题路径不一致")
    return prefix + "\n\n", content[len(prefix) + 2:]


def split_text(
    content: str, titles: list[str], protector: ReferenceProtector, *,
    chunk_size: int, chunk_overlap: int,
) -> list[str]:
    if len(content) <= chunk_size:
        return [content]
    prefix, body = separate_title(content, titles)
    budget = chunk_size - len(prefix)
    if budget <= 0:
        raise ValueError("标题长度过大，正文没有可用切片预算")
    if any(len(placeholder) > budget for placeholder in protector.placeholders):
        raise ValueError("完整占位符长度超过正文切片预算，不能截断")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=budget, chunk_overlap=min(chunk_overlap, budget - 1),
        length_function=lambda text: len(protector.restore(text)),
        separators=[r"\n[ \t]*\n", r"(?<=[。！？；.!?;])", r"\n", r"\s+", ""],
        is_separator_regex=True, keep_separator="end", strip_whitespace=False,
    )
    contents = [prefix + protector.restore(part) for part in splitter.split_text(protector.protect(body))]
    if not contents or any(len(part) > chunk_size for part in contents):
        raise ValueError("切片长度超过字符预算；请检查标题或不可拆分字符")
    return contents

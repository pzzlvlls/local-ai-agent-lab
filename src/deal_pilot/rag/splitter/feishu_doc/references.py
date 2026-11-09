"""保护完整占位符，并按实际切片内容筛选引用。"""

from copy import deepcopy
import re


_REFERENCE = re.compile(r"<document-ref\b[^>]*>.*?</document-ref>", re.DOTALL)


class ReferenceProtector:
    def __init__(
        self, content: str, references: list[dict[str, str]], *, allow_literal_tags: bool = False,
    ) -> None:
        self._references = {ref["placeholder"]: ref for ref in references}
        matches = list(_REFERENCE.finditer(content))
        remaining = _REFERENCE.sub("", content)
        if not allow_literal_tags and ("<document-ref" in remaining or "</document-ref>" in remaining):
            raise ValueError("存在不完整的 document-ref 占位符")
        found = {match[0] for match in matches}
        expected = set(self._references)
        if len(expected) != len(references) or not expected <= found or (not allow_literal_tags and expected != found):
            raise ValueError("references 与正文中的占位符引用不一致")
        self._encoded: dict[str, str] = {}
        self._decoded: dict[int, str] = {}
        candidate = 0xF0000
        for placeholder in self._references:
            while candidate <= 0x10FFFD and chr(candidate) in content:
                candidate += 1
            if candidate > 0x10FFFD:
                raise ValueError("占位符过多，无法分配无冲突的保护字符")
            marker = chr(candidate)
            self._encoded[placeholder] = marker
            self._decoded[candidate] = placeholder
            candidate += 1

    def protect(self, content: str) -> str:
        return _REFERENCE.sub(lambda match: self._encoded[match[0]], content)

    def restore(self, content: str) -> str:
        return content.translate(self._decoded)

    def references_for(self, content: str) -> list[dict[str, str]]:
        placeholders = dict.fromkeys(
            match[0] for match in _REFERENCE.finditer(content) if match[0] in self._references
        )
        return [deepcopy(self._references[placeholder]) for placeholder in placeholders]

    @property
    def placeholders(self) -> tuple[str, ...]:
        return tuple(self._references)

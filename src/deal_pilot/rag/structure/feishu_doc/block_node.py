"""飞书文档树的节点类型及关系维护；不实现 Block 列表构树或内容转换。"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import JsonValue

from deal_pilot.rag.structure.feishu_doc.block_type import BlockType


@dataclass(eq=False, slots=True)
class BlockNode:
    """独立承载切片所需信息的文档节点，所有块类型共用此类型。

    节点不持有 DocxBlock。构建过程提取 ID、类型和本节点内容，
    payload 为代码块保存原始语言编号，为表格保存行列数及合并信息，
    其他扩展数据预留后续按需添加。
    content 只包含本节点自身的内容，不提前拼接子树，避免重复切片；
    当前构树将图片 token 放入 content；无自身文本的容器可为空字符串。

    parent、children、prev、next 表示结构化后的节点关系，
    prev 和 next 仅指同一父节点下的相邻兄弟，不是深度优先遍历的前后节点。

    关系约束（通过 append、remove 维护，直接修改字段不自动校验）：
    - 文档根块也使用 BlockNode，其 parent 为 None；叶节点 children 为空。
    - 一个节点至多属于一个父节点，父子引用须双向一致，且不得成环。
    - children 是有序列表，prev、next 必须与该列表中的相邻关系一致。
    - 首个兄弟的 prev、末个兄弟的 next 为 None；根节点的两者均为 None。
    - 若 node.next 是 sibling，则 sibling.prev 必须是 node，反向同理。

    节点按对象身份比较，避免父子双向引用导致递归比较。
    导出树时只沿 children 遍历；不要直接使用 dataclasses.asdict，
    因为 parent、prev、next 会形成循环引用。
    """

    block_id: str
    """来源飞书块的 ID，用于定位与溯源。"""

    block_type: BlockType | int
    """已列出的类型使用 BlockType；未列出的类型保留原始整数编号。"""

    content: str
    """本节点可供切片使用的文本，可保留行内格式；不包含子节点内容。"""

    payload: dict[str, JsonValue] = field(default_factory=dict)
    """代码块保存 language，表格保存 column_size/row_size/merge_info；每个节点独享。"""

    parent: BlockNode | None = field(default=None, repr=False)
    """树中的父节点；根节点或尚未挂载的节点为 None。"""

    children: list[BlockNode] = field(default_factory=list, repr=False)
    """树中的直接子节点，按文档阅读顺序排列，每个实例独享列表。"""

    prev: BlockNode | None = field(default=None, repr=False)
    """同一父节点下的前一个兄弟；没有时为 None。"""

    next: BlockNode | None = field(default=None, repr=False)
    """同一父节点下的后一个兄弟；没有时为 None。"""

    def append(self, child: BlockNode) -> None:
        """将 child 及其子树添加到当前节点的子列表末尾。

        child 已有父节点时先从原位置移除；同一父节点下再次添加会移到末尾。
        禁止添加自身或祖先节点，抛出 ValueError 且不改变原树。
        调用前应保证已有树关系一致；请通过本方法和 remove 修改关系。
        """
        ancestor: BlockNode | None = self
        while ancestor is not None:
            if ancestor is child:
                raise ValueError("不能将节点自身或祖先添加为子节点")
            ancestor = ancestor.parent

        child.remove()
        previous = self.children[-1] if self.children else None
        child.parent = self
        child.prev = previous
        if previous is not None:
            previous.next = child
        self.children.append(child)

    def remove(self) -> None:
        """将当前节点及其子树从原树中移除，保留节点内容和子树内部关系。

        原位置的前后兄弟重新连接，当前节点的 parent、prev、next 清空。
        对根节点或已脱离的节点重复调用无副作用。
        若 parent 存在但其 children 中没有当前对象，抛出 ValueError，
        不修改现有关系；不通过 block_id 或内容相等定位节点。
        """
        if self.parent is not None:
            siblings = self.parent.children
            index = next(
                (index for index, sibling in enumerate(siblings) if sibling is self),
                None,
            )
            if index is None:
                raise ValueError("父节点的 children 中不存在当前节点")

            previous = siblings[index - 1] if index > 0 else None
            following = siblings[index + 1] if index + 1 < len(siblings) else None
            del siblings[index]
            if previous is not None:
                previous.next = following
            if following is not None:
                following.prev = previous

        self.parent = None
        self.prev = None
        self.next = None

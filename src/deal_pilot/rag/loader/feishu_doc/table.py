"""校验行优先排列的表格单元格及合并关系，输出 HTML。"""

from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType


def render_table(node: BlockNode, cells: list[str]) -> str:
    """合并起点声明跨度；被覆盖位置必须为空且不能声明另一合并区域。"""
    def invalid(reason: str) -> ValueError:
        return ValueError(f"表格 {node.block_id!r}: {reason}")

    rows = node.payload.get("row_size")
    columns = node.payload.get("column_size")
    if type(rows) is not int or rows <= 0 or type(columns) is not int or columns <= 0:
        raise invalid("row_size、column_size 必须为正整数")
    count = rows * columns
    if len(node.children) != count or any(child.block_type != BlockType.TABLE_CELL for child in node.children):
        raise invalid("children 必须为 row_size * column_size 个 TABLE_CELL（按行排列）")

    spans: list[tuple[int, int]] = [(1, 1)] * count
    if "merge_info" in node.payload:
        merges = node.payload["merge_info"]
        if not isinstance(merges, list) or len(merges) != count:
            raise invalid("merge_info 数量必须与单元格数量一致")
        spans = []
        for merge in merges:
            if not isinstance(merge, dict):
                raise invalid("merge_info 每项必须为对象")
            row_span, col_span = merge.get("row_span"), merge.get("col_span")
            if type(row_span) is not int or type(col_span) is not int or row_span < 0 or col_span < 0:
                raise invalid("row_span、col_span 必须为非负整数")
            spans.append((row_span, col_span))

    covered: set[int] = set()
    output = ["<table>"]
    for row in range(rows):
        output.append("<tr>")
        for column in range(columns):
            index = row * columns + column
            row_span, col_span = spans[index]
            if index in covered:
                if (row_span, col_span) not in {(0, 0), (1, 1)}:
                    raise invalid(f"位置 ({row}, {column}) 合并区域重叠")
                if cells[index]:
                    raise invalid(f"被覆盖位置 ({row}, {column}) 仍有内容")
                continue
            if row_span < 1 or col_span < 1:
                raise invalid(f"位置 ({row}, {column}) 不是有效合并起点")
            if row + row_span > rows or column + col_span > columns:
                raise invalid(f"位置 ({row}, {column}) 合并区域越界")
            for target_row in range(row, row + row_span):
                for target_column in range(column, column + col_span):
                    target = target_row * columns + target_column
                    if target == index:
                        continue
                    if target in covered:
                        raise invalid(f"位置 ({row}, {column}) 合并区域重叠")
                    covered.add(target)
            attrs = (f' rowspan="{row_span}"' if row_span > 1 else "")
            attrs += f' colspan="{col_span}"' if col_span > 1 else ""
            output.append(f"<td{attrs}>{cells[index]}</td>")
        output.append("</tr>")
    output.append("</table>")
    return "\n".join(output)

"""第一行作为表头，按数据行切 HTML 表格，展开纵向合并。"""

from copy import deepcopy

from bs4 import BeautifulSoup, Tag


def split_table(body: str, payload: dict[str, object]) -> list[tuple[str, int]]:
    soup = BeautifulSoup(body, "html.parser")
    tables = soup.find_all("table")
    if len(tables) != 1:
        raise ValueError("表格 Document 必须包含一张完整 HTML 表格")
    table = tables[0]
    rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
    row_count, column_count = payload.get("row_size"), payload.get("column_size")
    if type(row_count) is not int or type(column_count) is not int or row_count <= 0 or column_count <= 0:
        raise ValueError("表格 row_size 和 column_size 必须为正整数")
    if len(rows) != row_count:
        raise ValueError("表格 HTML 行数与原始 row_size 不一致")

    grid: list[list[Tag | None]] = [[None] * column_count for _ in rows]
    for row_index, row in enumerate(rows):
        column = 0
        for cell in row.find_all(["td", "th"], recursive=False):
            while column < column_count and grid[row_index][column] is not None:
                column += 1
            try:
                rowspan = int(str(cell.get("rowspan", "1")))
                colspan = int(str(cell.get("colspan", "1")))
            except ValueError as error:
                raise ValueError("表格合并跨度必须为正整数") from error
            if rowspan <= 0 or colspan <= 0 or row_index + rowspan > row_count or column + colspan > column_count:
                raise ValueError("表格合并区域越界或单元格数量超出列数")
            for target_row in range(row_index, row_index + rowspan):
                for target_column in range(column, column + colspan):
                    if grid[target_row][target_column] is not None:
                        raise ValueError("表格合并区域重叠")
                    grid[target_row][target_column] = cell
            column += colspan
        if any(cell is None for cell in grid[row_index]):
            raise ValueError("表格行存在缺失单元格")

    def render_row(index: int) -> str:
        cells: list[str] = []
        previous: Tag | None = None
        for original in grid[index]:
            if original is not None and original is not previous:
                cell = deepcopy(original)
                cell.attrs.pop("rowspan", None)
                cells.append(str(cell))
            previous = original
        return "<tr>\n" + "\n".join(cells) + "\n</tr>"

    # loader 生成单张顶层 table；表格前的说明文字与表格后的文本也保留。
    start = body.index("<table")
    end = body.rindex("</table>") + len("</table>")
    before, after = body[:start], body[end:]
    header = render_row(0)
    return [
        (before + "<table>\n" + header + ("\n" + render_row(index) if index else "") + "\n</table>" + after, index)
        for index in (range(1, row_count) if row_count > 1 else [0])
    ]

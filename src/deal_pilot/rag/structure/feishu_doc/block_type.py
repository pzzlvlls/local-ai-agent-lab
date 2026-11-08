"""飞书文档块类型枚举，数值对应飞书 block_type 编号。"""

from enum import IntEnum, unique


@unique
class BlockType(IntEnum):
    """已列出的飞书块类型；枚举成员不表示对应解析器已经实现。

    本表不宣称覆盖飞书未来或全部扩展类型。未列出的编号仍可作为 int
    保存在 BlockNode.block_type 中，不能统一改成 UNDEFINED 而丢失原值。
    UNDEFINED 仅表示飞书自身返回的 999。
    """

    PAGE = 1  # 页面（文档根节点）
    TEXT = 2  # 文本
    HEADING_1 = 3  # 一级标题
    HEADING_2 = 4  # 二级标题
    HEADING_3 = 5  # 三级标题
    HEADING_4 = 6  # 四级标题
    HEADING_5 = 7  # 五级标题
    HEADING_6 = 8  # 六级标题
    HEADING_7 = 9  # 七级标题
    HEADING_8 = 10  # 八级标题
    HEADING_9 = 11  # 九级标题
    BULLET = 12  # 无序列表
    ORDERED = 13  # 有序列表
    CODE = 14  # 代码块
    QUOTE = 15  # 引用
    EQUATION = 16  # 公式
    TODO = 17  # 待办事项
    BITABLE = 18  # 多维表格
    CALLOUT = 19  # 高亮块
    CHAT_CARD = 20  # 群聊卡片
    DIAGRAM = 21  # 流程图 / UML
    DIVIDER = 22  # 分割线
    FILE = 23  # 文件
    GRID = 24  # 分栏
    GRID_COLUMN = 25  # 分栏列
    IFRAME = 26  # 内嵌块
    IMAGE = 27  # 图片
    ISV = 28  # 开放平台小组件
    MINDNOTE = 29  # 思维笔记
    SHEET = 30  # 电子表格
    TABLE = 31  # 表格
    TABLE_CELL = 32  # 表格单元格
    VIEW = 33  # 视图
    QUOTE_CONTAINER = 34  # 引用容器
    TASK = 35  # 任务
    OKR = 36  # OKR
    OKR_OBJECTIVE = 37  # OKR 目标
    OKR_KEY_RESULT = 38  # OKR 关键结果
    OKR_PROGRESS = 39  # OKR 进展
    UNDEFINED = 999  # 飞书未支持的块

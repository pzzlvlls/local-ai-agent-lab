"""主图的运行参数和统计状态。"""

from operator import add
from typing import Annotated, TypedDict


class FeishuDocIndexContext(TypedDict):
    """调用时通过 context={"concurrency": N} 传入并发量。"""

    concurrency: int


class FeishuDocIndexState(TypedDict, total=False):
    """只保存统计信息，各节点返回的数字作为增量累加。"""

    batch_count: Annotated[int, add]
    """已取出的非空批次数。"""
    node_count: Annotated[int, add]
    """已取出的 node 总数。"""
    indexed_count: Annotated[int, add]
    """完成新索引创建及旧版本清理的文档数。"""
    skipped_count: Annotated[int, add]
    """跳过索引的文档数。"""
    failure_count: Annotated[int, add]
    """处理失败的文档数。"""
    failures: Annotated[list[dict[str, str]], add]
    """失败文档的 node_token、title 和 message，按列表累加。"""

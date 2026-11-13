"""飞书知识库的语义检索与标量查询工具。"""

from typing import TypedDict

from langchain.tools import tool
from langchain_core.tools import ToolException
from pydantic import BaseModel, Field

from deal_pilot.config.nacos.nacos_config import get_config
from deal_pilot.config.nacos.nacos_schemas import RagConfig
from deal_pilot.rag.retriever.feishu_doc.feishu_doc_retriever import search
from deal_pilot.rag.store.feishu_doc.get_store import get_store


class MilvusSearchInput(BaseModel):
    question: str = Field(min_length=1, description="用于检索知识库的自然语言问题")
    filter: str | None = Field(
        default=None,
        description='可选的 Milvus 标量过滤表达式，例如 space_id == "已知空间ID"',
    )


class MilvusQueryInput(BaseModel):
    filter: str = Field(
        description=(
            "Milvus 标量过滤表达式，使用检索结果中的真实 ID；"
            '例如 node_token == "已知节点token" and block_id == "已知块ID"。'
            "空字符串表示不筛选"
        )
    )
    limit: int = Field(default=20, ge=1, le=100, description="最多返回的切片数，1～100")
    offset: int = Field(
        default=0, ge=0, le=16383,
        description="跳过的记录数；offset 与 limit 之和不能超过 16384",
    )


class MilvusSearchResult(TypedDict):
    doc: dict[str, object]
    score: float


@tool(args_schema=MilvusSearchInput)
async def milvus_search(
    question: str, filter: str | None = None
) -> list[MilvusSearchResult]:
    """根据自然语言问题，在飞书知识库中检索相关内容。

    适用于尚不知道内容位置、需要发现相关文档或补充证据的场景。
    复用稠密向量与 BM25 混合检索，候选数、返回数和融合/重排方式由
    Nacos rag_config.retriever 决定，无需提供向量。已知 ID 的精确读取使用 milvus_query。

    参数：
        question: 非空的自然语言检索问题，可根据上一轮结果改写后再次检索。
        filter: 可选 Milvus 过滤表达式，不是 SQL 或自然语言；例如
            space_id == "已知空间ID" and kind == "table"。不传则不限定范围。

    返回：
        按检索排名排列的列表，每项包含 doc 和 score。doc 含 id（切片主键）、
        page_content（正文）及 metadata（来源与结构信息）。metadata 中的
        node_title、url 可用于引用来源，block_id、parent_block_id、references
        可用于后续查询，图片的 payload 可提供桶名和对象键。
        score 的含义取决于当前融合/重排方式，不是统一的置信概率。
        空列表表示本次检索未返回结果，不代表知识库一定不存在答案。

    仅返回已有内容；首次调用会沿用 get_store 的存储初始化行为。
    配置、模型及 Milvus 服务错误会向上传播，不会转换为空结果。
    """
    if not question.strip():
        raise ToolException("question 不能是空白文本")
    config = await get_config("rag_config", RagConfig)
    results = await search(question, filter=filter, config=config.retriever)
    return [
        {"doc": result.doc.model_dump(mode="json"), "score": result.score}
        for result in results
    ]


@tool(args_schema=MilvusQueryInput)
async def milvus_query(
    filter: str, limit: int = 20, offset: int = 0
) -> list[dict[str, object]]:
    """按 Milvus 标量过滤表达式，读取飞书知识库中满足条件的切片。

    适用于已有检索线索后读取父块、引用块、同文档其他切片，或精确筛选来源。
    直接调用 Milvus query，不执行向量相似度检索，也不生成相关性分数。

    参数：
        filter: Milvus 布尔表达式，不是 SQL 或自然语言。例如：
            id in ["已知切片ID1", "已知切片ID2"]，按切片主键读取；
            node_token == "已知节点token" and block_id == "已知父块ID"，读取父块；
            node_token == "已知节点token" and kind == "image"，读取文档图片。
            可组合 space_id、obj_token、revision_id、parent_block_id、chunk_index 等字段。
            block_id/parent_block_id 是来源块 ID，与切片主键 id 不同；同一块可能有多个切片。
            references 中的 id 也是来源块 ID，补查时用于 block_id 条件。
            ID 应从已有结果中获取；块关系查询应同时限定文档，必要时限定 revision_id。
            空字符串表示不筛选，仅返回当前页。
        limit: 本页最多返回的切片数，默认 20，范围 1～100。
        offset: 跳过的记录数，默认 0；offset + limit 不得超过 16384。

    返回：
        原始字段字典列表，包含 id、text（正文）、来源字段及结构元数据，
        不返回 dense/sparse 向量。空列表表示本页没有匹配结果。
        返回内容按切片存储，不自动拼成全文，也不保证按正文顺序排列；
        重建内容时需结合 order、chunk_index、table_row_index 等字段。
        满页不代表已取完，分页期间数据变化时不保证结果快照一致。

    首次调用会沿用 get_store 的存储初始化行为；查询本身不写入数据。
    配置及 Milvus 服务错误（包括无效过滤表达式）向上传播。
    """
    if offset + limit > 16384:
        raise ToolException("offset 与 limit 之和不能超过 16384")
    store = await get_store()
    # 不使用 *：BM25 生成的 sparse 不可查询，原始向量也无需交给模型。
    output_fields = [name for name in store.fields if name not in {"dense", "sparse"}]
    if store.enable_dynamic_field:
        output_fields.append("$meta")
    return await store.aclient.query(
        collection_name=store.collection_name,
        filter=filter,
        output_fields=output_fields,
        limit=limit,
        offset=offset,
    )


milvus_search.handle_tool_error = True
milvus_search.handle_validation_error = lambda exc: str(exc)
milvus_query.handle_tool_error = True
milvus_query.handle_validation_error = lambda exc: str(exc)

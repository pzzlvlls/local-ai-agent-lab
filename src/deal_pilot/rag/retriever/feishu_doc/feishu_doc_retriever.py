from dataclasses import dataclass
from langchain_core.documents import Document
from pymilvus import Function, FunctionType
from deal_pilot.config.nacos.nacos_schemas import RerankerConfig, RetrieverConfig
from deal_pilot.rag.store.feishu_doc.get_store import get_store


@dataclass
class SearchResult:
    doc: Document
    score: float


def _resolve_reranker_function(question: str, config: RerankerConfig) -> Function:
    if config.reranker == "model":
        return Function(
            name="model_rerank",
            input_field_names=["text"],  # 用于评分的正文字段
            function_type=FunctionType.RERANK,
            params={
                "reranker": "model",
                "provider": "cohere",
                "model_name": config.params.get("model_name", "rerank"),
                "queries": [question],
            },
        )
    if config.reranker == "rrf":
        return Function(
            name="dense_sparse_rrf",
            input_field_names=[],
            function_type=FunctionType.RERANK,
            params={"reranker": "rrf", "k": config.params.get("k", 60)},
        )
    if config.reranker == "weighted":
        return Function(
            name="dense_sparse_weighted",
            input_field_names=[],
            function_type=FunctionType.RERANK,
            params={
                "reranker": "weighted",
                "weights": config.params.get("weights", [0.5, 0.5]),
                "norm_score": True,
            },
        )
    raise ValueError(f"reranker取值{config.reranker}无效")


async def search(
    question: str,
    *,
    filter: str | None = None,
    config: RetrieverConfig | None = None,
    threshold: float = 0,
) -> list[SearchResult]:
    store = await get_store()

    if config is None:
        config = RetrieverConfig()

    reranker = _resolve_reranker_function(question, config.reranker)

    results = await store.asimilarity_search_with_score(
        query=question,
        fetch_k=config.fetch_k,
        k=config.k,
        param=config.param,
        expr=filter,
        reranker=reranker,
    )
    return [
        SearchResult(doc=doc, score=score)
        for doc, score in results
        if score >= threshold
    ]

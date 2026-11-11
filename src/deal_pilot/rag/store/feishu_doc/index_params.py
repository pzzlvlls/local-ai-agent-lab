from pymilvus import AsyncMilvusClient
from pymilvus.milvus_client.index import IndexParams

from deal_pilot.config.nacos.nacos_schemas import RagStoreConfig

DENSE_INDEX_NAME = "dense_index"
SPARSE_INDEX_NAME = "sparse_index"


def create_dense_index_params(config: RagStoreConfig) -> IndexParams:
    """按配置构造稠密索引参数，不创建索引。"""
    index_params = AsyncMilvusClient.prepare_index_params()

    index_params.add_index(
        field_name="dense",
        index_name=DENSE_INDEX_NAME,
        index_type=config.index_type,
        metric_type=config.metric_type,
    )
    return index_params


def create_sparse_index_params() -> IndexParams:
    """构造固定的 BM25 稀疏索引参数，不创建索引。"""
    index_params = AsyncMilvusClient.prepare_index_params()
    index_params.add_index(
        field_name="sparse",
        index_name=SPARSE_INDEX_NAME,
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
    )

    return index_params


async def has_index_changed(
    config: RagStoreConfig,
    collection_name: str,
    index_name: str,
    *,
    client: AsyncMilvusClient,
) -> bool:
    """比较索引类型和度量；客户端由调用方创建和关闭。"""
    if not await client.has_collection(collection_name=collection_name):
        return True

    actual = await client.describe_index(
        collection_name=collection_name, index_name=index_name
    )
    if actual is None:
        return True

    return (
        actual["index_type"] != config.index_type
        or actual["metric_type"] != config.metric_type
    )


async def drop_index(collection_name: str, *, client: AsyncMilvusClient) -> None:
    """释放集合并删除稠密索引，客户端由调用方管理；重建后需重新加载。"""
    await client.release_collection(collection_name=collection_name)
    await client.drop_index(
        collection_name=collection_name,
        index_name=DENSE_INDEX_NAME,
    )

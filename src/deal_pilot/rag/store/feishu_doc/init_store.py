from pymilvus import AsyncMilvusClient

from deal_pilot.config.milvus_settings import milvus_settings
from deal_pilot.config.nacos.nacos_config import get_config
from deal_pilot.config.nacos.nacos_schemas import RagConfig
from deal_pilot.rag.store.feishu_doc.index_params import (
    DENSE_INDEX_NAME,
    create_dense_index_params,
    create_sparse_index_params,
    drop_index,
    has_index_changed,
)
from deal_pilot.rag.store.feishu_doc.schema import create_schema

COLLECTION_NAME = "feishu_doc"


async def init_store() -> None:
    """确保数据库和飞书集合存在，稠密索引类型或度量变化时重建。"""
    rag_config = await get_config("rag_config", RagConfig)
    config = rag_config.store[COLLECTION_NAME]
    client = AsyncMilvusClient(uri=milvus_settings.uri)
    try:
        if milvus_settings.db_name not in await client.list_databases():
            await client.create_database(db_name=milvus_settings.db_name)
        await client.use_database(milvus_settings.db_name)

        if not await client.has_collection(collection_name=COLLECTION_NAME):
            await client.create_collection(
                collection_name=COLLECTION_NAME,
                schema=create_schema(rag_config.embedding_model.dimensions),
            )
            await client.create_index(
                collection_name=COLLECTION_NAME,
                index_params=create_dense_index_params(config),
            )
            await client.create_index(
                collection_name=COLLECTION_NAME,
                index_params=create_sparse_index_params(),
            )
            await client.load_collection(collection_name=COLLECTION_NAME)
        elif await has_index_changed(
            config, COLLECTION_NAME, DENSE_INDEX_NAME, client=client
        ):
            await drop_index(COLLECTION_NAME, client=client)
            await client.create_index(
                collection_name=COLLECTION_NAME,
                index_params=create_dense_index_params(config),
            )
            await client.load_collection(collection_name=COLLECTION_NAME)
    finally:
        await client.close()

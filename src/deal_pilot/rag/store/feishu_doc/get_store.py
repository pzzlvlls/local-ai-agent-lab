from langchain_milvus import Milvus, BM25BuiltInFunction
from deal_pilot.rag.embedding_model import create_embedding_model
from deal_pilot.config.nacos.nacos_schemas import RagConfig
from deal_pilot.config.nacos.nacos_config import get_config
from deal_pilot.rag.store.feishu_doc.init_store import COLLECTION_NAME
from deal_pilot.config.milvus_settings import milvus_settings
from deal_pilot.rag.store.feishu_doc.init_store import init_store
import asyncio

_store: Milvus | None = None
_lock = asyncio.Lock()


async def get_store():
    global _store

    async with _lock:
        if _store is None:
            await init_store()
            config = await get_config("rag_config", RagConfig)
            embedding = create_embedding_model(config.embedding_model)
            _store = await asyncio.to_thread(
                Milvus,
                embedding_function=embedding,
                collection_name=COLLECTION_NAME,
                connection_args={
                    "uri": milvus_settings.uri,
                    "db_name": milvus_settings.db_name,
                },
                primary_field="id",
                text_field="text",
                vector_field=["dense", "sparse"],
                builtin_function=BM25BuiltInFunction(
                    input_field_names="text", output_field_names="sparse"
                ),
                enable_dynamic_field=True,
                auto_id=False,
                drop_old=False,
            )
        return _store

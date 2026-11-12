"""显式回填历史切片缺失的知识空间标题，不重新向量化文档。"""

import asyncio

from pymilvus import AsyncMilvusClient

from deal_pilot.config.milvus_settings import milvus_settings
from deal_pilot.feishu.api import WikiAPI
from deal_pilot.rag.store.feishu_doc.init_store import COLLECTION_NAME, init_store


async def backfill_space_titles(
    *, client: AsyncMilvusClient, collection_name: str = COLLECTION_NAME,
    batch_size: int = 500,
) -> int:
    """更新 NULL/空标题，每个空间读取一次飞书；返回更新行数。

    调用前须完成 Schema 初始化并暂停并发写入。每批只发送 id 和 space_title，
    使用 Strong 查询确认进度；失败直接传播，已完成批次保留，再次调用可续填。
    """
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size 必须在 1 到 1000 之间")
    wiki = WikiAPI()
    titles: dict[str, str] = {}
    updated = 0
    previous_ids: set[str] = set()
    while True:
        rows = await client.query(
            collection_name=collection_name,
            filter='space_title is null or space_title == ""',
            output_fields=["id", "space_id"], limit=batch_size,
            consistency_level="Strong",
        )
        if not rows:
            return updated
        current_ids = {row["id"] for row in rows}
        if previous_ids & current_ids:
            raise RuntimeError("上一批标题更新后仍存在缺失值，请检查并发写入或服务状态")
        for row in rows:
            space_id = row["space_id"]
            if space_id not in titles:
                space = await wiki.get_space(space_id)
                if space is None:
                    raise ValueError(f"知识空间 {space_id} 不存在，无法回填标题")
                if not space.name or len(space.name.encode("utf-8")) > 300:
                    raise ValueError(f"知识空间 {space_id} 的标题为空或超过 300 字节")
                titles[space_id] = space.name
        result = await client.upsert(
            collection_name=collection_name,
            data=[{"id": row["id"], "space_title": titles[row["space_id"]]} for row in rows],
            partial_update=True,
        )
        if result["upsert_count"] != len(rows):
            raise RuntimeError("知识空间标题回填数量与请求不一致")
        updated += len(rows)
        previous_ids = current_ids


async def main() -> None:
    """按项目配置同步 Schema 后执行一次回填。"""
    await init_store()
    client = AsyncMilvusClient(uri=milvus_settings.uri, db_name=milvus_settings.db_name)
    try:
        count = await backfill_space_titles(client=client)
        print(f"已回填 {count} 条切片的 space_title")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

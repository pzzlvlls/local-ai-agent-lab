"""真实 Milvus Schema/局部更新验证；Nacos 与飞书仅替换配置和标题来源。"""
import asyncio
import importlib
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pymilvus import AsyncMilvusClient, CollectionSchema

from deal_pilot.config.milvus_settings import milvus_settings
from deal_pilot.config.nacos.nacos_schemas import RagConfig
from deal_pilot.rag.store.feishu_doc.index_params import create_dense_index_params, create_sparse_index_params
from deal_pilot.rag.store.feishu_doc.schema import create_schema
from deal_pilot.rag.store.feishu_doc.sync_schema import sync_schema

init_module = importlib.import_module('deal_pilot.rag.store.feishu_doc.init_store')
backfill_module = importlib.import_module('deal_pilot.rag.store.feishu_doc.backfill_space_titles')


def sample_row(index):
    return {
        'id': f'chunk_{index}', 'text': '退款申请需要订单号', 'space_id': 's1',
        'node_token': 'n1', 'node_title': '退款说明', 'obj_token': 'd1',
        'revision_id': 1, 'block_id': f'b{index}', 'block_type': 2,
        'kind': 'page', 'payload': {'keep': True}, 'order': index,
        'parent_block_id': None, 'url': 'https://www.feishu.cn/wiki/n1',
        'parent_node_token': None, 'title_path': ['说明'], 'references': [],
        'chunk_index': index, 'chunk_count': 3, 'table_row_index': None,
        'dense': [1.0, 0.0, 0.0, 0.0], 'custom_metadata': '保留动态字段',
    }


def test_live_schema_migration_and_partial_backfill(monkeypatch):
    if os.environ.get('MILVUS_INTEGRATION') != '1':
        pytest.skip('真实 Milvus 测试需设置 MILVUS_INTEGRATION=1')
    database = f'feishu_schema_it_{uuid4().hex}'
    config = RagConfig()
    config.embedding_model.dimensions = 4
    monkeypatch.setattr(init_module, 'get_config', AsyncMock(return_value=config))
    monkeypatch.setattr(init_module, 'milvus_settings', SimpleNamespace(uri=milvus_settings.uri, db_name=database))
    wiki = SimpleNamespace(get_space=AsyncMock(return_value=SimpleNamespace(name='售后知识库')))
    monkeypatch.setattr(backfill_module, 'WikiAPI', lambda: wiki)

    async def run():
        client = AsyncMilvusClient(uri=milvus_settings.uri, timeout=30)
        created = False
        try:
            await client.create_database(database)
            created = True
            await client.use_database(database)
            # 验证全新集合初始化，再重建仅属于本用例的旧版 fixture。
            await init_module.init_store()
            assert 'space_title' in {f['name'] for f in (await client.describe_collection('feishu_doc'))['fields']}
            await client.drop_collection('feishu_doc')
            old = create_schema(4).to_dict()
            old['fields'] = [f for f in old['fields'] if f['name'] != 'space_title']
            old['fields'][1]['params']['max_length'] = 2048
            await client.create_collection('feishu_doc', schema=CollectionSchema.construct_from_dict(old))
            await client.create_index('feishu_doc', create_dense_index_params(config.store['feishu_doc']))
            await client.create_index('feishu_doc', create_sparse_index_params())
            await client.load_collection('feishu_doc')
            await client.insert('feishu_doc', [sample_row(i) for i in range(3)])
            fields = [f['name'] for f in old['fields'] if f['name'] != 'sparse'] + ['custom_metadata']
            before = await client.query('feishu_doc', filter='', output_fields=fields, limit=10, consistency_level='Strong')
            collection_id = (await client.describe_collection('feishu_doc'))['collection_id']
            await init_module.init_store()
            await init_module.init_store()
            assert (await client.describe_collection('feishu_doc'))['collection_id'] == collection_id
            assert await backfill_module.backfill_space_titles(client=client, batch_size=2) == 3
            assert await backfill_module.backfill_space_titles(client=client) == 0
            wiki.get_space.assert_awaited_once_with('s1')
            after = await client.query('feishu_doc', filter='', output_fields=fields + ['space_title'], limit=10, consistency_level='Strong')
            assert len(after) == 3
            assert all(row.pop('space_title') == '售后知识库' for row in after)
            assert sorted(before, key=lambda row: row['id']) == sorted(after, key=lambda row: row['id'])
            assert await sync_schema('feishu_doc', create_schema(4), client=client) is False
            with pytest.raises(ValueError, match='dense.dim'):
                await sync_schema('feishu_doc', create_schema(8), client=client)
            # 既有稠密索引重建流程与 Schema 同步仍可组合执行。
            config.store['feishu_doc'].index_type = 'FLAT'
            await init_module.init_store()
            assert (await client.describe_index('feishu_doc', 'dense_index'))['index_type'] == 'FLAT'
            for field, data, metric in [('sparse', ['退款'], 'BM25'), ('dense', [[1.0, 0.0, 0.0, 0.0]], 'COSINE')]:
                result = await client.search('feishu_doc', data=data, anns_field=field, limit=3,
                    search_params={'metric_type': metric}, output_fields=['space_title'], consistency_level='Strong')
                assert len(result[0]) == 3
                assert all(hit['entity']['space_title'] == '售后知识库' for hit in result[0])
        finally:
            if created:
                await client.use_database(database)
                await client.drop_collection('feishu_doc')
                await client.use_database('default')
                await client.drop_database(database)
            await client.close()

    asyncio.run(run())

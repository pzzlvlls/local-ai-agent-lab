"""Schema 更新的无副作用预检与历史标题回填契约。"""
import asyncio
import copy
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pymilvus import DataType

from deal_pilot.rag.store.feishu_doc.schema import create_schema
from deal_pilot.rag.store.feishu_doc.sync_schema import sync_schema

backfill_module = importlib.import_module('deal_pilot.rag.store.feishu_doc.backfill_space_titles')


def client_for(schema):
    actual = copy.deepcopy(schema.to_dict())
    # 模拟真实 SDK 的返回格式，而非仅与工厂自身输出比较。
    for field in actual['fields']:
        field['field_id'] = 100
        if field['name'] == 'text':
            field['params']['enable_analyzer'] = 'true'
    for function in actual['functions']:
        for key in ('input_field_names', 'output_field_names'):
            function[key] = str(function[key])
    return SimpleNamespace(
        describe_collection=AsyncMock(return_value=actual),
        add_collection_field=AsyncMock(), alter_collection_field=AsyncMock(),
    ), actual


def test_equivalent_schema_is_noop():
    schema = create_schema(4)
    client, _ = client_for(schema)
    assert asyncio.run(sync_schema('test', schema, client=client)) is False
    client.add_collection_field.assert_not_called()
    client.alter_collection_field.assert_not_called()


def test_add_title_and_expand_text():
    schema = create_schema(4)
    client, actual = client_for(schema)
    actual['fields'] = [f for f in actual['fields'] if f['name'] != 'space_title']
    actual['fields'][1]['params']['max_length'] = 2048
    assert asyncio.run(sync_schema('test', schema, client=client)) is True
    client.add_collection_field.assert_awaited_once_with(
        collection_name='test', field_name='space_title', data_type=DataType.VARCHAR,
        nullable=True, max_length=300,
    )
    client.alter_collection_field.assert_awaited_once_with(
        collection_name='test', field_name='text', field_params={'max_length': 10000},
    )


@pytest.mark.parametrize('change', ['dimension', 'type', 'nullable', 'function', 'analyzer', 'remove', 'shrink', 'required_addition', 'dynamic'])
def test_incompatible_schema_rejected_before_any_write(change):
    schema = create_schema(4)
    client, actual = client_for(schema)
    # 即使同时缺少可新增字段，也必须先拒绝不兼容变更。
    actual['fields'] = [f for f in actual['fields'] if f['name'] != 'space_title']
    by_name = {f['name']: f for f in actual['fields']}
    if change == 'dimension':
        by_name['dense']['params']['dim'] = 8
    elif change == 'type':
        by_name['revision_id']['type'] = DataType.INT32
    elif change == 'nullable':
        by_name['parent_block_id']['nullable'] = False
    elif change == 'function':
        actual['functions'] = []
    elif change == 'analyzer':
        by_name['text']['params']['analyzer_params'] = '{"type":"standard"}'
    elif change == 'remove':
        actual['fields'].append({'name': 'legacy', 'type': DataType.INT64})
    elif change == 'shrink':
        by_name['text']['params']['max_length'] = 20000
    elif change == 'required_addition':
        actual['fields'].remove(by_name['space_id'])
    else:
        actual['enable_dynamic_field'] = False
    with pytest.raises(ValueError, match='显式迁移'):
        asyncio.run(sync_schema('test', schema, client=client))
    client.add_collection_field.assert_not_called()
    client.alter_collection_field.assert_not_called()


def test_backfill_batches_only_update_title_and_cache_spaces(monkeypatch):
    wiki = SimpleNamespace(get_space=AsyncMock(return_value=SimpleNamespace(name='产品知识库')))
    monkeypatch.setattr(backfill_module, 'WikiAPI', lambda: wiki)
    client = SimpleNamespace(
        query=AsyncMock(side_effect=[
            [{'id': '1', 'space_id': 's1'}, {'id': '2', 'space_id': 's1'}],
            [{'id': '3', 'space_id': 's1'}], [],
        ]), upsert=AsyncMock(side_effect=[{'upsert_count': 2}, {'upsert_count': 1}]),
    )
    assert asyncio.run(backfill_module.backfill_space_titles(client=client, batch_size=2)) == 3
    wiki.get_space.assert_awaited_once_with('s1')
    for call in client.upsert.await_args_list:
        assert call.kwargs['partial_update'] is True
        assert all(set(row) == {'id', 'space_title'} for row in call.kwargs['data'])
    assert all(call.kwargs['consistency_level'] == 'Strong' for call in client.query.await_args_list)


@pytest.mark.parametrize('name', [None, '', '中' * 101])
def test_backfill_rejects_missing_or_invalid_title_before_batch_write(monkeypatch, name):
    space = None if name is None else SimpleNamespace(name=name)
    monkeypatch.setattr(backfill_module, 'WikiAPI', lambda: SimpleNamespace(get_space=AsyncMock(return_value=space)))
    client = SimpleNamespace(query=AsyncMock(return_value=[{'id': '1', 'space_id': 's1'}]), upsert=AsyncMock())
    with pytest.raises(ValueError):
        asyncio.run(backfill_module.backfill_space_titles(client=client))
    client.upsert.assert_not_called()


def test_backfill_propagates_service_failure(monkeypatch):
    monkeypatch.setattr(backfill_module, 'WikiAPI', lambda: SimpleNamespace(get_space=AsyncMock(side_effect=RuntimeError('permission denied'))))
    client = SimpleNamespace(query=AsyncMock(return_value=[{'id': '1', 'space_id': 's1'}]), upsert=AsyncMock())
    with pytest.raises(RuntimeError, match='permission denied'):
        asyncio.run(backfill_module.backfill_space_titles(client=client))
    client.upsert.assert_not_called()


def test_new_document_metadata_contains_space_title(monkeypatch):
    nodes = importlib.import_module('deal_pilot.graphs.feishu_doc_index.document_index.nodes')
    monkeypatch.setattr(nodes, 'WikiAPI', lambda: SimpleNamespace(get_space=AsyncMock(return_value=SimpleNamespace(name='产品知识库'))))
    state = {
        'node': SimpleNamespace(space_id='s1', node_token='n1', title='产品', obj_token='d1', parent_node_token=None, url='https://www.feishu.cn/wiki/n1'),
        'document': SimpleNamespace(revision_id=3),
    }
    assert asyncio.run(nodes.build_metadata(state))['metadata']['space_title'] == '产品知识库'


def test_backfill_stops_if_update_makes_no_progress(monkeypatch):
    monkeypatch.setattr(backfill_module, 'WikiAPI', lambda: SimpleNamespace(get_space=AsyncMock(return_value=SimpleNamespace(name='知识库'))))
    client = SimpleNamespace(
        query=AsyncMock(return_value=[{'id': '1', 'space_id': 's1'}]),
        upsert=AsyncMock(return_value={'upsert_count': 1}),
    )
    with pytest.raises(RuntimeError, match='仍存在缺失值'):
        asyncio.run(backfill_module.backfill_space_titles(client=client))
    client.upsert.assert_awaited_once()


def test_backfill_checks_update_count(monkeypatch):
    monkeypatch.setattr(backfill_module, 'WikiAPI', lambda: SimpleNamespace(get_space=AsyncMock(return_value=SimpleNamespace(name='知识库'))))
    client = SimpleNamespace(
        query=AsyncMock(return_value=[{'id': '1', 'space_id': 's1'}]),
        upsert=AsyncMock(return_value={'upsert_count': 0}),
    )
    with pytest.raises(RuntimeError, match='数量'):
        asyncio.run(backfill_module.backfill_space_titles(client=client))

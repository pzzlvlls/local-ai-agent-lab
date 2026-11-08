"""运行真实 SDK 的请求构造、鉴权和响应解析，仅 Mock 网络边界。"""

import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
import requests as requests_lib
from lark_oapi.core.cache import LocalCache
from lark_oapi.core.token import TokenManager
from pydantic import ValidationError

from deal_pilot.feishu.api import DocxAPI, WikiAPI
from deal_pilot.feishu.api import _client
from deal_pilot.feishu.api.errors import (
    FeishuAPIError,
    FeishuAuthenticationError,
    FeishuConfigurationError,
    FeishuHTTPError,
    FeishuResponseError,
    UnsupportedWikiNodeTypeError,
)


def ok(data):
    return httpx.Response(200, json={"code": 0, "msg": "success", "data": data})


def page(items, *, has_more=False, page_token=None):
    return ok({"items": items, "has_more": has_more, "page_token": page_token})


def node(token, *, space_id="s1", parent="", has_child=False, obj_token=None, obj_type="docx"):
    return {
        "node_token": token, "space_id": space_id, "obj_token": obj_token or f"doc_{token}",
        "obj_type": obj_type, "title": f"标题 {token}", "parent_node_token": parent,
        "has_child": has_child,
    }


@pytest.fixture
def mock_feishu(monkeypatch):
    """拦截所有 HTTP 并替换配置；测试不使用 .env 中的身份。"""
    requests = []
    threads = []
    settings = SimpleNamespace(app_id="cli_test", app_secret="fake-secret")
    monkeypatch.setattr(_client, "feishu_settings", settings)
    monkeypatch.setattr(TokenManager, "cache", LocalCache())
    _client._build_client.cache_clear()

    def install(handler, *, token_handler=None):
        def dispatch(request):
            requests.append(request)
            if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
                assert request.method == "POST"
                assert "authorization" not in request.headers
                assert json.loads(request.content) == {
                    "app_id": settings.app_id, "app_secret": settings.app_secret,
                }
                if token_handler is None:
                    return httpx.Response(200, json={"code": 0, "tenant_access_token": "fake-token", "expire": 7200})
                response = token_handler(request)
                return response
            assert request.method == "GET"
            assert request.headers["authorization"] == "Bearer fake-token"
            response = handler(request)
            return response

        def fake_request(method, url, *, headers, params, data, timeout):
            assert timeout == 30
            threads.append(threading.get_ident())
            request = httpx.Request(method, url, headers=headers, params=params, content=data)
            response = dispatch(request)
            result = requests_lib.Response()
            result.status_code = response.status_code
            result.headers.update(response.headers)
            result._content = response.content
            return result

        monkeypatch.setattr(requests_lib, "request", fake_request)
        return requests, threads

    yield install
    _client._build_client.cache_clear()


def test_wiki_spaces_pagination_continues_after_empty_page(mock_feishu):
    def handler(request):
        assert request.url.path == "/open-apis/wiki/v2/spaces"
        assert request.url.params["page_size"] == "50"
        token = request.url.params.get("page_token")
        if token is None:
            return page([], has_more=True, page_token="next")
        assert token == "next"
        return page([{"space_id": "s1", "name": "产品知识库", "description": "产品资料"}])

    requests, threads = mock_feishu(handler)
    result = asyncio.run(WikiAPI().list_spaces())
    assert [(s.space_id, s.name, s.description) for s in result] == [("s1", "产品知识库", "产品资料")]
    assert len(requests) == 3
    assert all(t != threading.get_ident() for t in threads)


def test_get_space_node_and_docx_mapping_share_token(mock_feishu):
    def handler(request):
        if request.url.path.endswith("/spaces/s1"):
            return ok({"space": {"space_id": "s1", "name": "产品知识库"}})
        if request.url.path.endswith("/spaces/get_node"):
            assert dict(request.url.params) == {"token": "n1", "obj_type": "wiki"}
            return ok({"node": {**node("n1"), "url": "ignored"}})
        assert request.url.path.endswith("/documents/doc_n1")
        return ok({"document": {"document_id": "doc_n1", "title": "产品说明", "revision_id": 7}})

    requests, _ = mock_feishu(handler)

    async def scenario():
        space = await WikiAPI().get_space("s1")
        entry = await WikiAPI().get_node("n1")
        assert space is not None and space.description is None
        assert entry is not None and entry.parent_node_token is None
        assert entry.url == "https://www.feishu.cn/wiki/n1"
        assert entry.node_token != entry.obj_token
        document = await DocxAPI().get_document(entry.obj_token)
        assert document is not None and document.revision_id == 7

    asyncio.run(scenario())
    assert sum(r.method == "POST" for r in requests) == 1


@pytest.mark.parametrize("parent", [None, "parent"])
def test_list_nodes_reads_all_direct_children_only(mock_feishu, parent):
    def handler(request):
        assert request.url.path.endswith("/spaces/s1/nodes")
        assert request.url.params.get("parent_node_token") == parent
        if "page_token" not in request.url.params:
            return page([node("n1", parent=parent, has_child=True)], has_more=True, page_token="next")
        assert request.url.params["page_token"] == "next"
        return page([node("n2", parent=parent)])

    requests, _ = mock_feishu(handler)
    entries = asyncio.run(WikiAPI().list_nodes("s1", parent_node_token=parent))
    assert [n.node_token for n in entries] == ["n1", "n2"]
    assert len(requests) == 3  # 没有因为 has_child=True 继续读取孙节点。


def test_list_all_nodes_traverses_spaces_deduplicates_nodes_not_documents(mock_feishu):
    def handler(request):
        if request.url.path.endswith("/spaces"):
            return page([{"space_id": "s1", "name": "产品"}, {"space_id": "s2", "name": "销售"}])
        parent = request.url.params.get("parent_node_token")
        if "/s2/" in request.url.path:
            return page([node("n1", space_id="s2")])
        if parent is None:
            return page([node("n1", has_child=True), node("shortcut", obj_token="doc_n1")])
        if parent == "n1":
            return page([node("child", parent="n1", has_child=True), node("n1", has_child=True)])
        assert parent == "child"
        return page([node("leaf", parent="child")])

    requests, _ = mock_feishu(handler)
    entries = asyncio.run(WikiAPI().list_all_space_nodes())
    assert [(n.space_id, n.node_token) for n in entries] == [
        ("s1", "n1"), ("s1", "shortcut"), ("s1", "child"), ("s1", "leaf"), ("s2", "n1"),
    ]
    assert entries[0].obj_token == entries[1].obj_token
    assert all("/docx/" not in r.url.path for r in requests)


@pytest.mark.parametrize("operation", ["spaces", "nodes", "all", "blocks"])
def test_empty_lists(mock_feishu, operation):
    mock_feishu(lambda _: page([]))
    method = {
        "spaces": WikiAPI().list_spaces, "nodes": lambda: WikiAPI().list_nodes("s1"),
        "all": WikiAPI().list_all_space_nodes, "blocks": lambda: DocxAPI().list_blocks("doc1"),
    }[operation]
    assert asyncio.run(method()) == []


@pytest.mark.parametrize("operation,code,status", [
    ("space", 131005, 400), ("space", 131005, 200),
    ("node", 131005, 400), ("node", 131012, 400),
    ("doc", 1770002, 404), ("doc", 1770003, 400),
])
def test_only_explicit_missing_get_returns_none(mock_feishu, operation, code, status):
    mock_feishu(lambda _: httpx.Response(status, json={"code": code}))
    method = {"space": WikiAPI().get_space, "node": WikiAPI().get_node, "doc": DocxAPI().get_document}[operation]
    assert asyncio.run(method("resource")) is None


@pytest.mark.parametrize("code,status", [(131006, 400), (99991672, 403), (99991663, 401), (99991400, 429)])
@pytest.mark.parametrize("operation", ["space", "node", "doc"])
def test_permissions_authentication_and_rate_limit_raise(mock_feishu, operation, code, status):
    requests, _ = mock_feishu(lambda _: httpx.Response(
        status, json={"code": code, "msg": "fake-secret fake-token"}, headers={"x-tt-logid": "log-test"},
    ))
    method = {"space": WikiAPI().get_space, "node": WikiAPI().get_node, "doc": DocxAPI().get_document}[operation]
    with pytest.raises(FeishuAPIError) as caught:
        asyncio.run(method("resource"))
    assert caught.value.code == code and caught.value.http_status == status
    assert caught.value.log_id == "log-test"
    assert "fake-secret" not in str(caught.value) and "fake-token" not in str(caught.value)
    assert len(requests) == 2  # 不自动重试。


@pytest.mark.parametrize("operation", ["spaces", "nodes", "blocks"])
def test_later_page_failure_raises_instead_of_returning_partial_result(mock_feishu, operation):
    def handler(request):
        if "page_token" in request.url.params:
            return httpx.Response(400, json={"code": 131006})
        item = {
            "spaces": {"space_id": "s1", "name": "产品"}, "nodes": node("n1"),
            "blocks": {"block_id": "b1", "block_type": 2},
        }[operation]
        return page([item], has_more=True, page_token="next")

    mock_feishu(handler)
    method = {
        "spaces": WikiAPI().list_spaces, "nodes": lambda: WikiAPI().list_nodes("s1"),
        "blocks": lambda: DocxAPI().list_blocks("doc1"),
    }[operation]
    with pytest.raises(FeishuAPIError):
        asyncio.run(method())


def test_all_nodes_does_not_skip_failing_space(mock_feishu):
    def handler(request):
        if request.url.path.endswith("/spaces"):
            return page([{"space_id": "s1", "name": "一"}, {"space_id": "s2", "name": "二"}])
        if "/s1/" in request.url.path:
            return page([node("n1")])
        return httpx.Response(400, json={"code": 131006})

    mock_feishu(handler)
    with pytest.raises(FeishuAPIError):
        asyncio.run(WikiAPI().list_all_space_nodes())


@pytest.mark.parametrize("operation", ["get", "list", "all"])
def test_unsupported_node_type_is_explicit_error(mock_feishu, operation):
    def handler(request):
        if request.url.path.endswith("/spaces"):
            return page([{"space_id": "s1", "name": "产品"}])
        if request.url.path.endswith("/get_node"):
            return ok({"node": node("n1", obj_type="sheet")})
        return page([node("n1", obj_type="sheet")])

    mock_feishu(handler)
    method = {
        "get": lambda: WikiAPI().get_node("n1"), "list": lambda: WikiAPI().list_nodes("s1"),
        "all": WikiAPI().list_all_space_nodes,
    }[operation]
    with pytest.raises(UnsupportedWikiNodeTypeError):
        asyncio.run(method())


@pytest.mark.parametrize("revision", [-1, 7])
def test_blocks_preserve_raw_rich_text_unknown_fields_and_order(mock_feishu, revision):
    blocks = [
        {"block_id": "doc1", "block_type": 1, "parent_id": "", "children": ["b2"]},
        {"block_id": "b2", "block_type": 9999, "parent_id": "doc1",
         "future": {"payload": [1, "中文", None]},
         "text": {"elements": [{"text_run": {"content": "正文", "text_element_style": {"bold": True}}}]}},
    ]

    def handler(request):
        assert request.url.path == "/open-apis/docx/v1/documents/doc1/blocks"
        assert request.url.params["document_revision_id"] == str(revision)
        assert request.url.params["page_size"] == "500"
        if "page_token" not in request.url.params:
            return page(blocks[:1], has_more=True, page_token="next")
        return page(blocks[1:])

    mock_feishu(handler)
    result = asyncio.run(DocxAPI().list_blocks("doc1", document_revision_id=revision))
    assert [b.block_id for b in result] == ["doc1", "b2"]
    assert [b.raw for b in result] == blocks
    assert result[0].parent_id is None and result[0].children == ["b2"]
    assert result[1].children == []


@pytest.mark.parametrize("revision", [0, -2, True, 1.5, "1"])
def test_invalid_revision_fails_before_network(mock_feishu, revision):
    requests, _ = mock_feishu(lambda _: pytest.fail("不应请求网络"))
    with pytest.raises(ValueError, match="document_revision_id"):
        asyncio.run(DocxAPI().list_blocks("doc1", document_revision_id=revision))
    assert requests == []


@pytest.mark.parametrize("value", ["", " ", " s1", "https://example.feishu.cn/wiki/n1", "../x", "..", "s1?x=1"])
def test_invalid_identifiers_fail_before_network(mock_feishu, value):
    requests, _ = mock_feishu(lambda _: pytest.fail("不应请求网络"))

    async def scenario():
        calls = [
            WikiAPI().get_space(value), WikiAPI().get_node(value), WikiAPI().list_nodes(value),
            WikiAPI().list_nodes("s1", parent_node_token=value),
            DocxAPI().get_document(value), DocxAPI().list_blocks(value),
        ]
        for call in calls:
            with pytest.raises(ValueError):
                await call

    asyncio.run(scenario())
    assert requests == []


@pytest.mark.parametrize("data", [
    {"items": [], "has_more": True},
    {"items": [], "has_more": True, "page_token": "same"},
    {"items": "invalid", "has_more": False},
    {"items": [], "has_more": "false"},
    {"items": [{}]},
])
def test_malformed_pagination_fails_instead_of_truncating_or_looping(mock_feishu, data):
    requests, _ = mock_feishu(lambda _: ok(data))
    with pytest.raises(FeishuResponseError):
        asyncio.run(WikiAPI().list_spaces())
    assert len(requests) <= 3


@pytest.mark.parametrize("response", [
    lambda: httpx.Response(200, content=b"not json"),
    lambda: httpx.Response(200, json={"msg": "missing code"}),
    lambda: httpx.Response(200, json={"code": False, "data": {}}),
    lambda: httpx.Response(200, json={"code": 0}),
    lambda: ok({}),
])
def test_malformed_success_response_is_not_missing_resource(mock_feishu, response):
    mock_feishu(lambda _: response())
    with pytest.raises(FeishuResponseError):
        asyncio.run(WikiAPI().get_space("s1"))


def test_invalid_model_response_does_not_pass_as_success(mock_feishu):
    mock_feishu(lambda _: ok({"space": {"space_id": "s1"}}))
    with pytest.raises(ValidationError):
        asyncio.run(WikiAPI().get_space("s1"))


@pytest.mark.parametrize("status", [404, 500, 503])
def test_http_errors_are_not_mapped_to_none(mock_feishu, status):
    mock_feishu(lambda _: httpx.Response(status, content=b"gateway failure"))
    with pytest.raises(FeishuResponseError):
        asyncio.run(WikiAPI().get_space("s1"))


def test_sdk_timeout_propagates(mock_feishu):
    def handler(request):
        raise requests_lib.ReadTimeout("test timeout")

    mock_feishu(handler)
    with pytest.raises(requests_lib.ReadTimeout):
        asyncio.run(WikiAPI().list_spaces())


def test_missing_credentials_fail_without_network(mock_feishu, monkeypatch):
    requests, _ = mock_feishu(lambda _: pytest.fail("不应请求网络"))
    monkeypatch.setattr(_client.feishu_settings, "app_secret", "")
    with pytest.raises(FeishuConfigurationError):
        asyncio.run(WikiAPI().list_spaces())
    assert requests == []


def test_sdk_token_acquisition_and_request_do_not_block_event_loop(mock_feishu):
    started, release = threading.Event(), threading.Event()

    def token_handler(_):
        started.set()
        assert release.wait(2)
        return httpx.Response(200, json={"code": 0, "tenant_access_token": "fake-token", "expire": 7200})

    requests, threads = mock_feishu(lambda _: page([]), token_handler=token_handler)

    async def scenario():
        task = asyncio.create_task(WikiAPI().list_spaces())
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 1.5)
            # SDK 的同步 Token 请求尚未返回，事件循环仍然能执行到这里。
            assert not task.done()
        finally:
            release.set()
        assert await asyncio.wait_for(task, 2) == []

    asyncio.run(scenario())
    assert sum(r.method == "POST" for r in requests) == 1
    assert all(t != threading.get_ident() for t in threads)


def test_sdk_token_cache_refresh_and_application_isolation(mock_feishu, monkeypatch):
    import importlib

    clock = [1000.0]
    fake_time = SimpleNamespace(time=lambda: clock[0])
    monkeypatch.setattr(importlib.import_module("lark_oapi.core.token.manager"), "time", fake_time)
    monkeypatch.setattr(importlib.import_module("lark_oapi.core.cache.local_cache"), "time", fake_time)
    requests, _ = mock_feishu(lambda _: page([]))

    async def scenario():
        await WikiAPI().list_spaces()
        await DocxAPI().list_blocks("doc1")
        assert sum(r.method == "POST" for r in requests) == 1
        clock[0] += 7200
        await WikiAPI().list_spaces()
        assert sum(r.method == "POST" for r in requests) == 2
        monkeypatch.setattr(_client.feishu_settings, "app_id", "cli_other")
        await WikiAPI().list_spaces()
        assert sum(r.method == "POST" for r in requests) == 3

    asyncio.run(scenario())


def test_sdk_token_cache_survives_separate_event_loops(mock_feishu):
    requests, _ = mock_feishu(lambda _: page([]))
    assert asyncio.run(WikiAPI().list_spaces()) == []
    assert asyncio.run(WikiAPI().list_spaces()) == []
    assert sum(r.method == "POST" for r in requests) == 1


def test_sdk_token_acquisition_failure_can_recover(mock_feishu):
    attempts = [0]

    def token_handler(_):
        attempts[0] += 1
        if attempts[0] == 1:
            return httpx.Response(400, json={"code": 10014, "msg": "fake-secret"})
        return httpx.Response(200, json={"code": 0, "tenant_access_token": "fake-token", "expire": 7200})

    requests, _ = mock_feishu(lambda _: page([]), token_handler=token_handler)

    async def scenario():
        with pytest.raises(FeishuAuthenticationError) as error:
            await WikiAPI().list_spaces()
        assert error.value.code == 10014
        assert "fake-secret" not in str(error.value)
        assert await WikiAPI().list_spaces() == []

    asyncio.run(scenario())
    assert len(requests) == 3


def test_cancellation_propagates_while_sdk_worker_finishes(mock_feishu):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def handler(_):
        started.set()
        try:
            assert release.wait(2)
            return page([])
        finally:
            finished.set()

    mock_feishu(handler)

    async def scenario():
        task = asyncio.create_task(WikiAPI().list_spaces())
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 1.5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            assert await asyncio.wait_for(asyncio.to_thread(finished.wait, 1), 1.5)

    asyncio.run(scenario())


@pytest.mark.parametrize("status,code", [(500, 131005), (503, 0), (404, 0)])
def test_sdk_http_errors_do_not_become_missing_or_success(mock_feishu, status, code):
    mock_feishu(lambda _: httpx.Response(status, json={"code": code, "data": {}}, headers={"X-Tt-Logid": "http-log"}))
    with pytest.raises(FeishuHTTPError) as error:
        asyncio.run(WikiAPI().get_space("s1"))
    assert error.value.http_status == status
    assert error.value.log_id == "http-log"


def test_missing_document_blocks_raises_instead_of_empty_list(mock_feishu):
    mock_feishu(lambda _: httpx.Response(404, json={"code": 1770002}))
    with pytest.raises(FeishuAPIError) as error:
        asyncio.run(DocxAPI().list_blocks("missing"))
    assert error.value.code == 1770002

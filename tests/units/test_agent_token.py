import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from langgraph_sdk import Auth
from pydantic import SecretStr

from deal_pilot.config.agent_settings import AgentSettings
from deal_pilot.security import agent_token
from deal_pilot.security.auth import (
    authenticate,
    authorization,
    on_assistants,
    on_store,
)

SECRET = "unit-test-secret-" * 3


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    config = AgentSettings(
        _env_file=None, token_secret=SecretStr(SECRET), token_ttl_seconds=300
    )
    monkeypatch.setattr(agent_token, "agent_settings", config)
    return config


def test_authentication_returns_identity_without_permissions():
    token = agent_token.create_agent_token("open-id")
    assert agent_token.verify_agent_token(token) == "open-id"
    user = asyncio.run(authenticate(f"Bearer {token}"))
    assert user == {"identity": "open-id"}
    admin_token = agent_token.create_agent_token("admin")
    assert asyncio.run(authenticate(f"Bearer {admin_token}")) == {"identity": "admin"}


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "signature",
        "audience",
        "issuer",
        "missing_exp",
        "empty_subject",
        "algorithm",
    ],
)
def test_invalid_tokens_are_rejected(change):
    claims = jwt.decode(
        agent_token.create_agent_token("u"),
        SECRET,
        algorithms=["HS256"],
        audience="deal-pilot-agent",
    )
    key = SECRET
    algorithm = "HS256"
    if change == "expired":
        claims["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "signature":
        key = "wrong-test-secret-" * 3
    elif change == "audience":
        claims["aud"] = "other"
    elif change == "issuer":
        claims["iss"] = "other"
    elif change == "missing_exp":
        del claims["exp"]
    elif change == "empty_subject":
        claims["sub"] = " "
    elif change == "algorithm":
        algorithm = "HS384"
    token = jwt.encode(claims, key, algorithm=algorithm)
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(f"Bearer {token}"))
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "header",
    [None, "", "Basic test_user", "Bearer", "Bearer junk", "Bearer test_user "],
)
def test_invalid_authorization(header):
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(header))
    assert exc.value.status_code == 401


@pytest.mark.parametrize("token", ["admin", "user_1", "user_2", "test_user", "open-id"])
def test_unsigned_identity_and_legacy_tokens_are_rejected(token):
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(f"Bearer {token}"))
    assert exc.value.status_code == 401


def test_missing_secret_is_configuration_error(settings):
    settings.token_secret = SecretStr("")
    with pytest.raises(ValueError, match="AGENT_TOKEN_SECRET"):
        agent_token.create_agent_token("u")
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate("Bearer signed-token"))
    assert exc.value.status_code == 503


def test_resource_owner_and_namespace_remain_isolated():
    user = asyncio.run(authenticate(f"Bearer {agent_token.create_agent_token('u')}"))
    ctx = SimpleNamespace(
        user=SimpleNamespace(identity=user["identity"]), resource="store", action="get"
    )
    assert asyncio.run(on_store(ctx, {"namespace": ["u", "files"]})) is True
    assert asyncio.run(on_store(ctx, {"namespace": ["other", "files"]})) is False
    ctx.resource, ctx.action = "threads", "create"
    value = {"metadata": {"owner": "other"}}
    assert asyncio.run(authorization(ctx, value)) == {"owner": "u"}
    assert value["metadata"]["owner"] == "u"


@pytest.mark.parametrize("identity", ["admin", "user_id_001", "open-id"])
@pytest.mark.parametrize(
    "resource,action,handler",
    [
        ("store", "get", on_store),
        ("assistants", "read", on_assistants),
        ("threads", "create", authorization),
    ],
)
def test_allowed_operations_work_without_context_permissions(
    identity, resource, action, handler
):
    ctx = SimpleNamespace(
        user=SimpleNamespace(identity=identity),
        resource=resource,
        action=action,
    )
    value = {"namespace": [identity]} if resource == "store" else {}
    result = asyncio.run(handler(ctx, value))
    assert result == ({"owner": identity} if resource == "threads" else True)


@pytest.mark.parametrize("permissions", [[], ["assistants:create", "crons:create"]])
def test_context_permissions_do_not_change_policy(permissions):
    ctx = SimpleNamespace(
        user=SimpleNamespace(identity="u"),
        permissions=permissions,
        resource="assistants",
        action="read",
    )
    assert asyncio.run(on_assistants(ctx, {})) is True
    ctx.action = "create"
    assert asyncio.run(on_assistants(ctx, {})) is True
    ctx.resource = "crons"
    assert asyncio.run(authorization(ctx, {})) == {"owner": "u"}


def test_operations_are_not_filtered_and_user_resources_keep_owner():
    user = asyncio.run(
        authenticate(f"Bearer {agent_token.create_agent_token('admin')}")
    )
    ctx = SimpleNamespace(
        user=SimpleNamespace(identity=user["identity"]),
        resource="assistants",
        action="create",
    )
    assert asyncio.run(on_assistants(ctx, {})) is True
    ctx.resource = "crons"
    value = {"metadata": {"owner": "other", "label": "example"}}
    assert asyncio.run(authorization(ctx, value)) == {"owner": "admin"}
    assert value["metadata"] == {"owner": "admin", "label": "example"}


@pytest.mark.parametrize(
    "action", ["put", "get", "search", "delete", "list_namespaces"]
)
@pytest.mark.parametrize("namespace", [[], None, ["other", "files"]])
def test_store_isolation_applies_to_all_operations(action, namespace):
    ctx = SimpleNamespace(
        user=SimpleNamespace(identity="u"), resource="store", action=action
    )
    assert asyncio.run(on_store(ctx, {"namespace": namespace})) is False
    assert asyncio.run(on_store(ctx, {"namespace": ["u", "files"]})) is True


def test_benchmark_uses_signed_identity(monkeypatch):
    import importlib
    import json

    import httpx
    import langfuse
    from langgraph_sdk.client import LangGraphClient

    tracing = SimpleNamespace(
        get_current_trace_id=lambda: "trace-id",
        get_current_observation_id=lambda: "span-id",
    )
    monkeypatch.setattr(langfuse, "get_client", lambda: tracing)
    shared = importlib.import_module("deal_pilot.benchmarks.evaluators.shared")
    monkeypatch.setattr(shared, "langfuse", tracing)
    monkeypatch.setattr(
        shared,
        "benchmark_settings",
        SimpleNamespace(
            agent_server="http://agent.test",
            user_id="benchmark-user",
        ),
    )
    monkeypatch.setattr(
        shared.trace, "get_current_span", lambda: SimpleNamespace(attributes={})
    )
    requests = []

    async def handle(request):
        user = await authenticate(request.headers["authorization"])
        assert user["identity"] == "benchmark-user"
        requests.append(request)
        return httpx.Response(200, json={"structured_response": {"answer": "ok"}})

    clients = []

    def get_client(**kwargs):
        client = httpx.AsyncClient(
            base_url=kwargs["url"],
            headers=kwargs["headers"],
            transport=httpx.MockTransport(handle),
        )
        clients.append(client)
        return LangGraphClient(client)

    monkeypatch.setattr(shared, "get_agent_client", get_client)
    assert asyncio.run(shared.run_agent("retrieve_agent", "question")) == {
        "structured_response": {"answer": "ok"},
    }
    assert requests[0].headers["authorization"] != "Bearer benchmark-user"
    body = json.loads(requests[0].content)
    assert body["metadata"]["trace_id"] == "trace-id"
    assert body["metadata"]["parent_span_id"] == "span-id"
    assert all(client.is_closed for client in clients)

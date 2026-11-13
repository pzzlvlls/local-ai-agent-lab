from typing import Never

from jwt import InvalidTokenError
from langgraph_sdk import Auth
from deal_pilot.security.agent_token import verify_agent_token

auth = Auth()


def _raise_invalid_token() -> Never:
    raise Auth.exceptions.HTTPException(status_code=401, detail="invalid token")


@auth.authenticate
async def authenticate(
    authorization: str | None,
) -> Auth.types.MinimalUserDict:
    """验证 Authorization: Bearer <token> 并返回当前用户。"""
    if not authorization:
        _raise_invalid_token()
    schema, sep, token = authorization.partition(" ")
    if schema.lower() != "bearer" or not sep or not token or token != token.strip():
        _raise_invalid_token()
    try:
        identity = verify_agent_token(token)
    except InvalidTokenError:
        _raise_invalid_token()
    except ValueError as exc:
        raise Auth.exceptions.HTTPException(
            status_code=503, detail="agent token verification is not configured"
        ) from exc
    return {"identity": identity}


@auth.on.store
async def on_store(ctx: Auth.types.AuthContext, value: dict) -> bool:
    """Store 只允许访问当前用户 namespace 下的数据。"""
    namespace = tuple(value["namespace"]) if value["namespace"] else ()
    if not namespace or namespace[0] != ctx.user.identity:
        return False
    return True


@auth.on.assistants
async def on_assistants(ctx: Auth.types.AuthContext, value: dict) -> bool:
    """Assistant 为系统共享资源，不施加用户 owner 过滤。"""
    return True


@auth.on
async def authorization(ctx: Auth.types.AuthContext, value: dict) -> dict[str, str]:
    """线程等用户资源按当前身份写入 owner，并限制访问范围。"""
    metadata = value.setdefault("metadata", {})
    metadata["owner"] = ctx.user.identity

    return {"owner": ctx.user.identity}

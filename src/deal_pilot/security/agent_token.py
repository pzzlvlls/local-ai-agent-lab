"""可信业务入口与 Agent Server 之间的短期身份令牌。"""

from datetime import datetime, timedelta, timezone

import jwt

from deal_pilot.config.agent_settings import agent_settings

_ISSUER = "deal-pilot"
_AUDIENCE = "deal-pilot-agent"


def _get_secret() -> str:
    secret = agent_settings.token_secret.get_secret_value()
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("AGENT_TOKEN_SECRET 必须配置为至少 32 字节的随机密钥")
    return secret


def create_agent_token(user_id: str) -> str:
    """仅由已验证用户身份的业务入口调用；不向外提供按任意 ID 签发的接口。"""
    if not user_id.strip():
        raise ValueError("user_id 不能为空")
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "iat": now,
            "exp": now + timedelta(seconds=agent_settings.token_ttl_seconds),
        },
        _get_secret(),
        algorithm="HS256",
    )


def verify_agent_token(token: str) -> str:
    """校验签名、有效期及用途，返回认证用户 ID；无效令牌抛 InvalidTokenError。"""
    claims = jwt.decode(
        token,
        _get_secret(),
        algorithms=["HS256"],
        issuer=_ISSUER,
        audience=_AUDIENCE,
        options={"require": ["sub", "iss", "aud", "iat", "exp"]},
    )
    user_id = claims["sub"]
    if not isinstance(user_id, str) or not user_id.strip():
        raise jwt.InvalidTokenError("invalid subject")
    return user_id

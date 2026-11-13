"""官方 SDK 的调用边界、响应校验及全量分页。"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache

import lark_oapi as lark
from lark_oapi.api.cardkit.v1.version import V1 as CardkitV1
from lark_oapi.api.docx.v1.version import V1 as DocxV1
from lark_oapi.api.drive.v1.version import V1 as DriveV1
from lark_oapi.api.im.v1.version import V1 as ImV1
from lark_oapi.api.wiki.v2.version import V2 as WikiV2
from lark_oapi.core.exception import ObtainAccessTokenException, UnmarshalException
from lark_oapi.core.model import BaseResponse
from pydantic import JsonValue

from deal_pilot.config.feishu_settings import feishu_settings
from deal_pilot.feishu.api.errors import (
    FeishuAPIError,
    FeishuAuthenticationError,
    FeishuConfigurationError,
    FeishuHTTPError,
    FeishuResponseError,
)


@lru_cache(maxsize=1)
def _build_client(app_id: str, app_secret: str) -> lark.Client:
    return (lark.Client.builder().app_id(app_id).app_secret(app_secret)
            .timeout(30).log_level(lark.LogLevel.ERROR).build())


def _client() -> lark.Client:
    app_id, app_secret = feishu_settings.app_id, feishu_settings.app_secret
    if not app_id.strip() or not app_secret.strip():
        raise FeishuConfigurationError("请配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
    return _build_client(app_id, app_secret)


def wiki_client() -> WikiV2:
    client = _client()
    assert client.wiki is not None  # 官方 builder 会初始化所有服务。
    return client.wiki.v2


def docx_client() -> DocxV1:
    client = _client()
    assert client.docx is not None
    return client.docx.v1


def drive_client() -> DriveV1:
    client = _client()
    assert client.drive is not None
    return client.drive.v1


def im_client() -> ImV1:
    client = _client()
    assert client.im is not None
    return client.im.v1


def cardkit_client() -> CardkitV1:
    client = _client()
    assert client.cardkit is not None
    return client.cardkit.v1


def resource_id(value: str, name: str) -> str:
    """校验单个资源标识；路径编码由 SDK 处理。"""
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} 必须是非空资源 ID/token")
    if value in {".", ".."} or any(c.isspace() or c in "/\\?#" for c in value):
        raise ValueError(f"{name} 应传资源 ID/token，不能传链接或路径")
    return value


def object_value(value: JsonValue, name: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise FeishuResponseError(f"飞书响应缺少有效的 {name} 对象")
    return value


async def sdk_response[T: BaseResponse](operation: Callable[[], T]) -> T:
    """完整 SDK 调用在线程中执行，包括同步鉴权；Token 获取与缓存交给 SDK。"""
    try:
        response = await asyncio.to_thread(operation)
    except ObtainAccessTokenException as error:
        # SDK 的原始异常包含服务端 msg，不直接输出，避免带出凭据。
        raise FeishuAuthenticationError(error.code) from None
    except (json.JSONDecodeError, UnmarshalException):
        raise FeishuResponseError("飞书 SDK 无法解析服务响应") from None
    raw = response.raw
    if raw is None or type(raw.status_code) is not int:
        raise FeishuResponseError("飞书 SDK 响应缺少有效的 HTTP 状态")
    log_id = next((v for k, v in raw.headers.items() if k.lower() == "x-tt-logid"), None)
    if raw.status_code >= 500:
        raise FeishuHTTPError(raw.status_code, log_id)
    if type(response.code) is not int:
        raise FeishuResponseError("飞书 SDK 响应缺少有效的 code")
    if not response.success():
        raise FeishuAPIError(response.code, raw.status_code, log_id)
    if not 200 <= raw.status_code < 300:
        raise FeishuHTTPError(raw.status_code, log_id)
    return response


async def sdk_call(operation: Callable[[], BaseResponse]) -> dict[str, JsonValue]:
    """校验 JSON 业务响应，保留 SDK 模型未声明的原始字段。"""
    response = await sdk_response(operation)
    raw = response.raw
    assert raw is not None
    if raw.content is None:
        raise FeishuResponseError("飞书 SDK 响应缺少原始内容")
    # SDK 模型会忽略未声明字段；从 raw 保留完整块数据及未来新增字段。
    payload = object_value(json.loads(raw.content), "响应")
    return object_value(payload.get("data"), "data")


async def iter_items(
    fetch_page: Callable[[str | None], Awaitable[dict[str, JsonValue]]],
) -> AsyncIterator[dict[str, JsonValue]]:
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        data = await fetch_page(page_token)
        items = data.get("items")
        if items is None:
            items = []
        if not isinstance(items, list) or type(data.get("has_more")) is not bool:
            raise FeishuResponseError("飞书分页响应缺少有效的 items/has_more")
        for item in items:
            yield object_value(item, "items[]")
        if not data["has_more"]:
            return
        token = data.get("page_token")
        if not isinstance(token, str) or not token or token in seen_tokens:
            raise FeishuResponseError("飞书分页游标缺失或重复，无法读取完整列表")
        seen_tokens.add(token)
        page_token = token

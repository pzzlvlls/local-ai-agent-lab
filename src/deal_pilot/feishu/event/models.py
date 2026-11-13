"""事件数据、回调类型、监听错误及 v1/v2 原始 JSON 解析。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import JsonValue, TypeAdapter

_payload_adapter = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True)
class FeishuEvent:
    """事件类型、事件 ID 与飞书原始 JSON；payload 不应在回调内修改。"""

    event_type: str
    event_id: str | None
    payload: dict[str, JsonValue]


type EventCallback = Callable[[FeishuEvent], Awaitable[None] | None]


class FeishuEventListenerError(RuntimeError):
    """监听进程、IPC 或回调提交失败；不携带凭据、正文或 SDK 原始消息。"""


def decode_event(raw: bytes) -> FeishuEvent:
    """校验飞书事件结构，保留完整的原始字段。"""
    payload = _payload_adapter.validate_json(raw)
    if payload.get("schema"):
        header = payload.get("header")
        if not isinstance(header, dict):
            raise ValueError("飞书 v2 事件缺少 header")
        event_type, event_id = header.get("event_type"), header.get("event_id")
    else:
        body = payload.get("event")
        if not isinstance(body, dict):
            raise ValueError("飞书 v1 事件缺少 event")
        event_type, event_id = body.get("type"), payload.get("uuid")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("飞书事件缺少 event_type")
    if event_id is not None and not isinstance(event_id, str):
        raise ValueError("飞书事件的 event_id 必须是字符串")
    return FeishuEvent(event_type, event_id, payload)

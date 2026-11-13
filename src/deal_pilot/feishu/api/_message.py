"""文本和卡片共用的官方 IM 投递入口；不依赖业务 API 类。"""

from typing import Literal

from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from deal_pilot.feishu.api._client import im_client, sdk_call
from deal_pilot.feishu.api.errors import FeishuResponseError


def validate_recipient(
    receive_id: str, *,
    receive_id_type: Literal["open_id", "union_id", "user_id", "email", "chat_id"],
    uuid: str | None,
) -> None:
    if receive_id_type not in ("open_id", "union_id", "user_id", "email", "chat_id"):
        raise ValueError("receive_id_type 必须为 open_id、union_id、user_id、email 或 chat_id")
    if not isinstance(receive_id, str) or not receive_id or any(c.isspace() for c in receive_id):
        raise ValueError("receive_id 必须是非空且不含空白的接收者标识")
    if uuid is not None and (not isinstance(uuid, str) or not uuid.strip() or len(uuid) > 50):
        raise ValueError("uuid 必须是 1 到 50 个字符的非空白字符串")


async def send_message(
    receive_id: str,
    msg_type: Literal["text", "interactive"],
    content: str,
    *,
    receive_id_type: Literal["open_id", "union_id", "user_id", "email", "chat_id"],
    uuid: str | None,
) -> str:
    validate_recipient(receive_id, receive_id_type=receive_id_type, uuid=uuid)

    body = (CreateMessageRequestBody.builder().receive_id(receive_id).msg_type(msg_type)
            .content(content))
    if uuid is not None:
        body.uuid(uuid)
    request = (CreateMessageRequest.builder().receive_id_type(receive_id_type)
               .request_body(body.build()).build())
    api = im_client()
    data = await sdk_call(lambda: api.message.create(request))
    message_id = data.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        raise FeishuResponseError("飞书发送响应缺少有效的 message_id")
    return message_id

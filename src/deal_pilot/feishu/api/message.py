"""通过官方 IM 接口，以应用身份向指定用户发送文本消息。"""

import json
from typing import Literal

from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from deal_pilot.feishu.api._client import im_client, sdk_call
from deal_pilot.feishu.api.errors import FeishuResponseError


class MessageAPI:
    """用户单聊消息发送；复用 feishu_settings 的应用凭据。"""

    async def send_text(
        self,
        receive_id: str,
        text: str,
        *,
        receive_id_type: Literal["open_id", "union_id", "user_id", "email"] = "open_id",
        uuid: str | None = None,
    ) -> str:
        """发送一则文本消息，返回飞书 message_id。

        Args:
            receive_id: 与 receive_id_type 匹配的用户标识，不接受群 ID。
            text: 非空白文本，保留原始内容，由本方法序列化为飞书 content。
            receive_id_type: 默认 open_id；也可使用 union_id、user_id 或 email。
            uuid: 可选的发送去重标识，最多 50 个字符；重试同一消息时复用。

        应用须启用机器人并具备发送消息权限，目标用户须满足飞书可达范围。
        不自动重试；取消或网络超时并不表示远端一定未发送。
        参数错误抛 ValueError，其余错误沿用飞书 API 的异常契约。
        """
        if receive_id_type not in ("open_id", "union_id", "user_id", "email"):
            raise ValueError("receive_id_type 必须为 open_id、union_id、user_id 或 email")
        if not isinstance(receive_id, str) or not receive_id or any(c.isspace() for c in receive_id):
            raise ValueError("receive_id 必须是非空且不含空白的用户标识")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text 必须是非空白字符串")
        if uuid is not None and (not isinstance(uuid, str) or not uuid.strip() or len(uuid) > 50):
            raise ValueError("uuid 必须是 1 到 50 个字符的非空白字符串")

        body = (CreateMessageRequestBody.builder().receive_id(receive_id).msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False)))
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

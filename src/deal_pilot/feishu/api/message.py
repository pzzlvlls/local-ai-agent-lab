"""通过官方 IM 接口发送文本及撤回消息；卡片操作统一在 card 模块。"""

import json
from typing import Literal

from lark_oapi.api.im.v1 import DeleteMessageRequest

from deal_pilot.feishu.api._client import im_client, sdk_response, resource_id
from deal_pilot.feishu.api._message import send_message


class MessageAPI:
    """用户或群聊文本消息；复用 feishu_settings 的应用凭据。"""

    async def send_text(
        self,
        receive_id: str,
        text: str,
        *,
        receive_id_type: Literal["open_id", "union_id", "user_id", "email", "chat_id"] = "open_id",
        uuid: str | None = None,
    ) -> str:
        """发送一则文本消息，返回飞书 message_id。

        Args:
            receive_id: 与 receive_id_type 匹配的接收者标识，chat_id 时为会话 ID。
            text: 非空白文本，保留原始内容，由本方法序列化为飞书 content。
            receive_id_type: 默认 open_id；也可使用 union_id、user_id 、email 或 chat_id。
            uuid: 可选的发送去重标识，最多 50 个字符；重试同一消息时复用。

        应用须启用机器人并具备发送消息权限，目标用户须满足飞书可达范围。
        不自动重试；取消或网络超时并不表示远端一定未发送。
        参数错误抛 ValueError，其余错误沿用飞书 API 的异常契约。
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text 必须是非空白字符串")
        return await send_message(
            receive_id, "text", json.dumps({"text": text}, ensure_ascii=False),
            receive_id_type=receive_id_type, uuid=uuid,
        )

    async def recall(self, message_id: str) -> None:
        """撤回消息（含卡片）；权限、时间窗和发送身份由飞书校验。"""
        resource_id(message_id, "message_id")
        request = DeleteMessageRequest.builder().message_id(message_id).build()
        api = im_client()
        await sdk_response(lambda: api.message.delete(request))

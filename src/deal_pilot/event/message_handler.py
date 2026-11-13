from deal_pilot.feishu.event.models import FeishuEvent
import json
from deal_pilot.feishu.api import MessageAPI


async def message_handler(event: FeishuEvent) -> None:
    open_id = event.payload["event"]["sender"]["sender_id"]["open_id"]  # type: ignore
    content = event.payload["event"]["message"]["content"]  # type: ignore
    text = json.loads(content)["text"]  # type: ignore
    msg_api = MessageAPI()
    await msg_api.send_text(open_id, text)  # type: ignore

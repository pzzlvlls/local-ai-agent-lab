from deal_pilot.feishu.event.models import FeishuEvent
import json
from deal_pilot.event.message.reply import reply


async def message_handler(event: FeishuEvent) -> None:
    open_id = event.payload["event"]["sender"]["sender_id"]["open_id"]  # type: ignore
    content = event.payload["event"]["message"]["content"]  # type: ignore
    text = json.loads(content)["text"]  # type: ignore
    await reply(open_id, text)  # type: ignore

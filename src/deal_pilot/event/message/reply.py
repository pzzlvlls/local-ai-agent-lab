from deal_pilot.feishu.api import Card
import asyncio
from deal_pilot.event.message.card_schema import create_card_json, CONTENT_ID


async def reply(receive_id: str, receive_text: str):
    # 创建卡片
    card = await Card.create(
        create_card_json(),
        receive_id=receive_id,
    )
    # 流式更新
    text = ""
    for chunk in ["你好！", "这是一段", "**流式输出**。"]:
        await asyncio.sleep(1)
        text += chunk
        await card.stream_text(CONTENT_ID, text)
    # 完成
    await card.finish()

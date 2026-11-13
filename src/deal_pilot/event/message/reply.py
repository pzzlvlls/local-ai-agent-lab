import asyncio

from deal_pilot.event.message.card_schema import create_card_json, CONTENT_ID, STATUS_ID
from deal_pilot.event.message.status import CardStatus
from deal_pilot.feishu.api import Card
from deal_pilot.utils.run_agent import AgentOutput, AgentStatus, run_agent

CARD_UPDATE_INTERVAL = 0.2


async def reply(receive_id: str, receive_text: str) -> None:
    """以可信飞书事件的发送者 OpenID 运行主 Agent，并更新单聊卡片。"""
    card = await Card.create(
        create_card_json(),
        receive_id=receive_id,
    )
    content = ""
    status_text = CardStatus(AgentStatus.PROCESSING).get_text()
    stream = run_agent("main_agent", receive_text, user_id=receive_id)
    latest = AgentOutput(AgentStatus.PROCESSING)

    async def read_agent_output() -> None:
        nonlocal latest
        # 持续读取，只保留最新快照，不等待飞书请求，也不积压中间版本。
        async for output in stream:
            latest = output

    async def update_card() -> None:
        nonlocal content, status_text
        # 固定本次快照，避免请求期间新输出使正文与状态对应不上。
        output = latest
        if output.content != content:
            await card.patch_element(CONTENT_ID, {"content": output.content or " "})
            content = output.content
        current_status = CardStatus(output.status, output.payload).get_text()
        if current_status != status_text:
            await card.patch_element(
                STATUS_ID, {"content": f"<font color='grey'>{current_status}</font>"}
            )
            status_text = current_status

    reader = asyncio.create_task(read_agent_output())
    try:
        while not reader.done():
            # 到刷新间隔或 Agent 结束时更新；超时不会取消读取任务。
            await asyncio.wait({reader}, timeout=CARD_UPDATE_INTERVAL)
            await update_card()
        await reader
        # Agent 可能在飞书请求期间结束，收尾前再提交最新完整内容。
        await update_card()
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await stream.aclose()
        await card.finish()

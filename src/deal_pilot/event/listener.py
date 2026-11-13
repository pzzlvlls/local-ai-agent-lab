from deal_pilot.feishu.event import feishu_event_listener
from deal_pilot.event.message.message_handler import message_handler

HANDLERS = {"im.message.receive_v1": message_handler}


async def start_feishu_events() -> None:
    # 在 Agent Server 的异步启动逻辑中调用，注册时记录 Server 的事件循环。
    for event_name, handler in HANDLERS.items():
        feishu_event_listener.register(event_name, handler)
    feishu_event_listener.start_listener()


def cancel_feishu_events() -> None:
    """释放整个监听器；异步调用方需在线程中执行。"""
    feishu_event_listener.close()

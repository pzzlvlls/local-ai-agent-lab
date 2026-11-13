"""子进程入口：运行飞书 SDK 长连接，通过 Pipe 回传事件或启动错误。"""

import json
from multiprocessing.connection import Connection

from deal_pilot.feishu.event.models import decode_event


def run_listener(app_id: str, app_secret: str, sender: Connection) -> None:
    """spawn 入口；子进程内加载 SDK 并运行专用事件循环。"""
    try:
        import lark_oapi as lark

        class ForwardingHandler(lark.EventDispatcherHandler):
            def _do_without_validation(self, payload: bytes) -> None:
                # SDK 没有通配事件注册接口；在 WebSocket 专用分发边界保留原始 JSON。
                # 此接口不作为 HTTP Webhook 使用，连接鉴权仍由 SDK 完成。
                decode_event(payload)
                sender.send_bytes(b"E" + payload)

        client = lark.ws.Client(
            app_id, app_secret,
            event_handler=ForwardingHandler(),
            log_level=lark.LogLevel.CRITICAL,
            auto_reconnect=True,
        )
        client.start()
    except Exception as error:
        # SDK 异常文本可能含服务响应；仅回传类型与数字错误码。
        code = getattr(error, "code", None)
        failure = {"type": type(error).__name__, "code": code if type(code) is int else None}
        try:
            sender.send_bytes(b"X" + json.dumps(failure).encode())
        except (BrokenPipeError, EOFError, OSError):
            pass  # 主进程已关闭，无法再上报。
    finally:
        sender.close()

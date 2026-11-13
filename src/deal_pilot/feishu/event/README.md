# 飞书事件监听

`FeishuEventListener` 是线程安全的进程内单例，直接使用导出的 `feishu_event_listener` 即可。重复调用 `FeishuEventListener()` 也返回同一实例，不重置回调或创建新进程。创建实例和导入模块都不连接飞书，显式调用 `start_listener()` 才启动。

子进程运行官方 SDK 的 WebSocket 长连接，通过单向 Pipe 回传事件。主进程接收线程只提交回调，然后立即读取下一条事件：同步回调提交给专用线程池，异步回调提交给注册时的 Server 事件循环。

```python
from deal_pilot.feishu.event import FeishuEvent, feishu_event_listener


async def on_file_edit(event: FeishuEvent) -> None:
    print(event.event_type, event.event_id)
    # 在业务中自行执行异步操作、接入追踪。


async def start_feishu_events() -> None:
    # 在 Agent Server 的异步启动逻辑中调用，注册时记录 Server 的事件循环。
    feishu_event_listener.register("drive.file.edit_v1", on_file_edit)
    feishu_event_listener.start_listener()


def cancel_feishu_events() -> None:
    """释放整个监听器；异步调用方需在线程中执行。"""
    feishu_event_listener.close()
```

单例持有监听资源，启动函数返回后继续监听，不需要 `with` 或保活循环。普通脚本须在 `if __name__ == "__main__"` 保护内调用启动函数，避免 spawn 重复执行启动代码。

- `start_listener()`：读取 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`，幂等启动一个子进程和一个接收线程。重复或并发调用不重复启动，不等待飞书连接就绪。缺少配置可补好后重试；运行后故障不自动重启。
- `register(event_type, callback, *, loop=None)`：支持同步函数、异步函数及异步可调用对象，同类型同一回调去重。`*` 匹配全部事件。按类型回调、通配回调的顺序提交，但任务并发执行，不保证开始或完成顺序。
- 同步函数在线程池执行，默认 4 个工作线程。异步函数在注册时自动捕获的运行中循环执行；其他线程可通过 `loop=server_loop` 显式指定。没有可用循环时注册异步函数报错。普通包装函数返回 awaitable 时，也只提交给注册循环，不等待其完成。
- `unregister(event_type, callback)`：返回是否移除，不取消已经提交的任务。没有匹配回调的事件不保留或重放。
- `FeishuEvent`：包含 `event_type`、可选 `event_id` 和完整 JSON `payload`，支持 v1/v2；回调间共享事件，不应修改 `payload`。
- 分发器不保存提交返回的 Future，不读取业务结果、不记录业务异常，不统计或限制回调任务积压。业务追踪、异常处理由回调自身负责。
- `error` / `raise_if_failed()`：查看或抛出监听进程、IPC 或任务提交失败；任务内部的业务异常不转为监听器故障。注册循环已停止时无法提交任务，按监听错误报告，不另建循环。
- `process_id` / `is_alive`：查看本地进程、接收线程状态，不代表飞书连接就绪；断线重连由 SDK 负责。
- `close(timeout=5.0)`：关闭监听子进程、接收线程和新任务提交，可重复调用。已经提交的同步/异步回调继续执行，包括线程池排队任务；不等待或取消它们，也不读取其结果。线程池由标准库在已有任务结束后回收工作线程。关闭后同一单例不再启动。异步服务可用 `await asyncio.to_thread(feishu_event_listener.close)` 隔离进程/线程关闭等待。

飞书应用侧需启用长连接并配置事件订阅和权限，`register` 不更改远程订阅。项目已在 `app/main.py` 的 FastAPI lifespan 启动阶段调用 `event/listener.py:start_feishu_events()`；退出时在 finally 中通过 asyncio.to_thread 调用 cancel_feishu_events() 关闭监听器，不等待或取消已有业务任务；未接入 Agent 或索引流程。单例按 Python 进程生效，多工作进程各自独立。

SDK 在事件交给 Pipe 后即可回执，不等待业务处理完成。本模块不提供业务任务持久化、去重、重试或结果管理。SDK 没有通配事件注册接口，子进程局部覆写 `EventDispatcherHandler._do_without_validation` 接收原始事件；该 handler 不用于 HTTP Webhook 或需要同步业务响应的卡片交互。升级 SDK 时需检查这个内部 hook。官方示例见 [larksuite/oapi-sdk-python](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/samples/ws/sample.py)。

## 维护入口

| 文件            | 职责                                    |
| --------------- | --------------------------------------- |
| `models.py`     | 事件模型、类型、监听错误及 v1/v2 解析   |
| `worker.py`     | 子进程飞书 SDK 长连接及事件回传         |
| `dispatcher.py` | 回调注册/注销、同步线程池与异步循环提交 |
| `listener.py`   | 单例、幂等启动、IPC 接收及监听资源关闭  |
| `__init__.py`   | 统一公开导出                            |

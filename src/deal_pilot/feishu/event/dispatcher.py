"""主进程回调注册及提交；提交后继续接收，不管理业务任务的结果或生命周期。"""

import asyncio
import inspect
import threading
from collections.abc import Awaitable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from deal_pilot.feishu.event.models import EventCallback, FeishuEvent


@dataclass(frozen=True)
class _RegisteredCallback:
    callback: EventCallback
    loop: asyncio.AbstractEventLoop | None
    is_async: bool


async def _await_callback(result: Awaitable[None]) -> None:
    await result


class CallbackDispatcher:
    """同步回调提交到线程池，异步回调提交到注册循环；不保存返回的 Future。"""

    def __init__(self, stopping: threading.Event, *, max_workers: int = 4) -> None:
        self._lock = threading.Lock()
        self._stopping = stopping
        self._closed = False
        self._callbacks: dict[str, list[_RegisteredCallback]] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="feishu-callback")

    def register(
        self, event_type: str, callback: EventCallback, *, loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """校验回调并记录运行循环；同类型同一回调去重。"""
        if not isinstance(event_type, str) or not event_type.strip() or event_type != event_type.strip():
            raise ValueError("event_type 必须是非空事件类型或 *")
        if not callable(callback):
            raise TypeError("callback 必须是可调用对象")
        is_async = inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(callback.__call__)
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        if loop is not None and (loop.is_closed() or not loop.is_running()):
            raise ValueError("loop 必须是正在运行的事件循环")
        if loop is None and is_async:
            raise ValueError("异步回调须在运行中的事件循环内注册，或通过 loop 指定循环")
        with self._lock:
            if self._closed:
                raise RuntimeError("事件回调分发器已关闭")
            callbacks = self._callbacks.setdefault(event_type, [])
            if not any(entry.callback == callback for entry in callbacks):
                callbacks.append(_RegisteredCallback(callback, loop, is_async))

    def unregister(self, event_type: str, callback: EventCallback) -> bool:
        """移除回调；已提交的任务不取消。"""
        with self._lock:
            callbacks = self._callbacks.get(event_type, [])
            for entry in callbacks:
                if entry.callback == callback:
                    callbacks.remove(entry)
                    if not callbacks:
                        self._callbacks.pop(event_type, None)
                    return True
            return False

    def dispatch(self, event: FeishuEvent) -> None:
        """只提交当前事件的回调，不等待结果或接管业务异常处理。"""
        with self._lock:
            if self._closed or self._stopping.is_set():
                return
            callbacks = tuple(self._callbacks.get(event.event_type, ()))
            if event.event_type != "*":
                callbacks += tuple(self._callbacks.get("*", ()))
            for entry in callbacks:
                if entry.is_async:
                    self._submit_awaitable(self._run_async(entry, event), entry.loop)
                else:
                    self._executor.submit(self._run_sync, entry, event)

    @staticmethod
    async def _run_async(entry: _RegisteredCallback, event: FeishuEvent) -> None:
        result = entry.callback(event)
        if inspect.isawaitable(result):
            await result

    def _run_sync(self, entry: _RegisteredCallback, event: FeishuEvent) -> None:
        result = entry.callback(event)
        if inspect.isawaitable(result):
            self._submit_awaitable(result, entry.loop)

    @staticmethod
    def _submit_awaitable(result: Awaitable[None], loop: asyncio.AbstractEventLoop | None) -> None:
        if loop is None or loop.is_closed() or not loop.is_running():
            if inspect.iscoroutine(result):
                result.close()
            raise RuntimeError("异步回调的事件循环未运行")
        coroutine = result if inspect.iscoroutine(result) else _await_callback(result)
        try:
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        except BaseException:
            coroutine.close()
            raise

    def close(self) -> None:
        """停止新提交；已有回调继续执行，不等待或取消业务任务。"""
        with self._lock:
            self._closed = True
            self._stopping.set()
        self._executor.shutdown(wait=False, cancel_futures=False)

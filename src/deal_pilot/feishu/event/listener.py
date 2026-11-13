"""监听器单例、幂等启动、IPC 接收及进程/线程生命周期。"""

import asyncio
import json
import logging
import math
import multiprocessing
import threading
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import ClassVar, final

from deal_pilot.config.feishu_settings import feishu_settings
from deal_pilot.feishu.event import worker
from deal_pilot.feishu.event.dispatcher import CallbackDispatcher
from deal_pilot.feishu.event.models import EventCallback, FeishuEventListenerError, decode_event

logger = logging.getLogger(__name__)


@final
class FeishuEventListener:
    """进程内单例；显式幂等启动，运行期间可随时注册或注销回调。"""

    _instance: ClassVar["FeishuEventListener | None"] = None
    _instance_lock: ClassVar[threading.Lock] = threading.Lock()

    def __new__(cls) -> "FeishuEventListener":
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialize()
                cls._instance = instance
            return cls._instance

    def _initialize(self) -> None:
        # 在发布单例前完成初始化；重复构造不能重置回调和运行状态。
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._stopping = threading.Event()
        self._dispatcher = CallbackDispatcher(self._stopping)
        self._error: FeishuEventListenerError | None = None
        self._started = False
        self._receiver: Connection | None = None
        self._process: BaseProcess | None = None
        self._thread: threading.Thread | None = None

    def start_listener(self) -> None:
        """读取应用配置并启动一次；并发/重复调用复用已有监听，不等待远程就绪。"""
        with self._lifecycle_lock:
            self.raise_if_failed()
            if self._stopping.is_set():
                raise RuntimeError("事件监听器已关闭，不能再次启动")
            if self._started:
                return
            app_id, app_secret = feishu_settings.app_id, feishu_settings.app_secret
            if not app_id.strip() or not app_secret.strip():
                from deal_pilot.feishu.api.errors import FeishuConfigurationError

                raise FeishuConfigurationError("请配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
            context = multiprocessing.get_context("spawn")
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=worker.run_listener,
                args=(app_id, app_secret, sender),
                name="feishu-event-listener",
                daemon=True,
            )
            thread = threading.Thread(
                target=self._receive_events, args=(receiver,),
                name="feishu-event-dispatch", daemon=True,
            )
            self._receiver, self._process, self._thread = receiver, process, thread
            try:
                process.start()
                sender.close()  # 父进程不得保留写端，否则子进程退出后收不到 EOF。
                thread.start()
                self._started = True
            except BaseException:
                sender.close()
                self._stop_process(5.0)
                receiver.close()
                self._receiver = self._process = self._thread = None
                raise

    @property
    def process_id(self) -> int | None:
        with self._process_lock:
            return self._process.pid if self._process is not None else None

    @property
    def is_alive(self) -> bool:
        """本地进程与分发线程存活，不表示飞书连接已经就绪。"""
        with self._process_lock:
            return (
                not self._stopping.is_set()
                and self._process is not None and self._process.is_alive()
                and self._thread is not None and self._thread.is_alive()
            )

    @property
    def error(self) -> FeishuEventListenerError | None:
        with self._lock:
            return self._error

    def raise_if_failed(self) -> None:
        if error := self.error:
            raise error

    def register(
        self,
        event_type: str,
        callback: EventCallback,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """注册同步/异步回调；自动记录当前运行循环，也可通过 loop 显式指定。"""
        with self._lock:
            if self._error is not None:
                raise self._error
            if self._stopping.is_set():
                raise RuntimeError("事件监听器已关闭")
            self._dispatcher.register(event_type, callback, loop=loop)

    def unregister(self, event_type: str, callback: EventCallback) -> bool:
        """注销回调；已开始分发的事件继续使用其回调快照。"""
        return self._dispatcher.unregister(event_type, callback)

    def _receive_events(self, receiver: Connection) -> None:
        try:
            while not self._stopping.is_set():
                if not receiver.poll(0.1):
                    continue
                message = receiver.recv_bytes()
                if message[:1] == b"X":
                    failure = json.loads(message[1:])
                    raise FeishuEventListenerError(
                        f"飞书事件监听子进程失败：{failure['type']}，code={failure['code']}"
                    )
                if message[:1] != b"E":
                    raise FeishuEventListenerError("飞书事件监听 IPC 消息无效")
                self._dispatcher.dispatch(decode_event(message[1:]))
        except Exception as error:
            if not self._stopping.is_set():
                failure = error if isinstance(error, FeishuEventListenerError) else FeishuEventListenerError(
                    f"飞书事件监听中断：{type(error).__name__}"
                )
                with self._lock:
                    self._error = failure
                logger.error("%s", failure)
        finally:
            receiver.close()
            self._dispatcher.close()
            self._stop_process(5.0)

    def _stop_process(self, timeout: float) -> None:
        # close 与分发线程都可能负责收尾，避免同时 waitpid 同一个进程。
        with self._process_lock:
            process = self._process
            if process is None or process.pid is None:
                return
            if process.is_alive():
                process.terminate()
            process.join(timeout)
            if process.is_alive():
                process.kill()
                process.join(timeout)
            if process.is_alive():
                raise TimeoutError("飞书事件监听子进程未能退出")

    def close(self, timeout: float = 5.0) -> None:
        """关闭监听进程及接收线程；不等待或取消已提交的业务回调。可重复调用。"""
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须是有限正数")
        with self._lifecycle_lock:
            self._stopping.set()
            thread = self._thread
        self._dispatcher.close()
        # SDK 无公开 stop 方法，子进程是其连接与事件循环的生命周期边界。
        self._stop_process(timeout)
        if thread is not None and threading.current_thread() is not thread:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("飞书事件接收线程未能退出")


# 各模块直接导入此实例；重复 FeishuEventListener() 也始终返回同一对象。
feishu_event_listener = FeishuEventListener()

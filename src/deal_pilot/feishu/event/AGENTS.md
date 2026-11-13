# 飞书事件监听

## 模块分工

| 文件            | 职责                                                                                             |
| --------------- | ------------------------------------------------------------------------------------------------ |
| `models.py`     | `FeishuEvent`、回调类型、监听错误及 v1/v2 原始 JSON 校验解析                                     |
| `worker.py`     | 顶层 `run_listener` spawn 入口、SDK WebSocket handler、事件/启动错误回传；SDK 在子进程入口内加载 |
| `dispatcher.py` | `CallbackDispatcher` 管理回调注册/注销、快照与通配提交、专用线程池和异步循环桥接；不管理业务任务 |
| `listener.py`   | 单例、配置、幂等启动、IPC 接收、监听错误和资源关闭；组合调用 worker/dispatcher                   |
| `__init__.py`   | 导出 `FeishuEvent`、`FeishuEventListener`、`FeishuEventListenerError`、`feishu_event_listener`   |

依赖方向：worker、dispatcher 依赖 models，listener 组合 worker、dispatcher；不要把连接、回调注册表和单例生命周期重新集中到一个模块。

## 职责与接口

- `FeishuEventListener` 为线程安全的进程内单例，与导出的 `feishu_event_listener` 是同一对象。重复构造不重置状态或回调，创建实例不自动启动；导入不创建进程或请求网络。每个 Server 工作进程各自独立。
- `start_listener()` 从 `feishu_settings` 读取凭据并幂等启动一个 spawn 子进程和一个主进程接收线程；重复/并发调用不重复启动，不等待远程就绪。缺少配置可补齐后重试，运行后故障不自动重启。
- 子进程运行官方 SDK WebSocket，通过单向 Pipe 回传原始 JSON，不执行用户回调。主进程解析 `FeishuEvent` 后提交回调，立即读取下一条，不执行或等待业务函数。
- 支持 v1/v2 和 `*` 通配事件，保留可选 event_id 与完整 payload；同类型同一回调去重，类型回调先于通配回调提交。任务并发，不保证开始或完成顺序；共享事件不可由回调修改。无匹配回调的事件不重放。
- `register(event_type, callback, *, loop=None)` 支持同步函数、异步函数和异步可调用对象，自动捕获当前运行中循环，也可显式传入 loop 供其他线程注册。异步函数没有可用循环时注册报错。重复注册保留原循环；更换时先注销再注册。
- 同步回调提交给专用 `ThreadPoolExecutor`（默认 4 个工作线程），异步回调通过 `asyncio.run_coroutine_threadsafe` 提交给注册循环。普通包装函数返回 awaitable 时也只提交，不在工作线程等待结果。
- 按用户确定的边界，分发器不保存返回的 Future，不读取结果、不记录业务异常，不统计或限制任务积压；不恢复任务表、pending_count、上限或 done callback 管理。业务结果、追踪与异常处理归回调自身。本模块只负责接收和提交。
- `unregister` 返回是否移除，不取消已提交任务。单例不提供上下文管理接口，函数返回或局部变量离开作用域不关闭监听。
- `close(timeout=5.0)` 关闭监听进程、接收线程及新任务提交，可重复调用；不等待或取消已经提交的业务任务，线程池排队任务也继续执行。线程池以 `shutdown(wait=False, cancel_futures=False)` 停止新提交，工作线程由标准库在已有任务结束后回收。关闭后单例不再启动。异步路径用 `asyncio.to_thread` 隔离监听资源关闭等待；普通脚本须在 **main** 保护内启动。
- `error` / `raise_if_failed` 暴露监听进程、IPC 及接收线程内的回调提交失败，任务内部异常不转为监听器故障。异步函数的目标循环停止/关闭时，接收线程提交失败会记录监听错误，不另建循环；同步包装函数返回 awaitable 后的提交发生在线程池中，该路径失败不会被接收线程记录。监听错误日志不输出正文、凭据或 SDK 原始错误文本。`is_alive` 仅表示本地存活。
- 飞书订阅和权限由应用侧配置，本地注册不更改远程配置。本模块不自行接入生命周期；项目由 `app/main.py` 的 lifespan 调用 `event/listener.py:start_feishu_events()` 注册回调并启动监听，退出时在 finally 中通过 asyncio.to_thread 调用 cancel_feishu_events() 关闭监听器；Agent 调用位于上层 event/message/reply.py，本模块不承担 Agent 或索引编排。

## 方案与 SDK 边界

- 目标：独立进程监听，单例幂等启动，主进程随时增删回调；业务执行交给 Server 循环/线程池。
- 选定方案：模型、子进程、回调提交、单例生命周期分为四个模块。保留接收/提交，不承担业务任务管理，无需新增依赖。
- 原因：业务自行使用 Langfuse 等追踪，不需要分发器管理 Future、结果、业务异常或关闭取消。SDK 公开注册器没有通配接口，worker 局部覆写 `EventDispatcherHandler._do_without_validation`；升级时须核对签名与调用位置，不用于 HTTP Webhook 或需要同步业务响应的卡片交互。
- 实现状态：本地实现已接入应用生命周期，当前仓库没有专门测试，真实订阅、权限、连通性、回执时限或重连均未验证。转发 handler 在 Pipe 交付后返回给 SDK，不等待业务完成；本模块不持久化、去重或重试业务任务。

## 验证

- 当前不存在 `tests/units/test_feishu_event.py`；已有 `tests/units/test_feishu.py` 仅覆盖读取 API 及共同客户端，不验证事件监听。
- `.venv/bin/pyright --pythonpath .venv/bin/python src/deal_pilot/feishu/event`。
- 后续测试应覆盖单例/幂等启动、spawn/IPC、动态注册/注销、Server 循环与线程池提交、监听错误与业务异常的区别、关闭行为及 SDK hook；使用模拟事件与 Mock SDK，避免连接真实飞书。
- 本轮仅核对源码和指令，未运行上述类型检查或真实服务验证；用法见 README.md。

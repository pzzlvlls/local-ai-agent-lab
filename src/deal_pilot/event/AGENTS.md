# 业务事件处理

## 职责与入口

- 本目录负责业务事件回调与注册，底层飞书连接、IPC 和并发分发由 `../feishu/event` 提供。
- `listener.py:HANDLERS` 当前仅注册 `im.message.receive_v1` → `message/message_handler.py:message_handler`；没有注册 `card.action.trigger` 业务回调。
- `start_feishu_events()` 由 FastAPI lifespan 在 Server 事件循环内 await：先注册回调以捕获该循环，再调用单例的 `start_listener()`；不等待远程连接就绪。
- `cancel_feishu_events()` 同步关闭整个单例监听器；异步调用方通过 `asyncio.to_thread` 隔离关闭等待。关闭后不能重新启动，不等待或取消已提交的业务回调。
- `__init__.py` 为空；导入本目录不启动监听，实际入口见 `../app/main.py`。

## 当前消息行为与限制

- `message` 子目录负责接收消息解析、卡片结构和流式回复，具体契约见 `message/AGENTS.md`；旧的 `event/message_handler.py` 已迁入该目录。
- 当前解析发送者 open_id 和文本，由 reply 调用 main_agent，并向发送者单聊投递状态和正文流式更新的卡片；独立读取模型流，每隔约 200 毫秒合并刷新最新快照，结束前提交最终内容。即使收到群消息，也不向原群发送或回复原消息。
- 当前未过滤消息/聊天/发送者类型，无事件去重、自动重试或业务异常记录；回调内部失败不会由底层分发器作为监听故障报告。
- 已通过 utils/run_agent 接入 main_agent，可信长连接事件的发送者 open_id 作为 user_id 签发 JWT；固定用户/Agent 线程和排队由运行函数处理。不建立额外用户映射表，不自动运行索引；可用工具与子 Agent 仍由远程 AgentSpec 决定。

## 设计与修改约束

- 目标：将飞书消息接入服务生命周期并验证业务回调调用路径。选定方案：集中注册表加 `message` 子目录中的 Agent 流式卡片回复，复用已有监听器、run_agent 与 Card。原因：业务处理与 SDK 连接分离，不增加依赖。实现状态：源码已接入，reply 编排有本地 Mock 测试，未进行真实服务验证。
- 新事件在 HANDLERS 中显式注册；飞书远程订阅和权限需另行配置，本地注册不自动配置远程应用。
- 保持业务处理在本目录；同步 SDK 调用的线程隔离由 API 层负责，不在 Server 循环中直接调用阻塞 SDK。
- 本目录事件回调本身不经过 LangGraph HTTP 认证；信任官方长连接交付的发送者身份，再签发 JWT 请求 Agent Server；不得把消息正文的身份字段作为认证依据。

## 验证

- tests/units/test_message_reply.py 通过 Mock Card 和 run_agent 覆盖 reply 编排；消息解析、飞书监听和生命周期仍无专门测试。
- 后续本地测试应替换监听器与 Card，核对注册、启停、单聊目标、累计文本更新、收尾及异常行为，避免连接真实飞书或发送消息。
- 本轮进行了回复编排的本地测试与类型检查；真实订阅、消息收发、Server 生命周期及关闭时的任务行为仍未验证。

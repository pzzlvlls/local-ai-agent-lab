# 业务事件处理

## 职责与入口

- 本目录负责业务事件回调与注册，底层飞书连接、IPC 和并发分发由 `../feishu/event` 提供。
- `listener.py:HANDLERS` 当前仅注册 `im.message.receive_v1` → `message_handler`。
- `start_feishu_events()` 由 FastAPI lifespan 在 Server 事件循环内 await：先注册回调以捕获该循环，再调用单例的 `start_listener()`；不等待远程连接就绪。
- `cancel_feishu_events()` 同步关闭整个单例监听器；异步调用方通过 `asyncio.to_thread` 隔离关闭等待。关闭后不能重新启动，不等待或取消已提交的业务回调。
- `__init__.py` 为空；导入本目录不启动监听，实际入口见 `../app/main.py`。

## 当前消息行为与限制

- `message_handler(event: FeishuEvent)` 直接读取 `event.payload["event"]["sender"]["sender_id"]["open_id"]` 和消息 `content`，将 content 作为 JSON 解析并提取 `text`，然后 await `MessageAPI().send_text(open_id, text)`。
- 这是应用身份的文本回显，发送目标是发送者的 open_id；没有使用原消息 chat_id 或回复接口，即使收到群消息也按用户单聊发送。
- 当前未检查 message_type、chat_type 或发送者类型；缺字段、非文本内容、非法 JSON 与空白文本可能报错。未实现事件去重，也未传入发送 uuid；重复投递可能重复发送。
- 当前回调没有异常捕获、业务日志或追踪；底层分发器也不持有 Future 或读取业务结果，不能将回调失败视为已记录、已重试或监听器故障。
- 未接入 Agent、RAG、索引、会话管理或飞书用户到认证用户的映射。收到 open_id 不代表取得项目用户身份，不能据此选择用户沙箱或对象前缀。

## 设计与修改约束

- 目标：将飞书消息接入服务生命周期并验证业务回调调用路径。选定方案：集中注册表加异步文本回显，复用已有监听器与 MessageAPI。原因：业务处理与 SDK 连接分离，不增加依赖。实现状态：源码已接入，暂无专门测试或真实服务验证。
- 新事件在 HANDLERS 中显式注册；飞书远程订阅和权限需另行配置，本地注册不自动配置远程应用。
- 保持业务处理在本目录；同步 SDK 调用的线程隔离由 API 层负责，不在 Server 循环中直接调用阻塞 SDK。
- 本目录事件回调不经过 LangGraph HTTP 认证；后续接入 Agent 或用户资源时必须明确身份与权限边界。

## 验证

- 当前 `tests/units` 没有业务回调、消息发送或飞书监听的专门测试；已有飞书读取测试不覆盖此链路。
- 后续本地测试应替换监听器与 MessageAPI，核对注册、启停、文本回显目标及异常行为，避免连接真实飞书或发送消息。
- 本轮只做源码、路径和指令一致性检查；真实订阅、消息收发、Server 生命周期及关闭时的任务行为仍未验证。

# 飞书消息业务

## 文件职责与调用链

- 上层 `../listener.py` 注册 `im.message.receive_v1`，调用 `message_handler.py:message_handler`；本目录不启动监听或配置远程订阅。
- `message_handler.py` 从原始事件读取发送者 `sender_id.open_id` 和消息 `content`，解析 JSON 的 `text` 后 await `reply(open_id, text)`。
- `card_schema.py` 定义 `STATUS_ID = "status"`、`CONTENT_ID = "answer"` 和 `create_card_json(*, content="")`：JSON 2.0、fill 宽度、16px 内边距；初始为灰色小字号“正在处理…”状态行，经分隔线连接正常字号空 Markdown 正文（以空格占位），无操作区。`EXAMPLE_CONTENT` 仅供显式传入 content 预览，不发送给真实用户；组件 ID 必须与更新目标一致。
- `status.py` 直接复用 `utils/run_agent.py` 中的 `AgentStatus(StrEnum)`，不再定义 Literal 别名或另一份状态枚举。普通类 `CardStatus(status_type: AgentStatus, payload=None)` 保存状态类型和浅拷贝的载荷（默认独立空字典），通过 `get_text()` 的固定模板生成展示文本，无需传入文案。调用工具读取 `tool_name`，失败读取 `reason`；仅展示去除首尾空白后的非空字符串，缺失或类型不符时使用通用状态文案。调用方应传入适合用户阅读的原因，其他载荷字段不自动展示。卡片配置和回复过程共用此类生成状态文案。
- `reply.py:reply(receive_id, receive_text)` 创建并单聊投递 Card，独立读取任务持续消费 `run_agent("main_agent", receive_text, user_id=receive_id)`，只保留最新 AgentOutput 快照；主任务每隔 `CARD_UPDATE_INTERVAL = 0.2` 秒或读取结束时串行刷新卡片，不积压中间版本。使用 CardStatus 显示状态、工具名及失败原因，保持灰色字体；短暂的中间状态可能被合并。正文和状态均使用 `Card.patch_element(element_id, {"content": ...})` 更新组件属性，不调用 `stream_text`；只更新变化的内容，正文直接替换，不能再次拼接；空正文用空格清空显示。一次刷新固定同一份快照，先正文后状态；正常结束时再提交最新完整快照，最后 await finish。
- `__init__.py` 为空，没有导入时执行逻辑。旧入口 `event/message_handler.py` 已移除。

## 当前边界与修改约束

- 发送对象是发送者 open_id，不使用原消息 chat_id/message_id；函数名 reply 不代表调用飞书的消息回复接口。当前无卡片交互处理器或按钮/表单业务。
- 消息类型、聊天类型、发送者类型均未过滤；字段缺失、非文本消息、非法 JSON 会直接报错。没有事件去重或发送 uuid，重复事件可能生成多张卡片。
- 教学实现使用一个读取任务与一个串行刷新循环，仅保留一层 try/finally。正常路径 await reader 传播读取异常；finally 取消并等待读取任务退出，再依次 await stream.aclose()、card.finish()，避免关闭仍在运行的生成器或遗留后台读取。Agent 返回 FAILED 时照常展示；其他异常和取消直接传播，不追加通用失败提示。不使用 aclosing/suppress 或嵌套异常兜底。收尾若自身抛错仍可能中断后续语句或覆盖原异常，不保证远端卡片收尾成功。
- 当前无业务日志、自动重试、消息去重或业务持久化。底层分发器不读取业务任务结果，不能假设抛出的失败已记录。关闭生成器仅断开消费，run_agent 的 on_disconnect=continue 意味着已提交的 Server Run 可能继续执行。
- 业务编排留在本目录，SDK 请求和序号/锁管理复用 `feishu/api`。可信飞书长连接事件中的发送者 open_id 直接作为项目 user_id，由 run_agent 签发 JWT，Server 验签后用于线程及资源隔离；不使用消息正文提供的用户 ID，不建立额外用户映射表。reply 不是可接受任意外部用户 ID 的公开接口。
- 目标：用真实 Agent 回答替换固定卡片演示。选定方案：默认主入口 main_agent，复用渠道无关的 AgentOutput 和 CardStatus/Card。原因：状态、正文累计、身份签发及队列逻辑已有统一实现。实现状态：本地 Mock 业务测试通过，未验证真实飞书与 Agent Server 联调；需要有效的飞书凭据及 AGENT_SERVER_URL/AGENT_TOKEN_SECRET。

## 验证

- `tests/units/test_message_reply.py` Mock Card 与 run_agent，验证目标 Agent/文本/OpenID、空初始卡片、突发片段合并、慢卡片请求不阻塞流读取、周期状态刷新、跨生成正文替换、清空正文、最终提交顺序、失败/取消及收尾；`test_run_agent.py` 覆盖 SDK 输出适配和 CardStatus 文案。未发送真实消息，未验证真实订阅、卡片渲染速度或服务生命周期；消息事件解析仍无专门测试。

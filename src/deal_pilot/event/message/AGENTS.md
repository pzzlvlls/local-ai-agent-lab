# 飞书消息业务

## 文件职责与调用链

- 上层 `../listener.py` 注册 `im.message.receive_v1`，调用 `message_handler.py:message_handler`；本目录不启动监听或配置远程订阅。
- `message_handler.py` 从原始事件读取发送者 `sender_id.open_id` 和消息 `content`，解析 JSON 的 `text` 后 await `reply(open_id, text)`。
- `card_schema.py` 定义 `CONTENT_ID = "answer"` 和 `create_card_json()`：JSON 2.0、fill 宽度、单个 Markdown 组件，初始内容为“正在思考...”。组件 ID 必须与更新目标一致。
- `reply.py:reply(receive_id, receive_text)` 创建并单聊投递 Card，依次等待 1 秒、累加三个固定片段并 await `stream_text(CONTENT_ID, text)`，最后 await `finish()`。`receive_text` 当前未使用，输出不是 Agent 生成或文本回显。
- `__init__.py` 为空，没有导入时执行逻辑。旧入口 `event/message_handler.py` 已移除。

## 当前边界与修改约束

- 发送对象是发送者 open_id，不使用原消息 chat_id/message_id；函数名 reply 不代表调用飞书的消息回复接口。当前无卡片交互处理器或按钮/表单业务。
- 消息类型、聊天类型、发送者类型均未过滤；字段缺失、非文本消息、非法 JSON 会直接报错。没有事件去重或发送 uuid，重复事件可能生成多张卡片。
- 创建成功后的流式循环没有 try/finally；更新失败或取消会中断，不能保证执行 finish。Card 工厂的投递失败清理与这里的业务流式收尾是不同边界。
- 当前无业务日志、追踪、异常捕获、自动重试或持久化。底层分发器不读取业务任务结果，不能假设失败已记录。
- 业务编排留在本目录，SDK 请求和序号/锁管理复用 `feishu/api`；更新传累计全文，收尾必须 await。不得把 open_id 当作项目认证用户身份。

## 验证

- 当前没有本目录专门测试；`tests/units/test_feishu.py` 的读取测试不覆盖此链路。
- 后续本地测试可替换 Card 工厂和更新方法、时间等待，检查解析、单聊目标、累计全文、调用顺序及异常/取消边界，避免真实投递。
- 本轮只核对源码与指令；真实订阅、消息投递、卡片渲染及服务生命周期未验证。

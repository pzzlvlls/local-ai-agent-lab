# Agent 中间件

## 职责与入口

`turn_summary.py` 提供 `@after_agent` 中间件，由 `MainAgentFactory.get_middlewares()` 挂载，生成状态字段 `turn_summary`。

## 当前状态契约

- 从 `state['messages']` 筛选，返回 `{'turn_summary': [{'role': msg.type, 'content': msg.content}, ...]}`；字段定义见 `agents/main_agent_state.py`。
- 当前每次根据所收到的全部 messages 重新生成列表，不是把新消息追加到旧 summary，也不是 LLM 摘要。
- HumanMessage 可见；字符串内容的 AIMessage 可见；列表内容的 AIMessage 在没有 `type=tool_use` 块时可见。
- ToolMessage 只有内容字符串以 `Returning structured response:` 开头时保留。不能把当前过滤描述为覆盖所有工具调用表示形式。
- 保留原始 content 的字符串或块列表，不擅自转换为纯文本或丢失结构；role 当前是消息类型名，不是重新映射的 HTTP 角色名。

## 修改与验证

- 新中间件明确触发阶段、读取字段和返回更新，在 Agent 工厂中注册；增加状态字段同步对应 state schema。
- 修改筛选时用 Human、AI 字符串、AI 内容块、工具调用和 ToolMessage 样例验证，并检查重复执行不会意外叠加旧结果。
- 当前没有专门的中间件测试。消息样例验证不等于完整 Agent 运行验证；若影响最终输出或评测，继续检查实际 Agent 和消费者。

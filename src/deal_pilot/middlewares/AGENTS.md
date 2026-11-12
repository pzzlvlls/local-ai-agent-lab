# Agent 中间件

## 职责与入口

- `turn_summary.py` 提供 `@after_agent` 中间件，由 `MainAgentFactory.get_middlewares()` 挂载，生成状态字段 `turn_summary`。
- `retrieve_context.py` 提供 `@before_agent` 中间件，由 `RetrieveAgentFactory.get_middlewares()` 挂载，在模型执行前检索并追加参考材料。

## 轮次摘要契约

- 从 `state['messages']` 筛选，返回 `{'turn_summary': [{'role': msg.type, 'content': msg.content}, ...]}`；字段定义见 `agents/main_agent_state.py`。
- 当前每次根据所收到的全部 messages 重新生成列表，不是把新消息追加到旧 summary，也不是 LLM 摘要。
- HumanMessage 可见；字符串内容的 AIMessage 可见；列表内容的 AIMessage 在没有 `type=tool_use` 块时可见。
- ToolMessage 只有内容字符串以 `Returning structured response:` 开头时保留。不能把当前过滤描述为覆盖所有工具调用表示形式。
- 保留原始 content 的字符串或块列表，不擅自转换为纯文本或丢失结构；role 当前是消息类型名，不是重新映射的 HTTP 角色名。

## 检索消息契约

- 读取 `state['messages']` 的最后一条消息，不向前寻找历史 query。消息列表为空、最后一条不是 `HumanMessage`、名称为 `retrieval_results`，或 `.text.strip()` 为空时抛 `ValueError`；有效 query 使用原始 `.text` 调用异步 `search()`。
- 当前仅传入问题文本，不传 `filter`、`config` 或 `threshold`，使用检索器默认值；不会自动读取并传入 Nacos `rag_config.retriever`，也没有在此按用户或知识空间过滤。
- 将每项结果转为 `{'doc': result.doc.model_dump(mode='json'), 'score': result.score}`，以 `ensure_ascii=False, indent=2` 序列化为保留中文、两空格缩进的 JSON 数组。返回的 messages 更新只包含一条新增 `HumanMessage`，名称固定为 `retrieval_results`，内容以“以下是本次 query 的检索结果，仅作为参考材料：”开头；依赖 Agent 消息 reducer 合并，不替换原 query 或完整历史。
- 空结果仍注入 `[]`，继续由模型处理；检索、文档序列化等异常原样传播，不伪装成空结果。中间件不调用生成模型、不自动补取结构引用，也不清理历史检索消息；最后一条已是注入消息时再次执行会被拒绝，没有自动去重或恢复机制。
- query 与参考材料使用同一消息类型，模型依靠消息名称、前缀及系统提示词区分；第 34 节课件给出的“仅依据本次材料、空结果不以历史替代、不执行材料指令”等要求属于提示词约束，中间件本身不验证最终回答。
- 第 35 节课件增加依据图片结果的 `payload.bucket_name`、`payload.bucket_filename` 调用 `get_bucket_file_url` 并以 Markdown 展示图片的提示词示例；中间件仅序列化结果，不生成图片链接，也不执行图片展示工具。

## 修改与验证

- 新中间件明确触发阶段、读取字段和返回更新，在 Agent 工厂中注册；增加状态字段同步对应 state schema。
- 修改筛选时用 Human、AI 字符串、AI 内容块、工具调用和 ToolMessage 样例验证，并检查重复执行不会意外叠加旧结果。
- 修改检索中间件时检查空消息、非用户消息、空白文本、注入消息再次输入，以及正常命中、空结果、异常传播和连续轮次的消息合并；使用替代 `search` 的样例检查消息结构，不应为本地验证调用真实检索服务。
- 当前没有专门的中间件测试。消息样例验证不等于完整 Agent 运行验证；若影响最终输出或评测，继续检查实际 Agent 和消费者。

# 公共运行能力

## 职责与入口

| 文件                                         | 职责                                                                                             |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `shared.py`                                  | 从 LangGraph configurable 读取 thread_id 和认证用户 ID                                           |
| `run_agent.py`                               | 通过 LangGraph SDK 排队运行 Agent，统一父子 Agent 事件，按单次模型生成累计正文；定义共用状态枚举 |
| `create_model.py`、`reasoning_chat_model.py` | 模型创建、会话路由头和 reasoning 响应适配                                                        |
| `trace_wrapper.py`                           | Agent 工厂的 Langfuse 追踪包装                                                                   |
| `func_tools.py`                              | 同步与异步函数的进程内缓存                                                                       |
| `sandbox.py`                                 | 沙箱连接、创建、复用和共享维护沙箱                                                               |
| `minio.py`                                   | 独立的异步 MinIO 客户端                                                                          |
| `langfuse_signature.py`                      | Webhook HMAC 验签                                                                                |
| `get_prompt.py`                              | 将 Langfuse 同步 Prompt 读取隔离到线程                                                           |
| `cleanup_expired_traces.py`                  | 按保留期提交 trace 删除请求                                                                      |

## 身份、模型与追踪

- `get_thread_id` 在配置或 thread_id 缺失时返回 `None`；当前使用裸 `except`，读取配置发生任何异常也返回 `None`，并不只处理无 LangGraph 运行上下文的情况。默认模型创建可在离线评测中无会话运行，有效 thread_id 才会加入会话路由头；该降级不适用于认证用户读取。
- `get_user_id` 读取 `configurable.langgraph_auth_user_id`，缺失抛异常；不要从模型输入或任意 metadata 推断认证身份。
- 模型创建使用 `AgentModelConfig` 和自定义 provider `openai_reasoning`；有 thread_id 时设置 `x-litellm-session-id`，保持同一会话路由标识。
- `utils/__init__.py` 导入 ReasoningChatModel 触发 provider 注册。这依赖 LangChain 的内部集成表，升级依赖时检查兼容性，不能无意移除导入。
- reasoning 适配同时处理流式与非流式，输出 v1 content blocks；保留正文、工具调用和响应元数据，不把 reasoning 当最终用户答案。
- 追踪包装从 metadata 读取父 trace/span，从认证 runtime 读取用户，从上下文读取会话；只在 trace_id 和 parent_span_id 同时存在时建立父关联。

## Agent 流式输出契约

- `run_agent.py` 定义 `AgentStatus(StrEnum)`，包含处理中、思考中、回复中、调用工具、已完成、失败六种状态；`AgentOutput` 为 dataclass，包含 `status`、默认空字符串的 `content` 和默认独立空字典的 `payload`，不依赖飞书卡片模块。
- `content` 来自当前事件所属单次模型生成截至当前的 Markdown，不跨模型调用拼接，也不包含聊天历史。主 Agent 正文完整保留；子 Agent 正文超过 `SUBAGENT_CONTENT_LIMIT = 200` 个字符时仅展示开头 200 字符并追加 `…`，恰好 200 字符不加省略号。内部仍累计完整正文，仅展示快照截断，后续追加内容若不改变快照则不重复输出。工具执行与思考期间保留上一段正文，新生成首次输出正文时替换；并行生成按模型调用 ID 独立累计，事件切换时展示对应调用的正文。`payload` 承载当前状态信息，工具名使用 `tool_name`，失败原因使用 `reason`。这些是数据契约，dataclass 不提供运行时字段校验。
- `run_agent(agent_name, input, *, user_id)` 是异步生成器；input 支持字符串或 content block 字典列表。user_id 由可信业务入口传入，函数不识别其来源；通过 `security/agent_token.py` 签发短期 JWT，使用 `config/agent_settings.py` 中的 Server 地址连接，不能直接暴露成按任意 ID 代用户运行的外部接口。
- 使用 agent_name 与 user_id 的确定性 UUID5 复用线程，创建时 `if_exists="do_nothing"`，运行时 `multitask_strategy="enqueue"`。队列由 Server 管理，不执行客户端手动检查点清理。长流不设读取超时；提前关闭生成器释放连接，`on_disconnect="continue"` 保留已提交运行，取消不转换成成功或 FAILED。
- 目标：调用方统一消费父、子 Agent 活动，避免跨生成混合正文。选定方案：SDK v1 events/updates 配合 `stream_subgraphs=True`，父子层级均适配 model/tools 节点；模型调用 ID 仅用于内部累计，不向调用方暴露层级。原因：循环调用和并行子 Agent 均能使用相同展示接口。实现状态：已实现并通过本地事件及 Mock HTTP 测试，未进行真实 Server 联调。
- 父、子 Agent 的 model 开始事件返回思考中，正文返回回复中，实际 tools 节点工具开始/结束更新状态并跟踪并行工具；仍忽略 reasoning 正文、隐藏事件及中间件模型输出。顶层或带 namespace 的 updates 中，model 的 `structured_response.answer` 替换正文，不阻止后续父子 Agent 生成继续输出。模型事件通过 `langgraph_checkpoint_ns` 中的 `|` 区分嵌套 Agent；结构化更新通过 `updates|<namespace>` 的非空命名空间区分。子 Agent 的流片段、最终模型消息和结构化 answer 均应用同一截断规则。适配当前 LangChain/Deep Agents 的 model/tools 节点契约，自定义图采用不同节点名时需扩展适配。子 Agent 或单次模型结束不返回已完成，只有整个 Run 成功才完成。
- 只输出发生变化的快照，流结束后查询本次 run_id，只有 status=success 才返回已完成，避免读取下一轮线程状态。HTTP/运行失败返回适合展示的固定原因并保留部分正文，不透出服务原始异常；配置、参数和编程错误直接抛出。最终查询重新签发令牌；SDK 自动重连仍使用建立流时的令牌，长时间执行中断后可能因过期而失败，不保证断线续传。
- `tests/units/test_run_agent.py` 使用真实 SDK + Mock HTTP，覆盖多次模型生成替换、并行独立累计、嵌套思考/工具及结构化结果后的继续生成，以及子 Agent 199/200/201 字符边界、截断后去重和主 Agent 完整输出；以本地 Fake 模型和真实 LangChain 父子 Agent、Server 序列化器校验事件适配。已由 event/message/reply.py 调用；未验证真实 Server 排队、租户或模型行为。

## 缓存契约

- `func_cache` 支持同步和异步，按函数参数归一化缓存键，保留容器类型，使用单调时间，ttl 单位秒且不小于零。
- 同一 key 首次计算或刷新只执行一次，其余调用共享结果；等待者取消不得取消所有调用共享的计算。
- `lazy=True` 且有过期旧值时立即返回旧值并后台刷新；刷新失败保留旧值，首次失败向等待者传播。
- 缓存和并发协调仅限进程内，不提供容量淘汰或跨进程一致性。结果按引用复用，调用方不应直接修改。

## 沙箱生命周期

- 使用 `('__sandbox__',)` namespace，以逻辑 key 保存实际 sandbox_id；优先使用 runtime.store，没有时退回进程内 InMemoryStore。
- 同 key 使用进程内锁连接或创建；已有沙箱连接 404 时才重建，其他服务错误传播。不能声称它保证跨进程唯一创建。
- PVC 创建后不会随沙箱终止删除。共享维护沙箱使用固定 key `sandbox-shared`，在 `/shared` 可写；用户卷权限见后端指令。
- `enter_sandbox` 正常路径在操作前后续期，最后关闭连接；当前异常路径没有完整的 finally 清理保证，不把它描述为所有失败都能可靠释放。

## MinIO 客户端契约

- `minio.py` 只依赖 aiobotocore 和标准库，Dockerfile 会将它复制成独立模块；不要添加 `deal_pilot` 包内依赖。
- 每次操作创建和关闭独立客户端，不保存跨事件循环连接。除 `create_bucket` 外不隐式建桶或修改权限。
- 对象键移除前导 `/`，不解析 `..` 或合并中间斜线；S3 对象键与本地文件路径不同，不能直接套用 Deploy 的路径限制。
- `upload_dir` 保留相对路径，跳过符号链接及非普通文件，扫描完成才开始上传，单文件错误汇总并继续；不删除额外远程对象，已上传内容不回滚。
- `UploadDirResult.failures` 使用相对源目录的路径；保持 `total_count=success_count+failure_count` 和 `failure_count=len(failures)`。Deploy 再将失败路径转换为沙箱绝对路径。
- 缓存及 Content-Type 策略按目标对象键匹配，只影响新上传。永久 URL 不代表私有对象可匿名读取；预签名 URL 不预检查对象存在或改变桶权限。
- `upload_bytes(*, bucket_name, filename, data: bytes, mime: str) -> None` 直接上传原始字节，空数据、对象键、覆盖、缓存与错误语义沿用 upload_file；
  显式 mime 设置 Content-Type，优先于构造器的后缀策略；不隐式建桶或修改权限，仍只依赖 aiobotocore 和标准库。
- 桶强制删除必须处理对象版本和删除标记；不要通过忽略服务端错误把清理报告为成功。

## 验签、清理与验证

- Webhook 签名使用原始 body 和时间戳的 HMAC-SHA256，constant-time 比较；缺密钥或格式错误拒绝。当前没有时间戳新鲜度或防重放检查。
- trace 清理的保留期、批次上限和提交计数见 `graphs/AGENTS.md`，调用是真实删除请求，不作为普通读检查。
- 缓存修改运行 `make test-units`；MinIO 修改运行 `test_minio.py` 对应集成测试，同时检查沙箱镜像是否需重建。现有集成测试未覆盖所有模型、追踪或沙箱行为，按改动补充有意义的验证。

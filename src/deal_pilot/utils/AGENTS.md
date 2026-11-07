# 公共运行能力

## 职责与入口

| 文件 | 职责 |
| --- | --- |
| `shared.py` | 从 LangGraph configurable 读取 thread_id 和认证用户 ID |
| `create_model.py`、`reasoning_chat_model.py` | 模型创建、会话路由头和 reasoning 响应适配 |
| `trace_wrapper.py` | Agent 工厂的 Langfuse 追踪包装 |
| `func_tools.py` | 同步与异步函数的进程内缓存 |
| `sandbox.py` | 沙箱连接、创建、复用和共享维护沙箱 |
| `minio.py` | 独立的异步 MinIO 客户端 |
| `langfuse_signature.py` | Webhook HMAC 验签 |
| `get_prompt.py` | 将 Langfuse 同步 Prompt 读取隔离到线程 |
| `cleanup_expired_traces.py` | 按保留期提交 trace 删除请求 |
| `mock_user.py` | 本地模拟身份数据，不能当作生产用户中心 |

## 身份、模型与追踪

- `get_user_id` 读取 `configurable.langgraph_auth_user_id`，缺失抛异常；不要从模型输入或任意 metadata 推断认证身份。
- 模型创建使用 `AgentModelConfig` 和自定义 provider `openai_reasoning`；有 thread_id 时设置 `x-litellm-session-id`，保持同一会话路由标识。
- `utils/__init__.py` 导入 ReasoningChatModel 触发 provider 注册。这依赖 LangChain 的内部集成表，升级依赖时检查兼容性，不能无意移除导入。
- reasoning 适配同时处理流式与非流式，输出 v1 content blocks；保留正文、工具调用和响应元数据，不把 reasoning 当最终用户答案。
- 追踪包装从 metadata 读取父 trace/span，从认证 runtime 读取用户，从上下文读取会话；只在 trace_id 和 parent_span_id 同时存在时建立父关联。

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
- 桶强制删除必须处理对象版本和删除标记；不要通过忽略服务端错误把清理报告为成功。

## 验签、清理与验证

- Webhook 签名使用原始 body 和时间戳的 HMAC-SHA256，constant-time 比较；缺密钥或格式错误拒绝。当前没有时间戳新鲜度或防重放检查。
- trace 清理的保留期、批次上限和提交计数见 `graphs/AGENTS.md`，调用是真实删除请求，不作为普通读检查。
- 缓存修改运行 `make test-units`；MinIO 修改运行 `test_minio.py` 对应集成测试，同时检查沙箱镜像是否需重建。现有集成测试未覆盖所有模型、追踪或沙箱行为，按改动补充有意义的验证。

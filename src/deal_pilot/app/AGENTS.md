# HTTP 应用与 Webhook

## 职责与入口

- `main.py:app` 是 `langgraph.json` 挂载的 FastAPI 应用，负责注册路由及飞书监听的 lifespan。
- `alert_webhook.py` 接收 `/api/webhooks/langfuse/alerts`。
- `experiment_webhook.py` 接收 `/api/webhooks/langfuse/experiments`，通过 BackgroundTasks 启动指定数据集评测。

## 飞书监听生命周期

- `lifespan` 在 yield 前 await `event/listener.py:start_feishu_events()`，注册业务回调并启动监听；当前没有启用开关，缺少 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 会抛出配置错误并阻止启动。启动只确认本地监听资源创建，不等待远程连接就绪。
- yield 所在的 try/finally 退出时，通过 `await asyncio.to_thread(cancel_feishu_events)` 关闭整个监听器；该调用不只是注销回调，也不等待或取消已提交的业务任务。启动调用位于 try 之前，启动异常不会进入此 finally。
- 单例按进程生效，关闭后不能重新启动；不要假设同进程多次 lifespan 可以重用已关闭的监听器。应用当前没有轮询 `error` / `raise_if_failed` 或将监听故障接入健康检查。
- 业务处理见 `../event/AGENTS.md`，底层长连接与分发见 `../feishu/event/AGENTS.md`；此处不直接解析飞书事件，也不新增飞书 HTTP Webhook 路由。

## 核心约束

- 当前 `langgraph.json` 设置 `enable_custom_route_auth=false`，不能假设自定义路由自动受 LangGraph 认证保护。现有 Webhook 自行验签。
- 必须先使用对应的 Langfuse Webhook secret 验证原始请求体，再解析或启动任务；签名无效返回 401，不执行后续动作。
- 告警与实验使用不同密钥。验签逻辑集中在 `utils/langfuse_signature.py`，不要在路由中复制另一套算法。
- 实验读取 `datasetName`，后台任务提交成功后返回 202；这不表示实验已完成或评分已达标。
- 后台实验按 `benchmarks/experiment.py` 的注册表选择配置，当前仅支持 `retrieve`；未注册的数据集会在后台执行时报错，路由没有提前校验配置。Webhook 只调用实验入口，不执行 `tests/benchmarks/test_benchmark.py` 的逐项阈值回归判定。
- 告警当前验签、读取事件后返回 200，通知逻辑尚未实现。修改说明不能声称已接通 SMS 或邮件。
- BackgroundTasks 是当前进程内任务机制，没有持久队列、去重或失败自动重试的保证。

## 修改与验证

- 新路由在 `main.py` 显式注册；输入 schema、状态码或任务触发方式变化时检查 Webhook 调用方。
- 验证有效签名、无密钥、错误签名和错误输入；检查无效请求不会触发实验。
- 路由测试可替换后台实验函数，避免意外调用模型；真实 Webhook 与实验验证需要对应外部服务。当前没有专门的路由测试，不把其他测试的通过当作路由验证。
- 当前也没有 lifespan 专门测试；测试应用生命周期时应替换飞书启停函数，避免启动真实子进程、连接飞书或触发消息/卡片发送。本轮仅核对源码与指令，未启动服务验证。

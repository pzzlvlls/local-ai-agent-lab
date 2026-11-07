# HTTP 应用与 Webhook

## 职责与入口

- `main.py:app` 是 `langgraph.json` 挂载的 FastAPI 应用，负责注册路由。
- `alert_webhook.py` 接收 `/api/webhooks/langfuse/alerts`。
- `experiment_webhook.py` 接收 `/api/webhooks/langfuse/experiments`，通过 BackgroundTasks 启动指定数据集评测。

## 核心约束

- 当前 `langgraph.json` 设置 `enable_custom_route_auth=false`，不能假设自定义路由自动受 LangGraph 认证保护。现有 Webhook 自行验签。
- 必须先使用对应的 Langfuse Webhook secret 验证原始请求体，再解析或启动任务；签名无效返回 401，不执行后续动作。
- 告警与实验使用不同密钥。验签逻辑集中在 `utils/langfuse_signature.py`，不要在路由中复制另一套算法。
- 实验读取 `datasetName`，后台任务提交成功后返回 202；这不表示实验已完成或评分已达标。
- 告警当前验签、读取事件后返回 200，通知逻辑尚未实现。修改说明不能声称已接通 SMS 或邮件。
- BackgroundTasks 是当前进程内任务机制，没有持久队列、去重或失败自动重试的保证。

## 修改与验证

- 新路由在 `main.py` 显式注册；输入 schema、状态码或任务触发方式变化时检查 Webhook 调用方。
- 验证有效签名、无密钥、错误签名和错误输入；检查无效请求不会触发实验。
- 路由测试可替换后台实验函数，避免意外调用模型；真实 Webhook 与实验验证需要对应外部服务。当前没有专门的路由测试，不把其他测试的通过当作路由验证。

# 环境与配置模型

## 职责与分工

- `base_settings.py:BaseSettingsWithEnv` 从 `.env` 和进程环境读取配置，忽略额外字段。
- 各 `*_settings.py` 定义并实例化服务连接配置；`nacos` 子目录读取与组装远程行为资源，详细规则见其指令文件。
- Settings 负责地址和凭据等运行配置；AgentSpec、Prompt、Skill、MCP、`sandbox_config` 及 `rag_config` 由 Nacos 提供，不混淆两层职责。

## 配置契约

| Settings          | 环境变量前缀    |
| ----------------- | --------------- |
| OpenAISettings    | `OPENAI_`       |
| NacosSettings     | `NACOS_`        |
| SandboxSettings   | `OPEN_SANDBOX_` |
| MinioSettings     | `MINIO_`        |
| LangfuseSettings  | `LANGFUSE_`     |
| BenchMarkSettings | `BENCHMARK_`    |
| TavilySettings    | `TAVILY_`       |
| FeishuSettings    | `FEISHU_`       |
| MilvusSettings    | `MILVUS_`       |

- Settings 实例在模块导入时创建；修改环境后不会自动重建已有实例。验证配置时先准备环境再导入。
- `.env` 路径相对于运行目录，命令应从项目根目录执行。
- `NacosSettings.server_address` 移除末尾斜线；MinIO endpoint 不含协议，TLS 由 `secure` 控制，API 地址与控制台地址不能混用。
- MinIO 宿主地址用于客户端和交付 URL；`endpoint_in_sandbox` 用于沙箱内直传，两者不要求相同。
- 许多连接参数默认空字符串；默认值不表示已配置或已连通。需要参数的调用方应给出明确错误。
- 飞书读取、消息发送和事件监听共用 `feishu_settings.app_id/app_secret`；为空时 API 调用或监听启动抛出 `FeishuConfigurationError`，导入不检查连接、不发起网络请求。FastAPI lifespan 当前无条件启动监听，因此服务启动需要配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`；本地监听启动成功不代表远程连接或订阅就绪。
- `milvus_settings.uri` 默认 `http://127.0.0.1:19530`，`db_name` 默认 `deal_pilot`，分别对应 `MILVUS_URI`、`MILVUS_DB_NAME`。存储初始化负责创建缺失数据库；Settings 本身不连接或创建数据库。稠密索引配置及新集合的向量维度由 Nacos `rag_config` 提供。

## 修改与验证

- 新配置沿用服务前缀，补充类型和必要的校验，同步 `.env.example`、消费者与相关说明；不要写入实际凭据。
- 改名、改默认值或改单位时核对所有调用方。Nacos TTL 的单位为秒；Langfuse trace retention 的单位为天。
- 用临时环境验证解析、默认值和非法值，不修改真实 `.env`。真实连通性需要单独验证，Settings 构造成功不代表服务可用。

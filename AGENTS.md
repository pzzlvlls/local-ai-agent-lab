# Deal Pilot 开发指令

## 适用范围与阅读顺序

- 本文件适用于整个项目。修改源码前，沿目标路径逐级阅读 `src/AGENTS.md`、`src/deal_pilot/AGENTS.md` 和模块内的 `AGENTS.md`；子目录只补充局部规则。
- 文件名统一使用大写 `AGENTS.md`，不要同时创建 `Agents.md` 等大小写变体。

## 沟通与操作边界

- 当用户提问，或没有明确命令进行某种操作时，不改动工程的任何东西；回答问题或给出建议即可。可以按需进行无副作用的只读查看，不将讨论、询问或建议自动视为实施授权。
- 只有用户明确要求执行操作时，才在已授权范围内实施。不得仅因发现问题或认为某项修改有益，就自行修改代码、配置、依赖或指令文件，也不得执行会改变工程状态、数据或服务的命令。
- 保留已有修改，不顺手重构、提交或变更无关文件。下面的指令维护规则同样受此操作边界约束：只读讨论中发现指令过时，应告知用户并建议更新，不自动落盘。

## 项目定位与当前边界

- 当前项目是 Python Agent 服务：以 LangGraph Server 提供运行入口，以 Deep Agents 组装 Agent，以 Nacos 管理 AgentSpec、Prompt、Skill、MCP 与沙箱配置。
- Langfuse 用于追踪、离线评测和 Webhook；OpenSandbox 提供用户执行环境；MinIO 用于产物存储与交付；模型通过 OpenAI 兼容接口及自定义模型适配层调用。
- 当前 RAG 模块提供飞书标准树构建、到 Documents 的本地结构提取及进一步切片；`rag/store/feishu_doc` 提供 Milvus 初始化与缓存的 LangChain Milvus 对象，支持文档向量化写入和稠密/BM25 混合检索。`graphs/feishu_doc_index` 已编排目录分批、版本比较、构树、加载、切片、写入和旧版本清理，并注册为独立服务图；运行时显式调用，不在服务启动时自动入库，索引流程尚未接入 Agent。图片识图仍为占位，流程限制与验证边界见图模块指令。
- `retrieve_agent` 已注册为独立 Agent 服务入口：`retrieve_context` 在 Agent 执行前，读取 Nacos `rag_config.retriever`，以最后一条普通用户消息和该配置调用飞书检索器，将结果作为命名消息追加给模型。工厂使用 `ToolStrategy(RetrieveResponse)`，成功生成的结构化结果位于状态的 `structured_response`，包含 `status`、Markdown `answer`、`sources` 和 `gaps`。系统提示词仍由 Nacos 提供，第 34、35、36 节课件分别提供检索生成、图片展示和格式化输出提示词示例，不会自动加载。内置注册表已加入 `get_bucket_file_url`，可生成默认 1 小时的 MinIO GET 预签名链接；Agent 使用该工具仍需在远程 AgentSpec 中配置，不能据本地注册推断远程已启用。当前检索 Agent 未注册为主 Agent 的子 Agent；检索回答的质量回归入口见 `benchmarks`，图片展示仍无专门链路测试，本轮未进行真实服务联调。
- `benchmarks` 按 Langfuse 数据集名称选择评测配置，当前仅注册 `retrieve`，评测其结构化回答的来源精准率、来源召回率、回答正确性和完整性；LLM 评分 Prompt 优先读取 Nacos，空 Prompt 使用内置模板。回归报告逐项读取 `Evaluation.metadata.test.threshold` 判定，不再使用固定的总体相似度；评分口径与验证边界见 `src/deal_pilot/benchmarks/AGENTS.md` 和 `src/deal_pilot/benchmarks/evaluators/AGENTS.md`。第 37 节课件说明质量评估方法，`resource/评测数据集` 提供 CSV，不会自动导入 Langfuse。
- 本地 Compose 提供 Milvus Standalone `v3.0.2`，使用专用 `milvus-etcd`、`milvus-minio` 与三个 `milvus_standalone_*` 命名卷，不复用 Shared MinIO 或已有旧 Milvus 卷。存储初始化使用 PyMilvus，`get_store()` 使用 `langchain-milvus` 连接该服务；其锁定版本 0.4.0 在非 Windows 平台传递引入 `milvus-lite`，当前运行仍使用 Standalone，不使用本地 Lite 数据库。
- `feishu/api` 通过官方 `lark-oapi` SDK 实现应用身份的知识库目录、Docx 只读调用与图片下载；索引图已调用 WikiAPI 和 DocxAPI，尚未接入 Agent 工具，本地 Mock 测试不代表真实租户验证。
- 鉴权当前使用 `utils/mock_user.py` 中的模拟用户；告警 Webhook 已验签并接收事件，尚未实现短信或邮件通知。
- `graphs` 保存手工构建的普通 LangGraph 图，不存放通过 LangChain 或 Deep Agents 创建的 Agent 图；当前包含清理图和飞书文档索引图。调度计划由外部服务管理，代码中没有自动注册定时计划的逻辑。

## 架构与目录导航

| 路径                                      | 职责                                                                                                                                                                        |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/deal_pilot/agents`                   | Agent 工厂、主 Agent 状态、子 Agent 组装及独立检索 Agent                                                                                                                    |
| `src/deal_pilot/app`                      | FastAPI 自定义路由、Langfuse Webhook                                                                                                                                        |
| `src/deal_pilot/config`                   | 环境配置；`nacos` 子目录负责远程资源读取与同步                                                                                                                              |
| `src/deal_pilot/security`                 | LangGraph 身份认证与资源授权                                                                                                                                                |
| `src/deal_pilot/backends`                 | Deep Agents 后端到 OpenSandbox 的适配                                                                                                                                       |
| `src/deal_pilot/tools`                    | 模型可调用的工具及注册表                                                                                                                                                    |
| `src/deal_pilot/middlewares`              | 主 Agent 轮次摘要、检索 Agent 执行前的参考材料注入                                                                                                                          |
| `src/deal_pilot/utils`                    | 模型、追踪、缓存、存储、沙箱等公共能力                                                                                                                                      |
| `src/deal_pilot/benchmarks`               | 数据集与按名称选择的实验配置；`evaluators` 子目录负责 Agent 任务、来源指标及 LLM 回答评分                                                                                   |
| `src/deal_pilot/graphs`                   | 手工构建的普通 LangGraph 图及其入口                                                                                                                                         |
| `src/deal_pilot/graphs/feishu_doc_index`  | 飞书目录分批扇出与统计；单文档子图负责版本比较、解析切片、Milvus 写入和旧版本实体清理                                                                                       |
| `src/deal_pilot/feishu`                   | 官方 SDK 接入、知识空间/节点/Docx 读取、图片下载、分页与错误处理；Token 由 SDK 管理                                                                                         |
| `src/deal_pilot/rag/structure/feishu_doc` | 异步构树、原始关系校验、标题归组、内容及元数据提取、树形字典导出与还原；完整树构建后串行调用图片处理占位函数；提供 Data URL、私有图片上传及上下文辅助函数，尚未接入模型识图 |
| `src/deal_pilot/rag/loader/feishu_doc`    | 标准树到 LangChain Documents 的本地结构提取；父子占位引用、Markdown 正文、HTML 表格与合并校验，不按长度切片                                                                 |
| `src/deal_pilot/rag/splitter/feishu_doc`  | 结构 Documents 的本地进一步切片；图片/代码整体保留，表格首行表头加单行，页面/章节按段落、句子和长度切分，保护占位符并保留目标 overlap                                       |
| `src/deal_pilot/rag/store/feishu_doc`     | Milvus Schema 安全原地同步、数据库/集合初始化、稠密索引重建及历史知识库标题回填；缓存返回支持文档写入和稠密/BM25 混合检索的 LangChain Milvus 对象                           |
| `src/deal_pilot/rag/retriever/feishu_doc` | 基于缓存存储对象进行异步混合检索、重排及分数过滤，返回 Document 与 score；由检索中间件调用                                                                                  |
| `resource/feishu_doc_index`               | 索引流水线教学骨架；主图节点为省略号、子图业务节点为占位，不是独立运行实现                                                                                                  |
| `resource/评测数据集`                     | 企业知识库基础问答 CSV；含问题、参考答案和相关文档标注，需单独导入远程数据集                                                                                                |
| `tests/units`                             | 函数缓存、飞书 Mock、文档构树、Documents 结构提取、切片、Milvus Schema 预检、标题回填及 Benchmark 阈值报告单元测试                                                          |
| `tests/intergrations`                     | MinIO、Deploy 与 Milvus Schema 隔离集成测试，各自通过环境变量启用；保留现有目录拼写                                                                                         |
| `tests/benchmarks`                        | 依赖真实 Agent、Langfuse、Nacos 和模型的质量回归；按每项评分返回的阈值生成报告                                                                                              |
| `docker/sandbox/Dockerfile`               | 沙箱镜像，包含部署所需的上传工具                                                                                                                                            |

运行入口由 `langgraph.json` 定义：`main_agent` 指向追踪包装后的主 Agent 工厂，`retrieve_agent` 指向 `deal_pilot.agents.retrieve_agent:factory_with_trace`，`delete_old_trace` 指向清理图，`feishu_doc_index` 指向 `deal_pilot.graphs.feishu_doc_index.graph:factory_with_trace`；鉴权入口是 `security.auth:auth`，自定义 HTTP 应用是 `app.main:app`。调整导出名称或模块路径时同步检查该文件。

## 环境与常用命令

- 从项目根目录执行命令。Python 版本按 `pyproject.toml` 固定为 `3.13.11`，依赖使用 uv 管理，安装用 `uv sync`。
- 配置项见 `.env.example` 和各 Settings 类。不要将实际 `.env` 内容、访问密钥或令牌写入文档、日志和测试输出。

| 命令                                                                                                                               | 用途与前提                                                                                                                   |
| ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `make dev`                                                                                                                         | 启动 LangGraph 开发服务，端口 80；按配置依赖外部服务                                                                         |
| `make debug`                                                                                                                       | 开发服务另开调试端口 5678                                                                                                    |
| `docker compose up -d --wait milvus`                                                                                               | 仅启动 Milvus Standalone 及其专用 etcd、MinIO，并等待健康检查                                                                |
| `make build TAG=<镜像标签>`                                                                                                        | 构建 Agent 服务镜像                                                                                                          |
| `make test-units`                                                                                                                  | 本地缓存、飞书 Mock、构树、Documents 提取、切片、Schema 预检、标题回填及 Benchmark 报告单元测试，无需启动外部服务            |
| `MINIO_INTEGRATION=1 uv run pytest -q tests/intergrations/test_minio.py`                                                           | 仅验证真实 MinIO，使用随机测试桶                                                                                             |
| `MINIO_INTEGRATION=1 DEPLOY_INTEGRATION=1 DEPLOY_SANDBOX_IMAGE=<已准备的镜像> uv run pytest -q tests/intergrations/test_deploy.py` | 真实 MinIO 与 OpenSandbox 部署验证                                                                                           |
| `make test-integrations`                                                                                                           | 当前 Makefile 同时启用 MinIO 和 Deploy，并固定镜像为 `opensandbox-python-node:1.0`；Milvus 测试需另设 `MILVUS_INTEGRATION=1` |
| `MILVUS_INTEGRATION=1 .venv/bin/pytest -q tests/intergrations/test_feishu_doc_schema.py`                                           | 真实 Milvus 随机隔离库的 Schema 同步、历史标题局部更新及检索验证；Nacos/飞书使用 Mock                                        |
| `make test-benchmark DS=<数据集名称>`                                                                                              | 对已注册配置的真实数据集评测，当前为 `DS=retrieve`；会调用 Agent、Nacos 和模型并记录实验                                     |
| `make test-benchmark DS=all`                                                                                                       | 遍历 Langfuse 全部数据集；遇到未注册配置的数据集会报错，注意调用量和费用                                                     |

`make docker-recreate` 会强制重建 Compose 容器，不是普通测试的准备步骤。集成测试不会替你启动服务或构建镜像；详细测试契约见 `tests/intergrations/README.md`，若其命令说明与 Makefile 不一致，以实际 Makefile 和测试启用条件为准。

Milvus SDK 端口为 `127.0.0.1:19530`，健康检查及 WebUI 为 `127.0.0.1:9091`；专用 MinIO API / 控制台为 `127.0.0.1:19000` / `127.0.0.1:19001`。Milvus 容器设置 `TZ=Asia/Shanghai` 使用东八区；WebUI 日期显示需另行核对，不能仅凭容器时区推断。Compose 将 `docker/milvus/user.yaml` 只读挂载到 `/milvus/configs/user.yaml`；该文件为 DashScope 模型重排预留 `qwen_rerank` 凭据和 `ali.url`，调用前需填写真实 Key 和完整 Endpoint，真实凭据不得提交。当前是未启用 Milvus 身份认证的本地开发部署，MinIO 凭据不用于 Milvus 登录。部署修改检查 Compose 配置、服务健康和实际 SDK 读写；不要用 `down -v` 清理测试。新命名卷利用镜像目录的 UID/GID `999:999` 初始化权限，恢复外部数据卷后需另行核对所有权。

## 全局修改与验证要求

- 实现功能前先检查是否有适用的公开库，优先使用成熟、知名的库，尤其是官方库或官方 SDK；不要仅为了减少依赖而自行重写这些库已有的能力。确有不适用之处时，说明具体原因。需要新增安装库时，先向用户说明库名、用途和选择理由，获得用户明确许可后再添加依赖并安装；同一会话中已获许可的安装不重复询问，已有依赖可直接复用。
- 遵循局部现有风格，新接口补充准确的类型标注；不要为了统一排版扩大修改范围。项目尚未定义统一 formatter/linter 配置，不虚构检查命令。
- 异步路径使用异步客户端；同步 SDK 的阻塞调用需要适当隔离，例如 `asyncio.to_thread`。不要在已有事件循环内调用 `asyncio.run`。
- 用户身份来自认证上下文；不得通过模型可填写的参数选择其他用户的沙箱或对象前缀。
- 模型可修复的参数错误与认证、配置、服务错误应保持区分；不要捕获所有异常后伪装成功。
- 按改动选择验证：纯文档检查路径、命令与事实；缓存改动运行单元测试；存储和部署改动运行对应集成测试；Agent 行为改动按场景评测。不要对所有改动默认执行整个测试目录。
- 缺少外部服务时报告未验证项。区分源码检查、本地测试、Mock 和真实服务验证；测试跳过不等于验证通过。
- 模块接口、入口、环境变量、资源路径或行为契约变化时，同步检查相关调用方、测试和指令文件。

## 课件配图要求

- 课件图片默认不加标题，以图形、嵌套、连线、箭头、位置和颜色直观表达概念关系或流程，让图片本身承担解释作用。
- 不在图片中堆叠文字说明；必须使用文字时，仅保留少量必要的概念名、标签或简短示例，不用大段文字代替图形表达。

## 保持的设计约束

- 环境连接参数由 Settings 管理，Agent 行为资源由 Nacos 组装；避免把远程配置复制成多个本地硬编码版本。
- 普通用户沙箱使用私有可写 `/root` 和共享只读 `/shared`；共享资源维护沙箱可以写 `/shared`，不能将这一权限扩展到普通用户沙箱。
- Deploy 在沙箱内直传 MinIO；目录部署先清理目标前缀再上传，单文件只覆盖同名对象。目录替换不是原子操作，上传失败不恢复旧文件。
- 评测标准必须可比较；调整 Prompt、评分维度、权重、数据集或门槛时说明变化，不通过放宽标准掩盖回归。
- 新的持久设计决策用“目标、选定方案、原因、实现状态”简短记录；长篇讨论放独立文档并链接，不把未实现方案写成现有行为。

## AGENTS.md 的维护规则

- 维护范围包括根目录及各级子目录的 `AGENTS.md`。根目录记录项目全局事实和共同规则，子目录记录本目录的职责、实际行为与局部约束；避免重复上层内容，不将其他目录的实现写成本目录的能力。
- **何时新增**：在用户授权的开发中新增源码目录或独立业务模块时，同步新增对应的 `AGENTS.md`；已有目录缺少指令且需要明确职责、关键契约或局部验证方式时，在授权范围内补齐。不为缓存、构建产物、虚拟环境等生成目录创建指令文件。
- **何时修改**：目录职责、调用流程、入口或导出、接口与数据结构、配置项与默认值、资源路径、权限边界、错误语义、依赖要求、测试命令或覆盖范围发生变化时，在同一轮已授权修改中更新受影响的指令文件。功能完成、移除或替换后，同步更新实现状态，删除失效描述。
- **目录移动或删除**：移动模块时同步调整指令的适用范围、路径和上下层引用；删除模块时移除其指令，并清理根目录导航及其他指令中的失效引用。
- **以当前事实为依据**：编写和更新前核对本目录源码、配置、入口和测试；命令以实际定义为准，外部行为以可核实的文档或真实验证为准。不得凭目录名、旧指令或计划推断能力已经实现。
- **区分事实与要求**：当前实现、开发约束、已确定但未实现的方案应明确区分。发现代码未满足某项约束时，记录实际差距，不将约束表述成已经具备的保证；未经验证的行为标明验证边界。
- **同步上下层**：局部变化影响全局架构、导航或共同契约时，同时更新根目录；影响其他模块调用关系时，检查并更新相应目录的指令，保证各层描述一致。
- **完成前核对**：逐项确认本次改动涉及的指令仍与目录事实一致，路径存在、命令有效、状态准确且没有相互矛盾。维护指令不能成为扩大业务修改范围的理由；授权范围外发现的过时内容应向用户说明并提出建议。

# 飞书接入

## 职责与当前状态

- `api` 已实现应用身份的知识库与新版文档（Docx）只读接口、文档图片下载、用户/群消息与卡片操作、CardKit 全部 10 个接口及返回模型，Card 对象封装实体 ID、序号、更新锁和无参数 finish 收尾；不包含电子表格或旧版 doc。
- `event` 提供进程内单例 `FeishuEventListener` / `feishu_event_listener`，实例方法 `start_listener()` 支持并发幂等启动：子进程运行 SDK WebSocket，Pipe 回传原始事件，事件由调用进程后台线程提交同步/异步回调后立即继续接收。普通同步回调使用专用线程池，异步回调使用注册时的 Server 循环或显式 `loop`；普通任务并发、可动态增删，不持有回调 Future，不统计任务积压或接管业务异常。支持通配与 v1/v2 事件，创建实例不自动启动或接入索引。接口、生命周期和 SDK 内部 hook 边界见 `event/AGENTS.md`、`event/README.md`。
- 使用飞书官方 `lark-oapi` SDK，当前锁文件版本为 1.7.4；HTTP、Token 获取与缓存均由 SDK 管理，没有手写 HTTP 客户端或 Token 缓存。
- `graphs/feishu_doc_index` 已调用 WikiAPI 遍历目录、调用 DocxAPI 读取文档元信息与正文，再交给 RAG 模块处理；本目录提供来源读取、消息发送及独立事件监听，不承担索引编排，也未注册 Agent 工具。
- 项目已通过 `app/main.py` lifespan 调用 `deal_pilot/event/listener.py` 注册并启动监听，退出时在线程中关闭；业务回调位于 `deal_pilot/event/message`，调用 Card 对象向发送者单聊演示固定内容流式卡片；当前只注册消息接收事件，没有卡片交互业务回调。业务契约见 `../event/AGENTS.md`，未接入 Agent 或索引流程。

## 约定

- 使用 `from deal_pilot.feishu.api import WikiAPI, DocxAPI, ImageAPI, MessageAPI, CardAPI`，五个底层 API 类使用 Python 默认构造，没有模块级 API 实例；另导出 Card，通过 await Card.create/create_template 获取一张卡片的对象，读取 card.card_id，更新时不传 ID/sequence。
- 直接使用 `config/feishu_settings.py:feishu_settings` 中的 app_id/app_secret；导入不请求网络，缺少配置在调用时抛出 FeishuConfigurationError。
- 知识库的 `node_token` 与实际内容的 `obj_token` 不可混用；先判断 `obj_type` 再交给内容 API。
- 本目录不负责结构化解析、切分、索引、检索或 Agent 工具注册。
- 读取及消息发送方法使用 await；list_all_space_nodes 返回异步迭代器，使用 async for 按需消费，空间及目录分页均不预取。请求、缓存与错误细节见 `api/AGENTS.md`。
- 当前 SDK 的异步接口仍包含同步鉴权，因此完整同步 SDK 调用放入 asyncio.to_thread，不直接在事件循环中调用同步 SDK。
- 事件监听启动不等待远程就绪；回调注册只影响本地分发，不配置飞书订阅。单例持有运行资源，不随函数返回或上下文结束而关闭；服务最终关闭时可由调用方关闭，关闭后不再启动。异步路径使用 `asyncio.to_thread(listener.close)` 隔离等待。

## 验证边界

- `tests/units/test_feishu.py` 使用真实 SDK 的请求构造、鉴权、Token 缓存和响应解析，只 Mock 底层 requests.request；覆盖知识库、Docx、图片下载及公共客户端错误/线程隔离，不需要真实凭据或外部服务。
- 当前该文件没有 MessageAPI、CardAPI 或 Card 专门测试，仓库也没有 `tests/units/test_feishu_event.py` 或 `tests/units/test_feishu_card_callback.py`；业务回调与 lifespan 均无专门测试。
- 本轮仅核对源码与指令，未运行测试或类型检查，也未验证真实租户投递、卡片渲染、流式效果、交互回执或完整服务启停。

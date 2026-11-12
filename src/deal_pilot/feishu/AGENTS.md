# 飞书接入

## 职责与当前状态

- `api` 已实现应用身份的知识库与新版文档（Docx）只读接口、文档图片下载及返回模型；不包含电子表格或旧版 doc。
- 使用飞书官方 `lark-oapi` SDK，当前锁文件版本为 1.7.4；HTTP、Token 获取与缓存均由 SDK 管理，没有手写 HTTP 客户端或 Token 缓存。
- `graphs/feishu_doc_index` 已调用 WikiAPI 遍历目录、调用 DocxAPI 读取文档元信息与正文，再交给 RAG 模块处理；本目录仍只提供来源读取，不承担编排，也未注册 Agent 工具。

## 约定

- 使用 `from deal_pilot.feishu.api import WikiAPI, DocxAPI, ImageAPI`，三个 API 类使用 Python 默认构造，没有模块级 API 实例。
- 直接使用 `config/feishu_settings.py:feishu_settings` 中的 app_id/app_secret；导入不请求网络，缺少配置在调用时抛出 FeishuConfigurationError。
- 知识库的 `node_token` 与实际内容的 `obj_token` 不可混用；先判断 `obj_type` 再交给内容 API。
- 本目录不负责结构化解析、切分、索引、检索或 Agent 工具注册。
- 读取方法使用 await；list_all_space_nodes 返回异步迭代器，使用 async for 按需消费，空间及目录分页均不预取。请求、缓存与错误细节见 `api/AGENTS.md`。
- 当前 SDK 的异步接口仍包含同步鉴权，因此完整同步 SDK 调用放入 asyncio.to_thread，不直接在事件循环中调用同步 SDK。

## 验证边界

- `tests/units/test_feishu.py` 执行真实 SDK 的请求构造、鉴权、Token 缓存和响应解析，只 Mock 底层 requests.request；覆盖分页、遍历、原始块、图片下载及异常，不需要真实凭据或外部服务。
- 本轮完成本地单元测试和源码类型检查，没有执行真实租户调用，不能据此声称真实授权或连通性已通过。

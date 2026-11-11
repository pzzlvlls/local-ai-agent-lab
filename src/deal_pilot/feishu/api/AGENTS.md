# 飞书只读 API

## 文件职责

- `wiki.py:WikiAPI`：全量空间列表、空间信息、节点信息、全量直接子节点及所有空间的全层级节点。
- `docx.py:DocxAPI`：新版文档元信息查询和全量块列表；不含旧版 doc。
- `image.py:ImageAPI`：通过 Drive 素材接口下载 Docx 图片，返回 `DownloadedImage(mime: str, data: bytes)`。
- `models.py`：应用层 Pydantic 返回模型；不是官方响应结构的完整复刻。
- `_client.py`：官方 SDK 客户端、线程隔离、响应校验、资源 ID 校验及分页；不自行管理 Token 或 HTTP。
- `errors.py`：配置、Token 获取、业务响应、HTTP 状态、协议结构及不支持节点类型的错误。
- `__init__.py`：仅导出 WikiAPI、DocxAPI 和 ImageAPI，没有模块级 API 实例，导入不请求网络。

## 已实现的设计

- 目标：复用官方 SDK，按既定签名读取知识库目录及 Docx 原始块，失败时不伪装完整结果。
- 选定方案：使用官方 lark-oapi（当前 uv.lock 为 1.7.4）及其请求 Builder 和 Wiki/Docx/Drive 资源方法；
  用 feishu_settings.app_id/app_secret 构建客户端，超时 30 秒、日志级别 ERROR。
- 原因：HTTP、鉴权和 Token 缓存复用官方能力；1.7.4 的异步资源方法仍同步调用 verify/TokenManager，
  所以通过 asyncio.to_thread 执行完整同步 SDK 调用，隔离鉴权和数据请求的阻塞。
- 实现状态：全部 8 个读取方法使用官方 SDK；已删除手写 HTTP 和 Token 缓存实现。
  本地 Mock 测试与源码类型检查通过，真实租户尚未验证。

## 读取契约

- list_spaces 返回所有可访问空间；list_nodes 返回全部直接子节点，不递归；分页大小均为 50。
  parent_node_token=None 表示空间根目录，不接受空 token。
- list_all_space_nodes 返回 AsyncIterator[WikiNode]，使用 async for 按空间和目录广度优先遍历；
  开始消费才请求网络，空间及目录分页按需读取，不预取。list_spaces/list_nodes 仍返回全量列表，
  与遍历共用内部迭代器。请求随消费推进，没有固定速率限制，快速消费仍可能连续发起请求。
  按 `(space_id, node_token)` 去重，指向相同 obj_token 的不同节点仍保留；不读取正文，不保证跨请求的数据快照一致。
- WikiNode.obj_type 仍为 Literal["docx"]；其他类型抛出 UnsupportedWikiNodeTypeError，
  不转换、不静默过滤；混合类型空间的全量遍历会失败。
- 节点 URL 按 `https://www.feishu.cn/wiki/{node_token}` 生成，不使用 obj_token 或服务返回 URL；
  根节点的空 parent_node_token 规范化为 None。
- get_document 读取元信息；list_blocks 读取全部块，分页大小为 500。
  document_revision_id 仅接受 -1 或正整数，其余值在请求前抛出 ValueError。
- list_blocks 保持服务返回顺序，不组装树；raw 从 SDK 原始响应内容读取，保存完整 JSON，
  避免官方模型丢失未知字段。根块空 parent_id 规范化为 None，缺少 children 时使用空列表。
- ID/token 只接受单个资源标识，不解析链接或路径；传给请求 Builder 时保留原值，路径编码由 SDK 处理。
- `await ImageAPI().download_image(token)` 接收图片块的 `image.token`，请求 Drive `medias/{file_token}/download`，
  不使用 IM 消息图片接口。MIME 取响应 Content-Type，去参数并转小写；缺失或非 image/\* 时抛 FeishuResponseError。
  返回原始 bytes，不生成 URL、Base64 或落盘。JSON 错误响应仍校验业务 code，包括 HTTP 200；非 JSON HTTP 错误抛 FeishuHTTPError。

## SDK 与并发边界

- 客户端按 app_id/app_secret 延迟构建并缓存最近一组配置；三个 API 类仍使用 Python 默认构造。
- Token 获取、有效期与缓存策略由 SDK 决定；当前 SDK 按 app_id 复用进程内 Token，不提供跨进程共享。
  项目层不再维护 Token 过期偏移、刷新锁、失效清除或同凭据并发仅获取一次的保证。
- sdk_response 将完整同步资源调用放入 asyncio.to_thread 并校验 HTTP 与业务 code，sdk_call 进一步提取 JSON data；没有模块级 HTTP 会话或 asyncio.Lock。
- 不自动重试或切换身份；权限及资源授权由飞书管理员配置。
- 取消会向异步调用方传播，但不能中止已经运行的线程；线程中的只读 SDK 请求可能继续直到完成或超时。
  不把取消描述成已经关闭底层请求。

## 错误语义

- 参数错误抛出 ValueError；缺少配置抛出 FeishuConfigurationError。
- SDK 获取 Token 失败转为 FeishuAuthenticationError，保留 code，不输出 SDK 的原始服务端 msg。
- 非零业务 code 抛出 FeishuAPIError，保留 code、http_status、log_id，不输出原始响应体或凭据。
- get_space 的 131005、get_node 的 131005/131012、get_document 的 1770002/1770003，
  仅在 HTTP 200/400/404 时返回 None；其他错误不视为不存在。
- 有效 SDK 响应的 HTTP 5xx，或 code=0 但 HTTP 非 2xx，抛出 FeishuHTTPError，保留状态和 log_id。
- SDK JSON/模型反序列化失败，以及缺失状态、code、data、分页游标等协议问题，抛出 FeishuResponseError。
  SDK 在返回前解析非 JSON 错误页失败时也归入此错误，不当作不存在。
- 网络异常保留 SDK 底层 requests 异常；应用层模型字段不符合契约时保留 Pydantic ValidationError。
- 全量列表任何页失败即抛出，不返回部分列表；list_blocks 的文档不存在也抛出。
  list_all_space_nodes 后续页、空间或节点失败时在迭代中抛出，已产出的节点不撤回，不静默跳过失败。
- 空页且 has_more=True 时继续翻页；缺失或重复游标报错，防止截断或死循环。

## 验证与官方参考

- `.venv/bin/pytest -q tests/units/test_feishu.py` 运行飞书测试；make test-units 运行全部本地单元测试。
- 类型检查：`.venv/bin/pyright --pythonpath .venv/bin/python src/deal_pilot/feishu`。
- 单元测试保留真实 SDK 请求构造、鉴权和解析，只 Mock requests.request；用虚假配置及隔离的 SDK LocalCache，
  验证 Token 复用/过期/获取失败、线程隔离/取消、分页/遍历、原始块及错误，不调用真实飞书。
- 已核对安装的 1.7.4 源码及[官方 SDK 仓库](https://github.com/larksuite/oapi-sdk-python)，
  包括 Drive media.download、资源请求 Builder、core/token/auth.py、core/token/manager.py 和 core/http/transport.py。
- [官方文档：块的数据结构](https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/data-structure/block)：
  查询 block_type 的数值枚举、各类型含义及对应内容字段结构时优先参考此页；新增类型以官方文档为准，不将历史速查表视为完整枚举。
- 官方接口：[空间列表](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space/list)、
  [空间信息](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space/get)、
  [节点信息](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/get_node)、
  [直接子节点](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/list)、
  [文档信息](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/get)、
  [文档全部块](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/list)。
- 未实现导出、写入、删除、通用附件下载、Markdown 转换、自动重试或用户级权限过滤。
- 图片素材接口：[下载素材](https://open.feishu.cn/document/server-docs/docs/drive-v1/media/download)。

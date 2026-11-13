# 飞书 API

## 文件职责

- `wiki.py:WikiAPI`：全量空间列表、空间信息、节点信息、全量直接子节点及所有空间的全层级节点。
- `docx.py:DocxAPI`：新版文档元信息查询和全量块列表；不含旧版 doc。
- `image.py:ImageAPI`：通过 Drive 素材接口下载 Docx 图片，返回 `DownloadedImage(mime: str, data: bytes)`。
- `message.py:MessageAPI`：以应用身份向用户/群发送文本、按消息 ID 撤回；卡片能力归属 card.py。
- `card.py:Card`：一张卡片一个对象，持有只读 card_id/message_id/sequence 及更新锁，工厂创建、发送与组件更新均无需反复传 ID/序号；底层 `CardAPI` 保留卡片消息投递、回复、更新/撤回、延时更新及临时卡片接口，并提供显式 ID/序号接口，覆盖当前 SDK 的 10 个 CardKit 接口：JSON/模板创建、消息 ID 转换、配置/全量/批量更新和组件增删改；CardAPI 的底层 create/create_template 仅创建，不自动投递。
- `_message.py`：文本与卡片共享的私有 IM 投递、接收者校验；不依赖 MessageAPI 或 Card 类。
- `models.py`：应用层 Pydantic 返回模型；不是官方响应结构的完整复刻。
- `_client.py`：官方 SDK 客户端、线程隔离、响应校验、资源 ID 校验及分页；不自行管理 Token 或 HTTP。
- `errors.py`：配置、Token 获取、业务响应、HTTP 状态、协议结构及不支持节点类型的错误。
- `__init__.py`：仅导出 WikiAPI、DocxAPI、ImageAPI、MessageAPI、CardAPI 和 Card，没有模块级 API 实例，导入不请求网络。

## 已实现的设计

- 目标：复用官方 SDK，按既定签名读取知识库目录及 Docx 原始块，失败时不伪装完整结果。
- 选定方案：使用官方 lark-oapi（当前 uv.lock 为 1.7.4）及其请求 Builder 和 Wiki/Docx/Drive 资源方法；
  用 feishu_settings.app_id/app_secret 构建客户端，超时 30 秒、日志级别 ERROR。
- 原因：HTTP、鉴权和 Token 缓存复用官方能力；1.7.4 的异步资源方法仍同步调用 verify/TokenManager，
  所以通过 asyncio.to_thread 执行完整同步 SDK 调用，隔离鉴权和数据请求的阻塞。
- 实现状态：全部 8 个读取方法使用官方 SDK；已删除手写 HTTP 和 Token 缓存实现。
  已有读取能力的本地 Mock 测试；本轮未运行测试或类型检查，未做真实租户验证。

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

- 客户端按 app_id/app_secret 延迟构建并缓存最近一组配置；五个 API 类仍使用 Python 默认构造。
- Token 获取、有效期与缓存策略由 SDK 决定；当前 SDK 按 app_id 复用进程内 Token，不提供跨进程共享。
  项目层不再维护 Token 过期偏移、刷新锁、失效清除或同凭据并发仅获取一次的保证。
- sdk_response 将完整同步资源调用放入 asyncio.to_thread 并校验 HTTP 与业务 code，sdk_call 进一步提取 JSON data；没有模块级 HTTP 会话或 asyncio.Lock。
- 不自动重试或切换身份；权限及资源授权由飞书管理员配置。
- 取消会向异步调用方传播，但不能中止已经运行的线程；线程中的 SDK 请求可能继续直到完成或超时。
  不把取消描述成已经关闭底层请求。

## 消息发送契约

- 目标：向用户或群发送文本或卡片消息。选定方案：`MessageAPI.send_text` / `Card.create(..., receive_id=...)`，复用官方 IM V1
  `message.create`、已有客户端和错误边界。原因：沿用 SDK 鉴权与请求序列化，不增加依赖。
  实现状态：已实现，`deal_pilot/event/message/reply.py` 调用 Card.create 创建并发送 Agent 回复卡片；reply 编排有 Mock 测试，当前没有底层消息发送或卡片 API 专门测试，未做真实发送验证，未注册为 Agent 工具。
- `await MessageAPI().send_text(receive_id, text, *, receive_id_type="open_id", uuid=None)`
  返回非空 `message_id: str`；支持 open_id、union_id、user_id、email 和 chat_id。
  receive_id 必须是非空且不含空白的字符串，标识的真实性和类型匹配由服务端校验。
  text 必须是非空白字符串，保留原始文本并序列化为 `{"text": text}` 的 JSON 字符串。
- `await CardAPI().send_card(receive_id, card, *, receive_id_type="open_id", uuid=None)`
  以 `interactive` 类型发送非空 `dict[str, JsonValue]`，返回非空消息 ID，收件人范围与 send_text 相同。
  card 为卡片 JSON（可含 Markdown 组件）、template 引用或已有 card 实体引用，不传外层 msg_type/content，
  由封装序列化为 content 字符串；本地检查非空字典及 JSON 可序列化性（拒绝 NaN/Infinity），具体卡片结构由服务端校验。
  send_card 本身不创建实体或编排流式；其他消息操作见下文与 CARDS.md。
- 可选 uuid 是 1 到 50 字符的非空白去重标识；同一消息重试时由调用方复用，去重由飞书执行。
  不自动重试；取消、超时或响应解析失败时消息仍可能已发送，不代表远端撤回或发送失败。
- 应用需开启机器人能力、具备消息发送权限，目标用户须满足飞书可达范围；本模块不查通讯录或配置权限。
- 本地参数错误抛 ValueError；配置、鉴权、HTTP、业务响应与网络异常沿用共同契约。
  成功响应缺少有效 message_id 时抛 FeishuResponseError，不返回空值伪装成功。

## 卡片完整封装

- CardAPI 覆盖已安装 SDK 的全部 10 个 CardKit V1 接口。API 版本与 JSON 2.0 卡片结构版本不可混用。接口说明见 [CARDS.md](CARDS.md)，以当前源码为准；该文档仍引用不存在的交互处理器、示例脚本和卡片测试，并描述了当前未注册的交互流程，不能据此认定已实现或验证。
- `create`、`create_template`、`id_from_message` 返回非空 card_id；其余实体/组件更新返回 None，以 sdk_response 接受没有 data 的成功响应。
- 底层 CardAPI 更新方法支持 int32 正整数 sequence 和可选 uuid，显式调用时由调用方管理序号；业务推荐使用 Card 对象自动管理序号和串行更新。两层均不校验远端序号、不自动重试。JSON 结构由飞书服务端验证，本地检查可序列化性及必要类型/ID。
- 实体/组件方法包括 create、create_template、id_from_message、stream_text、set_streaming、update_settings、update、batch_update、add_elements、update_element、patch_element 和 delete_element。
- CardAPI 的卡片消息方法包括：send_card、reply_card、update_card、recall、delayed_update_card、send_ephemeral_card、delete_ephemeral_card。MessageAPI 保留 send_text/recall；卡片投递及更新链不依赖它。历史三个接口使用官方 Client.request，其余使用生成式 SDK。
- 延时更新接收交互 token，必须在回执已经交付后调用；不自行 sleep 或调度任务。当前业务注册表只注册消息接收事件，未接入卡片交互处理；不能仅凭此 API 推断交互回执已交付。临时卡片和 JSON 2.0 的 update_multi 是不同能力。
- CardKit 权限为 cardkit:card:write；发送、回复、更新、撤回等消息权限按官方接口和应用后台配置。没有自动授权、用户级资源过滤、HTTP Webhook、持久业务队列或去重保证。
- 当前没有卡片 API、Card 对象、消息发送或交互回执专门测试；tests/units/test_message_reply.py 只 Mock Card 验证业务编排，不能据此声称底层并发、取消、组件 JSON 或远端交互已验证。

## Card 对象契约

- 目标：业务不反复传实体 ID 和操作序号。选定方案：Card.create/create_template 返回一个对象，持有 card_id、sequence 和 asyncio.Lock，复用底层 CardAPI。原因：一张卡片一套状态，无需进程级卡片注册表。实现状态：对象及流式业务调用已实现，第 40 节课件展示用法；当前无 Card 专门测试或模板/组件脚本，本轮未做真实飞书联调。
- card_id、message_id、sequence 为只读属性；sequence 表示最后分配值，不保证远端已生效。更新接口不接收外部 sequence；JSON 创建初始化为 0；模板创建后开启流式消耗 1 个序号；每次更新前在锁内加一，同一对象全部更新共用序号；达到 2147483647 后拒绝继续请求。发送/回复不消耗更新序号。
- Card.create/create_template 自动开启 streaming_mode 和 update_multi；JSON 创建保留其他 config、不修改输入对象。传 receive_id 时工厂先创建实体再投递，返回后可以直接 stream_text；不传时仅创建，随后用 send/reply 投递。模板工厂创建后用 settings 启用流式。
- Card.send/reply 通过 CardAPI 调用官方 IM SDK，返回消息 ID，并保存最近一次成功投递的 message_id；未投递为 None，from_message 保存传入消息 ID。as_reference 仅为低层实体引用。创建与发送不是原子操作；投递失败或取消尽力关闭流式后抛出原异常，不自动重试。
- 目标：业务以无参数 finish() 完成流式收尾。选定方案：finish 通过同一更新锁/序号调用 set_streaming(False)，仅关闭模式，保留已提交的组件与内容，不缓存或重建整卡 JSON。原因：组件修改已经逐次提交，避免旧快照覆盖动态增删改；实现状态：`event/message/reply.py` 已使用 `await card.finish()` 收尾，不做最终全量更新；第 40 节课件的收尾片段仍缺少 await，不能视为可直接运行的完整示例。
- 调用 finish 前应 await 所有业务更新，它不接管尚未提交的生产任务。每次调用都发请求并消耗序号；失败/取消语义同其他更新，无自动重试。finish 后可继续普通组件编辑，再次 stream_text 前须先 set_streaming(True)。
- 每个对象在同一事件循环使用，同一卡片由一个对象负责；不管理跨对象/跨进程协调、限流或持久化。Card(card_id, sequence=...) 和 await Card.from_message(message_id, sequence=...) 接管旧卡时必须显式提供已知序号并停止旧操作方；转换接口不会查询远端序号。
- 分配的序号不因本地校验、服务错误或取消回退；等待锁期间取消不发请求、不占序号。在途更新用独立任务执行并 shield，调用方取消仍传播，更新锁保留到 SDK 调用结束；对象持有在途任务引用并消费其异常。进程/循环退出或 HTTP 超时仍不保证远端完成顺序。
- 监听层不管理 Card 对象，当前没有交互业务处理器。后续仅持有消息 ID 的调用方不得假设已知当前 sequence，从零构造对象覆盖原序号。

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
- 当前 `tests/units/test_feishu.py` 仅覆盖读取和公共客户端，没有 MessageAPI/CardAPI/Card 测试；收件人、编码、去重参数、消息返回 ID、序号、并发及取消等消息/卡片行为尚无专门测试。本轮仅检查源码、路径与指令一致性，未运行上述测试或类型检查。
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
- 未实现文档导出/写入/删除、通用附件下载、Markdown 转换、自动重试或用户级权限过滤。
- 图片素材接口：[下载素材](https://open.feishu.cn/document/server-docs/docs/drive-v1/media/download)。
- 消息接口：[发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)、
  [消息内容结构](https://open.feishu.cn/document/server-docs/im-v1/message-content-description/create_json)。

# 飞书卡片封装与示例

本封装覆盖当前安装的 lark-oapi SDK 中 CardKit V1 的全部 10 个接口，以及应用机器人发送、回复、更新、撤回卡片消息、异步交互处理和临时卡片。CardKit V1 是 API 版本，卡片使用 JSON 2.0。卡片组件仍以官方 JSON 描述，支持传入按钮、表单、图片、图表等配置，不重复实现官方完整组件 Schema 或可视化搭建器。

仅本地 Mock 与类型检查验证。实际权限、客户端渲染、流式效果、平台频控、临时卡片及长连接远程交互须在真实租户验证。

## 最快体验

配置已有 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，开通机器人能力。应用身份权限：

- `im:message.p2p_msg:readonly`：接收单聊文本。
- `im:message:send_as_bot`：发送/回复卡片。
- `cardkit:card:write`：创建、配置和更新实体。
- 群里 @ 触发示例时另需 `im:message.group_at_msg:readonly`，机器人须在群中。
- 更新、撤回等额外操作按对应接口申请权限，如 `im:message:update`、`im:message:recall`；以后台显示的可选权限及应用现有授权为准。

在飞书应用后台分别配置：

1. **事件配置**：使用长连接，添加 `im.message.receive_v1`。
2. **回调配置**：使用长连接，添加新版 `card.action.trigger`（卡片回传交互）。不要选择旧版卡片回调。
3. 发布并完成权限审批，测试用户在应用可用范围内。
4. 按项目现有方式启动服务，向机器人发送“卡片示例”：得到按钮、链接、下拉选择与反馈表单卡片。发送其他文本：演示流式输出。

点击“确认”、选择主题或提交表单后，业务函数通过 `CardAPI.update_card` 更新原卡片展示结果；表单读取 `form_value` 并显示输入内容，示例不保存业务数据，也不通过回执弹出 Toast。要继续体验其他操作，重新发送“卡片示例”获取新卡片。

也可以从项目根目录显式运行脚本。下面命令会调用真实飞书并发送消息；导入模块或 `--help` 不发送：

```bash
uv run python resource/feishu_cards.py interactive --receive-id ou_xxx
uv run python resource/feishu_cards.py stream --receive-id ou_xxx
uv run python resource/feishu_cards.py components --receive-id ou_xxx
uv run python resource/feishu_cards.py interactive --receive-id oc_xxx --receive-id-type chat_id
uv run python resource/feishu_cards.py template --receive-id ou_xxx --template-id TEMPLATE_ID --version 1.0.0
uv run python resource/feishu_cards.py reply --receive-id ou_xxx --message-id om_xxx --in-thread
uv run python resource/feishu_cards.py ephemeral --receive-id ou_xxx --chat-id oc_xxx
```

脚本不会启动监听器；按钮、选择器和表单的服务端反馈需要项目服务已经运行，并完成回调订阅。模板示例传入变量 `name`，请使用包含该变量的新版模板。示例消息不会自动撤回；组件示例只删除自己刚新增的组件。

## Card：一张卡片一个对象

```python
from deal_pilot.feishu.api import Card

card = await Card.create({
    "schema": "2.0",
    "config": {"update_multi": True},
    "body": {"elements": [
        {"tag": "markdown", "element_id": "answer", "content": "初始内容"}
    ]},
}, receive_id="ou_xxx")
await card.stream_text("answer", "更新")
await card.stream_text("answer", "更新后的内容")
await card.finish()
print(card.message_id)  # 本次投递的消息 ID
print(card.card_id)   # 只读实体 ID
print(card.sequence)  # 最后分配的更新序号，此时为 3
```

`Card.create()` 和 `Card.create_template()` 创建时自动开启流式和共享更新。传入 `receive_id` 会同时投递，返回 Card 对象后直接更新；无须调用 MessageAPI。JSON 参数无须显式配置 streaming_mode/update_multi，工厂会覆盖为 True，并保留其他配置且不修改原字典。模板创建后用配置接口开启流式，因此返回时 sequence 为 1。每个对象自己持有 card_id、message_id、sequence 和 asyncio.Lock；没有进程级卡片注册表。同一卡片后续更新应复用同一个对象，并在同一事件循环执行。发送不消耗更新序号。

| 操作 | Card 对象接口 | 用途 |
| --- | --- | --- |
| 创建 | `await Card.create(card_json, receive_id="ou_xxx")` / `await Card.create_template(template_id, receive_id="ou_xxx", variables=..., version=...)` | 创建流式实体、投递并返回对象 |
| 读取 ID | `card.card_id` | 获取实体 ID，只读 |
| 发送 | `await card.send(receive_id, receive_id_type="open_id", uuid=None)` | 自动发送实体引用，返回 message_id |
| 回复 | `await card.reply(message_id, reply_in_thread=False, uuid=None)` | 用实体回复消息，返回新消息 ID |
| 实体引用 | `card.as_reference()` | 返回底层投递需要的字典，普通业务不必使用 |
| 配置 | `await card.update_settings(settings)` / `await card.set_streaming(enabled)` | 更新配置或流式状态 |
| 结束流式 | `await card.finish()` | 无参数，关闭流式状态，保留当前组件与内容 |
| 全量更新 | `await card.update(card_json)` | 替换卡片内容 |
| 流式更新 | `await card.stream_text(element_id, text)` | 提交累计全文 |
| 添加组件 | `await card.add_elements(elements, placement=..., target_element_id=...)` | 在目标前后插入或向容器追加 |
| 替换组件 | `await card.update_element(element_id, element)` | 全量替换组件 |
| 局部更新 | `await card.patch_element(element_id, partial_element)` | 更新组件属性 |
| 删除组件 | `await card.delete_element(element_id)` | 删除组件及其嵌套内容 |
| 批量更新 | `await card.batch_update(actions)` | 提交官方 action/params 列表 |

正常结束只需调用无参数的 `await card.finish()`。它等待排在前面的对象更新操作结束，自动递增序号并关闭流式状态；已提交的文字和动态增删改的组件保持原样，不重写整张卡片，也不要求业务重新传入最终 JSON。调用前应 await 所有业务更新，finish 不会等待尚未提交的生产任务。

finish 失败直接抛出，不自动重试；调用方取消时沿用对象的在途锁保护。每次调用 finish 都会提交关闭配置并消耗一个序号。结束后仍可使用组件编辑方法；若要再次调用 stream_text，先通过 set_streaming(True) 开启新一轮流式。

所有更新自动分配序号，支持可选 `uuid`，不再接受外部 card_id/sequence。一个对象的全部更新接口共用严格递增的 sequence，内部串行执行；不同卡片互不阻塞。序号上限为 2147483647，耗尽后在网络请求前报错。

分配过的序号不回退，即使参数校验、请求失败或取消；允许跳号。取消尚在排队的操作不消耗序号、不发请求。取消正在执行的更新会向调用方传播，但 SDK 线程可能仍运行，对象会保留更新锁直到本次调用结束。事件循环关闭、远端超时后的执行结果仍无法保证；没有自动重试、限流、持久化或跨对象/进程协调。

### 已有卡片与底层接口

新卡片优先通过工厂创建。恢复已有卡片时必须提供已知的最后分配序号，不能默认从 0 重新开始：

```python
card = Card("已保存的 card_id", sequence=12)
# 或根据消息 ID 转换；转换接口只查询 ID，不查询远端 sequence。
card = await Card.from_message("om_xxx", sequence=12)
await card.patch_element("answer", {"content": "继续更新"})  # 自动使用 13
```

这两种接管方式要求旧对象/其他进程已停止操作，且提供的序号不小于已使用值。回调只有消息 ID 时，不能由此自动恢复序号；业务需保留原 Card 对象关联，或自行保存并恢复状态。当前交互教学示例使用 CardAPI.update_card 按消息 ID 更新，不依赖 Card 对象缓存。

`CardAPI` 保留为底层无状态接口，兼容已有显式 card_id/sequence 调用；`create/create_template/id_from_message` 仍返回 ID。Card 对象复用它调用官方 SDK，覆盖全部 10 个 CardKit 接口。不应绕过对象同时用 CardAPI 更新同一卡片，否则对象内的序号会失去同步。

所有 JSON 参数均传 Python 字典/列表，由封装序列化；不要重复 `json.dumps`。`batch_update` 的 actions 列表内，params 中哪些字段必须是 JSON 字符串，仍依照官方 action 契约传递。

CardKit 当前资源清单没有单独的“读取完整卡片”或“删除卡片实体”接口，本封装没有编造这类方法。要移除会话里的卡片，调用消息撤回/临时卡片删除。当前安装的 SDK 提供 `lark_oapi.channel.card` 构建器，可以在适用时复用；这里接受原生 JSON，以保留所有组件与新字段，并保持现有 SDK 客户端、鉴权和异常契约。

## CardAPI：补充消息操作（按需使用）

下列卡片方法已从 MessageAPI 迁移到 CardAPI；MessageAPI 仅保留 send_text 和 recall。普通流式业务使用上面的 Card 对象。这些接口保留之前封装的历史卡片、临时卡片和仅持有消息 ID 的回调更新能力，不需要插入正常流式流程。

| 方法 | 参数与用途 |
| --- | --- |
| `send_card(receive_id, card, receive_id_type="open_id", uuid=None)` | 发送 JSON、模板或 card_id 引用；支持用户四类标识和 chat_id |
| `reply_card(message_id, card, reply_in_thread=False, uuid=None)` | 回复一条消息，返回新消息 ID |
| `update_card(message_id, card)` | 根据消息 ID 更新共享卡片，不是 CardKit sequence 接口 |
| `recall(message_id)` | 撤回普通消息或卡片消息 |
| `delayed_update_card(token, card, open_ids=None)` | 回调完成后用其 token 延时更新，须遵守 token 有效期和调用次数限制 |
| `send_ephemeral_card(chat_id, open_id, card)` | 在群中发送指定用户可见的临时卡片，返回消息 ID |
| `delete_ephemeral_card(message_id)` | 删除临时卡片 |

后三个历史卡片接口在已安装 SDK 中没有生成式 Builder，因此通过官方 `Client.request` 调用，仍由 SDK 管理 Token、HTTP 和序列化。不是自定义 Webhook 机器人的接口。临时卡片有群聊、在线可见性等平台限制，不等同于 JSON 2.0 的共享更新开关。

## 长连接交互回调

卡片操作复用原来的事件监听与异步分发，不改动 `feishu/event`。子进程把操作交给 Pipe 后返回 None，由 SDK 发送无业务内容的成功回执；主进程只提交业务函数，不等待其完成。回执时限不约束业务函数的执行时长。

```python
from deal_pilot.feishu.event import FeishuEvent, feishu_event_listener
from deal_pilot.event.card_handler import card_handler

# 在 Server 事件循环内注册，与普通消息事件相同。
feishu_event_listener.register("card.action.trigger", card_handler)

# 业务处理函数签名：async def card_handler(event: FeishuEvent) -> None
# 可以 await 耗时业务，完成后主动调用 CardAPI.update_card 或保留的 Card 对象更新。
# 不需要返回 CardActionResponse，也不需要为了回执再拆一个后台任务。
```

- 原始交互数据位于 `event.payload["event"]`，含 operator、action、context、token。按钮参数在 action.value，选择项在 option/options，表单数据在 form_value；消息 ID 在 context.open_message_id。
- 身份来自 operator，不能以 action.value 中的用户标识授权；token 不应记录日志。示例只演示操作结果，不进行业务数据持久化。
- 监听器不读取业务返回值，不设置业务超时，不因回执时限取消任务；业务自行处理异常、幂等和任务持久化。进程退出或重启不保证长任务继续运行。
- 当前固定为空回执，不通过回执弹出 Toast 或即时替换卡片。结果展示使用独立的卡片更新 API；示例在 `event/card_handler.py`，适用于具有 open_message_id 的消息卡片。
- 不提供 HTTP Webhook 或旧版回调协议。后台仍需将新版 `card.action.trigger` 配置为长连接订阅。

`delayed_update_card` 仍作为独立 API 保留，调用受交互 token 的有效期、次数及回执交付顺序约束；监听层没有“回执已交付”通知，不用固定 sleep 推断。长任务完成后的示例使用消息 ID 更新，不依赖这个 token。

## 流式示例

`event/message_handler.py` 展示 Card.create(..., receive_id=...) 创建并投递流式卡片 → 按序提交累计全文 → finish() 结束流式，保留最后提交的全文。异常/取消时尽力关闭模式，保留原始错误。`DEMO_TEXT`、`CHUNK_SIZE`、`CHUNK_INTERVAL` 可修改。

不传 receive_id 时仅创建实体；传入时工厂负责创建及发送，两次请求不是原子操作。投递失败或取消会尽力关闭流式后抛出原异常，不能保证远端回滚。同一实体的发送次数与有效期由平台限制。这里不持久化消息/实体关联，不实现事件去重。`update_multi=True` 是共享更新，不会扩大消息接收范围。

## 验证与官方参考

```bash
.venv/bin/pytest -q tests/units/test_feishu.py tests/units/test_feishu_card_callback.py
.venv/bin/pyright --pythonpath .venv/bin/python src/deal_pilot/feishu src/deal_pilot/event resource/feishu_cards.py
```

- [CardKit 资源概述](https://open.feishu.cn/document/cardkit-v1/feishu-card-resource-overview)
- [卡片 JSON 2.0](https://open.feishu.cn/document/feishu-cards/card-json-v2-structure)
- [回调概述及长连接接入](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/callback-overview)
- [消息与卡片接口清单](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1)

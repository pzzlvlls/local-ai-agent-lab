"""通过官方 CardKit 接口创建、流式更新及定稿卡片实体。"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from lark_oapi.api.cardkit.v1 import (
    Card as SDKCard,
    BatchUpdateCardRequest,
    BatchUpdateCardRequestBody,
    IdConvertCardRequest,
    IdConvertCardRequestBody,
    CreateCardElementRequest,
    CreateCardElementRequestBody,
    DeleteCardElementRequest,
    DeleteCardElementRequestBody,
    PatchCardElementRequest,
    PatchCardElementRequestBody,
    UpdateCardElementRequest,
    UpdateCardElementRequestBody,

    ContentCardElementRequest,
    ContentCardElementRequestBody,
    CreateCardRequest,
    CreateCardRequestBody,
    SettingsCardRequest,
    SettingsCardRequestBody,
    UpdateCardRequest,
    UpdateCardRequestBody,
)
from lark_oapi.api.im.v1 import (
    ReplyMessageRequest, ReplyMessageRequestBody, PatchMessageRequest,
    PatchMessageRequestBody, DeleteMessageRequest,
)
from lark_oapi.core.enum import AccessTokenType, HttpMethod
from lark_oapi.core.model import BaseRequest
from pydantic import JsonValue

from deal_pilot.feishu.api._client import cardkit_client, im_client, resource_id, sdk_call, sdk_response, _client
from deal_pilot.feishu.api._message import send_message, validate_recipient
from deal_pilot.feishu.api.errors import FeishuResponseError

logger = logging.getLogger(__name__)


def _card_json(card: dict[str, JsonValue]) -> str:
    if not isinstance(card, dict) or not card:
        raise ValueError("card 必须是非空卡片 JSON 字典")
    try:
        return json.dumps(card, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("card 必须可序列化为有效 JSON") from None


def _uuid(value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 50):
        raise ValueError("uuid 必须是 1 到 50 字符的非空白字符串")


def _json_list(values: list[dict[str, JsonValue]]) -> str:
    if not isinstance(values, list) or not values:
        raise ValueError("必须传非空 JSON 对象列表")
    for value in values:
        _card_json(value)
    return json.dumps(values, ensure_ascii=False, allow_nan=False)


def _sequence(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise ValueError("sequence 必须为 1～2147483647 的整数，同一卡片的操作序号须严格递增")
    return value


class CardAPI:
    """卡片底层接口：实体、组件，以及消息投递和历史卡片操作。

    复用应用凭据及 SDK 线程隔离，不自动重试。调用方负责串行操作同一卡片、
    维护递增 sequence；具体卡片结构、权限及流式状态由飞书校验。
    """

    async def create(self, card: dict[str, JsonValue]) -> str:
        """创建 JSON 卡片实体，返回 card_id，不自动发送消息。"""
        body = CreateCardRequestBody.builder().type("card_json").data(_card_json(card)).build()
        request = CreateCardRequest.builder().request_body(body).build()
        api = cardkit_client()
        data = await sdk_call(lambda: api.card.create(request))
        card_id = data.get("card_id")
        if not isinstance(card_id, str) or not card_id.strip():
            raise FeishuResponseError("飞书创建卡片响应缺少有效的 card_id")
        return card_id

    async def stream_text(
        self, card_id: str, element_id: str, text: str, *, sequence: int, uuid: str | None = None,
    ) -> None:
        """更新已开启流式模式的文本组件；text 是累计全文，不是本次增量。"""
        resource_id(card_id, "card_id")
        resource_id(element_id, "element_id")
        if not isinstance(text, str) or not text:
            raise ValueError("text 必须是非空字符串")
        body = (ContentCardElementRequestBody.builder().content(text)
                .sequence(_sequence(sequence)).build())
        _uuid(uuid)
        body.uuid = uuid
        request = (ContentCardElementRequest.builder().card_id(card_id).element_id(element_id)
                   .request_body(body).build())
        api = cardkit_client()
        await sdk_response(lambda: api.card_element.content(request))

    async def set_streaming(self, card_id: str, enabled: bool, *, sequence: int, uuid: str | None = None) -> None:
        """开启或关闭流式模式；不修改卡片正文。"""
        if type(enabled) is not bool:
            raise ValueError("enabled 必须是 bool")
        await self.update_settings(card_id, {"config": {"streaming_mode": enabled}}, sequence=sequence, uuid=uuid)

    async def update_settings(
        self, card_id: str, settings: dict[str, JsonValue], *, sequence: int, uuid: str | None = None,
    ) -> None:
        """更新 config 或 card_link 配置；settings 是对象，不预先 JSON 编码。"""
        resource_id(card_id, "card_id")
        _uuid(uuid)
        body = (SettingsCardRequestBody.builder().settings(_card_json(settings))
                .sequence(_sequence(sequence)).build())
        body.uuid = uuid
        request = SettingsCardRequest.builder().card_id(card_id).request_body(body).build()
        api = cardkit_client()
        await sdk_response(lambda: api.card.settings(request))

    async def update(self, card_id: str, card: dict[str, JsonValue], *, sequence: int, uuid: str | None = None) -> None:
        """全量替换卡片实体；流式完成后可用于写入最终完整正文。"""
        resource_id(card_id, "card_id")
        body = (UpdateCardRequestBody.builder()
                .card(SDKCard.builder().type("card_json").data(_card_json(card)).build())
                .sequence(_sequence(sequence)).build())
        _uuid(uuid)
        body.uuid = uuid
        request = UpdateCardRequest.builder().card_id(card_id).request_body(body).build()
        api = cardkit_client()
        await sdk_response(lambda: api.card.update(request))

    async def create_template(
        self, template_id: str, *, variables: dict[str, JsonValue] | None = None,
        version: str | None = None,
    ) -> str:
        """从新版卡片模板创建实体；version 省略时由飞书选择版本。"""
        resource_id(template_id, "template_id")
        data: dict[str, JsonValue] = {"template_id": template_id}
        if variables is not None:
            data["template_variable"] = variables
        if version is not None:
            resource_id(version, "version")
            data["template_version_name"] = version
        body = CreateCardRequestBody.builder().type("template").data(_card_json(data)).build()
        request = CreateCardRequest.builder().request_body(body).build()
        api = cardkit_client()
        result = await sdk_call(lambda: api.card.create(request))
        card_id = result.get("card_id")
        if not isinstance(card_id, str) or not card_id.strip():
            raise FeishuResponseError("飞书创建卡片响应缺少有效的 card_id")
        return card_id

    async def id_from_message(self, message_id: str) -> str:
        """将已有卡片消息的 message_id 转为 card_id；适用范围由飞书校验。"""
        resource_id(message_id, "message_id")
        body = IdConvertCardRequestBody.builder().message_id(message_id).build()
        request = IdConvertCardRequest.builder().request_body(body).build()
        api = cardkit_client()
        data = await sdk_call(lambda: api.card.id_convert(request))
        card_id = data.get("card_id")
        if not isinstance(card_id, str) or not card_id.strip():
            raise FeishuResponseError("飞书转换响应缺少有效的 card_id")
        return card_id

    async def batch_update(
        self, card_id: str, actions: list[dict[str, JsonValue]], *, sequence: int, uuid: str | None = None,
    ) -> None:
        """提交官方 actions 列表，具体 action/params 结构由飞书校验。"""
        resource_id(card_id, "card_id")
        _uuid(uuid)
        body = (BatchUpdateCardRequestBody.builder().actions(_json_list(actions))
                .sequence(_sequence(sequence)).build())
        body.uuid = uuid
        request = BatchUpdateCardRequest.builder().card_id(card_id).request_body(body).build()
        api = cardkit_client()
        await sdk_response(lambda: api.card.batch_update(request))

    async def add_elements(
        self, card_id: str, elements: list[dict[str, JsonValue]], *,
        placement: Literal["insert_before", "insert_after", "append"], target_element_id: str,
        sequence: int, uuid: str | None = None,
    ) -> None:
        """在目标组件前/后插入，或向容器 append 子组件。"""
        resource_id(card_id, "card_id")
        resource_id(target_element_id, "target_element_id")
        if placement not in ("insert_before", "insert_after", "append"):
            raise ValueError("placement 必须为 insert_before、insert_after 或 append")
        _uuid(uuid)
        body = (CreateCardElementRequestBody.builder().type(placement).target_element_id(target_element_id)
                .elements(_json_list(elements)).sequence(_sequence(sequence)).build())
        body.uuid = uuid
        request = CreateCardElementRequest.builder().card_id(card_id).request_body(body).build()
        api = cardkit_client()
        await sdk_response(lambda: api.card_element.create(request))

    async def update_element(
        self, card_id: str, element_id: str, element: dict[str, JsonValue], *, sequence: int, uuid: str | None = None,
    ) -> None:
        """替换整个组件。"""
        resource_id(card_id, "card_id")
        resource_id(element_id, "element_id")
        _uuid(uuid)
        body = UpdateCardElementRequestBody.builder().element(_card_json(element)).sequence(_sequence(sequence)).build()
        body.uuid = uuid
        request = (UpdateCardElementRequest.builder().card_id(card_id).element_id(element_id)
                   .request_body(body).build())
        api = cardkit_client()
        await sdk_response(lambda: api.card_element.update(request))

    async def patch_element(
        self, card_id: str, element_id: str, partial_element: dict[str, JsonValue], *, sequence: int, uuid: str | None = None,
    ) -> None:
        """局部更新组件属性，不改变 tag。"""
        resource_id(card_id, "card_id")
        resource_id(element_id, "element_id")
        _uuid(uuid)
        body = PatchCardElementRequestBody.builder().partial_element(_card_json(partial_element)).sequence(_sequence(sequence)).build()
        body.uuid = uuid
        request = (PatchCardElementRequest.builder().card_id(card_id).element_id(element_id)
                   .request_body(body).build())
        api = cardkit_client()
        await sdk_response(lambda: api.card_element.patch(request))

    async def delete_element(
        self, card_id: str, element_id: str, *, sequence: int, uuid: str | None = None,
    ) -> None:
        """删除组件及其嵌套内容。"""
        resource_id(card_id, "card_id")
        resource_id(element_id, "element_id")
        _uuid(uuid)
        body = DeleteCardElementRequestBody.builder().sequence(_sequence(sequence)).build()
        body.uuid = uuid
        request = (DeleteCardElementRequest.builder().card_id(card_id).element_id(element_id)
                   .request_body(body).build())
        api = cardkit_client()
        await sdk_response(lambda: api.card_element.delete(request))


    async def send_card(
        self,
        receive_id: str,
        card: dict[str, JsonValue],
        *,
        receive_id_type: Literal["open_id", "union_id", "user_id", "email", "chat_id"] = "open_id",
        uuid: str | None = None,
    ) -> str:
        """发送一则卡片消息，返回飞书 message_id。

        card 为非空卡片 JSON 字典（可含 Markdown 组件），不传外层 msg_type/content。
        也可传飞书支持的 template 或 card 实体引用；本方法不创建卡片实体。
        本地检查字典及 JSON 可序列化性，具体卡片结构由飞书服务端校验。
        本方法仅负责投递；流式业务使用 Card 对象管理实体和序号。
        """
        if not isinstance(card, dict) or not card:
            raise ValueError("card 必须是非空卡片 JSON 字典")
        try:
            content = json.dumps(card, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("card 必须可序列化为有效 JSON") from None
        return await send_message(
            receive_id, "interactive", content,
            receive_id_type=receive_id_type, uuid=uuid,
        )

    async def reply_card(
        self, message_id: str, card: dict[str, JsonValue], *,
        reply_in_thread: bool = False, uuid: str | None = None,
    ) -> str:
        """以卡片回复指定消息，可选择话题回复。"""
        resource_id(message_id, "message_id")
        _uuid(uuid)
        if type(reply_in_thread) is not bool:
            raise ValueError("reply_in_thread 必须是 bool")
        body = (ReplyMessageRequestBody.builder().msg_type("interactive").content(_card_json(card))
                .reply_in_thread(reply_in_thread).build())
        body.uuid = uuid
        request = ReplyMessageRequest.builder().message_id(message_id).request_body(body).build()
        api = im_client()
        data = await sdk_call(lambda: api.message.reply(request))
        result = data.get("message_id")
        if not isinstance(result, str) or not result.strip():
            raise FeishuResponseError("飞书回复响应缺少有效的 message_id")
        return result

    async def update_card(self, message_id: str, card: dict[str, JsonValue]) -> None:
        """按消息 ID 更新共享卡片；与按 card_id 更新实体是不同接口。"""
        resource_id(message_id, "message_id")
        body = PatchMessageRequestBody.builder().content(_card_json(card)).build()
        request = PatchMessageRequest.builder().message_id(message_id).request_body(body).build()
        api = im_client()
        await sdk_response(lambda: api.message.patch(request))

    async def recall(self, message_id: str) -> None:
        """撤回消息（含卡片）；权限、时间窗和发送身份由飞书校验。"""
        resource_id(message_id, "message_id")
        request = DeleteMessageRequest.builder().message_id(message_id).build()
        api = im_client()
        await sdk_response(lambda: api.message.delete(request))

    async def delayed_update_card(
        self, token: str, card: dict[str, JsonValue], *, open_ids: list[str] | None = None,
    ) -> None:
        """使用交互回调 token 延时更新；须在回调响应已交付后调用，不自行 sleep 或调度。"""
        resource_id(token, "token")
        _card_json(card)
        body: dict[str, JsonValue] = {"token": token, "card": card}
        if open_ids is not None:
            if not open_ids:
                raise ValueError("open_ids 不能是空列表")
            for open_id in open_ids:
                resource_id(open_id, "open_id")
            body["open_ids"] = list(open_ids)
        request = _legacy_card_request("/open-apis/interactive/v1/card/update", body)
        api = _client()
        await sdk_response(lambda: api.request(request))

    async def send_ephemeral_card(self, chat_id: str, open_id: str, card: dict[str, JsonValue]) -> str:
        """在群内发送仅指定用户可见的卡片。"""
        resource_id(chat_id, "chat_id")
        resource_id(open_id, "open_id")
        _card_json(card)
        request = _legacy_card_request("/open-apis/ephemeral/v1/send", {
            "chat_id": chat_id, "open_id": open_id, "msg_type": "interactive", "card": card,
        })
        api = _client()
        data = await sdk_call(lambda: api.request(request))
        message_id = data.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            raise FeishuResponseError("飞书临时卡片响应缺少有效的 message_id")
        return message_id

    async def delete_ephemeral_card(self, message_id: str) -> None:
        """删除仅指定用户可见的卡片；普通消息请使用 recall。"""
        resource_id(message_id, "message_id")
        request = _legacy_card_request("/open-apis/ephemeral/v1/delete", {"message_id": message_id})
        api = _client()
        await sdk_response(lambda: api.request(request))


class Card:
    """一张卡片的本地对象，持有 ID、操作序号和更新锁。

    新卡片用 create/create_template；接管已有卡片须显式提供已知 sequence。
    同一卡片应复用同一个对象及事件循环，不提供跨对象/进程协调或持久化。
    """

    def __init__(self, card_id: str, *, sequence: int) -> None:
        self._card_id = resource_id(card_id, "card_id")
        if type(sequence) is not int or not 0 <= sequence <= 2147483647:
            raise ValueError("已知 sequence 必须为 0～2147483647 的整数")
        self._sequence = sequence
        self._message_id: str | None = None
        self._api = CardAPI()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: asyncio.Task[None] | None = None

    @property
    def card_id(self) -> str:
        """飞书卡片实体 ID，只读。"""
        return self._card_id

    @property
    def sequence(self) -> int:
        """已分配的最后一个更新序号；请求失败或取消后也不回退。"""
        return self._sequence

    @property
    def message_id(self) -> str | None:
        """最近一次成功发送/回复的消息 ID；尚未发送时为 None。"""
        return self._message_id

    @classmethod
    async def create(
        cls, card: dict[str, JsonValue], *, receive_id: str | None = None,
        receive_id_type: Literal["open_id", "union_id", "user_id", "email", "chat_id"] = "open_id",
        uuid: str | None = None,
    ) -> "Card":
        """创建流式卡片；传 receive_id 时同时投递，返回后可直接 stream_text。

        自动设置 streaming_mode/update_multi，不修改传入字典。
        创建、投递是两次远程请求，不是原子操作；失败直接抛出，不自动重试。
        """
        if receive_id is not None:
            validate_recipient(receive_id, receive_id_type=receive_id_type, uuid=uuid)
        _card_json(card)
        config = card.get("config", {})
        if not isinstance(config, dict):
            raise ValueError("card.config 必须是 JSON 对象")
        payload = {**card, "config": {**config, "streaming_mode": True, "update_multi": True}}
        instance = cls(await CardAPI().create(payload), sequence=0)
        if receive_id is not None:
            await instance._send_created(receive_id, receive_id_type=receive_id_type, uuid=uuid)
        return instance

    @classmethod
    async def create_template(
        cls, template_id: str, *, variables: dict[str, JsonValue] | None = None,
        version: str | None = None, receive_id: str | None = None,
        receive_id_type: Literal["open_id", "union_id", "user_id", "email", "chat_id"] = "open_id",
        uuid: str | None = None,
    ) -> "Card":
        """创建模板实体后启用流式，传 receive_id 时同时投递。"""
        if receive_id is not None:
            validate_recipient(receive_id, receive_id_type=receive_id_type, uuid=uuid)
        instance = cls(await CardAPI().create_template(template_id, variables=variables, version=version), sequence=0)
        await instance.update_settings({"config": {"streaming_mode": True, "update_multi": True}})
        if receive_id is not None:
            await instance._send_created(receive_id, receive_id_type=receive_id_type, uuid=uuid)
        return instance

    @classmethod
    async def from_message(cls, message_id: str, *, sequence: int) -> "Card":
        """转换消息 ID 后接管实体；接口不会查询或恢复序号，须由调用方提供。"""
        if type(sequence) is not int or not 0 <= sequence <= 2147483647:
            raise ValueError("已知 sequence 必须为 0～2147483647 的整数")
        instance = cls(await CardAPI().id_from_message(message_id), sequence=sequence)
        instance._message_id = message_id
        return instance

    def as_reference(self) -> dict[str, JsonValue]:
        """生成底层投递所需的实体引用；普通业务不必手工使用。"""
        return {"type": "card", "data": {"card_id": self.card_id}}

    async def send(
        self, receive_id: str, *,
        receive_id_type: Literal["open_id", "union_id", "user_id", "email", "chat_id"] = "open_id",
        uuid: str | None = None,
    ) -> str:
        """发送实体引用并返回 message_id；发送不消耗 CardKit 更新序号。"""
        self._message_id = await self._api.send_card(receive_id, self.as_reference(), receive_id_type=receive_id_type, uuid=uuid)
        return self._message_id

    async def _send_created(
        self, receive_id: str, *,
        receive_id_type: Literal["open_id", "union_id", "user_id", "email", "chat_id"],
        uuid: str | None,
    ) -> None:
        try:
            await self.send(receive_id, receive_id_type=receive_id_type, uuid=uuid)
        except (Exception, asyncio.CancelledError):
            # 创建工厂抛错后业务拿不到对象，由这里尽力关闭流式模式。
            try:
                await self.finish()
            except Exception as error:
                logger.warning("关闭新卡片流式模式失败：%s", type(error).__name__)
            raise

    async def reply(self, message_id: str, *, reply_in_thread: bool = False, uuid: str | None = None) -> str:
        """用本卡片回复消息，返回新 message_id。"""
        self._message_id = await self._api.reply_card(message_id, self.as_reference(), reply_in_thread=reply_in_thread, uuid=uuid)
        return self._message_id

    async def _mutate(self, operation: Callable[[int], Awaitable[None]]) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("同一个 Card 对象须在同一事件循环中更新")
        self._loop = loop
        await self._lock.acquire()
        if self._sequence >= 2147483647:
            self._lock.release()
            raise ValueError("卡片 sequence 已达到 int32 上限")
        self._sequence += 1
        sequence = self._sequence

        async def execute() -> None:
            try:
                await operation(sequence)
            finally:
                self._lock.release()

        # 调用方取消时，SDK 线程可能仍在运行；保留锁直至本次调用结束，
        # 后续更新才能开始。仅排队等待锁的调用被取消时，不发请求、不占序号。
        task = asyncio.create_task(execute())
        self._pending = task

        def completed(done: asyncio.Task[None]) -> None:
            if self._pending is done:
                self._pending = None
            if not done.cancelled():
                done.exception()  # 调用方已取消时也消费异常；正常调用仍经 await 抛出。

        task.add_done_callback(completed)
        await asyncio.shield(task)

    async def stream_text(self, element_id: str, text: str, *, uuid: str | None = None) -> None:
        """提交累计全文，自动递增序号。"""
        await self._mutate(lambda seq: self._api.stream_text(self.card_id, element_id, text, sequence=seq, uuid=uuid))

    async def finish(self) -> None:
        """结束本轮流式输出，保留已提交的组件结构和内容。

        与其他更新共用锁和递增序号，关闭流式模式，不重写整张卡片。
        调用前应 await 所有业务更新；失败直接抛出，不自动重试。
        """
        await self.set_streaming(False)

    async def set_streaming(self, enabled: bool, *, uuid: str | None = None) -> None:
        await self._mutate(lambda seq: self._api.set_streaming(self.card_id, enabled, sequence=seq, uuid=uuid))

    async def update_settings(self, settings: dict[str, JsonValue], *, uuid: str | None = None) -> None:
        await self._mutate(lambda seq: self._api.update_settings(self.card_id, settings, sequence=seq, uuid=uuid))

    async def update(self, card: dict[str, JsonValue], *, uuid: str | None = None) -> None:
        await self._mutate(lambda seq: self._api.update(self.card_id, card, sequence=seq, uuid=uuid))

    async def batch_update(self, actions: list[dict[str, JsonValue]], *, uuid: str | None = None) -> None:
        await self._mutate(lambda seq: self._api.batch_update(self.card_id, actions, sequence=seq, uuid=uuid))

    async def add_elements(
        self, elements: list[dict[str, JsonValue]], *,
        placement: Literal["insert_before", "insert_after", "append"], target_element_id: str,
        uuid: str | None = None,
    ) -> None:
        await self._mutate(lambda seq: self._api.add_elements(
            self.card_id, elements, placement=placement, target_element_id=target_element_id, sequence=seq, uuid=uuid,
        ))

    async def update_element(self, element_id: str, element: dict[str, JsonValue], *, uuid: str | None = None) -> None:
        await self._mutate(lambda seq: self._api.update_element(self.card_id, element_id, element, sequence=seq, uuid=uuid))

    async def patch_element(self, element_id: str, partial_element: dict[str, JsonValue], *, uuid: str | None = None) -> None:
        await self._mutate(lambda seq: self._api.patch_element(self.card_id, element_id, partial_element, sequence=seq, uuid=uuid))

    async def delete_element(self, element_id: str, *, uuid: str | None = None) -> None:
        await self._mutate(lambda seq: self._api.delete_element(self.card_id, element_id, sequence=seq, uuid=uuid))


def _legacy_card_request(path: str, body: dict[str, JsonValue]) -> BaseRequest:
    # SDK 未提供这三个历史卡片接口的生成式 Builder，使用其官方通用请求入口。
    return (BaseRequest.builder().http_method(HttpMethod.POST).uri(path)
            .token_types({AccessTokenType.TENANT}).body(body).build())

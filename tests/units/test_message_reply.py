"""Mock Agent 与飞书边界，验证卡片业务编排；不发送真实消息。"""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from deal_pilot.event.message.card_schema import CONTENT_ID, STATUS_ID
from deal_pilot.utils.run_agent import AgentOutput, AgentStatus

reply_module = importlib.import_module("deal_pilot.event.message.reply")


@pytest.fixture
def boundary(monkeypatch):
    card = SimpleNamespace(patch_element=AsyncMock(), finish=AsyncMock())
    create = AsyncMock(return_value=card)
    monkeypatch.setattr(reply_module, "Card", SimpleNamespace(create=create))
    calls = []
    closed = []

    def install(outputs=(), error=None):
        async def run_agent(agent_name, input, *, user_id):
            calls.append((agent_name, input, user_id))
            try:
                for output in outputs:
                    yield output
                if error is not None:
                    raise error
            finally:
                closed.append(True)

        monkeypatch.setattr(reply_module, "run_agent", run_agent)
        return card, create, calls, closed

    return install


def test_reply_coalesces_burst_and_flushes_latest(boundary):
    card, create, calls, closed = boundary(
        [
            AgentOutput(AgentStatus.PROCESSING),
            AgentOutput(AgentStatus.THINKING),
            AgentOutput(AgentStatus.REPLYING, "先查询"),
            AgentOutput(AgentStatus.CALLING_TOOL, "先查询", {"tool_name": "search"}),
            AgentOutput(AgentStatus.THINKING, "先查询"),
            AgentOutput(AgentStatus.REPLYING, "结果"),
            AgentOutput(AgentStatus.REPLYING, "结果如下"),
            AgentOutput(AgentStatus.COMPLETED, "结果如下"),
        ]
    )
    asyncio.run(reply_module.reply("open-id", "用户问题"))
    assert calls == [("main_agent", "用户问题", "open-id")]
    assert create.await_args.kwargs == {"receive_id": "open-id"}
    schema = create.await_args.args[0]
    elements = {item.get("element_id"): item for item in schema["body"]["elements"]}
    assert elements[CONTENT_ID]["content"] == " "
    assert elements[STATUS_ID]["content"] == "<font color='grey'>正在处理…</font>"
    assert [
        item
        for item in card.patch_element.await_args_list
        if item.args[0] == CONTENT_ID
    ] == [
        call(CONTENT_ID, {"content": "结果如下"}),
    ]
    assert card.patch_element.await_args_list[-1] == call(
        STATUS_ID, {"content": "<font color='grey'>已完成</font>"}
    )
    card.finish.assert_awaited_once()
    assert closed == [True]


def test_agent_failure_keeps_partial_content_and_finishes(boundary):
    card, _, _, closed = boundary(
        [
            AgentOutput(AgentStatus.REPLYING, "部分回答"),
            AgentOutput(AgentStatus.FAILED, "部分回答", {"reason": "Agent 执行超时"}),
        ]
    )
    asyncio.run(reply_module.reply("u", "q"))
    assert card.patch_element.await_args_list[-1] == call(
        STATUS_ID,
        {"content": "<font color='grey'>失败：Agent 执行超时</font>"},
    )
    assert (
        sum(item.args[0] == CONTENT_ID for item in card.patch_element.await_args_list)
        == 1
    )
    card.finish.assert_awaited_once()
    assert closed == [True]


@pytest.mark.parametrize("final_content", ["", "新一轮回答"])
def test_latest_generation_replaces_displayed_text(
    boundary, monkeypatch, final_content
):
    card, _, _, _ = boundary()

    async def scenario():
        first_sent = asyncio.Event()

        async def patch_element(element_id, partial_element):
            text = partial_element["content"]
            if element_id == CONTENT_ID and text == "临时回答":
                first_sent.set()

        async def run_agent(*args, **kwargs):
            yield AgentOutput(AgentStatus.REPLYING, "临时回答")
            await first_sent.wait()
            yield AgentOutput(AgentStatus.COMPLETED, final_content)

        monkeypatch.setattr(reply_module, "run_agent", run_agent)
        card.patch_element.side_effect = patch_element
        await asyncio.wait_for(reply_module.reply("u", "q"), timeout=2)

    asyncio.run(scenario())
    assert [
        item
        for item in card.patch_element.await_args_list
        if item.args[0] == CONTENT_ID
    ] == [
        call(CONTENT_ID, {"content": "临时回答"}),
        call(CONTENT_ID, {"content": final_content or " "}),
    ]
    card.finish.assert_awaited_once()


def test_slow_card_does_not_block_agent_and_final_content_precedes_finish(
    boundary, monkeypatch
):
    card, _, _, _ = boundary()
    operations = []

    async def scenario():
        request_started = asyncio.Event()
        release_request = asyncio.Event()
        agent_done = asyncio.Event()

        async def patch_element(element_id, partial_element):
            text = partial_element["content"]
            operations.append((element_id, text))
            if element_id == CONTENT_ID and text == "开头":
                request_started.set()
                await release_request.wait()

        async def finish():
            operations.append("finish")

        async def run_agent(*args, **kwargs):
            yield AgentOutput(AgentStatus.REPLYING, "开头")
            await request_started.wait()
            for length in range(1, 1001):
                yield AgentOutput(AgentStatus.REPLYING, "文" * length)
            yield AgentOutput(AgentStatus.COMPLETED, "最终完整回答")
            agent_done.set()

        monkeypatch.setattr(reply_module, "run_agent", run_agent)
        card.patch_element.side_effect = patch_element
        card.finish.side_effect = finish
        task = asyncio.create_task(reply_module.reply("u", "q"))
        await asyncio.wait_for(agent_done.wait(), timeout=2)
        # 飞书请求还未完成，模型流已全部读完，没有积压千次卡片更新。
        assert operations == [(CONTENT_ID, "开头")]
        assert not task.done()
        release_request.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    assert [
        op for op in operations if isinstance(op, tuple) and op[0] == CONTENT_ID
    ] == [
        (CONTENT_ID, "开头"),
        (CONTENT_ID, "最终完整回答"),
    ]
    assert operations[-2:] == [
        (STATUS_ID, "<font color='grey'>已完成</font>"),
        "finish",
    ]


def test_tool_status_updates_while_agent_waits(boundary, monkeypatch):
    card, _, _, _ = boundary()

    async def scenario():
        status_sent = asyncio.Event()

        async def patch_element(element_id, partial_element):
            text = partial_element["content"]
            if element_id == STATUS_ID and "search" in text:
                status_sent.set()

        async def run_agent(*args, **kwargs):
            yield AgentOutput(AgentStatus.CALLING_TOOL, payload={"tool_name": "search"})
            await status_sent.wait()
            yield AgentOutput(AgentStatus.COMPLETED, "回答")

        monkeypatch.setattr(reply_module, "run_agent", run_agent)
        card.patch_element.side_effect = patch_element
        await asyncio.wait_for(reply_module.reply("u", "q"), timeout=2)

    asyncio.run(scenario())
    assert (
        call(STATUS_ID, {"content": "<font color='grey'>正在调用工具：search</font>"})
        in card.patch_element.await_args_list
    )


@pytest.mark.parametrize(
    "error", [ValueError("private configuration"), asyncio.CancelledError()]
)
def test_agent_exception_or_cancellation_closes_stream_and_card(boundary, error):
    card, _, _, closed = boundary(error=error)
    with pytest.raises(type(error)) as caught:
        asyncio.run(reply_module.reply("u", "q"))
    assert caught.value is error
    card.patch_element.assert_not_awaited()
    card.finish.assert_awaited_once()
    assert closed == [True]


def test_card_update_failure_closes_agent_and_card(boundary):
    card, _, _, closed = boundary(
        [
            AgentOutput(AgentStatus.REPLYING, "部分"),
            AgentOutput(AgentStatus.COMPLETED, "完整"),
        ]
    )
    error = RuntimeError("update failed")
    card.patch_element.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(reply_module.reply("u", "q"))
    assert caught.value is error
    card.finish.assert_awaited_once()
    assert closed == [True]


@pytest.mark.parametrize("cancel_reply", [False, True])
def test_stopping_reply_closes_background_reader(boundary, monkeypatch, cancel_reply):
    card, _, _, _ = boundary()
    closed = []

    async def scenario():
        reading = asyncio.Event()
        keep_reading = asyncio.Event()

        async def run_agent(*args, **kwargs):
            try:
                yield AgentOutput(AgentStatus.REPLYING, "部分回答")
                reading.set()
                await keep_reading.wait()
            finally:
                closed.append(True)

        monkeypatch.setattr(reply_module, "run_agent", run_agent)
        if not cancel_reply:
            card.patch_element.side_effect = RuntimeError("update failed")
        task = asyncio.create_task(reply_module.reply("u", "q"))
        await asyncio.wait_for(reading.wait(), timeout=2)
        if cancel_reply:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel_reply else RuntimeError):
            await asyncio.wait_for(task, timeout=2)
        assert closed == [True]
        card.finish.assert_awaited_once()

    asyncio.run(scenario())


def test_creation_failure_does_not_start_agent(boundary):
    card, create, calls, closed = boundary()
    create.side_effect = RuntimeError("create failed")
    with pytest.raises(RuntimeError, match="create failed"):
        asyncio.run(reply_module.reply("u", "q"))
    assert calls == closed == []
    card.finish.assert_not_awaited()


def test_normal_finish_failure_is_not_hidden(boundary):
    card, _, _, _ = boundary([AgentOutput(AgentStatus.COMPLETED, "回答")])
    card.finish.side_effect = RuntimeError("finish failed")
    with pytest.raises(RuntimeError, match="finish failed"):
        asyncio.run(reply_module.reply("u", "q"))

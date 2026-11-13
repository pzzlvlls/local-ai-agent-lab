"""使用真实 LangGraph SDK 和 Mock HTTP，验证流协议、身份及输出契约。"""

import asyncio
import importlib
import json

import httpx
import pytest
from langgraph_sdk.client import LangGraphClient
from pydantic import SecretStr

from deal_pilot.config.agent_settings import AgentSettings
from deal_pilot.event.message.status import CardStatus
from deal_pilot.security import agent_token
from deal_pilot.utils.run_agent import AgentStatus, run_agent

runner = importlib.import_module("deal_pilot.utils.run_agent")


def event(kind, *, run_id="model-1", node="model", namespace=None, **data):
    return (
        "events",
        {
            "event": kind,
            "run_id": run_id,
            "name": data.pop("name", "test"),
            "metadata": {
                "langgraph_node": node,
                "langgraph_checkpoint_ns": namespace or f"{node}:node-id",
            },
            "data": data,
        },
    )


def chunk(text, **kwargs):
    return event("on_chat_model_stream", chunk={"content": text}, **kwargs)


@pytest.fixture
def server(monkeypatch):
    settings = AgentSettings(
        _env_file=None,
        server_url="http://agent.test",
        token_secret=SecretStr("test-only-secret-" * 3),
        token_ttl_seconds=300,
    )
    monkeypatch.setattr(runner, "agent_settings", settings)
    monkeypatch.setattr(agent_token, "agent_settings", settings)
    requests = []
    clients = []

    def install(events, *, status="success", error=None, metadata=True):
        def handle(request):
            requests.append(request)
            token = request.headers["authorization"].removeprefix("Bearer ")
            agent_token.verify_agent_token(token)
            if error is not None:
                if isinstance(error, BaseException):
                    raise error
                return httpx.Response(error, json={"detail": "private server error"})
            if request.url.path == "/threads":
                return httpx.Response(
                    200, json={"thread_id": json.loads(request.content)["thread_id"]}
                )
            if request.url.path.endswith("/stream"):
                parts = [("metadata", {"run_id": "run-1"})] if metadata else []
                parts += events
                body = "".join(
                    f"id: {i}\nevent: {name}\ndata: {json.dumps(data)}\n\n"
                    for i, (name, data) in enumerate(parts)
                )
                return httpx.Response(
                    200, text=body, headers={"Content-Type": "text/event-stream"}
                )
            assert request.url.path.endswith("/runs/run-1")
            return httpx.Response(200, json={"run_id": "run-1", "status": status})

        def get_client(**kwargs):
            client = httpx.AsyncClient(
                base_url=kwargs["url"],
                headers=kwargs["headers"],
                transport=httpx.MockTransport(handle),
            )
            clients.append(client)
            return LangGraphClient(client)

        monkeypatch.setattr(runner, "get_client", get_client)
        return requests, clients

    return install


def collect(**kwargs):
    async def run():
        return [
            item
            async for item in run_agent(
                kwargs.get("agent_name", "main_agent"),
                kwargs.get("input", "问题"),
                user_id=kwargs.get("user_id", "open-id"),
            )
        ]

    return asyncio.run(run())


def test_stream_reasoning_tools_text_and_completion(server):
    requests, clients = server(
        [
            event("on_chat_model_start"),
            chunk([{"type": "reasoning", "reasoning": "private"}]),
            event("on_tool_start", run_id="tool-1", node="tools", name="search"),
            event(
                "on_tool_end", run_id="tool-1", node="tools", output="private result"
            ),
            event("on_chat_model_start", run_id="model-2"),
            chunk("你好", run_id="model-2"),
            chunk([{"type": "text", "text": "，世界"}], run_id="model-2"),
            event(
                "on_chat_model_end", run_id="model-2", output={"content": "你好，世界"}
            ),
        ]
    )
    outputs = collect()
    assert [item.status for item in outputs] == [
        AgentStatus.PROCESSING,
        AgentStatus.THINKING,
        AgentStatus.CALLING_TOOL,
        AgentStatus.PROCESSING,
        AgentStatus.THINKING,
        AgentStatus.REPLYING,
        AgentStatus.REPLYING,
        AgentStatus.COMPLETED,
    ]
    assert outputs[2].payload == {"tool_name": "search"}
    assert outputs[-2].content == outputs[-1].content == "你好，世界"
    assert outputs[-1].payload == {}
    assert outputs[0].content == ""
    body = json.loads(requests[1].content)
    assert body["multitask_strategy"] == "enqueue"
    assert body["input"] == {"messages": [{"role": "user", "content": "问题"}]}
    assert body["stream_mode"] == ["events", "updates"]
    assert body["stream_subgraphs"] is True
    assert all(client.is_closed for client in clients)


def test_fixed_thread_is_scoped_to_user_and_agent_and_preserves_blocks(server):
    requests, _ = server([])
    blocks = [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
    ]
    collect(input=blocks)
    collect()
    collect(user_id="other")
    collect(agent_name="retrieve_agent")
    ids = [
        json.loads(request.content)["thread_id"]
        for request in requests
        if request.url.path == "/threads"
    ]
    assert ids[0] == ids[1]
    assert len(set(ids)) == 3
    assert json.loads(requests[1].content)["input"]["messages"][0]["content"] == blocks


def test_nested_models_are_visible_but_summary_and_history_are_not(server):
    server(
        [
            chunk("子 Agent 正文", run_id="child", namespace="tools:1|model:2"),
            chunk("private summary", node="SummarizationMiddleware.before_model"),
            ("values", {"messages": [{"content": "old answer"}]}),
            chunk("临时正文"),
            (
                "updates",
                {
                    "model": {
                        "structured_response": {"answer": "**最终回答**", "sources": []}
                    }
                },
            ),
        ]
    )
    outputs = collect()
    assert [item.content for item in outputs] == [
        "",
        "子 Agent 正文",
        "临时正文",
        "**最终回答**",
        "**最终回答**",
    ]


def test_each_model_generation_replaces_previous_text(server):
    server(
        [
            chunk("先查询", run_id="first"),
            event("on_chat_model_end", run_id="first", output={"content": "先查询"}),
            event("on_tool_start", node="tools", run_id="tool", name="search"),
            event("on_tool_end", node="tools", run_id="tool"),
            event("on_chat_model_start", run_id="second"),
            chunk([{"type": "reasoning", "reasoning": "private"}], run_id="second"),
            chunk("查询结果", run_id="second"),
            chunk("如下", run_id="second"),
            event(
                "on_chat_model_end", run_id="second", output={"content": "查询结果如下"}
            ),
        ]
    )
    outputs = collect()
    assert [
        item.content for item in outputs if item.status == AgentStatus.REPLYING
    ] == [
        "先查询",
        "查询结果",
        "查询结果如下",
    ]
    assert (
        next(item for item in outputs if item.status == AgentStatus.THINKING).content
        == "先查询"
    )
    assert outputs[-1].content == "查询结果如下"


def test_nested_thinking_tools_and_parallel_model_buffers(server):
    child = "tools:parent|tools:child|model:node"
    server(
        [
            event("on_tool_start", node="tools", run_id="parent-tool", name="task"),
            event("on_chat_model_start", run_id="a", namespace=child),
            chunk("甲", run_id="a", namespace=child),
            event(
                "on_chat_model_start", run_id="b", namespace="tools:other|model:node"
            ),
            chunk("乙", run_id="b", namespace="tools:other|model:node"),
            chunk("一", run_id="a", namespace=child),
            event(
                "on_tool_start",
                node="tools",
                run_id="inner-tool",
                name="search",
                namespace=child,
            ),
            event("on_tool_end", node="tools", run_id="inner-tool", namespace=child),
            chunk("二", run_id="b", namespace="tools:other|model:node"),
            event(
                "on_chat_model_end",
                run_id="a",
                namespace=child,
                output={"content": "甲一"},
            ),
            event(
                "on_chat_model_end",
                run_id="b",
                namespace="tools:other|model:node",
                output={"content": "乙二"},
            ),
            event("on_tool_end", node="tools", run_id="parent-tool"),
            event("on_chat_model_start", run_id="parent"),
            chunk("父 Agent 回复", run_id="parent"),
        ]
    )
    outputs = collect()
    assert [
        item.content for item in outputs if item.status == AgentStatus.REPLYING
    ] == [
        "甲",
        "乙",
        "甲一",
        "乙二",
        "甲一",
        "乙二",
        "父 Agent 回复",
    ]
    assert sum(item.status == AgentStatus.THINKING for item in outputs) == 3
    assert any(item.payload == {"tool_name": "search"} for item in outputs)
    assert [item.status for item in outputs].count(AgentStatus.COMPLETED) == 1
    assert outputs[-1].content == "父 Agent 回复"


def test_child_structured_answer_does_not_block_next_generation(server):
    server(
        [
            (
                "updates|tools:parent",
                {"model": {"structured_response": {"answer": "子任务结果"}}},
            ),
            event("on_chat_model_start", run_id="parent"),
            chunk("父任务", run_id="parent"),
            chunk("结果", run_id="parent"),
            (
                "updates",
                {"model": {"structured_response": {"answer": "父任务最终结果"}}},
            ),
        ]
    )
    outputs = collect()
    assert [
        item.content for item in outputs if item.status == AgentStatus.REPLYING
    ] == [
        "子任务结果",
        "父任务",
        "父任务结果",
        "父任务最终结果",
    ]
    assert outputs[-1].content == "父任务最终结果"


def test_parallel_tools_and_recoverable_tool_error(server):
    server(
        [
            event("on_tool_start", node="tools", run_id="a", name="search"),
            event("on_tool_start", node="tools", run_id="b", name="query"),
            event("on_tool_end", node="tools", run_id="a"),
            event("on_tool_error", node="tools", run_id="b"),
            event("on_chat_model_end", output={"content": "已处理"}),
        ]
    )
    outputs = collect()
    assert outputs[2].payload == {"tool_name": "query"}
    assert outputs[-1].status == AgentStatus.COMPLETED
    assert outputs[-1].content == "已处理"


@pytest.mark.parametrize("length", [199, 200, 201])
@pytest.mark.parametrize("source", ["stream", "end", "structured"])
def test_subagent_content_limit_and_full_parent_answer(server, length, source):
    child_text = "子" * length
    parent_text = "主" * 250
    if source == "structured":
        events = [
            (
                "updates|tools:parent",
                {"model": {"structured_response": {"answer": child_text}}},
            ),
            ("updates", {"model": {"structured_response": {"answer": parent_text}}}),
        ]
    elif source == "end":
        events = [
            event(
                "on_chat_model_end",
                run_id="child",
                namespace="tools:parent|model:child",
                output={"content": child_text},
            ),
            event("on_chat_model_end", output={"content": parent_text}),
        ]
    else:
        events = [
            chunk(child_text, run_id="child", namespace="tools:parent|model:child"),
            chunk(parent_text),
        ]
    server(events)
    outputs = collect()
    expected = child_text if length <= 200 else child_text[:200] + "…"
    assert [
        item.content for item in outputs if item.status == AgentStatus.REPLYING
    ] == [
        expected,
        parent_text,
    ]
    assert outputs[-1].content == parent_text


def test_subagent_stream_stops_repeated_content_updates_after_limit(server):
    child = {"run_id": "child", "namespace": "tools:parent|tools:child|model:node"}
    server(
        [
            chunk("甲" * 199, **child),
            chunk("乙", **child),
            chunk("丙", **child),
            chunk("丁" * 100, **child),
            event(
                "on_chat_model_end",
                output={"content": "甲" * 199 + "乙丙" + "丁" * 100},
                **child,
            ),
            chunk("新一轮", run_id="next-child", namespace=child["namespace"]),
            chunk("主" * 250),
            chunk("继续"),
        ]
    )
    outputs = collect()
    assert [
        item.content for item in outputs if item.status == AgentStatus.REPLYING
    ] == [
        "甲" * 199,
        "甲" * 199 + "乙",
        "甲" * 199 + "乙…",
        "新一轮",
        "主" * 250,
        "主" * 250 + "继续",
    ]


@pytest.mark.parametrize("status", ["error", "timeout", "interrupted", "running"])
def test_unsuccessful_run_preserves_partial_answer(server, status):
    server([chunk("部分回答")], status=status)
    outputs = collect()
    assert outputs[-1].status == AgentStatus.FAILED
    assert outputs[-1].content == "部分回答"
    assert outputs[-1].payload["reason"]
    assert not any(item.status == AgentStatus.COMPLETED for item in outputs)


def test_error_event_is_sanitized_and_closes_client(server):
    requests, clients = server(
        [chunk("部分"), ("error", {"message": "secret password"})]
    )
    outputs = collect()
    assert outputs[-1].status == AgentStatus.FAILED
    assert outputs[-1].content == "部分"
    assert "secret" not in repr(outputs)
    assert len(requests) == 2
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize(
    "error",
    [
        401,
        403,
        500,
        httpx.ConnectError("private address"),
        httpx.ReadTimeout("private"),
    ],
)
def test_http_failure(server, error):
    _, clients = server([], error=error)
    outputs = collect()
    assert outputs[-1].status == AgentStatus.FAILED
    assert "private" not in repr(outputs)
    assert all(client.is_closed for client in clients)


def test_missing_run_id_does_not_claim_success(server):
    server([], metadata=False)
    assert collect()[-1].status == AgentStatus.FAILED


def test_cancellation_propagates_and_client_closes(server):
    _, clients = server([], error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        collect()
    assert all(client.is_closed for client in clients)


def test_consumer_close_releases_client(server):
    _, clients = server([chunk("部分"), chunk("其余")])

    async def run():
        stream = run_agent("main_agent", "hi", user_id="u")
        await anext(stream)
        await anext(stream)
        await stream.aclose()

    asyncio.run(run())
    assert all(client.is_closed for client in clients)


def test_shared_enum_card_text():
    assert (
        CardStatus(AgentStatus.CALLING_TOOL, {"tool_name": "search"}).get_text()
        == "正在调用工具：search"
    )
    assert CardStatus(AgentStatus.FAILED, {"reason": "超时"}).get_text() == "失败：超时"
    assert CardStatus(AgentStatus.FAILED).get_text() == "失败"


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_real_local_agent_events_match_adapter(server, structured, nested):
    """真实 Agent 产出事件，替换模型和 HTTP；不依赖 Agent Server 或外部模型。"""
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langchain_core.runnables import RunnableConfig
    from langgraph_api.serde import json_dumpb
    from pydantic import BaseModel

    class ToolModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    @tool
    def lookup(query: str) -> str:
        """Lookup test data."""
        return "private tool result"

    class Answer(BaseModel):
        answer: str

    answer = "来自真实事件的回答" * 30
    final = AIMessage(content=answer)
    if structured:
        final = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "response-1",
                    "name": "Answer",
                    "args": {"answer": answer},
                }
            ],
        )
    graph = create_agent(
        ToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "call-1", "name": "lookup", "args": {"query": "q"}}
                    ],
                ),
                final,
            ]
        ),
        tools=[lookup],
        response_format=ToolStrategy(Answer) if structured else None,
    )

    if nested:
        child = graph

        @tool
        async def delegate(query: str, config: RunnableConfig) -> str:
            """Delegate to a child Agent."""
            await child.ainvoke(
                {"messages": [{"role": "user", "content": query}]}, config
            )
            return "private child result"

        graph = create_agent(
            ToolModel(
                responses=[
                    AIMessage(
                        content="先委派任务",
                        tool_calls=[
                            {
                                "id": "delegate-1",
                                "name": "delegate",
                                "args": {"query": "q"},
                            }
                        ],
                    ),
                    AIMessage(content="父 Agent 最终回答"),
                ]
            ),
            tools=[delegate],
        )

    async def events():
        result = []
        root = None
        async for item in graph.astream_events(
            {"messages": [{"role": "user", "content": "hi"}]},
            version="v2",
            stream_mode=["updates"],
            subgraphs=True,
        ):
            root = root or item["run_id"]
            item = json.loads(json_dumpb(item))
            if item["event"] == "on_chain_stream" and item["run_id"] == root:
                namespace, mode, update = item["data"]["chunk"]
                result.append(("|".join([mode, *namespace]), update))
            else:
                result.append(("events", item))
        return result

    server(asyncio.run(events()))
    outputs = collect()
    assert any(item.payload == {"tool_name": "lookup"} for item in outputs)
    assert outputs[-1].content == ("父 Agent 最终回答" if nested else answer)
    expected = answer[:200] + "…" if nested else answer
    assert any(item.content == expected for item in outputs)
    if nested:
        assert not any(item.content == answer for item in outputs)
    assert outputs[-1].status == AgentStatus.COMPLETED
    assert "private" not in repr(outputs)

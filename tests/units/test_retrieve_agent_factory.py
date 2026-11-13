"""真实本地 Agent 图配合假模型，验证检索工厂与主 Agent 委派。"""

import asyncio
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from deal_pilot.agents.agent_factory import AgentFactory
from deal_pilot.agents.retrieve_agent import RetrieveAgentFactory, RetrieveResponse
from deal_pilot.config.nacos.nacos_schemas import AgentSpec, RagConfig

retrieval = importlib.import_module("deal_pilot.agents.retrieve_agent")
factories = importlib.import_module("deal_pilot.agents.agent_factory")
context = importlib.import_module("deal_pilot.middlewares.retrieve_context")
nacos = importlib.import_module("deal_pilot.config.nacos.nacos_agent_spec")


def test_retrieve_agent_structured_result_and_parent_delegation(monkeypatch):
    bound_tools = set()

    class ToolModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            bound_tools.update(
                convert_to_openai_tool(item)["function"]["name"] for item in tools
            )
            return self

    @tool
    def lookup(query: str) -> str:
        """返回本地测试资料。"""
        return "报销需提供凭证"

    answer = {
        "status": "answered",
        "answer": "报销需提供凭证",
        "sources": [{"title": "报销说明", "url": None}],
        "gaps": [],
    }
    model = ToolModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "lookup-1",
                        "name": "lookup",
                        "args": {"query": "报销"},
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "answer-1",
                        "name": "RetrieveResponse",
                        "args": answer,
                    }
                ],
            ),
        ]
    )
    spec = AgentSpec(name="retrieve_agent", skills=["unused"], subagents=["unused"])
    get_spec = AsyncMock(return_value=spec)
    monkeypatch.setattr(retrieval, "get_agent_spec", get_spec)
    monkeypatch.setattr(factories, "get_agent_spec", get_spec)
    monkeypatch.setattr(context, "get_config", AsyncMock(return_value=RagConfig()))
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(context, "search", search)
    child_factory = RetrieveAgentFactory()
    monkeypatch.setattr(child_factory, "_get_model", lambda: model)
    monkeypatch.setattr(child_factory, "_get_tools", AsyncMock(return_value=[lookup]))
    monkeypatch.setattr(retrieval, "factory", child_factory.factory)

    def unexpected(*args, **kwargs):
        raise AssertionError("检索 Agent 不应创建沙箱或自身的子 Agent")

    monkeypatch.setattr(child_factory, "get_backend", unexpected)
    monkeypatch.setattr(child_factory, "_get_subagents", unexpected)

    class ParentFactory(AgentFactory):
        @property
        def name(self) -> str:
            return "main_agent"

        def get_backend(self):
            return None

    async def run():
        child = await child_factory.factory()
        result = await child.ainvoke(
            {"messages": [{"role": "user", "content": "报销要求"}]}
        )
        assert isinstance(result["structured_response"], RetrieveResponse)
        assert result["structured_response"].model_dump() == answer
        assert bound_tools == {"lookup", "RetrieveResponse"}
        assert "files" not in result
        assert "todos" not in result

        parent_factory = ParentFactory()
        parent_factory.agent_config = AgentSpec(
            name="main_agent", subagents=["retrieve_agent"]
        )
        subagents = await parent_factory._get_subagents()
        parent_model = ToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "task-1",
                            "name": "task",
                            "args": {
                                "subagent_type": "retrieve_agent",
                                "description": "报销要求",
                            },
                        }
                    ],
                ),
                AIMessage(content="最终答复：报销需提供凭证"),
            ]
        )
        parent = await parent_factory.create_agent(
            model=parent_model,
            system_prompt="回答用户问题",
            tools=[],
            subagents=subagents,
            skills=[],
        )
        result = await parent.ainvoke(
            {"messages": [{"role": "user", "content": "报销要求"}]}
        )
        report = next(msg for msg in result["messages"] if isinstance(msg, ToolMessage))
        assert json.loads(report.content) == answer
        assert result["messages"][-1].content == "最终答复：报销需提供凭证"

    asyncio.run(run())
    assert search.await_count == 2
    assert all(
        call.kwargs == {"sync_skills": False} for call in get_spec.await_args_list
    )


@pytest.mark.parametrize("sync_skills", [False, True])
def test_agent_spec_can_skip_skill_sandbox(monkeypatch, sync_skills):
    def handle(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "content": json.dumps({"skills": ["example"]}),
                    "resource": {},
                },
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        nacos.httpx,
        "AsyncClient",
        lambda **kwargs: client(
            **kwargs,
            transport=httpx.MockTransport(handle),
        ),
    )
    monkeypatch.setattr(
        nacos,
        "nacos_settings",
        SimpleNamespace(
            server_address="http://nacos.test",
            namespace_id="test",
        ),
    )
    monkeypatch.setattr(nacos, "get_access_token", AsyncMock(return_value="test-token"))
    monkeypatch.setattr(nacos, "get_prompts", AsyncMock(return_value="test prompt"))
    save_skills = AsyncMock()
    monkeypatch.setattr(nacos, "save_skills", save_skills)
    spec = asyncio.run(
        nacos.get_agent_spec.__wrapped__("retrieve_agent", sync_skills=sync_skills)
    )
    assert spec.system_prompt == "\n\ntest prompt"
    if sync_skills:
        save_skills.assert_awaited_once_with("retrieve_agent", ["example"])
    else:
        save_skills.assert_not_awaited()

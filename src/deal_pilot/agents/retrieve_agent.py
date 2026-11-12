from collections.abc import Sequence
from typing import Any, Literal

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field

from deal_pilot.utils.trace_wrapper import trace_wrapper
from deal_pilot.agents.agent_factory import AgentFactory
from deal_pilot.middlewares.retrieve_context import retrieve_context


class Source(BaseModel):
    title: str = Field(
        description="实际引用的来源文档标题，使用检索结果中的标题，不编造"
    )
    url: str | None = Field(
        description="检索结果提供的来源文档链接；缺失时为 null，不编造，也不使用图片链接代替"
    )


class RetrieveResponse(BaseModel):
    """基于本次检索材料生成的回答。"""

    status: Literal["answered", "partial", "unanswerable"] = Field(
        description=(
            "answered：材料足以回答；partial：只能回答部分内容；"
            "unanswerable：材料无法支持回答。检索有命中不代表材料足以回答"
        )
    )
    answer: str = Field(
        description=(
            "基于本次检索材料生成的 Markdown 正文，保留条件、例外和必要的来源引用；"
            "需要展示图片时使用工具实际返回的图片 URL。"
            "材料无法支持回答时，简要说明材料不足，不编造业务事实"
        )
    )
    sources: list[Source] = Field(
        description=(
            "仅列出与本次问题相关、且实际用于支持回答内容的来源文档，"
            "不直接复制全部检索结果。"
            "检索结果中与问题无关、或未被回答采用的来源不列出。"
            "按来源文档去重；没有符合条件的来源时返回空列表"
        )
    )
    gaps: list[str] = Field(
        description="尚缺少的信息或无法解决的材料冲突；没有则返回空列表"
    )


class RetrieveAgentFactory(AgentFactory):
    @property
    def name(self) -> str:
        return "retrieve_agent"

    def get_middlewares(self) -> Sequence[AgentMiddleware[AgentState[Any], None, Any]]:
        return [retrieve_context]

    def get_response_format(self) -> ToolStrategy[RetrieveResponse]:
        return ToolStrategy(RetrieveResponse)


retrieve_agent_factory = RetrieveAgentFactory()

factory = retrieve_agent_factory.factory

factory_with_trace = trace_wrapper(factory)

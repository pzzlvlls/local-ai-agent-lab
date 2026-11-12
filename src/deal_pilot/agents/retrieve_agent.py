from collections.abc import Sequence
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware

from deal_pilot.utils.trace_wrapper import trace_wrapper
from deal_pilot.agents.agent_factory import AgentFactory
from deal_pilot.middlewares.retrieve_context import retrieve_context


class RetrieveAgentFactory(AgentFactory):
    @property
    def name(self) -> str:
        return "retrieve_agent"

    def get_middlewares(self) -> Sequence[AgentMiddleware[AgentState[Any], None, Any]]:
        return [retrieve_context]


retrieve_agent_factory = RetrieveAgentFactory()

factory = retrieve_agent_factory.factory

factory_with_trace = trace_wrapper(factory)

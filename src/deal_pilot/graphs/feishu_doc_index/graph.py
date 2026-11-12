"""主图：分批获取 node，动态扇出到子图，处理完成后继续取下一批。"""

from typing import Literal

from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from deal_pilot.feishu.api.models import WikiNode
from deal_pilot.graphs.feishu_doc_index.state import (
    FeishuDocIndexContext,
    FeishuDocIndexState,
)
from deal_pilot.utils.trace_wrapper import trace_wrapper
from deal_pilot.feishu.api import WikiAPI
from deal_pilot.graphs.feishu_doc_index.document_index.graph import graph as doc_graph


async def factory() -> CompiledStateGraph[FeishuDocIndexState, FeishuDocIndexContext]:
    """每次运行只保留自己的迭代器，用于继续取下一批。"""
    node_iter = WikiAPI().list_all_space_nodes()

    async def fetch_batch_node(
        state: FeishuDocIndexState, runtime: Runtime[FeishuDocIndexContext]
    ) -> Command[Literal["index_document", "__end__"]]:
        """取到 node 就更新统计并直接扇出，没有 node 就结束。"""
        concurrency = 3
        if runtime.context and "concurrency" in runtime.context:
            concurrency = runtime.context["concurrency"]

        nodes: list[WikiNode] = []  # 该批次待处理的node
        for _ in range(concurrency):
            node = await anext(node_iter, None)
            if node is not None and node.obj_type == "docx":
                nodes.append(node)
        node_count = len(nodes)
        if node_count == 0:
            return Command(goto="__end__")
        return Command(
            update={"batch_count": 1, "node_count": node_count},
            goto=[Send("index_document", node) for node in nodes],
        )

    async def index_document(state: WikiNode) -> FeishuDocIndexState:
        """调用单文档子图，失败时记录文档信息，其余文档继续处理。"""
        try:
            result = await doc_graph.ainvoke({"node": state})
            status = result["status"]
            if status == "success":
                return {"indexed_count": 1}
            else:
                return {"skipped_count": 1}
        except Exception as error:
            return {
                "failure_count": 1,
                "failures": [
                    {
                        "node_token": state.node_token,
                        "title": state.title,
                        "message": str(error),
                    }
                ],
            }

    builder = StateGraph(FeishuDocIndexState, context_schema=FeishuDocIndexContext)
    builder.add_node("fetch_batch", fetch_batch_node)
    builder.add_node("index_document", index_document)
    builder.add_edge(START, "fetch_batch")
    # 本批所有子图返回后，才进入下一次取批。
    builder.add_edge("index_document", "fetch_batch")
    return builder.compile(name="feishu_doc_index")


factory_with_trace = trace_wrapper(factory)

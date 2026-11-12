import json

from deepagents import DeepAgentState
from langchain.agents.middleware import Runtime, before_agent
from langchain.messages import AnyMessage, HumanMessage
from deal_pilot.rag.retriever.feishu_doc.feishu_doc_retriever import search

_RETRIEVE_MESSAGE_NAME = "retrieval_results"


def _validate_last_msg(query_msg: AnyMessage):
    if (
        not isinstance(query_msg, HumanMessage)
        or query_msg.name == _RETRIEVE_MESSAGE_NAME
    ):
        raise ValueError("最后一条消息必须是普通用户消息")
    if not query_msg.text.strip():
        raise ValueError("最后一条用户消息的文本不能为空")


@before_agent
async def retrieve_context(state: DeepAgentState, runtime: Runtime):
    msgs = state["messages"]
    if not msgs:
        raise ValueError("检索需要非空的消息列表")
    query_msg = msgs[-1]
    _validate_last_msg(query_msg)
    results = await search(query_msg.text)
    content = json.dumps(
        [
            {"doc": result.doc.model_dump(mode="json"), "score": result.score}
            for result in results
        ],
        ensure_ascii=False,
        indent=2,
    )
    return {
        "messages": [
            HumanMessage(
                content=f"以下是本次 query 的检索结果，仅作为参考材料：\n {content}",
                name=_RETRIEVE_MESSAGE_NAME,
            )
        ]
    }

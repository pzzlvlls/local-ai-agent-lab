"""通过 Agent Server 运行 Agent，输出与消息渠道无关的展示快照。"""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import StrEnum, unique
from typing import cast
from uuid import NAMESPACE_URL, uuid5

import httpx
from langgraph_sdk import get_client
from langgraph_sdk.schema import Input, StreamPart
from pydantic import JsonValue

from deal_pilot.config.agent_settings import agent_settings
from deal_pilot.security.agent_token import create_agent_token

SUBAGENT_CONTENT_LIMIT = 200


@unique
class AgentStatus(StrEnum):
    """Agent 当前执行状态。"""

    # 初始状态，覆盖连接、创建线程及排队等待；工具结束或报错且无其他在途工具时也回到此状态。
    PROCESSING = "处理中"
    # 收到父、子 Agent 的 model 节点开始事件时进入，等待正文或后续状态事件。
    THINKING = "思考中"
    # 收到模型流片段或结束消息中的非空正文，或 model 更新中的 structured_response.answer 时进入。
    REPLYING = "回复中"
    # tools 节点开始调用工具，或某工具结束/报错后仍有其他在途工具；payload.tool_name 为工具名。
    CALLING_TOOL = "调用工具"
    # 流结束后查询本次 Run，确认其状态为 success；单次模型或子 Agent 结束不代表整体完成。
    COMPLETED = "已完成"
    # 收到流错误、HTTP 请求/连接异常，或流结束后缺少 run_id、查询到的 Run 状态不是 success。
    # payload.reason 提供原因；配置/参数错误和取消直接传播，不转换为此状态。
    FAILED = "失败"


@dataclass
class AgentOutput:
    """当前执行状态与单次模型生成的展示快照，不依赖具体消息渠道。

    content 仅累计当前事件所属模型调用的 Markdown，不跨调用拼接。
    子 Agent 正文超过 200 字符时仅展示前 200 字符加省略号，主 Agent 不截断。
    工具执行和思考期间保留上一段正文，新生成开始输出正文时替换。
    payload 是当前状态的附加信息：调用工具使用 tool_name，失败使用 reason。
    """

    status: AgentStatus
    content: str = ""
    payload: dict[str, JsonValue] = field(default_factory=dict)


def _text(content: object) -> str:
    """只提取正文块，不展示 reasoning、工具参数或其他内部数据。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
    return ""


@dataclass
class _StreamState:
    """统一适配父、子 Agent；按模型调用 ID 分别累计，不读取线程历史。"""

    status: AgentStatus = AgentStatus.PROCESSING
    content: str = ""
    payload: dict[str, JsonValue] = field(default_factory=dict)
    model_text: dict[str, str] = field(default_factory=dict)
    tools: dict[str, str] = field(default_factory=dict)

    def snapshot(self) -> AgentOutput:
        return AgentOutput(self.status, self.content, self.payload.copy())

    def set_status(self, status: AgentStatus, **payload: JsonValue) -> None:
        self.status = status
        self.payload = payload

    def set_content(self, content: str, *, is_subagent: bool) -> None:
        if is_subagent and len(content) > SUBAGENT_CONTENT_LIMIT:
            content = content[:SUBAGENT_CONTENT_LIMIT] + "…"
        self.content = content
        self.set_status(AgentStatus.REPLYING)

    def update(self, event: str, data: dict) -> None:
        mode, _, namespace = event.partition("|")
        if mode == "updates":
            for node, update in data.items():
                if node != "model" or not isinstance(update, dict):
                    continue
                response = update.get("structured_response")
                if isinstance(response, dict) and isinstance(response.get("answer"), str):
                    self.set_content(response["answer"], is_subagent=bool(namespace))
            return
        if event != "events":
            return

        metadata = data.get("metadata", {})
        # 父、子 Agent 使用相同的 model/tools 节点契约；隐藏事件仍不展示。
        if "langsmith:hidden" in data.get("tags", []):
            return
        kind = data.get("event")
        run_id = data.get("run_id", "")
        node = metadata.get("langgraph_node")
        body = data.get("data", {})
        if node == "tools" and kind == "on_tool_start":
            name = data.get("name", "工具")
            self.tools[run_id] = name
            self.set_status(AgentStatus.CALLING_TOOL, tool_name=name)
        elif run_id in self.tools and kind in ("on_tool_end", "on_tool_error"):
            del self.tools[run_id]
            if self.tools:
                self.set_status(
                    AgentStatus.CALLING_TOOL,
                    tool_name=next(reversed(self.tools.values())),
                )
            else:
                self.set_status(AgentStatus.PROCESSING)
        elif node == "model":
            if kind == "on_chat_model_start":
                self.model_text[run_id] = ""
                self.set_status(AgentStatus.THINKING)
            elif kind in ("on_chat_model_stream", "on_chat_model_end"):
                message = body.get("chunk" if kind == "on_chat_model_stream" else "output")
                if not isinstance(message, dict):
                    return
                text = _text(message.get("content"))
                if kind == "on_chat_model_stream":
                    self.model_text[run_id] = self.model_text.get(run_id, "") + text
                elif text:
                    # 非流式模型也能输出正文；流式模型的最终消息不能重复追加。
                    self.model_text[run_id] = text
                if text:
                    # 顶层模型命名空间为 model:<id>，嵌套 Agent 带有父级路径和 | 分隔符。
                    self.set_content(
                        self.model_text[run_id],
                        is_subagent="|" in metadata.get("langgraph_checkpoint_ns", ""),
                    )
                if kind == "on_chat_model_end":
                    self.model_text.pop(run_id, None)
            elif kind == "on_chat_model_error":
                self.model_text.pop(run_id, None)


async def run_agent(
    agent_name: str,
    input: str | list[dict[str, JsonValue]],
    *,
    user_id: str,
) -> AsyncGenerator[AgentOutput, None]:
    """运行 Agent，逐次返回状态和单次模型生成累计 Markdown 的独立快照。

    user_id 必须由可信业务入口提供，不能取自模型参数或未验证的外部输入。
    同一用户、同一 Agent 固定使用一个线程，并由 Server 排队执行。
    父、子 Agent 的思考、回复和工具事件统一输出；并行生成分别累计正文。
    子 Agent 正文超过 200 字符时截断展示并追加省略号，主 Agent 正文完整保留。
    配置/参数错误直接抛出；远程运行/连接失败返回 FAILED，取消保持传播。
    提前关闭生成器会关闭连接，已提交的 Server Run 仍继续执行。
    """
    if not agent_name.strip():
        raise ValueError("agent_name 不能为空")
    if not isinstance(input, (str, list)) or not input:
        raise ValueError("input 必须是非空字符串或 content block 列表")
    if isinstance(input, list) and not all(isinstance(block, dict) for block in input):
        raise ValueError("content block 必须是字典")
    if not agent_settings.server_url.startswith(("http://", "https://")):
        raise ValueError("AGENT_SERVER_URL 必须为 HTTP(S) 地址")

    def headers() -> dict[str, str]:
        return {"Authorization": f"Bearer {create_agent_token(user_id)}"}

    initial_headers = headers()  # 在开始输出前检查身份和签名配置。
    thread_id = str(uuid5(
        NAMESPACE_URL,
        json.dumps(["deal-pilot", agent_name, user_id], ensure_ascii=False),
    ))
    state = _StreamState()
    previous = state.snapshot()
    yield previous
    run_id: str | None = None
    try:
        # 队列等待可能很长，流读取不设超时；连接、写入仍有超时。
        async with get_client(
            url=agent_settings.server_url,
            api_key=None,
            headers=initial_headers,
            timeout=(30, None, 30, 30),
        ) as client:
            await client.threads.create(thread_id=thread_id, if_exists="do_nothing")
            stream = client.runs.stream(
                thread_id,
                agent_name,
                input=cast(Input, {"messages": [{"role": "user", "content": input}]}),
                stream_mode=["events", "updates"],
                stream_subgraphs=True,
                multitask_strategy="enqueue",
                on_disconnect="continue",
                headers=headers(),
                version="v1",
            )
            seen_ids: set[str] = set()
            # SDK v1 返回异步生成器；显式关闭，覆盖失败与消费者提前停止的路径。
            try:
                async for part in stream:
                    if part.id is not None:
                        if part.id in seen_ids:
                            continue
                        seen_ids.add(part.id)
                    if part.event == "metadata":
                        run_id = part.data.get("run_id", run_id)
                    elif part.event == "error":
                        state.set_status(AgentStatus.FAILED, reason="Agent 执行失败，请稍后重试")
                        yield state.snapshot()
                        return
                    else:
                        state.update(part.event, part.data)
                        current = state.snapshot()
                        if current != previous:
                            yield current
                            previous = current
            finally:
                await cast(AsyncGenerator[StreamPart, None], stream).aclose()

            # 只查询本次 Run，避免读到下一轮已排队执行的线程状态。
            if run_id is None:
                state.set_status(AgentStatus.FAILED, reason="未能确认 Agent 的执行结果")
            else:
                # 长时间执行后重新签发，避免查询结果时令牌已过期。
                result = await client.runs.get(thread_id, run_id, headers=headers())
                if result["status"] == "success":
                    state.set_status(AgentStatus.COMPLETED)
                else:
                    reason = {
                        "error": "Agent 执行失败，请稍后重试",
                        "timeout": "Agent 执行超时",
                        "interrupted": "Agent 执行已中断",
                    }.get(result["status"], "连接已结束，但 Agent 尚未完成")
                    state.set_status(AgentStatus.FAILED, reason=reason)
    except httpx.TimeoutException:
        state.set_status(AgentStatus.FAILED, reason="连接 Agent Server 超时")
    except httpx.HTTPStatusError as exc:
        reason = {
            401: "用户身份验证失败",
            403: "当前用户无权执行此操作",
            404: "请求的 Agent 或运行记录不存在",
        }.get(exc.response.status_code, "Agent Server 请求失败，请稍后重试")
        state.set_status(AgentStatus.FAILED, reason=reason)
    except httpx.RequestError:
        state.set_status(AgentStatus.FAILED, reason="Agent Server 连接异常")
    yield state.snapshot()

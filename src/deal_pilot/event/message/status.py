from pydantic import JsonValue

from deal_pilot.utils.run_agent import AgentStatus


class CardStatus:
    """卡片状态及载荷，通过固定模板生成展示文本。"""

    def __init__(
        self,
        status_type: AgentStatus,
        payload: dict[str, JsonValue] | None = None,
    ) -> None:
        """载荷可提供 tool_name 或适合向用户展示的 reason。"""
        self.type: AgentStatus = status_type
        self.payload: dict[str, JsonValue] = (
            payload.copy() if payload is not None else {}
        )

    def get_text(self) -> str:
        """返回状态文案；缺少有效的工具名或原因时使用通用文案。"""
        match self.type:
            case AgentStatus.PROCESSING:
                return "正在处理…"
            case AgentStatus.THINKING:
                return "正在思考…"
            case AgentStatus.REPLYING:
                return "正在回复…"
            case AgentStatus.CALLING_TOOL:
                tool_name = self._get_payload_text("tool_name")
                return f"正在调用工具：{tool_name}" if tool_name else "正在调用工具…"
            case AgentStatus.COMPLETED:
                return "已完成"
            case AgentStatus.FAILED:
                reason = self._get_payload_text("reason")
                return f"失败：{reason}" if reason else "失败"
        raise ValueError(f"不支持的卡片状态类型：{self.type}")

    def _get_payload_text(self, key: str) -> str:
        """仅将非空字符串载荷插入文案，其他数据仍保留在载荷中。"""
        value = self.payload.get(key)
        return value.strip() if isinstance(value, str) else ""

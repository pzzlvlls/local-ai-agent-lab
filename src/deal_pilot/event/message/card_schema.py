from pydantic import JsonValue

from deal_pilot.event.message.status import CardStatus
from deal_pilot.utils.run_agent import AgentStatus

STATUS_ID = "status"
CONTENT_ID = "answer"


def create_card_json(*, content: str = "") -> dict[str, JsonValue]:
    """创建处理中卡片；默认空正文。"""
    return {
        "schema": "2.0",
        "config": {"width_mode": "fill"},
        "body": {
            "direction": "vertical",
            "padding": "16px 16px 16px 16px",
            "elements": [
                {
                    "tag": "markdown",
                    "element_id": STATUS_ID,
                    "content": (
                        f"<font color='grey'>{CardStatus(AgentStatus.PROCESSING).get_text()}</font>"
                    ),
                    "text_size": "notation",
                    "text_align": "left",
                    "margin": "0px 0px 8px 0px",
                },
                {
                    "tag": "hr",
                    "margin": "0px 0px 8px 0px",
                },
                {
                    "tag": "markdown",
                    "element_id": CONTENT_ID,
                    "content": content or " ",
                    "text_size": "normal",
                    "text_align": "left",
                    "margin": "0px 0px 0px 0px",
                },
            ],
        },
    }

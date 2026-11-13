CONTENT_ID = "answer"


def create_card_json():
    return {
        "schema": "2.0",
        "config": {"width_mode": "fill"},
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "element_id": CONTENT_ID,
                    "content": "正在思考...",
                }
            ]
        },
    }

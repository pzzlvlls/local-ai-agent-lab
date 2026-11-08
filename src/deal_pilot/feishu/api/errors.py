"""飞书调用错误；不在异常中输出请求体、响应体或访问凭证。"""


class FeishuConfigurationError(RuntimeError):
    """缺少飞书应用配置。"""


class FeishuResponseError(RuntimeError):
    """服务响应不符合协议，无法作为完整读取结果使用。"""


class FeishuAPIError(RuntimeError):
    """飞书业务错误；通过 code 区分认证、权限、限流和资源错误。"""

    def __init__(self, code: int, http_status: int, log_id: str | None) -> None:
        self.code = code
        self.http_status = http_status
        self.log_id = log_id
        super().__init__(f"飞书 API 调用失败：code={code}, HTTP={http_status}")


class FeishuAuthenticationError(RuntimeError):
    """SDK 获取应用 Token 失败；不输出原始错误消息。"""

    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"飞书 SDK 获取应用 Token 失败：code={code}")


class FeishuHTTPError(RuntimeError):
    """SDK 返回非正常 HTTP 状态；保留状态和排障 ID。"""

    def __init__(self, http_status: int, log_id: str | None) -> None:
        self.http_status = http_status
        self.log_id = log_id
        super().__init__(f"飞书 HTTP 调用失败：HTTP={http_status}")


class UnsupportedWikiNodeTypeError(RuntimeError):
    """当前只支持 docx，不能将其他类型节点伪装成新版文档。"""

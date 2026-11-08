"""通过官方 Drive 素材接口下载文档图片。"""

import json

from lark_oapi.api.drive.v1 import DownloadMediaRequest, DownloadMediaResponse

from deal_pilot.feishu.api._client import drive_client, object_value, resource_id, sdk_response
from deal_pilot.feishu.api.errors import FeishuHTTPError, FeishuResponseError
from deal_pilot.feishu.api.models import DownloadedImage


class ImageAPI:
    """以应用身份下载图片；传入 Docx 图片块的 image.token。"""

    async def download_image(self, token: str) -> DownloadedImage:
        token = resource_id(token, "token")
        api = drive_client()
        request = DownloadMediaRequest.builder().file_token(token).build()

        def download() -> DownloadMediaResponse:
            response = api.media.download(request)
            raw = response.raw
            if raw is not None:
                headers = {key.lower(): value for key, value in raw.headers.items()}
                mime = headers.get("content-type", "").split(";", 1)[0].strip().lower()
                # SDK 将所有 2xx 都视为二进制成功，且错误 JSON 的头名区分大小写。
                # 从原始 JSON 恢复业务 code，交给共同边界校验，不能把错误当图片。
                if mime == "application/json":
                    payload = object_value(json.loads(raw.content or b""), "响应")
                    code = payload.get("code")
                    response.code = code if type(code) is int else None
                elif type(raw.status_code) is int and not 200 <= raw.status_code < 300:
                    raise FeishuHTTPError(raw.status_code, headers.get("x-tt-logid"))
            return response

        response = await sdk_response(download)
        raw = response.raw
        assert raw is not None
        mime = next((value for key, value in raw.headers.items() if key.lower() == "content-type"), "")
        mime = mime.split(";", 1)[0].strip().lower()
        if not mime.startswith("image/") or not mime[6:] or not isinstance(raw.content, bytes):
            raise FeishuResponseError("飞书下载响应缺少有效的图片 MIME 类型或字节数据")
        return DownloadedImage(mime=mime, data=raw.content)

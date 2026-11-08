"""飞书只读 API；仅导出类，导入时不创建客户端或发起请求。"""

from deal_pilot.feishu.api.docx import DocxAPI
from deal_pilot.feishu.api.image import ImageAPI
from deal_pilot.feishu.api.wiki import WikiAPI

__all__ = ["WikiAPI", "DocxAPI", "ImageAPI"]

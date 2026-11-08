"""飞书读取接口的返回值规格；是应用层模型，不是 SDK 响应类。"""

from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class WikiSpace(BaseModel):
    """知识空间基本信息。"""

    space_id: str = Field(description="知识空间 ID")
    name: str = Field(description="知识空间名称")
    description: str | None = Field(default=None, description="知识空间描述")


class WikiNode(BaseModel):
    """知识库目录节点；节点身份与实际内容的身份分开保存。"""

    node_token: str = Field(description="知识库节点 token，不是文档 ID")
    space_id: str = Field(description="所属知识空间 ID")
    obj_token: str = Field(description="实际文档 token，交给 DocxAPI 读取文档")
    obj_type: Literal["docx"] = Field(description="内容类型，MVP 仅支持新版文档 docx")
    title: str = Field(description="节点标题")
    url: str = Field(
        min_length=1,
        description="知识库节点访问地址，按 https://www.feishu.cn/wiki/{node_token} 拼接",
    )
    has_child: bool = Field(description="是否有子节点")
    parent_node_token: str | None = Field(default=None, description="父节点；根节点为 None")


class DocxDocument(BaseModel):
    """新版文档元信息，不包含正文。"""

    document_id: str = Field(description="新版文档 ID，即 docx 类型节点的 obj_token")
    title: str = Field(description="文档标题")
    revision_id: int = Field(description="文档版本号")


class DocxBlock(BaseModel):
    """文档块的公共字段及完整原始数据，不在本层转换为 Markdown。"""

    block_id: str = Field(description="块 ID")
    block_type: int = Field(description="飞书定义的块类型编号")
    parent_id: str | None = Field(default=None, description="父块 ID；根块为 None")
    children: list[str] = Field(default_factory=list, description="按原始顺序排列的子块 ID")
    raw: dict[str, JsonValue] = Field(description="完整的原始块 JSON，保留富文本及未知字段")



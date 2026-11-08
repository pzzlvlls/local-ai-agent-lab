import base64
import json
import mimetypes
from fnmatch import fnmatchcase

from botocore.exceptions import ClientError
from pydantic import BaseModel

from deal_pilot.config.minio_settings import minio_settings
from deal_pilot.config.nacos.nacos_config import get_config
from deal_pilot.config.nacos.nacos_schemas import RagConfig
from deal_pilot.rag.structure.feishu_doc.block_node import BlockNode
from deal_pilot.rag.structure.feishu_doc.block_type import BlockType
from deal_pilot.utils.minio import MinIO


class ImageLocation(BaseModel):
    bucket_name: str
    filename: str


class AttachmentInfo(BaseModel):
    parent_trace: list[str]
    prevs: list[str]
    nexts: list[str]


def _generate_dataurl(data: bytes, mime: str) -> str:
    """生成供模型输入使用的 Data URL，不用于持久化。"""
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


async def _upload_minio(data: bytes, mime: str, block_id: str) -> ImageLocation:
    """将图片保存到配置的私有桶根目录；拒绝公共桶，不改写已有权限。"""
    media_type = mime.split(";", 1)[0].strip().lower()
    extension = mimetypes.guess_extension(media_type, strict=False)
    if not media_type.startswith("image/") or extension is None:
        raise ValueError("mime 必须是具有已知文件后缀的图片 MIME 类型")
    if not block_id or block_id in {".", ".."} or any(c in block_id for c in "/\\\x00"):
        raise ValueError("block_id 必须是非空且不包含路径的块 ID")
    config = await get_config("rag_config", RagConfig)
    bucket_name = config.image_parser.bucket_name
    filename = f"{block_id}{extension}"
    client = MinIO(
        endpoint=minio_settings.endpoint,
        access_key=minio_settings.access_key,
        secret_key=minio_settings.secret_key,
        secure=minio_settings.secure,
    )
    await client.create_bucket(bucket_name, allow_public_read=False)
    # create_bucket(False) 不撤销已有策略；当前 MinIO 的 policyStatus 不能可靠识别公共读。
    # 保守检查实际策略，不尝试模拟 Condition/Deny 的完整 IAM 求值。
    async with client._client() as s3:
        try:
            response = await s3.get_bucket_policy(Bucket=bucket_name)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "NoSuchBucketPolicy":
                raise
        else:
            policy = json.loads(response["Policy"])
            statements = policy["Statement"]
            if isinstance(statements, dict):
                statements = [statements]
            for statement in statements:
                if statement["Effect"] != "Allow":
                    continue
                principal = statement.get("Principal")
                public = principal == "*" or "NotPrincipal" in statement
                if isinstance(principal, dict):
                    public = public or any(
                        value == "*" or isinstance(value, list) and "*" in value
                        for value in principal.values()
                    )
                actions = statement.get("Action", [])
                if isinstance(actions, str):
                    actions = [actions]
                readable = "NotAction" in statement or any(
                    fnmatchcase(action, pattern)
                    for pattern in actions
                    for action in ("s3:GetObject", "s3:GetObjectVersion")
                )
                if public and readable:
                    raise ValueError("图片桶必须禁用公共读，存在匿名读取授权时拒绝上传")
    await client.upload_bytes(bucket_name=bucket_name, filename=filename, data=data, mime=mime)
    return ImageLocation(bucket_name=bucket_name, filename=filename)


async def _attachment_info(image_block: BlockNode) -> AttachmentInfo:
    """仅从父链及同父兄弟提取图片上下文，不修改树。"""
    config = await get_config("rag_config", RagConfig)
    count = config.image_parser.sibling_count
    if count < 0:
        raise ValueError("sibling_count 不能为负数")
    parent_trace: list[str] = []
    parent = image_block.parent
    while parent is not None:
        if parent.content:
            parent_trace.append(parent.content)
        parent = parent.parent
    parent_trace.reverse()

    prevs: list[str] = []
    previous = image_block.prev
    while previous is not None and previous.parent is image_block.parent and len(prevs) < count:
        prevs.append(previous.content)
        previous = previous.prev
    prevs.reverse()

    nexts: list[str] = []
    following = image_block.next
    while following is not None and following.parent is image_block.parent and len(nexts) < count:
        if following.block_type != BlockType.IMAGE:
            nexts.append(following.content)
        following = following.next
    return AttachmentInfo(parent_trace=parent_trace, prevs=prevs, nexts=nexts)


async def parse_image_block(image_block: BlockNode) -> None:
    image_block.payload = {"token": image_block.content}
    image_block.content = f"图片token: {image_block.content}"

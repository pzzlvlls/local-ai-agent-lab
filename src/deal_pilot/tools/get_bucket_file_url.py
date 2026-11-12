from langchain.tools import tool

from deal_pilot.utils.minio import MinIO
from deal_pilot.config.minio_settings import minio_settings


@tool
async def get_bucket_file_url(bucket_name: str, bucket_filename: str):
    """
    返回一个临时可访问的MinIO文件URL，该URL有效期为1小时
    参数：
    - bucket_name: 存储桶的名称
    - bucket_filename: 文件名称
    """
    minio = MinIO(
        endpoint=minio_settings.endpoint,
        access_key=minio_settings.access_key,
        secret_key=minio_settings.secret_key,
        secure=minio_settings.secure,
    )
    return await minio.presigned_get_file_url(
        bucket_name=bucket_name, filename=bucket_filename
    )

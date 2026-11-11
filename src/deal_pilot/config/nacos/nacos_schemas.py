from typing import Literal, get_args

from pydantic import BaseModel, Field
from deal_pilot.config.openai_settings import openai_settings


class AgentModelConfig(BaseModel):
    name: str = Field(default=openai_settings.default_model)
    thinking: bool = Field(default=True)
    temperature: float | None = Field(default=None)
    top_p: float | None = Field(default=None)


class MCPServerConfig(BaseModel):
    name: str
    url: str
    disabled_tools: list[str] = Field(default_factory=list)


class AgentSpec(BaseModel):
    name: str
    description: str = Field(default="")
    system_prompt: str = Field(default="")
    model: AgentModelConfig = Field(default_factory=AgentModelConfig)
    mcps: dict[str, MCPServerConfig] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    subagents: list[str] = Field(default_factory=list)
    link_prompts: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class OpenSandboxConfig(BaseModel):
    image: str = Field(default="python:3.12-slim", min_length=1)
    timeout_seconds: int = Field(default=600, gt=0)
    ready_timeout_seconds: int = Field(default=180, gt=0)
    command_timeout_seconds: int = Field(default=90, gt=0)


class RagImageParser(BaseModel):
    bucket_name: str = Field(
        description="配置待索引的图像所在的桶名", default="feishu-images"
    )
    sibling_count: int = Field(
        description="参与图像上下文前后兄弟节点的数量", default=3
    )
    vl_model_config: AgentModelConfig = Field(
        description="描述图片的模型配置", default_factory=AgentModelConfig
    )
    image_parser_prompt: str = Field(default="image_parser_prompt")


class RagEmbeddingModel(BaseModel):
    model_name: str = Field(default="text-embedding")
    chunk_size: int = Field(default=10)
    dimensions: int = Field(default=1024)


class RagStoreConfig(BaseModel):
    index_type: str = Field(description="索引类型", default="HNSW")
    metric_type: str = Field(description="相似度计算算法", default="COSINE")


type MilvusCollection = Literal["feishu_doc"]


class RagConfig(BaseModel):
    image_parser: RagImageParser = Field(default_factory=RagImageParser)
    embedding_model: RagEmbeddingModel = Field(default_factory=RagEmbeddingModel)
    store: dict[MilvusCollection, RagStoreConfig] = Field(
        default_factory=lambda: {
            name: RagStoreConfig() for name in get_args(MilvusCollection.__value__)
        }
    )

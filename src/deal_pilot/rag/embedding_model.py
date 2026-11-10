from deal_pilot.config.nacos.nacos_schemas import RagEmbeddingModel
from langchain_openai import OpenAIEmbeddings


def create_embedding_model(config: RagEmbeddingModel | None = None):
    if config is None:
        config = RagEmbeddingModel()
    return OpenAIEmbeddings(
        model=config.model_name,
        check_embedding_ctx_length=False,
        model_kwargs={"encoding_format": "float"},
        chunk_size=config.chunk_size,
        dimensions=config.dimensions,
    )

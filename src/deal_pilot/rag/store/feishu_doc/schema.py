from pymilvus import (
    CollectionSchema,
    Function,
    FunctionType,
    AsyncMilvusClient,
    DataType,
)


def create_schema(dim: int) -> CollectionSchema:
    """构造飞书切片的 Schema；Document.id 映射到主键 id，不创建集合。"""
    schema = AsyncMilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field("id", DataType.VARCHAR, max_length=64, is_primary=True)
    # 待检索的文本字段需要开启分析器功能
    schema.add_field(
        "text",
        DataType.VARCHAR,
        max_length=10000,
        enable_analyzer=True,
        analyzer_params={"type": "chinese"},
    )

    # 来源结构：关系字段仍指向原 block_id，而不是切片 id。
    schema.add_field("space_id", DataType.VARCHAR, max_length=64)
    # 已有集合原地新增字段要求可空；历史数据由 backfill_space_titles 回填。
    schema.add_field("space_title", DataType.VARCHAR, max_length=300, nullable=True)
    schema.add_field("node_token", DataType.VARCHAR, max_length=64)
    schema.add_field("node_title", DataType.VARCHAR, max_length=300)
    schema.add_field("obj_token", DataType.VARCHAR, max_length=64)
    schema.add_field("revision_id", DataType.INT64)
    schema.add_field("block_id", DataType.VARCHAR, max_length=64)
    schema.add_field("block_type", DataType.INT64)
    schema.add_field("kind", DataType.VARCHAR, max_length=16)
    schema.add_field("payload", DataType.JSON)
    schema.add_field("order", DataType.INT64)
    schema.add_field("parent_block_id", DataType.VARCHAR, max_length=64, nullable=True)
    schema.add_field("url", DataType.VARCHAR, max_length=200)
    schema.add_field(
        "parent_node_token", DataType.VARCHAR, max_length=64, nullable=True
    )
    # JSON 保留标题字符串列表、引用对象列表的原始结构。
    schema.add_field("title_path", DataType.JSON)
    schema.add_field("references", DataType.JSON)

    # 切片位置；只有表格切片含原表行号。
    schema.add_field("chunk_index", DataType.INT64)
    schema.add_field("chunk_count", DataType.INT64)
    schema.add_field("table_row_index", DataType.INT64, nullable=True)

    # 稠密向量
    schema.add_field("dense", DataType.FLOAT_VECTOR, dim=dim)

    # 新增稀疏向量字段
    schema.add_field(
        field_name="sparse",
        datatype=DataType.SPARSE_FLOAT_VECTOR,
    )

    # 新增稀疏向量入库函数
    bm25_function = Function(
        name="text_to_bm25",
        input_field_names=["text"],
        output_field_names=["sparse"],
        function_type=FunctionType.BM25,
    )
    schema.add_function(bm25_function)
    return schema

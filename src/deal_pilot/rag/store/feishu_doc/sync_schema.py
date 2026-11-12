"""比较并原地同步 Schema；不可安全原地更新的差异在写入前报错。"""

import ast
import json
from typing import Any

from pymilvus import AsyncMilvusClient, CollectionSchema, DataType


def _value(value: Any) -> Any:
    """归一化 SDK 返回的字符串布尔、数字及 JSON 参数。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    return value


def _functions(functions: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for function in functions:
        names = {}
        for key in ("input_field_names", "output_field_names"):
            value = function[key]
            # describe_collection 在当前 SDK 中将 repeated 字段转成 Python 列表字符串。
            names[key] = ast.literal_eval(value) if isinstance(value, str) else value
        result[function["name"]] = {
            "type": function["type"], "params": _value(function.get("params", {})), **names
        }
    return result


async def sync_schema(
    collection_name: str, schema: CollectionSchema, *, client: AsyncMilvusClient
) -> bool:
    """同步可空标量新增及 VARCHAR 长度扩容；返回是否执行了更新。

    全量预检后才写入。删除、类型/维度/分析器/Function 等变化需要另行迁移，
    不自动删除集合或已有数据。服务端操作失败直接传播，已完成操作不回滚。
    """
    actual = await client.describe_collection(collection_name=collection_name)
    expected = schema.to_dict()
    errors: list[str] = []
    additions: list[dict[str, Any]] = []
    changes: list[tuple[str, dict[str, Any]]] = []
    for key in ("auto_id", "enable_dynamic_field", "enable_namespace"):
        if actual.get(key, False) != expected.get(key, False):
            errors.append(key)
    if _functions(actual.get("functions", [])) != _functions(expected.get("functions", [])):
        errors.append("functions")
    fields = {field["name"]: field for field in actual["fields"] if not field.get("is_dynamic")}
    target = {field["name"]: field for field in expected["fields"]}
    errors.extend(f"删除字段 {name}" for name in fields.keys() - target.keys())
    scalar_types = {
        DataType.BOOL, DataType.INT8, DataType.INT16, DataType.INT32, DataType.INT64,
        DataType.FLOAT, DataType.DOUBLE, DataType.VARCHAR, DataType.JSON,
    }
    for name, field in target.items():
        old = fields.get(name)
        if old is None:
            if field["type"] not in scalar_types or not field.get("nullable", False):
                errors.append(f"新增字段 {name} 必须是 nullable 标量字段")
            else:
                additions.append(field)
            continue
        for key in ("type", "is_primary", "is_partition_key", "is_clustering_key", "nullable", "is_function_output", "element_type", "default_value"):
            default = False if key.startswith("is_") or key == "nullable" else None
            if _value(old.get(key, default)) != _value(field.get(key, default)):
                errors.append(f"{name}.{key}")
        old_params = _value(old.get("params", {}))
        params = _value(field.get("params", {}))
        updates = {}
        for key in old_params.keys() | params.keys():
            if old_params.get(key) == params.get(key):
                continue
            if (
                key == "max_length" and field["type"] == DataType.VARCHAR
                and not field.get("is_primary", False)
                and isinstance(params.get(key), int) and isinstance(old_params.get(key), int)
                and params[key] > old_params[key]
            ):
                updates[key] = params[key]
            else:
                errors.append(f"{name}.{key}")
        if updates:
            changes.append((name, updates))
    if errors:
        raise ValueError("Milvus Schema 存在需要显式迁移的差异：" + "、".join(errors))
    for field in additions:
        await client.add_collection_field(
            collection_name=collection_name, field_name=field["name"],
            data_type=field["type"], nullable=True,
            **field.get("params", {}),
            **({"default_value": field["default_value"]} if "default_value" in field else {}),
        )
    for name, params in changes:
        await client.alter_collection_field(
            collection_name=collection_name, field_name=name, field_params=params
        )
    return bool(additions or changes)

# RAG 存储

- 当前仅有 `feishu_doc`，负责 Milvus Schema、索引参数、显式调用的存储初始化及缓存的 LangChain Milvus 对象获取；具体接口及字段契约见 `feishu_doc/AGENTS.md`。
- 正式实现位于本目录，通过 `deal_pilot.rag.store...` 导入；旧 `resource/store` 副本已移除，不再作为实现或导入来源。
- Milvus 连接地址和数据库名来自 `config/milvus_settings.py`；存储及 Embedding 配置来自 Nacos `rag_config`，不在此复制环境配置。
- `get_store()` 返回对象提供文档向量化写入和稠密/BM25 混合检索；`graphs/feishu_doc_index/document_index` 使用其异步客户端查询版本，通过 `aupsert` 写入切片、`adelete` 清理旧版本实体。业务编排归属图模块，未接入 Agent 或服务启动流程。`__init__.py` 为空，导入包不触发初始化。
- Schema 同步及标题回填的本地测试为 `tests/units/test_feishu_doc_schema.py`；真实 Milvus 隔离测试为 `tests/integrations/test_feishu_doc_schema.py`，设置 `MILVUS_INTEGRATION=1` 启用。后者仅替换 Nacos 配置和飞书标题来源，不代表真实飞书/Nacos 联调。
- 修改工厂可先验证本地 SDK Schema/索引参数构造；初始化与重建涉及真实数据库写操作，验证时使用隔离的临时数据库，不修改已有业务集合。区分源码检查、Mock 与真实 Milvus/Nacos 联调结果。

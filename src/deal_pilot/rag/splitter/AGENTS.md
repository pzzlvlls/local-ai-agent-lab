# Documents 进一步切片

- 目标：消费 loader 已提取的结构 Documents，生成适合后续索引的切片，不重新读取来源或构树。
- 选定方案：按来源组织实现；飞书入口为 `feishu_doc/feishu_doc_splitter.py:split_feishu_doc`，具体契约见下级指令。
- 原因：保留 loader 的结构提取约定，由 splitter 单独负责长度、重叠和表格行粒度。
- 实现状态：本地飞书 Documents 切片；不执行模型、向量化、存储或检索，不要求持久化原始 Documents。

# 飞书文档索引主图

## 职责与结构

- 对应 `课件/29. LangGraph实现索引流水线.md`，负责知识库目录分批、动态扇出、批次循环和统计；单文档业务归属 `document_index/`。保持课堂流程所需结构，不添加教学范围之外的功能。
- `graph.py:async factory()` 创建 `WikiAPI().list_all_space_nodes()` 异步迭代器及编译图；`factory_with_trace = trace_wrapper(factory)` 复用现有追踪包装，在 `langgraph.json` 以 `feishu_doc_index` 注册。
- `state.py` 定义 `FeishuDocIndexContext` 和 `FeishuDocIndexState`。Context 只有 `concurrency: int`；状态的 batch_count、node_count、indexed_count、skipped_count、failure_count 与 failures 均使用 add reducer。失败记录只保存字符串 node_token、title、message，不保存异常对象。
- `resource/feishu_doc_index` 是教学骨架，不能据其占位函数推断正式实现状态，也不能用它替代本目录运行。

## 取批、扇出和错误边界

- 主图为 START → fetch_batch → 非空批 Send 到 index_document → 本批全部完成后取下一批；空批直接结束。
- 每次取批最多消费 concurrency 次迭代器，只收集 `obj_type == "docx"` 的节点。默认并发量为 3，可用 `context={"concurrency": N}` 覆盖；调用方应传正整数，当前未额外校验。
- 非 Docx 节点也占一次消费次数，迭代器耗尽后本轮仍继续剩余次数的 anext 调用。末批有 Docx 时仍会处理；一轮没有 Docx 就结束，即使迭代器后续仍有节点。不能宣称会跳过任意数量非 Docx 节点后继续遍历完整知识库。
- 非空批通过 Command.update 累加 batch_count=1、node_count=本批 Docx 数量，再通过 `Send("index_document", node)` 直接传递 WikiNode。过滤掉的其他类型不计入 node_count。
- index_document 以 `{"node": node}` 调用子图 ainvoke；status 为 success 时返回 indexed_count=1，其他返回状态计为 skipped_count=1，不将子图正文和切片合并进主图状态。
- 单文档边界捕获 Exception，返回 failure_count=1 及 failures 记录后继续其他文档和批次；当前未专门放行继承 Exception 的 GraphBubbleUp / GraphInterrupt，不能保证主动中断语义保持不变。不捕获 BaseException，任务取消继续传播。目录迭代异常在此边界之外，直接终止主图。

## 生命周期与验证

- 每次工厂调用有独立的闭包迭代器；本地新运行也应重新 `await factory()`。导入及构图只定义流程，开始消费目录才请求飞书；没有跨进程恢复迭代器进度或自动注册调度计划的实现。
- 子图已接通版本读取与比较、元数据、正文、构树、Loader、Splitter、Milvus 写入及旧版本实体清理；图片识图仍未实现，具体限制见 `document_index/AGENTS.md`。
- 当前不存在 `tests/units/test_feishu_doc_index.py`，不要将它列为可执行检查或声称已有对应 Mock 覆盖。源码类型检查可用 `.venv/bin/pyright --pythonpath .venv/bin/python src/deal_pilot/graphs/feishu_doc_index`，执行结果需另行记录。
- 本次指令同步仅核对源码、入口与路径，没有运行索引图或真实飞书、Nacos、Embedding、Milvus 联调。真实运行会写入并删除实体，应使用明确授权的数据范围；源码检查不能证明全库索引完成。

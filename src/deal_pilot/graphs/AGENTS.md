# 普通 LangGraph 图

## 职责与入口

- 本目录保存直接使用 LangGraph 状态、节点和边构建的普通图，不存放通过 LangChain `create_agent` 或 Deep Agents `create_deep_agent` 创建的 Agent 图；Agent 组装放在 `agents`。
- 普通图可用于后台任务或其他确定流程，不要求具备 cron 调度。每个模块明确自身状态、节点和图导出。
- 当前 `delete_old_trace.py:graph` 使用 `StateGraph` 导出 START → delete_old_trace → END，在 `langgraph.json` 以 `delete_old_trace` 注册，入口为 `deal_pilot.graphs.delete_old_trace:graph`。节点调用 `utils/cleanup_expired_traces.py`，状态返回 `submitted_count`。

## 当前清理图的删除范围与计数

- 保留天数来自 `LANGFUSE_TRACE_RETENTION_DAYS`；缺失或不大于零时使用 30 天，不能解释为关闭清理。
- 截止时间使用 UTC。查询 root observations，按截止时间收集 trace_id，先收集后删除，避免删除影响后续分页。
- 最多读取 10 页，每页 50 条，去重后每批最多 50 个 trace_id 提交；单次最多提交 500 个 trace 的删除请求。
- 返回值是已提交删除请求的 trace 数量，不是确认从存储移除的数量；Langfuse 异步执行删除。
- 当前按配置对应的 Langfuse 项目查询，没有按单个用户或会话过滤；不能将它描述为用户级清理。
- 服务错误向调用方传播，不把清理失败记录为零并伪装成功。

## 扩展、调度与修改

- 本目录提供可被外部调度的图，不在模块导入时创建 cron，也不自动注册运行频率。
- 新增普通图时定义独立的状态、节点和图导出；只有需要作为服务入口时才注册 `langgraph.json`。导入只完成定义和编译，不执行任务副作用。
- 调整模块名称、导出或目录时同步服务入口和所有引用；不要将 LangGraph 调度 API 的 `crons:*` 权限名称随目录更名一起替换。
- 调整保留期、分页、删除范围或上限时同步本文件、公共清理函数和配置说明。

## 验证方式

当前没有专门的清理测试。可用替代客户端验证 UTC 截止时间、分页上限、去重、批次和异常传播；真实调用会删除数据，应使用隔离测试项目与可删除 fixture。不要为了检查图能否加载就直接调用节点，也不要把提交成功称为异步删除完成。

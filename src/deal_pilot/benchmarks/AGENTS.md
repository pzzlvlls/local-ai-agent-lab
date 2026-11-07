# 数据集与离线实验

## 职责与入口

- `dataset.py` 读取 Langfuse 数据集，列表按分页取全；`get_items` 返回指定数据集的条目。
- `benchmark.py` 提供单数据集与全部数据集入口；`experiment.py` 配置任务、评分器和组合评分。
- 评分细节见 `evaluators/AGENTS.md`。实验也可由 `app/experiment_webhook.py` 触发。

## 数据与追踪流程

- 每个 DatasetItem 的 input 作为单条用户消息发送到 Agent Server，`thread_id=None`；返回消息列表的最后一条 content 作为实验输出。
- 通过 `BENCHMARK_AGENT_SERVER` 和 `BENCHMARK_GRAPH_ID` 选择服务和图。`BENCHMARK_USER_ID` 当前被直接用作 Bearer token，名称不代表它可以绕过认证。
- 任务将当前 trace_id、parent_span_id 和 environment 写入运行 metadata，由 Agent 追踪包装关联；不要丢失这些字段造成实验与 Agent trace 断开。
- 当前评分器为内容与情绪相似度，组合输出为总体相似度；调整时同步评分注册、Prompt 配置与回归报告。

## 回归标准

- 真实回归入口为 `tests/benchmarks/test_benchmark.py`，通过 `make test-benchmark DS=<名称>` 或 `DS=all` 执行。
- 当前门槛为 0.8：每条用例都要有唯一、有限且在 0–1 的总体评分，并达到门槛；平均分也需达标，缺输出、缺评分、未完成或空数据集会失败。
- 不只用平均分掩盖单条失败，不把模型调用失败当成质量评分，也不通过跳过失败用例让报告通过。
- 修改评测标准说明原因和可比性影响；旧实验和新实验评分不一定能直接比较。

## 修改与验证

运行实验会调用真实 Agent 和评审模型、写入 Langfuse，产生费用及远程记录。先选择受影响的单个数据集；全量评测按任务需要运行。缺少服务或配置时先验证数据转换和追踪参数，并明确真实质量回归未运行。不要对纯文档改动自动启动实验。

# 数据集与离线实验

## 职责与入口

- `dataset.py` 读取 Langfuse 数据集，列表按分页取全；`get_items` 返回指定数据集的条目。
- `benchmark.py` 提供单数据集与全部数据集入口；`experiment.py` 按数据集名称选择 `EvalConfig`，未注册的数据集报错。
- `evaluators/shared.py` 定义 `EvalConfig`、Agent 调用及 LLM 回答评分工厂；`evaluators/retrieve.py` 提供检索实验任务和评分配置。详细评分契约见 `evaluators/AGENTS.md`。实验也可由 `app/experiment_webhook.py` 触发。
- 当前 `_config` 仅注册远程数据集名 `retrieve`；`run_all_benchmarks()` 遍历 Langfuse 全部数据集，不会过滤未注册名称，遇到未注册配置会报错。`resource/评测数据集/企业知识库_基础问答.csv` 是导入材料，文件名不自动映射到配置，也不会自动创建远程数据集。

## 数据与追踪流程

- 检索任务将每个 DatasetItem 的 input 作为单条用户消息发送到 `retrieve_agent`，`thread_id=None`；返回状态的 `structured_response` 作为实验输出。
- 通过 `BENCHMARK_AGENT_SERVER` 选择服务，检索任务显式指定图名，未使用 `BENCHMARK_GRAPH_ID`。`BENCHMARK_USER_ID` 当前被直接用作 Bearer token，名称不代表它可以绕过认证。
- 任务将当前 trace_id、parent_span_id 和 environment 写入运行 metadata，由 Agent 追踪包装关联；不要丢失这些字段造成实验与 Agent trace 断开。
- `retrieve` 注册四项评分：`retrieve_precision`、`retrieve_recall`、`correctness` 和 `completeness`，当前均返回 0.8 阈值，未配置组合评分。来源指标比较 Agent 输出的 `sources[].title` 与数据集 `metadata.related_documents` 的去重集合，不直接读取检索器原始候选；回答指标只提取 `answer` 交给 LLM 评分。

## 回归标准

- 真实回归入口为 `tests/benchmarks/test_benchmark.py`，通过 `make test-benchmark DS=<名称>` 或 `DS=all` 执行。
- 每条用例的每个评分都读取自身 `metadata.test.threshold`，以 `value >= threshold` 判定；评分与阈值都必须为 0–1 的有限数值，不接受布尔值，不提供默认阈值。
- 每条用例必须具有本次实验所有结果中出现的评分名称且名称不重复，所有指标都达标才通过；输出为 `None`、无评分、缺失或无效阈值、未完成或空数据集会失败。评分名称集合来自实际结果而非配置注册表，因此不能检测某指标在所有用例中都缺失的情况。
- 各指标分别汇总有效评分的平均值及实际阈值，平均值仅用于展示；不再检查“总体相似度”或在报告中设统一的 0.8 门槛。报告仅检查输出是否为 `None`，不承担完整结构化回答校验。
- 不只用平均分掩盖单条失败，不把模型调用失败当成质量评分，也不通过跳过失败用例让报告通过。
- 修改评测标准说明原因和可比性影响；旧实验和新实验评分不一定能直接比较。

## 修改与验证

运行实验会调用真实 Agent、配置的评分器并写入 Langfuse，可能产生模型费用及远程记录。先选择受影响的单个数据集；全量评测按任务需要运行。缺少服务或配置时先验证数据转换和追踪参数，并明确真实质量回归未运行。不要对纯文档改动自动启动实验。

`tests/units/test_benchmark_report.py` 使用本地实验结果验证逐指标阈值、无效数值、缺失或重复评分、未完成及空数据集与报告展示，不调用真实服务。可运行 `.venv/bin/pytest -q tests/units/test_benchmark_report.py`；该测试不验证来源公式、LLM 评分效果或真实 Agent 链路。

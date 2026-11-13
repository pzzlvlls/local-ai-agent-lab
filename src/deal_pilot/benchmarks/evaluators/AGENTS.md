# 评测任务与评分器

## 职责与入口

- `shared.py:EvalConfig` 组合 `task`、`evaluators` 和可选的 `composite_evaluator`；`run_agent(agent_name, input)` 调用指定 Agent 并返回完整状态，服务地址、认证和追踪契约见上级指令。
- `shared.py:create_llm_score_evaluator` 创建 `correctness` 或 `completeness` 异步评分器；`AnswerEvaluation` 约束 0–1 数值 `score` 和非空 `reason`。
- `retrieve.py:experiment_task` 调用 `retrieve_agent`，返回 `structured_response`；`retrieve_eval_config` 注册来源精准率、来源召回率、回答正确性和完整性，未设置组合评分。
- 原有内容相似度、情绪相似度、加权总体评分及其 Langfuse Prompt 工厂已移除；当前评分与旧总体相似度不能直接比较。

## 来源评分契约

- 两个来源评分器要求数据项 `metadata.related_documents` 非空，缺失或为空抛出 `ValueError`；不从参考答案推测完整相关文档集合。
- `R` 为 Agent 结构化输出 `sources[].title` 的去重集合，`G` 为 `related_documents` 的去重集合；精准率为 `|R ∩ G| / |R|`，召回率为 `|R ∩ G| / |G|`。无来源时两项均为 0，评分名分别为 `retrieve_precision`、`retrieve_recall`，阈值均为 0.8。
- 当前按标题精确匹配，CSV 标注使用文档 basename 且不含 `.md`；保持两侧命名与统计粒度一致，不将切片数当成文档数。调用方需提供符合结构的输出与 metadata，评分器没有完整输入 schema 校验。
- 实际被统计的是 Agent 最终列出的来源，不是中间件注入的全部检索结果；不能据此宣称已独立验证原始召回或引用内容的支持关系。

## LLM 回答评分契约

- `correctness` 核对已回答内容的事实与结论；`completeness` 按参考答案必答要点的正确覆盖比例评分。检索配置通过 `output_extact` 提取 `output["answer"]`，以原问题、实际回答和参考答案组成 JSON 用户消息，使用 `ToolStrategy(AnswerEvaluation)` 获取分数和理由。
- Prompt 优先异步读取 Nacos `correctness_eval_prompt`、`completeness_eval_prompt`，返回空字符串时使用对应内置模板；网络或解析异常不会被本地模板自动兜底。模型使用 `create_model()` 的默认配置，不再从 Langfuse Prompt 配置获取模型或评分名称。
- 内置 Prompt 将待评测 JSON 视为数据，要求只依据问题和参考答案评分；远程 Prompt 会替换内置模板，修改时保持指标口径与历史可比性。当前未注册忠实度、相关性、引用准确性等其他课件维度。
- 提取后的回答、输入或参考答案为空时返回 0 分，不创建评分模型，但此前仍会读取 Nacos Prompt；这些分支的阈值当前固定为 0.8。正常分支使用工厂 `threshold` 参数，默认也是 0.8；传入其他阈值时应注意两类分支的差异。
- 每项返回 `Evaluation`，通过 `metadata.test.threshold` 提供回归门槛；`run_experiment` 负责记录，是否达标由 Benchmark 报告判定。

## 修改与验证

- 新任务或评分维度同步 `experiment.py` 的数据集配置、数据标注、阈值和报告说明；不要恢复隐式加权或通过降低阈值掩盖回归。
- `tests/units/test_benchmark_report.py` 只覆盖本地结果报告，当前没有来源公式或 LLM 评分工厂的专门单元测试。真实验证使用 `make test-benchmark DS=retrieve`，依赖 Langfuse、Agent Server、Nacos 和模型，会产生远程记录及可能的费用；纯指令维护不自动启动实验。

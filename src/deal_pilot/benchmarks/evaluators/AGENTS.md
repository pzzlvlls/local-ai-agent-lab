# 评分器与聚合

## 职责与入口

- `create_score_evaluator.py` 创建基于 Langfuse Prompt 的模型评分器。
- `content_similarity.py` 使用 `evaluator/content_similarity`，`emotional_similarity.py` 使用 `evaluator/emotional_similarity`。
- `schemas.py:EvaluationResult` 约束结构化评分，`weighted_average.py` 输出总体评分。

## 评分契约

- 评分器接收 input、output、expected_output，编译 Prompt 并以 ToolStrategy 获取 EvaluationResult；输出 Langfuse NUMERIC Evaluation。
- score 在 0–1，reason 至少一个字符；保持数值与原因分离，不从自然语言自行解析分数。
- output 为空时返回 0 分和“没有实际输出”，不调用评审模型；名称仍取 Prompt 配置。
- 模型配置来自 Prompt 的 `model_config`，评分名称来自 `name`。改变配置时核对 `utils/create_model.py` 实际接受的参数形式，不能默认任意远程字典都兼容。
- 当前权重为“内容相似度”0.4、“情绪相似度”0.6，组合名称为“总体相似度”；名称必须与远程 Prompt 配置精确一致。
- 聚合当前按名称建立字典，再按权重索引；缺维度会报错，重复名称会覆盖。不要声称现有聚合已经验证完整性，不用默认零分掩盖缺失。

## 修改与验证

- 新维度同步实验注册、远程 Prompt 配置、权重和回归报告；权重及评分名称变化说明对历史可比性的影响。
- 有针对性地验证空输出、分数边界、结构化响应、评分名称和聚合公式；本地固定结果只能证明计算，不证明评审模型可靠。
- 真实验证通过父目录的单数据集 Benchmark，依赖 Langfuse、Agent Server 和模型；当前没有独立的评分器单元测试。

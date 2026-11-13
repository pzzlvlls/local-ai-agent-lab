from typing import Any

from langfuse import Evaluation
from langfuse.api import DatasetItem

from deal_pilot.benchmarks.evaluators.shared import (
    EvalConfig,
    create_llm_score_evaluator,
    run_agent,
)


async def retrieve_precision_eval(
    *,
    input: str,
    output: dict[str, Any],
    expected_output: str,
    metadata: dict[str, Any] | None,
    **kwargs: Any,
) -> Evaluation:
    "精准率评估"
    if not metadata or not metadata.get("related_documents"):
        raise ValueError("数据集 metadata.realated_documents 不能为空")
    sources = output.get("sources", [])  # 检索到的来源
    sources = set([s["title"] for s in sources])
    related_documents = set(metadata.get("related_documents", []))

    return Evaluation(
        name="retrieve_precision",
        data_type="NUMERIC",
        value=len(sources & related_documents) / len(sources) if sources else 0.0,
        metadata={"test": {"threshold": 0.8}},
    )


async def retrieve_recall_eval(
    *,
    input: str,
    output: dict[str, Any],
    expected_output: str,
    metadata: dict[str, Any] | None,
    **kwargs: Any,
) -> Evaluation:
    "召回率评估"
    if not metadata or not metadata.get("related_documents"):
        raise ValueError("数据集 metadata.realated_documents 不能为空")
    sources = output.get("sources", [])  # 检索到的来源
    sources = set([s["title"] for s in sources])
    related_documents = set(metadata.get("related_documents", []))

    return Evaluation(
        name="retrieve_recall",
        data_type="NUMERIC",
        value=(
            len(sources & related_documents) / len(related_documents)
            if related_documents
            else 0.0
        ),
        metadata={"test": {"threshold": 0.8}},
    )


async def experiment_task(*, item: DatasetItem, **kwargs):
    question = item.input
    # 运行 Agent
    result = await run_agent("retrieve_agent", question)
    return result["structured_response"]  # type: ignore


correctness_eval = create_llm_score_evaluator(
    "correctness", lambda output: output["answer"]
)

completeness_eval = create_llm_score_evaluator(
    "completeness", lambda output: output["answer"]
)

retrieve_eval_config = EvalConfig(task=experiment_task, evaluators=[correctness_eval, completeness_eval])  # type: ignore

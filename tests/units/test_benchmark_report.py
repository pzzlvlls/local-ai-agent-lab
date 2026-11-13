"""Validate Benchmark threshold decisions without Agent or Langfuse calls."""

import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from langfuse import Evaluation


_report_module = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "benchmarks" / "test_benchmark.py")
)
_summarize = _report_module["_summarize_benchmark_result"]
_print_report = _report_module["_print_report"]


@pytest.fixture
def items(monkeypatch: pytest.MonkeyPatch) -> list[SimpleNamespace]:
    items = [SimpleNamespace(id="case-1", input="测试问题")]
    dataset = ModuleType("deal_pilot.benchmarks.dataset")
    setattr(dataset, "get_items", lambda name: items)
    monkeypatch.setitem(sys.modules, dataset.__name__, dataset)
    return items


def _evaluation(name: str, value: float, threshold: float) -> Evaluation:
    return Evaluation(
        name=name,
        value=value,
        metadata={"test": {"threshold": threshold}},
        data_type="NUMERIC",
    )


def _result(
    items: list[SimpleNamespace], evaluations: list[list[Evaluation]]
) -> SimpleNamespace:
    return SimpleNamespace(
        item_results=[
            SimpleNamespace(item=item, output={"answer": "回答"}, evaluations=scores)
            for item, scores in zip(items, evaluations)
        ],
        dataset_run_url="https://example.test/experiment",
    )


@pytest.mark.parametrize(
    ("precision", "precision_threshold", "recall", "recall_threshold", "passed"),
    [
        (0.7, 0.6, 0.9, 0.85, True),
        (0.8, 0.8, 0.9, 0.9, True),
        (0.85, 0.9, 1.0, 0.8, False),
        (1.0, 0.8, 0.85, 0.9, False),
        (0.0, 0.0, 1.0, 1.0, True),
    ],
)
def test_each_metric_uses_its_returned_threshold(
    items: list[SimpleNamespace],
    precision: float,
    precision_threshold: float,
    recall: float,
    recall_threshold: float,
    passed: bool,
) -> None:
    result = _result(
        items,
        [[
            _evaluation("precision", precision, precision_threshold),
            _evaluation("recall", recall, recall_threshold),
        ]],
    )

    report = _summarize("retrieve", result)

    assert report["passed"] is passed
    assert report["passed_items"] == int(passed)


def test_threshold_can_vary_between_items(items: list[SimpleNamespace]) -> None:
    items.append(SimpleNamespace(id="case-2", input="第二个问题"))
    result = _result(
        items,
        [
            [_evaluation("precision", 0.5, 0.5)],
            [_evaluation("precision", 0.9, 0.9)],
        ],
    )

    report = _summarize("retrieve", result)

    assert report["passed"]
    assert report["metrics"]["precision"]["average"] == pytest.approx(0.7)
    assert report["metrics"]["precision"]["thresholds"] == [0.5, 0.9]


@pytest.mark.parametrize("field", ["score", "threshold"])
@pytest.mark.parametrize(
    "value", [None, True, "0.8", float("nan"), float("inf"), -0.1, 1.1]
)
def test_invalid_score_or_threshold_fails(
    items: list[SimpleNamespace], field: str, value: object
) -> None:
    evaluation = _evaluation("precision", 0.9, 0.8)
    if field == "score":
        setattr(evaluation, "value", value)
    else:
        evaluation.metadata = {"test": {"threshold": value}}

    report = _summarize("retrieve", _result(items, [[evaluation]]))

    assert not report["passed"]
    assert "无效" in report["failed_cases"][0]


@pytest.mark.parametrize("metadata", [None, {}, {"test": {}}, {"test": []}])
def test_missing_threshold_fails(
    items: list[SimpleNamespace], metadata: dict | None
) -> None:
    evaluation = _evaluation("precision", 1.0, 0.8)
    evaluation.metadata = metadata

    report = _summarize("retrieve", _result(items, [[evaluation]]))

    assert not report["passed"]
    assert "阈值缺失或无效" in report["failed_cases"][0]


@pytest.mark.parametrize(
    "problem",
    ["no_output", "no_scores", "duplicate", "missing_metric", "incomplete", "empty"],
)
def test_incomplete_or_ambiguous_evaluations_fail(
    items: list[SimpleNamespace], problem: str
) -> None:
    result = _result(items, [[_evaluation("precision", 1.0, 0.8)]])
    row = result.item_results[0]
    if problem == "no_output":
        row.output = None
    elif problem == "no_scores":
        row.evaluations.clear()
    elif problem == "duplicate":
        row.evaluations.append(_evaluation("precision", 1.0, 0.8))
    elif problem == "missing_metric":
        items.append(SimpleNamespace(id="case-2", input="第二个问题"))
        result = _result(
            items,
            [
                [_evaluation("precision", 1.0, 0.8)],
                [_evaluation("precision", 1.0, 0.8), _evaluation("recall", 1.0, 0.8)],
            ],
        )
    elif problem == "incomplete":
        result.item_results.clear()
    else:
        items.clear()
        result.item_results.clear()

    report = _summarize("retrieve", result)

    assert not report["passed"]
    assert report["failed_cases"]


def test_report_shows_each_metric_and_failed_threshold(
    items: list[SimpleNamespace], capsys: pytest.CaptureFixture[str]
) -> None:
    result = _result(
        items,
        [[
            _evaluation("precision", 0.7, 0.6),
            _evaluation("recall", 0.85, 0.9),
        ]],
    )

    _print_report([_summarize("retrieve", result)])

    output = capsys.readouterr().out
    assert "precision：平均分 0.700，阈值 0.600" in output
    assert "recall：平均分 0.850，阈值 0.900" in output
    assert "recall 0.850 < 阈值 0.900" in output
    assert "达标 0 条，未达标 1 条" in output

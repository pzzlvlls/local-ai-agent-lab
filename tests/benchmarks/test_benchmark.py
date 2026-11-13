"""Report Benchmark quality for one or all Langfuse datasets."""

import math
import os
from pathlib import Path
from typing import TypeGuard

import pytest
from dotenv import load_dotenv


EXPERIMENT_NAME_PREFIX = "实验数据集:"


def test_benchmark_regression():
    # Langfuse SDK 和模型客户端会从进程环境读取配置，需在导入项目模块前加载。
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    from deal_pilot.benchmarks.benchmark import run_all_benchmarks, run_benchmark

    dataset_name = os.environ.get("BENCHMARK_DATASET", "").strip()
    assert dataset_name, "请运行 make test-benchmark DS=all 或 DS=<数据集名称>"

    if dataset_name == "all":
        results = run_all_benchmarks()
        reports = [
            _summarize_benchmark_result(
                result.name.removeprefix(EXPERIMENT_NAME_PREFIX), result
            )
            for result in results
        ]
    else:
        reports = [
            _summarize_benchmark_result(dataset_name, run_benchmark(dataset_name))
        ]

    _print_report(reports)
    failed_datasets = [report["dataset"] for report in reports if not report["passed"]]
    if not reports:
        pytest.fail("没有可测试的数据集", pytrace=False)
    if failed_datasets:
        pytest.fail(
            f"{len(failed_datasets)} 个数据集未达标：{', '.join(failed_datasets)}",
            pytrace=False,
        )


def _summarize_benchmark_result(dataset_name, result):
    from deal_pilot.benchmarks.dataset import get_items

    items = get_items(dataset_name)
    scores = {e.name: [] for row in result.item_results for e in row.evaluations}
    thresholds = {name: set() for name in scores}
    passed_items = 0
    failed_cases = []
    completed_ids = set()

    for index, row in enumerate(result.item_results, start=1):
        case_id = getattr(row.item, "id", index)
        case_name = _case_name(row.item, index)
        completed_ids.add(case_id)
        if row.output is None:
            failed_cases.append(f"{case_name}: Agent 没有输出")
            continue

        if not row.evaluations:
            failed_cases.append(f"{case_name}: 没有评估评分")
            continue

        case_passed = True
        seen_names = set()
        for evaluation in row.evaluations:
            name = evaluation.name
            if name in seen_names:
                failed_cases.append(f"{case_name}: {name} 评分重复")
                case_passed = False
                continue
            seen_names.add(name)

            score = evaluation.value
            if not _is_valid_score(score):
                failed_cases.append(f"{case_name}: {name} 评分无效 ({score!r})")
                case_passed = False
                continue

            test_config = (evaluation.metadata or {}).get("test")
            threshold = (
                test_config.get("threshold") if isinstance(test_config, dict) else None
            )
            if not _is_valid_score(threshold):
                failed_cases.append(
                    f"{case_name}: {name} 阈值缺失或无效 ({threshold!r})"
                )
                case_passed = False
                continue

            scores[name].append(score)
            thresholds[name].add(threshold)
            if score < threshold:
                failed_cases.append(
                    f"{case_name}: {name} {score:.3f} < 阈值 {threshold:.3f}"
                )
                case_passed = False

        for name in sorted(scores.keys() - seen_names):
            failed_cases.append(f"{case_name}: {name} 评分缺失")
            case_passed = False

        if case_passed:
            passed_items += 1

    for item in items:
        if item.id not in completed_ids:
            failed_cases.append(f"{_case_name(item, item.id)}: 实验未完成")

    passed = (
        bool(items)
        and len(result.item_results) == len(items)
        and passed_items == len(items)
        and not failed_cases
    )
    if not items:
        failed_cases.append("数据集没有测试用例")

    return {
        "dataset": dataset_name,
        "total": len(items),
        "passed_items": passed_items,
        "metrics": {
            name: {
                "average": sum(values) / len(values) if values else None,
                "thresholds": sorted(thresholds[name]),
            }
            for name, values in scores.items()
        },
        "passed": passed,
        "failed_cases": failed_cases,
        "url": result.dataset_run_url,
    }


def _is_valid_score(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1
    )


def _case_name(item, fallback):
    case_id = getattr(item, "id", fallback)
    content = getattr(item, "input", None)
    if content is None:
        return str(case_id)
    preview = " ".join(str(content).split())
    if len(preview) > 60:
        preview = f"{preview[:60]}…"
    return f"{case_id}（{preview}）"


def _print_report(reports):
    print("\nBenchmark 汇总（各评分按 metadata.test.threshold 判定）")
    if not reports:
        print("没有可测试的数据集")
        return

    for report in reports:
        status = "达标" if report["passed"] else "未达标"
        failed_count = report["total"] - report["passed_items"]
        print(
            f"- {report['dataset']}：{status}；"
            f"用例 {report['total']} 条，达标 {report['passed_items']} 条，"
            f"未达标 {failed_count} 条"
        )
        for name, metric in report["metrics"].items():
            average = metric["average"]
            average_text = f"{average:.3f}" if average is not None else "无有效评分"
            threshold_text = ", ".join(f"{t:.3f}" for t in metric["thresholds"])
            print(
                f"    {name}：平均分 {average_text}，"
                f"阈值 {threshold_text or '无有效阈值'}"
            )
        for case in report["failed_cases"]:
            print(f"    - {case}")
        if report["url"]:
            print(f"  实验详情：{report['url']}")

    passed_datasets = sum(report["passed"] for report in reports)
    total_items = sum(report["total"] for report in reports)
    passed_items = sum(report["passed_items"] for report in reports)
    print(
        f"总计：数据集 {len(reports)} 个，达标 {passed_datasets} 个，"
        f"未达标 {len(reports) - passed_datasets} 个；"
        f"用例 {total_items} 条，达标 {passed_items} 条，"
        f"未达标 {total_items - passed_items} 条"
    )

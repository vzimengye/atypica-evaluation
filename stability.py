from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from task_benchmark import ai_source_materials, load_tasks, run_task_answering


SPLIT_WEIGHTS = {"building": 0.4, "holdout": 0.6}


def answer_map(answer_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("task_id", ""): item for item in answer_result.get("answers", [])}


def normalized(answer: dict[str, Any], task_id: str) -> Any:
    return answer_map(answer).get(task_id, {}).get("normalized_answer")


def consistency_ratio(values: list[Any]) -> float:
    if not values:
        return 0.0
    normalized_values = [json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values]
    most_common = Counter(normalized_values).most_common(1)[0][1]
    return most_common / len(values)


def ranking_top1(values: list[Any]) -> list[Any]:
    top = []
    for value in values:
        if isinstance(value, list) and value:
            top.append(value[0])
        else:
            top.append(None)
    return top


def numeric_range(values: list[Any]) -> float | None:
    numeric = []
    for value in values:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numeric:
        return None
    return max(numeric) - min(numeric)


def classify_stability(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def score_stability(tasks: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    per_task: list[dict[str, Any]] = []
    task_scores: list[float] = []
    classification_scores: list[float] = []
    counterfactual_scores: list[float] = []
    ranking_scores: list[float] = []
    continuous_ranges: list[float] = []
    split_task_scores: dict[str, list[float]] = {"building": [], "holdout": []}

    for task in tasks.get("tasks", []):
        task_id = task["id"]
        task_type = task["type"]
        split = task.get("split", "holdout")
        values = [normalized(run, task_id) for run in runs]
        result: dict[str, Any] = {
            "task_id": task_id,
            "type": task_type,
            "split": split,
            "values": values,
        }

        if task_type in ("classification", "counterfactual"):
            score = consistency_ratio(values)
            result["consistency"] = score
            result["stable_answer"] = Counter(json.dumps(v, ensure_ascii=False, sort_keys=True) for v in values).most_common(1)[0][0] if values else None
            task_scores.append(score)
            split_task_scores.setdefault(split, []).append(score)
            if task_type == "classification":
                classification_scores.append(score)
            else:
                counterfactual_scores.append(score)
        elif task_type == "ranking":
            top_values = ranking_top1(values)
            score = consistency_ratio(top_values)
            result["top1_consistency"] = score
            task_scores.append(score)
            split_task_scores.setdefault(split, []).append(score)
            ranking_scores.append(score)
        elif task_type == "continuous":
            value_range = numeric_range(values)
            scale = float(task.get("scale_max", 10)) - float(task.get("scale_min", 0))
            score = max(0.0, 1.0 - (value_range or 0.0) / scale) if scale > 0 and value_range is not None else 0.0
            result["range"] = value_range
            result["consistency"] = score
            task_scores.append(score)
            split_task_scores.setdefault(split, []).append(score)
            if value_range is not None:
                continuous_ranges.append(value_range)
        else:
            result["consistency"] = None

        per_task.append(result)

    overall = sum(task_scores) / len(task_scores) if task_scores else 0.0
    building_score = average(split_task_scores.get("building", []))
    holdout_score = average(split_task_scores.get("holdout", []))
    available_weight = sum(weight for split, weight in SPLIT_WEIGHTS.items() if average(split_task_scores.get(split, [])) is not None)
    weighted = None
    if available_weight > 0:
        weighted = sum(
            (average(split_task_scores.get(split, [])) or 0.0) * weight
            for split, weight in SPLIT_WEIGHTS.items()
            if average(split_task_scores.get(split, [])) is not None
        ) / available_weight
    metrics = {
        "overall_stability_score": weighted if weighted is not None else overall,
        "raw_average_stability_score": overall,
        "stability_label": classify_stability(weighted if weighted is not None else overall),
        "building_stability_score": building_score,
        "holdout_stability_score": holdout_score,
        "split_weights": SPLIT_WEIGHTS,
        "classification_consistency": sum(classification_scores) / len(classification_scores) if classification_scores else None,
        "counterfactual_consistency": sum(counterfactual_scores) / len(counterfactual_scores) if counterfactual_scores else None,
        "ranking_top1_consistency": sum(ranking_scores) / len(ranking_scores) if ranking_scores else None,
        "continuous_average_range": sum(continuous_ranges) / len(continuous_ranges) if continuous_ranges else None,
    }
    return {"metrics": metrics, "per_task": per_task}


def pct(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.0f}%"
    return "n/a"


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def render_stability_markdown(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    lines = [
        "# Stability Report",
        "",
        f"**Evaluation mode:** {report.get('evaluation_mode', 'n/a')}",
        f"**Stability label:** {metrics.get('stability_label', 'n/a')}",
        f"**Overall stability score:** {pct(metrics.get('overall_stability_score'))}",
        f"**Building stability score:** {pct(metrics.get('building_stability_score'))}",
        f"**Holdout stability score:** {pct(metrics.get('holdout_stability_score'))}",
        "",
        "## Metrics",
        f"- Classification consistency: {pct(metrics.get('classification_consistency'))}",
        f"- Counterfactual consistency: {pct(metrics.get('counterfactual_consistency'))}",
        f"- Ranking top-1 consistency: {pct(metrics.get('ranking_top1_consistency'))}",
        f"- Continuous average range: {metrics.get('continuous_average_range', 'n/a')}",
        "",
        "## Per-Task Stability",
    ]
    for item in report.get("per_task", []):
        score = item.get("consistency", item.get("top1_consistency", "n/a"))
        lines.extend(
            [
                f"### {item.get('task_id')}",
                f"- Type: {item.get('type')}",
                f"- Split: {item.get('split')}",
                f"- Stability: {pct(score) if isinstance(score, (int, float)) else score}",
                f"- Values: {item.get('values')}",
                "",
            ]
        )
    return "\n".join(lines)


def write_stability_files(case_dir: Path, runs: list[dict[str, Any]], report: dict[str, Any]) -> None:
    runs_dir = case_dir / "stability_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for index, run in enumerate(runs, start=1):
        (runs_dir / f"run_{index}_ai_task_answers.json").write_text(
            json.dumps(run, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (case_dir / "stability_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "stability_report.md").write_text(
        render_stability_markdown(report),
        encoding="utf-8",
    )


def run_stability_test(case_dir: Path, model: str, runs: int = 3) -> dict[str, Any]:
    tasks = load_tasks()
    source = ai_source_materials(case_dir)
    run_results = [run_task_answering("ai_persona", source, tasks, model) for _ in range(runs)]
    scored = score_stability(tasks, run_results)
    report = {
        "evaluation_mode": "fixed_holdout_phase_1",
        "runs": runs,
        "metrics": scored["metrics"],
        "per_task": scored["per_task"],
    }
    write_stability_files(case_dir, run_results, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeated task answers to measure AI persona stability.")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--model",
        default=os.getenv("PPIO_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek/deepseek-v3-turbo",
    )
    args = parser.parse_args()

    run_stability_test(args.case_dir, args.model, args.runs)
    print(f"Wrote stability files to: {args.case_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

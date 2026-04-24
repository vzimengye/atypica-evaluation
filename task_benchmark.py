from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from ai_interview import call_llm, read_required
from evaluation import find_source_pdf
from persona_from_pdf import extract_pdf_text, load_cached_source_text, parse_json_object


ROOT = Path(__file__).resolve().parent
TASKS_PATH = ROOT / "benchmark_tasks.json"
PROMPT_PATH = ROOT / "prompts" / "task_answering.md"
SPLIT_WEIGHTS = {"building": 0.4, "holdout": 0.6}


def load_tasks() -> dict[str, Any]:
    return json.loads(read_required(TASKS_PATH))


def build_answer_prompt(
    respondent_type: str,
    source_materials: str,
    tasks: dict[str, Any],
) -> str:
    instruction = read_required(PROMPT_PATH)
    return "\n\n".join(
        [
            instruction,
            f"respondent_type: {respondent_type}",
            "## Source materials",
            source_materials,
            "## Benchmark tasks",
            "```json",
            json.dumps(tasks, ensure_ascii=False, indent=2),
            "```",
            "Return the benchmark answers JSON only.",
        ]
    )


def human_source_materials(case_dir: Path, max_chars: int = 45000) -> str:
    split_info = (case_dir / "evaluation_split.json").read_text(encoding="utf-8") if (case_dir / "evaluation_split.json").exists() else "{}"
    building_md = (case_dir / "building_ground_truth.md").read_text(encoding="utf-8") if (case_dir / "building_ground_truth.md").exists() else ""
    holdout_md = (case_dir / "holdout_ground_truth.md").read_text(encoding="utf-8") if (case_dir / "holdout_ground_truth.md").exists() else ""
    schema = read_required(case_dir / "schema.json")
    source_pdf = find_source_pdf(case_dir)
    cached_text = load_cached_source_text(case_dir)
    if cached_text:
        human_text = cached_text
        if len(human_text) > max_chars:
            human_text = human_text[:max_chars] + "\n\n[TRUNCATED: human material exceeded max chars]"
    elif source_pdf:
        human_text = extract_pdf_text(source_pdf)
        if len(human_text) > max_chars:
            human_text = human_text[:max_chars] + "\n\n[TRUNCATED: human material exceeded max chars]"
    else:
        human_text = "[SOURCE PDF NOT FOUND. Use building and holdout ground truth as primary human evidence.]"
    return "\n\n".join(
        [
            "### Evaluation split metadata",
            "```json",
            split_info,
            "```",
            "### Human building subset",
            "```markdown",
            building_md,
            "```",
            "### Human holdout subset",
            "```markdown",
            holdout_md,
            "```",
            "### Human interview material",
            "```text",
            human_text,
            "```",
            "### Persona schema for context only",
            "```json",
            schema,
            "```",
        ]
    )


def ai_source_materials(case_dir: Path) -> str:
    persona_card = read_required(case_dir / "persona_card.md")
    simulation_prompt = read_required(case_dir / "simulation_prompt.md")
    schema = read_required(case_dir / "schema.json")
    split_info = (case_dir / "evaluation_split.json").read_text(encoding="utf-8") if (case_dir / "evaluation_split.json").exists() else "{}"
    return "\n\n".join(
        [
            "### Evaluation split metadata",
            "```json",
            split_info,
            "```",
            "### AI persona card",
            "```markdown",
            persona_card,
            "```",
            "### AI simulation prompt",
            "```markdown",
            simulation_prompt,
            "```",
            "### Source schema used to construct the AI persona",
            "```json",
            schema,
            "```",
            "### Important benchmark rule",
            "Use only the persona package above. Do not assume access to the withheld human answers or the AI interview outputs.",
        ]
    )


def run_task_answering(
    respondent_type: str,
    source_materials: str,
    tasks: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    prompt = build_answer_prompt(respondent_type, source_materials, tasks)
    output_text = call_llm(prompt, model)
    result = parse_json_object(output_text)
    return result


def answer_map(answer_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("task_id", ""): item for item in answer_result.get("answers", [])}


def normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def top_k_overlap(a: list[Any], b: list[Any], k: int) -> float:
    if not a or not b:
        return 0.0
    a_set = set(a[:k])
    b_set = set(b[:k])
    return len(a_set & b_set) / max(1, min(k, len(a_set | b_set)))


def score_tasks(tasks: dict[str, Any], human_answers: dict[str, Any], ai_answers: dict[str, Any]) -> dict[str, Any]:
    human = answer_map(human_answers)
    ai = answer_map(ai_answers)
    per_task: list[dict[str, Any]] = []
    buckets: dict[str, list[dict[str, Any]]] = {
        "classification": [],
        "continuous": [],
        "ranking": [],
        "open": [],
        "counterfactual": [],
    }

    for task in tasks.get("tasks", []):
        task_id = task["id"]
        task_type = task["type"]
        human_item = human.get(task_id, {})
        ai_item = ai.get(task_id, {})
        h = normalize_value(human_item.get("normalized_answer"))
        a = normalize_value(ai_item.get("normalized_answer"))
        result: dict[str, Any] = {
            "task_id": task_id,
            "type": task_type,
            "split": task.get("split", "holdout"),
            "question": task.get("question", ""),
            "human_answer": h,
            "ai_answer": a,
            "human_evidence": human_item.get("evidence", ""),
            "ai_evidence": ai_item.get("evidence", ""),
        }

        if task_type == "classification":
            match = h == a and h is not None
            result["match"] = match
            result["score"] = 1.0 if match else 0.0
        elif task_type == "continuous":
            try:
                h_num = float(h)
                a_num = float(a)
                mae = abs(h_num - a_num)
                scale = float(task.get("scale_max", 10)) - float(task.get("scale_min", 0))
                result["mae"] = mae
                result["score"] = max(0.0, 1.0 - mae / scale) if scale > 0 else 0.0
            except (TypeError, ValueError):
                result["mae"] = None
                result["score"] = 0.0
        elif task_type == "ranking":
            h_rank = h if isinstance(h, list) else []
            a_rank = a if isinstance(a, list) else []
            result["top1_match"] = bool(h_rank and a_rank and h_rank[0] == a_rank[0])
            result["top3_overlap"] = top_k_overlap(h_rank, a_rank, 3)
            result["score"] = (0.5 if result["top1_match"] else 0.0) + 0.5 * result["top3_overlap"]
        elif task_type == "counterfactual":
            match = h == a and h is not None
            result["direction_match"] = match
            result["score"] = 1.0 if match else 0.0
        else:
            result["score"] = None

        per_task.append(result)
        buckets.setdefault(task_type, []).append(result)

    metrics = summarize_metrics(buckets, per_task)
    return {"metrics": metrics, "per_task": per_task}


def summarize_metrics(buckets: dict[str, list[dict[str, Any]]], per_task: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    classification = buckets.get("classification", [])
    if classification:
        matches = sum(1 for item in classification if item.get("match"))
        metrics["classification_accuracy"] = matches / len(classification)
        metrics["classification_match_count"] = f"{matches}/{len(classification)}"

    continuous = buckets.get("continuous", [])
    mae_values = [item["mae"] for item in continuous if isinstance(item.get("mae"), (int, float))]
    if mae_values:
        metrics["continuous_mae"] = sum(mae_values) / len(mae_values)
        metrics["continuous_similarity"] = average_score(continuous)

    ranking = buckets.get("ranking", [])
    if ranking:
        top1 = sum(1 for item in ranking if item.get("top1_match"))
        metrics["ranking_top1_agreement"] = top1 / len(ranking)
        metrics["ranking_top1_count"] = f"{top1}/{len(ranking)}"
        metrics["ranking_top3_overlap"] = sum(float(item.get("top3_overlap", 0)) for item in ranking) / len(ranking)

    counterfactual = buckets.get("counterfactual", [])
    if counterfactual:
        matches = sum(1 for item in counterfactual if item.get("direction_match"))
        metrics["counterfactual_direction_match"] = matches / len(counterfactual)
        metrics["counterfactual_direction_count"] = f"{matches}/{len(counterfactual)}"

    scored = [
        item
        for items in buckets.values()
        for item in items
        if isinstance(item.get("score"), (int, float)) and not math.isnan(float(item["score"]))
    ]
    metrics["raw_average_task_score"] = average_score(scored) if scored else None
    split_scores = summarize_split_scores(per_task)
    metrics.update(split_scores)
    metrics["overall_task_score"] = metrics.get("weighted_task_score")
    return metrics


def summarize_split_scores(per_task: list[dict[str, Any]]) -> dict[str, Any]:
    split_values: dict[str, list[dict[str, Any]]] = {"building": [], "holdout": []}
    for item in per_task:
        if isinstance(item.get("score"), (int, float)):
            split = str(item.get("split", "holdout"))
            split_values.setdefault(split, []).append(item)

    result: dict[str, Any] = {}
    for split, items in split_values.items():
        result[f"{split}_task_score"] = average_score(items)
        result[f"{split}_task_count"] = len(items)

    available_weight = sum(
        weight for split, weight in SPLIT_WEIGHTS.items() if result.get(f"{split}_task_score") is not None
    )
    if available_weight > 0:
        weighted = sum(
            (result.get(f"{split}_task_score") or 0.0) * weight
            for split, weight in SPLIT_WEIGHTS.items()
            if result.get(f"{split}_task_score") is not None
        ) / available_weight
    else:
        weighted = None
    result["weighted_task_score"] = weighted
    result["split_weights"] = SPLIT_WEIGHTS
    return result


def average_score(items: list[dict[str, Any]]) -> float | None:
    values = [float(item["score"]) for item in items if isinstance(item.get("score"), (int, float))]
    if not values:
        return None
    return sum(values) / len(values)


def percent(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.0f}%"
    return "n/a"


def render_benchmark_markdown(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    lines = [
        "# Task Benchmark Report",
        "",
        f"- Evaluation mode: {report.get('evaluation_mode', 'n/a')}",
        "",
        "## Summary Metrics",
        f"- Overall task score: {percent(metrics.get('overall_task_score'))}",
        f"- Building task score: {percent(metrics.get('building_task_score'))} ({metrics.get('building_task_count', 0)} tasks)",
        f"- Holdout task score: {percent(metrics.get('holdout_task_score'))} ({metrics.get('holdout_task_count', 0)} tasks)",
        f"- Classification accuracy: {percent(metrics.get('classification_accuracy'))} ({metrics.get('classification_match_count', 'n/a')})",
        f"- Continuous MAE: {metrics.get('continuous_mae', 'n/a')}",
        f"- Ranking top-1 agreement: {percent(metrics.get('ranking_top1_agreement'))} ({metrics.get('ranking_top1_count', 'n/a')})",
        f"- Ranking top-3 overlap: {percent(metrics.get('ranking_top3_overlap'))}",
        f"- Counterfactual direction match: {percent(metrics.get('counterfactual_direction_match'))} ({metrics.get('counterfactual_direction_count', 'n/a')})",
        "",
        "## Per-Task Comparison",
    ]
    for item in report.get("per_task", []):
        lines.extend(
            [
                f"### {item.get('task_id')}",
                f"- Type: {item.get('type')}",
                f"- Split: {item.get('split')}",
                f"- Human: {item.get('human_answer')}",
                f"- AI: {item.get('ai_answer')}",
                f"- Score: {item.get('score', 'n/a')}",
                f"- Human evidence: {item.get('human_evidence', '')}",
                f"- AI evidence: {item.get('ai_evidence', '')}",
                "",
            ]
        )
    return "\n".join(lines)


def write_benchmark_files(
    case_dir: Path,
    human_answers: dict[str, Any],
    ai_answers: dict[str, Any],
    report: dict[str, Any],
) -> None:
    (case_dir / "human_task_answers.json").write_text(
        json.dumps(human_answers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "ai_task_answers.json").write_text(
        json.dumps(ai_answers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "task_benchmark_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "task_benchmark_report.md").write_text(
        render_benchmark_markdown(report),
        encoding="utf-8",
    )


def run_task_benchmark(case_dir: Path, model: str) -> dict[str, Any]:
    tasks = load_tasks()
    benchmark_version = tasks.get("version")
    existing_human = {}
    human_answers_path = case_dir / "human_task_answers.json"
    if human_answers_path.exists():
        try:
            existing_human = json.loads(human_answers_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_human = {}
    if existing_human.get("benchmark_version") == benchmark_version and existing_human.get("answers"):
        human_answers = existing_human
    else:
        human_answers = run_task_answering("human", human_source_materials(case_dir), tasks, model)
        human_answers["benchmark_version"] = benchmark_version
    ai_answers = run_task_answering("ai_persona", ai_source_materials(case_dir), tasks, model)
    scored = score_tasks(tasks, human_answers, ai_answers)
    report = {
        "benchmark_version": benchmark_version,
        "evaluation_mode": "fixed_holdout_phase_1",
        "metrics": scored["metrics"],
        "per_task": scored["per_task"],
    }
    write_benchmark_files(case_dir, human_answers, ai_answers, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fixed task benchmark for one case directory.")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument(
        "--model",
        default=os.getenv("PPIO_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek/deepseek-v3-turbo",
    )
    args = parser.parse_args()

    run_task_benchmark(args.case_dir, args.model)
    print(f"Wrote task benchmark files to: {args.case_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

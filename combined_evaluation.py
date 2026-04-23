from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


WEIGHTS = {
    "response_fidelity": 0.35,
    "counterfactual_sensitivity": 0.30,
    "persona_grounding": 0.20,
    "behavior_consistency": 0.15,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def score_1_to_100(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(100.0, float(value) / 5.0 * 100.0))
    return None


def ratio_to_100(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(100.0, float(value) * 100.0))
    return None


def average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def label(score: float | None, complete: bool) -> str:
    if score is None:
        return "insufficient_evidence"
    if not complete:
        return "provisional"
    if score >= 85:
        return "high_fidelity"
    if score >= 70:
        return "medium_high_fidelity"
    if score >= 55:
        return "medium_fidelity"
    return "low_fidelity"


def compute_combined(case_dir: Path) -> dict[str, Any]:
    evaluation = read_json(case_dir / "evaluation_report.json")
    benchmark = read_json(case_dir / "task_benchmark_report.json")
    stability = read_json(case_dir / "stability_report.json")

    eval_scopes = evaluation.get("scope_scores", {})
    benchmark_metrics = benchmark.get("metrics", {})
    stability_metrics = stability.get("metrics", {})

    persona_grounding = score_1_to_100(eval_scopes.get("persona_grounding", {}).get("score"))
    response_fidelity = average(
        [
            score_1_to_100(eval_scopes.get("response_fidelity", {}).get("score")),
            ratio_to_100(benchmark_metrics.get("overall_task_score")),
            ratio_to_100(benchmark_metrics.get("classification_accuracy")),
            ratio_to_100(benchmark_metrics.get("ranking_top1_agreement")),
        ]
    )
    counterfactual_sensitivity = average(
        [
            score_1_to_100(eval_scopes.get("counterfactual_sensitivity", {}).get("score")),
            ratio_to_100(benchmark_metrics.get("counterfactual_direction_match")),
        ]
    )
    behavior_consistency = ratio_to_100(stability_metrics.get("overall_stability_score"))

    subscores = {
        "response_fidelity": response_fidelity,
        "counterfactual_sensitivity": counterfactual_sensitivity,
        "persona_grounding": persona_grounding,
        "behavior_consistency": behavior_consistency,
    }
    complete = all(value is not None for value in subscores.values())
    available_weight = sum(weight for key, weight in WEIGHTS.items() if subscores.get(key) is not None)
    overall = None
    if available_weight > 0:
        overall = sum((subscores[key] or 0.0) * weight for key, weight in WEIGHTS.items() if subscores.get(key) is not None) / available_weight

    missing = [key for key, value in subscores.items() if value is None]
    report = {
        "summary": {
            "overall_score": round(overall, 1) if overall is not None else None,
            "overall_label": label(overall, complete),
            "is_complete": complete,
            "missing_components": missing,
            "weights": WEIGHTS,
            "conclusion": build_conclusion(overall, complete, missing),
        },
        "subscores": {key: round(value, 1) if value is not None else None for key, value in subscores.items()},
        "evidence_sources": {
            "qualitative_judge": bool(evaluation),
            "task_benchmark": bool(benchmark),
            "stability_test": bool(stability),
        },
        "recommendation": build_recommendation(overall, complete),
    }
    write_combined_files(case_dir, report)
    return report


def build_conclusion(score: float | None, complete: bool, missing: list[str]) -> str:
    if score is None:
        return "Combined evaluation cannot be computed yet because no evaluation evidence is available."
    prefix = "Complete" if complete else "Provisional"
    missing_text = "" if complete else f" Missing components: {', '.join(missing)}."
    if score >= 75:
        return f"{prefix} combined result suggests the persona is promising for internal simulation use.{missing_text}"
    if score >= 55:
        return f"{prefix} combined result suggests partial fidelity with notable gaps that should be reviewed before use.{missing_text}"
    return f"{prefix} combined result suggests weak fidelity; this persona should not be relied on without further improvement.{missing_text}"


def build_recommendation(score: float | None, complete: bool) -> dict[str, list[str]]:
    if score is None:
        return {
            "appropriate_uses": [],
            "not_safe_for": ["Any decision use before evaluation is run"],
            "next_steps": ["Run qualitative judge, task benchmark, and stability test"],
        }
    appropriate = ["internal hypothesis generation", "research discussion aid"]
    if score >= 70:
        appropriate.append("early concept screening with human review")
    not_safe = ["replacing human interviews", "final quantitative claims", "external proof of consumer behavior"]
    next_steps = []
    if not complete:
        next_steps.append("Complete the missing evaluation components")
    next_steps.append("Review mismatched tasks and counterfactual failures")
    return {
        "appropriate_uses": appropriate,
        "not_safe_for": not_safe,
        "next_steps": next_steps,
    }


def pct(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.1f}/100"
    return "n/a"


def render_combined_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    subscores = report.get("subscores", {})
    rec = report.get("recommendation", {})

    def items(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) if values else "- None"

    return "\n".join(
        [
            "# Combined Evaluation Result",
            "",
            f"**Overall score:** {pct(summary.get('overall_score'))}",
            f"**Overall label:** {summary.get('overall_label', 'n/a')}",
            f"**Complete:** {summary.get('is_complete', False)}",
            "",
            summary.get("conclusion", ""),
            "",
            "## Subscores",
            f"- Response fidelity: {pct(subscores.get('response_fidelity'))}",
            f"- Counterfactual sensitivity: {pct(subscores.get('counterfactual_sensitivity'))}",
            f"- Persona grounding: {pct(subscores.get('persona_grounding'))}",
            f"- Behavior consistency: {pct(subscores.get('behavior_consistency'))}",
            "",
            "## Appropriate Uses",
            items(rec.get("appropriate_uses", [])),
            "",
            "## Not Safe For",
            items(rec.get("not_safe_for", [])),
            "",
            "## Next Steps",
            items(rec.get("next_steps", [])),
            "",
        ]
    )


def write_combined_files(case_dir: Path, report: dict[str, Any]) -> None:
    (case_dir / "combined_evaluation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "combined_evaluation_report.md").write_text(
        render_combined_markdown(report),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build combined evaluation report for one case directory.")
    parser.add_argument("case_dir", type=Path)
    args = parser.parse_args()
    compute_combined(args.case_dir)
    print(f"Wrote combined evaluation files to: {args.case_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

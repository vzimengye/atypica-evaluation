from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from ai_interview import call_llm, read_required
from persona_from_pdf import extract_pdf_text, parse_json_object


ROOT = Path(__file__).resolve().parent
PROMPT_PATH = ROOT / "prompts" / "persona_evaluation.md"
UPLOADS_DIR = ROOT / "uploads"


def find_source_pdf(case_dir: Path) -> Path | None:
    candidates = [
        UPLOADS_DIR / f"{case_dir.name}.pdf",
        ROOT / f"{case_dir.name}.pdf",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def build_evaluation_prompt(case_dir: Path, max_human_chars: int = 45000) -> str:
    rubric = read_required(PROMPT_PATH)
    schema = read_required(case_dir / "schema.json")
    persona_card = read_required(case_dir / "persona_card.md")
    simulation_prompt = read_required(case_dir / "simulation_prompt.md")
    ai_transcript = read_required(case_dir / "ai_interview_transcript.md")
    ai_summary = read_required(case_dir / "ai_interview_summary.json")

    source_pdf = find_source_pdf(case_dir)
    if source_pdf:
        human_material = extract_pdf_text(source_pdf)
        if len(human_material) > max_human_chars:
            human_material = human_material[:max_human_chars] + "\n\n[TRUNCATED: human material exceeded max chars]"
    else:
        human_material = "[SOURCE PDF NOT FOUND. Use structured schema as the main human ground truth.]"

    return "\n\n".join(
        [
            rubric,
            "Evaluation inputs:",
            "## Human interview material",
            "```text",
            human_material,
            "```",
            "## Human structured decision schema",
            "```json",
            schema,
            "```",
            "## Generated AI persona card",
            "```markdown",
            persona_card,
            "```",
            "## Generated simulation prompt",
            "```markdown",
            simulation_prompt,
            "```",
            "## AI persona interview transcript",
            "```markdown",
            ai_transcript,
            "```",
            "## AI persona interview summary",
            "```json",
            ai_summary,
            "```",
            "Now produce the evaluation JSON only.",
        ]
    )


def render_evaluation_markdown(report: dict[str, Any]) -> str:
    if report.get("report_markdown"):
        return str(report["report_markdown"])

    summary = report.get("summary", {})
    scopes = report.get("scope_scores", {})
    dimensions = report.get("dimension_scores", {})
    boundary = report.get("boundary_conclusion", {})

    def list_items(items: list[Any]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- None"

    lines = [
        "# Evaluation Report",
        "",
        f"**Overall score:** {summary.get('overall_score', 'n/a')}",
        f"**Overall label:** {summary.get('overall_label', 'n/a')}",
        "",
        summary.get("one_paragraph_conclusion", ""),
        "",
        "## Scope Scores",
    ]
    for key, value in scopes.items():
        lines.extend(
            [
                f"### {key}",
                f"- Score: {value.get('score', 'n/a')}",
                f"- Reason: {value.get('reason', value.get('current_consistency_risk', ''))}",
            ]
        )
    lines.append("")
    lines.append("## Dimension Scores")
    for key, value in dimensions.items():
        lines.extend(
            [
                f"### {key}",
                f"- Score: {value.get('score', 'n/a')}",
                f"- Reason: {value.get('reason', '')}",
            ]
        )
    lines.extend(
        [
            "",
            "## Boundary Conclusion",
            boundary.get("current_capability", ""),
            "",
            "### Appropriate Internal Uses",
            list_items(boundary.get("appropriate_internal_uses", [])),
            "",
            "### Risks Before External Use",
            list_items(boundary.get("risks_before_external_use", [])),
            "",
        ]
    )
    return "\n".join(lines)


def write_evaluation_files(report: dict[str, Any], case_dir: Path) -> None:
    (case_dir / "evaluation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "evaluation_report.md").write_text(
        render_evaluation_markdown(report),
        encoding="utf-8",
    )


def run_evaluation(case_dir: Path, model: str) -> dict[str, Any]:
    prompt = build_evaluation_prompt(case_dir)
    output_text = call_llm(prompt, model)
    report = parse_json_object(output_text)
    write_evaluation_files(report, case_dir)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run persona-vs-human evaluation for one case directory.")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument(
        "--model",
        default=os.getenv("PPIO_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek/deepseek-v3-turbo",
    )
    args = parser.parse_args()

    run_evaluation(args.case_dir, args.model)
    print(f"Wrote evaluation files to: {args.case_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

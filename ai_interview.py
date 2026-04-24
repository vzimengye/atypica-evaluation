from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from interview_protocol import QUESTION_SET, protocol_json, protocol_markdown
from persona_from_pdf import (
    call_openai_compatible_chat,
    call_openai_responses,
    parse_json_object,
)


ROOT = Path(__file__).resolve().parent
PROMPT_PATH = ROOT / "prompts" / "ai_interviewer.md"


def read_required(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    return path.read_text(encoding="utf-8")


def build_ai_interview_prompt(case_dir: Path) -> str:
    protocol = read_required(PROMPT_PATH)
    schema = read_required(case_dir / "schema.json")
    persona_card = read_required(case_dir / "persona_card.md")
    simulation_prompt = read_required(case_dir / "simulation_prompt.md")
    split_info = (case_dir / "evaluation_split.json").read_text(encoding="utf-8") if (case_dir / "evaluation_split.json").exists() else "{}"
    full_protocol = protocol_markdown(QUESTION_SET)

    return "\n\n".join(
        [
            protocol,
            "Evaluation split metadata:",
            "```json",
            split_info,
            "```",
            "Use this full interview protocol. Each question already carries its building or holdout role in the JSON metadata:",
            "```json",
            protocol_json(QUESTION_SET),
            "```",
            "Readable interview protocol:",
            "```markdown",
            full_protocol,
            "```",
            "Simulated consumer source materials:",
            "## structured decision schema",
            "```json",
            schema,
            "```",
            "## persona card",
            "```markdown",
            persona_card,
            "```",
            "## simulation prompt",
            "```markdown",
            simulation_prompt,
            "```",
            "Now conduct the full AI persona interview and return the requested JSON only.",
        ]
    )


def call_llm(prompt: str, model: str) -> str:
    ppio_key = os.getenv("PPIO_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if ppio_key:
        return call_openai_compatible_chat(
            prompt,
            model,
            ppio_key,
            os.getenv("PPIO_BASE_URL", "https://api.ppio.com/openai"),
        )
    if openai_key:
        return call_openai_responses(prompt, model, openai_key)
    raise RuntimeError("Set PPIO_API_KEY or OPENAI_API_KEY before running AI interview.")


def is_placeholder_markdown(value: str) -> bool:
    stripped = (value or "").strip()
    if not stripped:
        return True
    normalized = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not normalized:
        return True
    if normalized == ["# AI Persona Interview Transcript", "..."]:
        return True
    if normalized == ["# AI Interview Summary", "..."]:
        return True
    if len(normalized) <= 2 and any(line == "..." for line in normalized):
        return True
    return False


def render_fallback_transcript(question_answers: list[dict[str, Any]]) -> str:
    lines = ["# AI Persona Interview Transcript", ""]
    current_block = None
    for item in question_answers:
        block_label = str(item.get("block_label", "")).strip()
        if block_label != current_block:
            current_block = block_label
            if current_block:
                lines.extend([f"## {current_block}", ""])
        qid = str(item.get("question_id", "")).strip()
        split = str(item.get("split", "")).strip() or "unknown"
        question = str(item.get("question", "")).strip()
        answer_summary = str(item.get("answer_summary", "")).strip() or "No clear answer extracted."
        key_reason = str(item.get("key_reason", "")).strip()
        concrete_example = str(item.get("concrete_example", "")).strip()
        lines.append(f"### {qid} ({split})")
        lines.append(f"**Interviewer:** {question}")
        lines.append(f"**Persona:** {answer_summary}")
        if key_reason:
            lines.append(f"**Reason:** {key_reason}")
        if concrete_example:
            lines.append(f"**Example:** {concrete_example}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_fallback_summary(summary: dict[str, Any], question_answers: list[dict[str, Any]]) -> str:
    lines = ["# AI Interview Summary", ""]
    if question_answers:
        building_count = sum(1 for item in question_answers if item.get("split") == "building")
        holdout_count = sum(1 for item in question_answers if item.get("split") == "holdout")
        lines.extend(
            [
                "## Coverage",
                f"- Building questions answered: {building_count}",
                f"- Holdout questions answered: {holdout_count}",
                "",
            ]
        )

    key_sections = [
        ("Decision Context", summary.get("decision_context")),
        ("Consideration Set", summary.get("consideration_set")),
        ("Evaluation Criteria", summary.get("evaluation_criteria")),
        ("Drivers", summary.get("drivers")),
        ("Barriers", summary.get("barriers")),
        ("Trust Signals", summary.get("trust_signals")),
        ("Deal Breakers", summary.get("deal_breakers")),
        ("Thresholds", summary.get("thresholds")),
        ("Counterfactual Shifts", summary.get("counterfactual_shifts")),
        ("Reflection", summary.get("reflection")),
        ("Language Markers", summary.get("language_markers")),
        ("Confidence Flags", summary.get("confidence_flags")),
    ]
    for title, value in key_sections:
        lines.append(f"## {title}")
        if isinstance(value, dict):
            if value:
                for key, item in value.items():
                    lines.append(f"- {key}: {item}")
            else:
                lines.append("- None")
        elif isinstance(value, list):
            if value:
                for item in value:
                    lines.append(f"- {item}")
            else:
                lines.append("- None")
        elif value:
            lines.append(f"- {value}")
        else:
            lines.append("- None")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_ai_interview_files(result: dict[str, Any], case_dir: Path) -> None:
    transcript = str(result.get("transcript_markdown", "") or "")
    question_answers = result.get("question_answers", [])
    summary = result.get("summary", {})
    summary_markdown = str(result.get("summary_markdown", "") or "")

    if is_placeholder_markdown(transcript):
        transcript = render_fallback_transcript(question_answers)
    if is_placeholder_markdown(summary_markdown):
        summary_markdown = render_fallback_summary(summary, question_answers)

    (case_dir / "ai_interview_transcript.md").write_text(transcript, encoding="utf-8")
    (case_dir / "ai_interview_answers.json").write_text(
        json.dumps(question_answers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "ai_interview_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "ai_interview_summary.md").write_text(summary_markdown, encoding="utf-8")


def run_ai_interview(case_dir: Path, model: str) -> dict[str, Any]:
    prompt = build_ai_interview_prompt(case_dir)
    output_text = call_llm(prompt, model)
    result = parse_json_object(output_text)
    write_ai_interview_files(result, case_dir)
    return result


def repair_ai_interview_files(case_dir: Path) -> bool:
    answers_path = case_dir / "ai_interview_answers.json"
    summary_json_path = case_dir / "ai_interview_summary.json"
    transcript_path = case_dir / "ai_interview_transcript.md"
    summary_md_path = case_dir / "ai_interview_summary.md"

    if not answers_path.exists() or not summary_json_path.exists():
        return False

    question_answers = json.loads(answers_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_json_path.read_text(encoding="utf-8"))
    transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
    summary_markdown = summary_md_path.read_text(encoding="utf-8") if summary_md_path.exists() else ""

    changed = False
    if is_placeholder_markdown(transcript):
        transcript_path.write_text(render_fallback_transcript(question_answers), encoding="utf-8")
        changed = True
    if is_placeholder_markdown(summary_markdown):
        summary_md_path.write_text(render_fallback_summary(summary, question_answers), encoding="utf-8")
        changed = True
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed AI persona interview for one case directory.")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--repair", action="store_true", help="Repair placeholder transcript/summary files from existing JSON outputs.")
    parser.add_argument(
        "--model",
        default=os.getenv("PPIO_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek/deepseek-v3-turbo",
    )
    args = parser.parse_args()

    if args.repair:
        changed = repair_ai_interview_files(args.case_dir)
        print(f"Repaired AI interview files: {args.case_dir}" if changed else f"No repair needed: {args.case_dir}")
    else:
        run_ai_interview(args.case_dir, args.model)
        print(f"Wrote AI interview files to: {args.case_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

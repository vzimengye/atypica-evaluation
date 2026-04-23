from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

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

    return "\n\n".join(
        [
            protocol,
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


def write_ai_interview_files(result: dict[str, Any], case_dir: Path) -> None:
    transcript = result.get("transcript_markdown", "")
    summary = result.get("summary", {})
    summary_markdown = result.get("summary_markdown", "")

    (case_dir / "ai_interview_transcript.md").write_text(transcript, encoding="utf-8")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed AI persona interview for one case directory.")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument(
        "--model",
        default=os.getenv("PPIO_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek/deepseek-v3-turbo",
    )
    args = parser.parse_args()

    run_ai_interview(args.case_dir, args.model)
    print(f"Wrote AI interview files to: {args.case_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pypdf import PdfReader


SYSTEM_PROMPT = """You are a research assistant for Atypica AI Simulation validation.

Your job is to transform one real-consumer interview PDF into three artifacts:
1. structured_decision_schema
2. ai_persona_card
3. simulation_prompt

Important principles:
- This is decision-making simulation, not generic persona writing.
- Ground every claim in the interview evidence.
- Preserve the respondent's constraints, trade-offs, deal breakers, trust signals, and natural explanation style.
- Do not invent demographic facts or brands that are not in the interview.
- If evidence is weak or missing, mark it in confidence_flags instead of guessing.
- Return ONLY valid JSON. Do not include markdown fences.
"""


USER_PROMPT_TEMPLATE = """Convert the following interview material into an AI simulation persona package.

Source file: __SOURCE_FILE__

Return a single valid JSON object with exactly these top-level keys:

{
  "source_metadata": {
    "source_file": string,
    "respondent_name": string | null,
    "scenario": string | null,
    "extraction_notes": string[]
  },
  "structured_decision_schema": {
    "person_id": string,
    "basic_profile": {
      "known_facts": string[],
      "do_not_infer": string[]
    },
    "decision_context": {
      "category": string | null,
      "trigger": string | null,
      "job_to_be_done": string | null,
      "decision_owner": string | null,
      "constraints": string[],
      "stakes_if_no_decision": string | null
    },
    "consideration_set": {
      "initial_options": string[],
      "actually_considered": string[],
      "default_baseline": string | null,
      "most_attractive_option": string | null,
      "discarded_options": [
        {
          "option": string,
          "reason": string,
          "evidence": string
        }
      ]
    },
    "goals": string[],
    "evaluation_criteria": [
      {
        "criterion": string,
        "priority": "must_have" | "high" | "medium" | "low" | "unknown",
        "rule": string,
        "evidence": string
      }
    ],
    "decision_drivers": [
      {
        "driver": string,
        "why_it_matters": string,
        "evidence": string
      }
    ],
    "trust_signals": [
      {
        "signal": string,
        "trust_level": "very_high" | "high" | "medium" | "low",
        "evidence": string
      }
    ],
    "barriers": [
      {
        "barrier": string,
        "effect_on_decision": string,
        "evidence": string
      }
    ],
    "deal_breakers": [
      {
        "condition": string,
        "expected_behavior": string,
        "evidence": string
      }
    ],
    "trade_offs": [
      {
        "trade_off": string,
        "likely_resolution": string,
        "evidence": string
      }
    ],
    "counterfactual_shifts": [
      {
        "condition_change": string,
        "expected_shift": string,
        "direction": "more_likely" | "less_likely" | "switch_option" | "no_change" | "unclear",
        "evidence": string
      }
    ],
    "language_markers": string[],
    "confidence_flags": [
      {
        "field": string,
        "issue": string,
        "severity": "low" | "medium" | "high"
      }
    ]
  },
  "ai_persona_card": {
    "one_sentence_summary": string,
    "decision_style": string,
    "core_decision_rules": string[],
    "trust_hierarchy": string[],
    "likely_hesitations": string[],
    "persuasion_path": string[],
    "abandonment_conditions": string[],
    "response_style": string,
    "should_not_do": string[]
  },
  "simulation_prompt": {
    "system_prompt": string,
    "task_prompt_template": string,
    "answering_rules": string[],
    "output_format": {
      "decision": string,
      "interest_score": string,
      "trust_score": string,
      "main_drivers": string,
      "main_barriers": string,
      "counterfactual_reaction": string,
      "natural_explanation": string,
      "evidence_used": string
    }
  }
}

Interview material:
---
__INTERVIEW_TEXT__
---
"""


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    chunks: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks.append(f"\n--- Page {index} ---\n{text.strip()}")
    return "\n".join(chunks).strip()


def slugify(value: str) -> str:
    value = re.sub(r"\.[^.]+$", "", value)
    value = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", value).strip("_")
    return value[:80] or "persona"


def build_prompt(source_file: str, interview_text: str, max_chars: int) -> str:
    if len(interview_text) > max_chars:
        interview_text = interview_text[:max_chars] + "\n\n[TRUNCATED: input exceeded max_chars]"
    return (
        USER_PROMPT_TEMPLATE.replace("__SOURCE_FILE__", source_file)
        .replace("__INTERVIEW_TEXT__", interview_text)
    )


def call_openai_responses(prompt: str, model: str, api_key: str) -> str:
    payload = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": prompt,
        "max_output_tokens": 8000,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {details}") from exc

    if data.get("output_text"):
        return data["output_text"]

    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if "text" in content:
                parts.append(content["text"])
    if not parts:
        raise RuntimeError(f"Could not find text output in API response: {data}")
    return "\n".join(parts)


def call_openai_compatible_chat(
    prompt: str,
    model: str,
    api_key: str,
    base_url: str,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 8000,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI-compatible API error {exc.code}: {details}") from exc

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"Could not find choices in API response: {data}")
    message = choices[0].get("message", {})
    content = message.get("content")
    if not content:
        raise RuntimeError(f"Could not find message content in API response: {data}")
    return content


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def render_persona_card(package: dict[str, Any]) -> str:
    card = package["ai_persona_card"]

    def lines(items: list[Any]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- None"

    return "\n".join(
        [
            f"# {card.get('one_sentence_summary', 'AI Persona Card')}",
            "",
            f"**Decision Style:** {card.get('decision_style', '')}",
            "",
            "## Core Decision Rules",
            lines(card.get("core_decision_rules", [])),
            "",
            "## Trust Hierarchy",
            lines(card.get("trust_hierarchy", [])),
            "",
            "## Likely Hesitations",
            lines(card.get("likely_hesitations", [])),
            "",
            "## Persuasion Path",
            lines(card.get("persuasion_path", [])),
            "",
            "## Abandonment Conditions",
            lines(card.get("abandonment_conditions", [])),
            "",
            "## Response Style",
            card.get("response_style", ""),
            "",
            "## Should Not Do",
            lines(card.get("should_not_do", [])),
            "",
        ]
    )


def render_simulation_prompt(package: dict[str, Any]) -> str:
    sim = package["simulation_prompt"]
    rules = "\n".join(f"- {rule}" for rule in sim.get("answering_rules", [])) or "- None"
    output_format = json.dumps(sim.get("output_format", {}), ensure_ascii=False, indent=2)
    return "\n".join(
        [
            "# Simulation Prompt",
            "",
            "## System Prompt",
            "",
            "```text",
            sim.get("system_prompt", "").strip(),
            "```",
            "",
            "## Task Prompt Template",
            "",
            "```text",
            sim.get("task_prompt_template", "").strip(),
            "```",
            "",
            "## Answering Rules",
            rules,
            "",
            "## Output Format",
            "",
            "```json",
            output_format,
            "```",
            "",
        ]
    )


def write_result_files(package: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "schema.json").write_text(
        json.dumps(package["structured_decision_schema"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "persona_card.md").write_text(
        render_persona_card(package),
        encoding="utf-8",
    )
    (output_dir / "simulation_prompt.md").write_text(
        render_simulation_prompt(package),
        encoding="utf-8",
    )


def generate_persona_package(
    pdf_path: Path,
    output_dir: Path,
    model: str,
    max_chars: int = 45000,
) -> dict[str, Any]:
    interview_text = extract_pdf_text(pdf_path)
    prompt = build_prompt(pdf_path.name, interview_text, max_chars)

    ppio_key = os.getenv("PPIO_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if ppio_key:
        output_text = call_openai_compatible_chat(
            prompt,
            model,
            ppio_key,
            os.getenv("PPIO_BASE_URL", "https://api.ppio.com/openai"),
        )
    elif openai_key:
        output_text = call_openai_responses(prompt, model, openai_key)
    else:
        raise RuntimeError("Set PPIO_API_KEY or OPENAI_API_KEY before running automatic generation.")

    package = parse_json_object(output_text)
    write_result_files(package, output_dir)
    return package


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a structured decision schema, AI persona card, and simulation prompt from an interview PDF."
    )
    parser.add_argument("pdf", type=Path, help="Path to interview PDF")
    parser.add_argument("--outdir", type=Path, default=Path("results"))
    parser.add_argument(
        "--model",
        default=os.getenv("PPIO_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek/deepseek-v3-turbo",
    )
    parser.add_argument("--max-chars", type=int, default=45000)
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 1

    args.outdir.mkdir(parents=True, exist_ok=True)
    stem = slugify(args.pdf.name)
    output_dir = args.outdir / stem
    generate_persona_package(args.pdf, output_dir, args.model, args.max_chars)

    print(f"Wrote schema: {output_dir / 'schema.json'}")
    print(f"Wrote persona card: {output_dir / 'persona_card.md'}")
    print(f"Wrote simulation prompt: {output_dir / 'simulation_prompt.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

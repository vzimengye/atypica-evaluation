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

from interview_protocol import (
    QUESTION_SET,
    holdout_questions,
    protocol_json,
    questions_for_persona,
    render_ground_truth_markdown,
    render_split_markdown,
    split_summary,
)


EXTRACTION_SYSTEM_PROMPT = """You are a research assistant for Atypica AI Simulation validation.

Your first job is to extract the real respondent's answers against a fixed interview protocol.

Rules:
- Ground every extracted answer in the source interview evidence.
- Do not infer answers that are not supported.
- If the interview only partially answers a question, mark it as partial.
- Keep evidence snippets short.
- Return ONLY valid JSON. Do not include markdown fences.
"""


PERSONA_SYSTEM_PROMPT = """You are a research assistant for Atypica AI Simulation validation.

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


EXTRACTION_USER_PROMPT_TEMPLATE = """Extract the respondent's answers for the fixed interview protocol below.

Source file: __SOURCE_FILE__

Return a single valid JSON object with exactly this structure:

{
  "source_metadata": {
    "source_file": string,
    "respondent_name": string | null,
    "scenario": string | null,
    "extraction_notes": string[]
  },
  "question_answers": [
    {
      "question_id": string,
      "block_id": string,
      "block_label": string,
      "question_number": number,
      "question": string,
      "target": string,
      "use_for_persona": boolean,
      "answer_status": "answered" | "partial" | "not_answered",
      "answer_summary": string,
      "concrete_example": string,
      "evidence_snippets": [string],
      "confidence": "high" | "medium" | "low",
      "notes": string
    }
  ]
}

Protocol:
```json
__QUESTION_PROTOCOL_JSON__
```

Interview material:
---
__INTERVIEW_TEXT__
---
"""


PERSONA_USER_PROMPT_TEMPLATE = """Convert the following building-only interview material into an AI simulation persona package.

Source file: __SOURCE_FILE__

This persona must be built ONLY from the provided building subset.
Do not use hidden or withheld answers.

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

Question split summary:
```json
__SPLIT_SUMMARY_JSON__
```

Building-only human material:
```json
__BUILDING_QUESTION_ANSWERS_JSON__
```

Interview material for persona grounding:
---
__BUILDING_QUESTION_ANSWERS_MARKDOWN__
---
"""


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    chunks: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks.append(f"\n--- Page {index} ---\n{text.strip()}")
    return "\n".join(chunks).strip()


def load_cached_source_text(case_dir: Path) -> str:
    path = case_dir / SOURCE_TEXT_FILE
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def slugify(value: str) -> str:
    value = re.sub(r"\.[^.]+$", "", value)
    value = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", value).strip("_")
    return value[:80] or "persona"


def build_extraction_prompt(source_file: str, interview_text: str, max_chars: int) -> str:
    if len(interview_text) > max_chars:
        interview_text = interview_text[:max_chars] + "\n\n[TRUNCATED: input exceeded max_chars]"
    return (
        EXTRACTION_USER_PROMPT_TEMPLATE.replace("__SOURCE_FILE__", source_file)
        .replace("__QUESTION_PROTOCOL_JSON__", protocol_json(QUESTION_SET))
        .replace("__INTERVIEW_TEXT__", interview_text)
    )


def build_persona_prompt(source_file: str, building_data: dict[str, Any]) -> str:
    building_json = json.dumps(building_data, ensure_ascii=False, indent=2)
    building_markdown = render_ground_truth_markdown(
        "Persona Building Ground Truth",
        building_data.get("question_answers", []),
    )
    return (
        PERSONA_USER_PROMPT_TEMPLATE.replace("__SOURCE_FILE__", source_file)
        .replace("__SPLIT_SUMMARY_JSON__", json.dumps(split_summary(), ensure_ascii=False, indent=2))
        .replace("__BUILDING_QUESTION_ANSWERS_JSON__", building_json)
        .replace("__BUILDING_QUESTION_ANSWERS_MARKDOWN__", building_markdown)
    )


def call_with_active_provider(prompt: str, model: str, system_prompt: str) -> str:
    ppio_key = os.getenv("PPIO_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if ppio_key:
        return call_openai_compatible_chat(
            prompt,
            model,
            ppio_key,
            os.getenv("PPIO_BASE_URL", "https://api.ppio.com/openai"),
            system_prompt,
        )
    if openai_key:
        return call_openai_responses(prompt, model, openai_key, system_prompt)
    raise RuntimeError("Set PPIO_API_KEY or OPENAI_API_KEY before running automatic generation.")


def question_lookup() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in QUESTION_SET}


def normalize_question_answers(extraction: dict[str, Any]) -> dict[str, Any]:
    lookup = question_lookup()
    normalized = []
    existing = {item.get("question_id"): item for item in extraction.get("question_answers", [])}
    for question in QUESTION_SET:
        raw = existing.get(question["id"], {})
        normalized.append(
            {
                "id": question["id"],
                "question_id": question["id"],
                "block_id": question["block_id"],
                "block_label": question["block_label"],
                "question_number": question["question_number"],
                "target": question["target"],
                "question": question["question"],
                "use_for_persona": question["use_for_persona"],
                "evaluation_focus": question.get("evaluation_focus", []),
                "answer_status": raw.get("answer_status", "not_answered"),
                "answer_summary": raw.get("answer_summary", ""),
                "concrete_example": raw.get("concrete_example", ""),
                "evidence_snippets": raw.get("evidence_snippets", []),
                "confidence": raw.get("confidence", "low"),
                "notes": raw.get("notes", ""),
            }
        )
    extraction["question_answers"] = normalized
    extraction.setdefault("source_metadata", {})
    extraction["source_metadata"].setdefault("source_file", "")
    extraction["source_metadata"].setdefault("respondent_name", None)
    extraction["source_metadata"].setdefault("scenario", None)
    extraction["source_metadata"].setdefault("extraction_notes", [])
    return extraction


def select_question_answers(extraction: dict[str, Any], use_for_persona: bool) -> dict[str, Any]:
    selected = [item for item in extraction.get("question_answers", []) if item.get("use_for_persona") == use_for_persona]
    return {
        "source_metadata": extraction.get("source_metadata", {}),
        "mode": "building" if use_for_persona else "holdout",
        "question_answers": selected,
    }


def build_split_artifacts(extraction: dict[str, Any]) -> dict[str, Any]:
    building = select_question_answers(extraction, True)
    holdout = select_question_answers(extraction, False)
    split = split_summary()
    split["building_questions"] = questions_for_persona()
    split["holdout_questions"] = holdout_questions()
    return {
        "all_questions": extraction,
        "building": building,
        "holdout": holdout,
        "split": split,
    }


def attach_grounding_scope(schema: dict[str, Any], split: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(schema)
    enriched["grounding_scope"] = {
        "mode": split.get("mode"),
        "building_question_ids": split.get("building_question_ids", []),
        "holdout_question_ids": split.get("holdout_question_ids", []),
    }
    return enriched


def call_openai_responses(prompt: str, model: str, api_key: str, system_prompt: str = PERSONA_SYSTEM_PROMPT) -> str:
    payload = {
        "model": model,
        "instructions": system_prompt,
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
    system_prompt: str = PERSONA_SYSTEM_PROMPT,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
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


def write_result_files(package: dict[str, Any], split_artifacts: dict[str, Any], interview_text: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    schema = attach_grounding_scope(package["structured_decision_schema"], split_artifacts["split"])
    (output_dir / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2),
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
    (output_dir / "interview_ground_truth.json").write_text(
        json.dumps(split_artifacts["all_questions"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "interview_ground_truth.md").write_text(
        render_ground_truth_markdown("Interview Ground Truth", split_artifacts["all_questions"]["question_answers"]),
        encoding="utf-8",
    )
    (output_dir / "building_ground_truth.json").write_text(
        json.dumps(split_artifacts["building"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "building_ground_truth.md").write_text(
        render_ground_truth_markdown("Persona Building Ground Truth", split_artifacts["building"]["question_answers"]),
        encoding="utf-8",
    )
    (output_dir / "holdout_ground_truth.json").write_text(
        json.dumps(split_artifacts["holdout"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "holdout_ground_truth.md").write_text(
        render_ground_truth_markdown("Holdout Evaluation Ground Truth", split_artifacts["holdout"]["question_answers"]),
        encoding="utf-8",
    )
    (output_dir / "evaluation_split.json").write_text(
        json.dumps(split_artifacts["split"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "evaluation_split.md").write_text(
        render_split_markdown(split_artifacts["split"]),
        encoding="utf-8",
    )
    (output_dir / SOURCE_TEXT_FILE).write_text(interview_text, encoding="utf-8")


def generate_persona_package(
    pdf_path: Path,
    output_dir: Path,
    model: str,
    max_chars: int = 45000,
) -> dict[str, Any]:
    interview_text = extract_pdf_text(pdf_path)
    extraction_prompt = build_extraction_prompt(pdf_path.name, interview_text, max_chars)
    extraction_text = call_with_active_provider(extraction_prompt, model, EXTRACTION_SYSTEM_PROMPT)
    extraction = normalize_question_answers(parse_json_object(extraction_text))
    split_artifacts = build_split_artifacts(extraction)

    persona_prompt = build_persona_prompt(pdf_path.name, split_artifacts["building"])
    persona_text = call_with_active_provider(persona_prompt, model, PERSONA_SYSTEM_PROMPT)
    package = parse_json_object(persona_text)
    write_result_files(package, split_artifacts, interview_text, output_dir)
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
SOURCE_TEXT_FILE = "source_pdf_text.txt"

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import threading
import warnings
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

warnings.filterwarnings("ignore", message="'cgi' is deprecated*", category=DeprecationWarning)
import cgi

from ai_interview import run_ai_interview
from combined_evaluation import compute_combined
from evaluation import run_evaluation
from persona_from_pdf import generate_persona_package, slugify
from stability import run_stability_test
from task_benchmark import run_task_benchmark


ROOT = Path(__file__).resolve().parent
UPLOADS_DIR = ROOT / "uploads"
RESULTS_DIR = ROOT / "results"
CORE_FILES = ("schema.json", "persona_card.md", "simulation_prompt.md")
INTERVIEW_FILES = (
    "ai_interview_transcript.md",
    "ai_interview_summary.json",
    "ai_interview_summary.md",
)
EVALUATION_FILES = ("evaluation_report.json", "evaluation_report.md")
BENCHMARK_FILES = (
    "human_task_answers.json",
    "ai_task_answers.json",
    "task_benchmark_report.json",
    "task_benchmark_report.md",
)
STABILITY_FILES = ("stability_report.json", "stability_report.md")
COMBINED_FILES = ("combined_evaluation_report.json", "combined_evaluation_report.md")
JOB_STATUS_FILE = "evaluation_job_status.json"
DOWNLOADABLE_FILES = CORE_FILES + INTERVIEW_FILES + EVALUATION_FILES + BENCHMARK_FILES + STABILITY_FILES + COMBINED_FILES
JOB_LOCK = threading.Lock()
ACTIVE_JOBS: set[str] = set()


def unique_dir(base: Path) -> Path:
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = base.with_name(f"{base.name}_{index}")
        if not candidate.exists():
            return candidate
        index += 1


def has_any_result(path: Path) -> bool:
    return any((path / name).exists() for name in DOWNLOADABLE_FILES)


def has_core_result(path: Path) -> bool:
    return all((path / name).exists() for name in CORE_FILES)


def has_interview_result(path: Path) -> bool:
    return all((path / name).exists() for name in INTERVIEW_FILES)


def has_evaluation_result(path: Path) -> bool:
    return all((path / name).exists() for name in EVALUATION_FILES)


def has_benchmark_result(path: Path) -> bool:
    return all((path / name).exists() for name in BENCHMARK_FILES)


def has_stability_result(path: Path) -> bool:
    return all((path / name).exists() for name in STABILITY_FILES)


def has_combined_result(path: Path) -> bool:
    return all((path / name).exists() for name in COMBINED_FILES)


def job_status_path(case_dir: Path) -> Path:
    return case_dir / JOB_STATUS_FILE


def read_job_status(case_dir: Path) -> dict:
    return parse_json_file(job_status_path(case_dir))


def write_job_status(case_dir: Path, status: dict) -> None:
    job_status_path(case_dir).write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def is_job_running(case_dir: Path) -> bool:
    status = read_job_status(case_dir)
    return status.get("status") == "running"


def list_cases() -> list[Path]:
    if not RESULTS_DIR.exists():
        return []
    cases = [item for item in RESULTS_DIR.iterdir() if item.is_dir() and has_any_result(item)]
    return sorted(cases, key=lambda item: item.stat().st_mtime, reverse=True)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    rendered: list[str] = []
    in_code = False
    code_lines: list[str] = []

    def inline(value: str) -> str:
        escaped = html.escape(value)
        parts = escaped.split("**")
        if len(parts) >= 3:
            rebuilt = []
            bold = False
            for part in parts:
                rebuilt.append(f"<strong>{part}</strong>" if bold else part)
                bold = not bold
            escaped = "".join(rebuilt)
        return escaped

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                rendered.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if stripped.startswith("# "):
            rendered.append(f"<h1>{inline(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            rendered.append(f"<h2>{inline(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            rendered.append(f"<h3>{inline(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            rendered.append(f"<p class='bullet'>- {inline(stripped[2:])}</p>")
        elif stripped:
            rendered.append(f"<p>{inline(stripped)}</p>")
        else:
            rendered.append("<div class='spacer'></div>")

    if in_code:
        rendered.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    return "\n".join(rendered)


def parse_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def score_to_percent(score: object) -> int:
    if isinstance(score, (int, float)):
        value = max(0.0, min(5.0, float(score)))
        return round(value / 5.0 * 100)
    return 0


def score_label(score: object) -> str:
    if isinstance(score, (int, float)):
        return f"{score}/5"
    return str(score or "n/a")


def humanize_key(value: str) -> str:
    return value.replace("_", " ").title()


def render_score_bar(label: str, score: object, reason: str = "") -> str:
    percent = score_to_percent(score)
    return f"""
    <div class="score-row">
      <div class="score-row-head">
        <span>{html.escape(label)}</span>
        <strong>{html.escape(score_label(score))}</strong>
      </div>
      <div class="score-bar" aria-label="{html.escape(label)} score">
        <div class="score-bar-fill" style="width: {percent}%"></div>
      </div>
      {f"<p>{html.escape(reason)}</p>" if reason else ""}
    </div>
    """


def render_list_chips(items: list, empty: str) -> str:
    if not items:
        return f"<span class='chip muted'>{html.escape(empty)}</span>"
    return "".join(f"<span class='chip'>{html.escape(str(item))}</span>" for item in items[:6])


def render_evaluation_dashboard(report: dict) -> str:
    if not report:
        return ""

    summary = report.get("summary", {})
    scope_scores = report.get("scope_scores", {})
    dimensions = report.get("dimension_scores", {})
    boundary = report.get("boundary_conclusion", {})
    overall_score = summary.get("overall_score")
    overall_label = summary.get("overall_label", "n/a")
    overall_percent = score_to_percent(overall_score)

    scope_cards = []
    for key in ("persona_grounding", "response_fidelity", "counterfactual_sensitivity"):
        value = scope_scores.get(key, {})
        scope_cards.append(
            f"""
            <div class="metric-card">
              <span>{html.escape(humanize_key(key))}</span>
              <strong>{html.escape(score_label(value.get("score")))}</strong>
              <p>{html.escape(value.get("reason", ""))}</p>
            </div>
            """
        )
    consistency = scope_scores.get("behavior_consistency", {})
    if consistency:
        scope_cards.append(
            f"""
            <div class="metric-card">
              <span>Behavior Consistency</span>
              <strong>{html.escape(score_label(consistency.get("score")))}</strong>
              <p>Current risk: {html.escape(str(consistency.get("current_consistency_risk", "n/a")))}</p>
            </div>
            """
        )

    dimension_bars = []
    for key, value in dimensions.items():
        dimension_bars.append(render_score_bar(humanize_key(key), value.get("score"), value.get("reason", "")))

    return f"""
    <div class="evaluation-dashboard">
      <div class="dashboard-head">
        <div>
          <span class="eyebrow">Judge Snapshot</span>
          <h3>{html.escape(str(overall_label).replace("_", " ").title())}</h3>
          <p>{html.escape(summary.get("one_paragraph_conclusion", ""))}</p>
        </div>
        <div class="overall-score">
          <div class="score-ring" style="--score: {overall_percent}%">
            <span>{html.escape(score_label(overall_score))}</span>
          </div>
          <small>Overall</small>
        </div>
      </div>

      <div class="metric-grid">
        {''.join(scope_cards)}
      </div>

      <div class="chart-card">
        <h3>Dimension Scores</h3>
        {''.join(dimension_bars)}
      </div>

      <div class="insight-grid">
        <div>
          <h3>Good For</h3>
          <div class="chips">{render_list_chips(summary.get("usable_for", []), "No recommended uses listed")}</div>
        </div>
        <div>
          <h3>Not Safe For</h3>
          <div class="chips">{render_list_chips(summary.get("not_yet_safe_for", []), "No risks listed")}</div>
        </div>
        <div>
          <h3>Next Tests</h3>
          <div class="chips">{render_list_chips(boundary.get("what_to_test_next", []), "No next tests listed")}</div>
        </div>
      </div>
    </div>
    """


def pct_label(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.0f}%"
    return "n/a"


def render_benchmark_dashboard(report: dict) -> str:
    if not report:
        return ""
    metrics = report.get("metrics", {})
    cards = [
        ("Overall Task Score", metrics.get("overall_task_score"), None),
        ("Classification", metrics.get("classification_accuracy"), metrics.get("classification_match_count")),
        ("Ranking Top-1", metrics.get("ranking_top1_agreement"), metrics.get("ranking_top1_count")),
        ("Counterfactual", metrics.get("counterfactual_direction_match"), metrics.get("counterfactual_direction_count")),
    ]
    card_html = []
    for label, value, count in cards:
        card_html.append(
            f"""
            <div class="metric-card compact">
              <span>{html.escape(label)}</span>
              <strong>{html.escape(pct_label(value))}</strong>
              <p>{html.escape(str(count or ""))}</p>
            </div>
            """
        )

    bars = [
        ("Classification Accuracy", metrics.get("classification_accuracy")),
        ("Continuous Similarity", metrics.get("continuous_similarity")),
        ("Ranking Top-3 Overlap", metrics.get("ranking_top3_overlap")),
        ("Counterfactual Direction Match", metrics.get("counterfactual_direction_match")),
    ]
    bar_html = []
    for label, value in bars:
        score = float(value) * 5 if isinstance(value, (int, float)) else None
        bar_html.append(render_score_bar(label, score, ""))

    mae = metrics.get("continuous_mae", "n/a")
    overall_task_percent = round(float(metrics.get("overall_task_score", 0) or 0) * 100)
    return f"""
    <div class="evaluation-dashboard">
      <div class="dashboard-head">
        <div>
          <span class="eyebrow">Task Benchmark Snapshot</span>
          <h3>{html.escape(pct_label(metrics.get("overall_task_score")))} Overall Task Alignment</h3>
          <p>Compares human-derived task answers and AI persona task answers across classification, continuous, ranking, open, and counterfactual tasks.</p>
        </div>
        <div class="overall-score">
          <div class="score-ring" style="--score: {overall_task_percent}%">
            <span>{html.escape(pct_label(metrics.get("overall_task_score")))}</span>
          </div>
          <small>Benchmark</small>
        </div>
      </div>
      <div class="metric-grid">
        {''.join(card_html)}
      </div>
      <div class="chart-card">
        <h3>Task Metrics</h3>
        {''.join(bar_html)}
        <p class="metric-note">Continuous MAE: {html.escape(str(mae))}</p>
      </div>
    </div>
    """


def render_stability_dashboard(report: dict) -> str:
    if not report:
        return ""
    metrics = report.get("metrics", {})
    overall = metrics.get("overall_stability_score")
    overall_percent = round(float(overall or 0) * 100)
    bars = [
        ("Classification Consistency", metrics.get("classification_consistency")),
        ("Counterfactual Consistency", metrics.get("counterfactual_consistency")),
        ("Ranking Top-1 Consistency", metrics.get("ranking_top1_consistency")),
    ]
    bar_html = []
    for label, value in bars:
        score = float(value) * 5 if isinstance(value, (int, float)) else None
        bar_html.append(render_score_bar(label, score, ""))
    return f"""
    <div class="evaluation-dashboard">
      <div class="dashboard-head">
        <div>
          <span class="eyebrow">Stability Snapshot</span>
          <h3>{html.escape(str(metrics.get("stability_label", "n/a")).title())} Stability</h3>
          <p>Measures whether the same AI persona gives stable answers when the same fixed tasks are repeated.</p>
        </div>
        <div class="overall-score">
          <div class="score-ring" style="--score: {overall_percent}%">
            <span>{html.escape(pct_label(overall))}</span>
          </div>
          <small>Stability</small>
        </div>
      </div>
      <div class="chart-card">
        <h3>Stability Metrics</h3>
        {''.join(bar_html)}
        <p class="metric-note">Continuous average range: {html.escape(str(metrics.get("continuous_average_range", "n/a")))}</p>
      </div>
    </div>
    """


def render_combined_dashboard(report: dict) -> str:
    if not report:
        return ""
    summary = report.get("summary", {})
    subscores = report.get("subscores", {})
    recommendation = report.get("recommendation", {})
    overall = summary.get("overall_score")
    overall_percent = round(float(overall or 0))
    bars = [
        ("Response Fidelity", subscores.get("response_fidelity")),
        ("Counterfactual Sensitivity", subscores.get("counterfactual_sensitivity")),
        ("Persona Grounding", subscores.get("persona_grounding")),
        ("Behavior Consistency", subscores.get("behavior_consistency")),
    ]
    bar_html = []
    for label, value in bars:
        score = float(value) / 20 if isinstance(value, (int, float)) else None
        bar_html.append(render_score_bar(label, score, ""))
    return f"""
    <div class="evaluation-dashboard combined-dashboard">
      <div class="dashboard-head">
        <div>
          <span class="eyebrow">Overall Evaluation</span>
          <h3>{html.escape(str(summary.get("overall_label", "n/a")).replace("_", " ").title())}</h3>
          <p>{html.escape(summary.get("conclusion", ""))}</p>
        </div>
        <div class="overall-score">
          <div class="score-ring" style="--score: {overall_percent}%">
            <span>{html.escape(str(overall if overall is not None else "n/a"))}</span>
          </div>
          <small>Combined / 100</small>
        </div>
      </div>
      <div class="chart-card">
        <h3>Weighted Subscores</h3>
        {''.join(bar_html)}
      </div>
      <div class="insight-grid">
        <div>
          <h3>Appropriate Uses</h3>
          <div class="chips">{render_list_chips(recommendation.get("appropriate_uses", []), "No uses listed")}</div>
        </div>
        <div>
          <h3>Not Safe For</h3>
          <div class="chips">{render_list_chips(recommendation.get("not_safe_for", []), "No risks listed")}</div>
        </div>
        <div>
          <h3>Next Steps</h3>
          <div class="chips">{render_list_chips(recommendation.get("next_steps", []), "No next steps listed")}</div>
        </div>
      </div>
    </div>
    """


def status_badges(case: Path) -> str:
    persona_status = "done" if has_core_result(case) else "missing"
    interview_status = "done" if has_interview_result(case) else "not run"
    evaluation_status = "done" if has_evaluation_result(case) else "not run"
    benchmark_status = "done" if has_benchmark_result(case) else "not run"
    stability_status = "done" if has_stability_result(case) else "not run"
    combined_status = "done" if has_combined_result(case) else "not run"
    running = "running" if is_job_running(case) else None
    badges = (
        f"<span class='badge ok'>Persona: {persona_status}</span>"
        f"<span class='badge {'ok' if interview_status == 'done' else 'idle'}'>AI Interview: {interview_status}</span>"
        f"<span class='badge {'ok' if evaluation_status == 'done' else 'idle'}'>Judge: {evaluation_status}</span>"
        f"<span class='badge {'ok' if benchmark_status == 'done' else 'idle'}'>Benchmark: {benchmark_status}</span>"
        f"<span class='badge {'ok' if stability_status == 'done' else 'idle'}'>Stability: {stability_status}</span>"
        f"<span class='badge {'ok' if combined_status == 'done' else 'idle'}'>Overall: {combined_status}</span>"
    )
    if running:
        badges += f"<span class='badge running'>Full Evaluation: {running}</span>"
    return badges


def render_download_links(case_name: str) -> str:
    links = []
    case_dir = RESULTS_DIR / case_name
    for name in DOWNLOADABLE_FILES:
        if (case_dir / name).exists():
            links.append(f"<a href='/download/{quote(case_name)}/{name}'>{html.escape(name)}</a>")
    return "".join(links)


def component_status(done: bool, running: bool = False) -> str:
    if running:
        return "running"
    return "done" if done else "pending"


def render_evaluation_suite(case: Path) -> str:
    job = read_job_status(case)
    steps = job.get("steps", {}) if job.get("status") == "running" else {}
    components = [
        ("AI Interview", has_interview_result(case), steps.get("ai_interview") == "running"),
        ("Judge", has_evaluation_result(case), steps.get("qualitative_judge") == "running"),
        ("Task Benchmark", has_benchmark_result(case), steps.get("task_benchmark") == "running"),
        ("Stability Test", has_stability_result(case), steps.get("stability_test") == "running"),
        ("Overall Result", has_combined_result(case), steps.get("overall") == "running"),
    ]
    cards = []
    for label, done, running in components:
        status = component_status(done, running)
        cards.append(
            f"""
            <div class="suite-card {html.escape(status)}">
              <span>{html.escape(label)}</span>
              <strong>{html.escape(status.title())}</strong>
            </div>
            """
        )
    return f"""
    <section class="panel suite-panel" id="evaluation-suite">
      <h2>Evaluation Suite</h2>
      <p>Full Evaluation runs the three evidence modules in order. Each completed module appears immediately; Overall is added after all three are done.</p>
      <div class="suite-grid">{''.join(cards)}</div>
    </section>
    """


def render_case_content(case: Path) -> str:
    case_name = case.name
    persona = markdown_to_html(read_text(case / "persona_card.md"))
    simulation = markdown_to_html(read_text(case / "simulation_prompt.md"))
    schema = html.escape(read_text(case / "schema.json"))
    transcript = markdown_to_html(read_text(case / "ai_interview_transcript.md"))
    interview_summary_md = markdown_to_html(read_text(case / "ai_interview_summary.md"))
    interview_summary_json = html.escape(read_text(case / "ai_interview_summary.json"))
    evaluation_md = markdown_to_html(read_text(case / "evaluation_report.md"))
    evaluation_json = html.escape(read_text(case / "evaluation_report.json"))
    evaluation_dashboard = render_evaluation_dashboard(parse_json_file(case / "evaluation_report.json"))
    benchmark_md = markdown_to_html(read_text(case / "task_benchmark_report.md"))
    benchmark_json = html.escape(read_text(case / "task_benchmark_report.json"))
    benchmark_dashboard = render_benchmark_dashboard(parse_json_file(case / "task_benchmark_report.json"))
    stability_md = markdown_to_html(read_text(case / "stability_report.md"))
    stability_json = html.escape(read_text(case / "stability_report.json"))
    stability_dashboard = render_stability_dashboard(parse_json_file(case / "stability_report.json"))
    combined_md = markdown_to_html(read_text(case / "combined_evaluation_report.md"))
    combined_json = html.escape(read_text(case / "combined_evaluation_report.json"))
    combined_dashboard = render_combined_dashboard(parse_json_file(case / "combined_evaluation_report.json"))
    job_status = read_job_status(case)
    interview_panel = ""
    evaluation_panel = ""
    benchmark_panel = ""
    stability_panel = ""
    combined_panel = ""
    job_panel = ""

    if has_interview_result(case):
        interview_panel = f"""
        <section class="panel" id="ai-interview-transcript">
          <h2>AI Interview Transcript</h2>
          <div class="markdown">{transcript}</div>
        </section>
        <section class="panel" id="ai-interview-summary">
          <h2>AI Interview Summary</h2>
          <div class="markdown">{interview_summary_md}</div>
          <details>
            <summary>View summary JSON</summary>
            <pre><code>{interview_summary_json}</code></pre>
          </details>
        </section>
        """
    else:
        interview_panel = """
        <section class="panel muted-panel" id="ai-interview-transcript">
          <h2>AI Interview</h2>
          <p>No AI interview yet. Run the fixed Block 1-6 interview to test this persona's decision logic.</p>
        </section>
        """

    if has_evaluation_result(case):
        evaluation_panel = f"""
        <section class="panel" id="evaluation-report">
          <h2>Judge</h2>
          {evaluation_dashboard}
          <div class="markdown">{evaluation_md}</div>
          <details>
            <summary>View evaluation JSON</summary>
            <pre><code>{evaluation_json}</code></pre>
          </details>
        </section>
        """
    else:
        evaluation_panel = """
        <section class="panel muted-panel" id="evaluation-report">
          <h2>Judge</h2>
          <p>No judge result yet. Run it after the AI interview is complete.</p>
        </section>
        """

    if has_benchmark_result(case):
        benchmark_panel = f"""
        <section class="panel" id="task-benchmark">
          <h2>Task Benchmark</h2>
          {benchmark_dashboard}
          <div class="markdown">{benchmark_md}</div>
          <details>
            <summary>View benchmark JSON</summary>
            <pre><code>{benchmark_json}</code></pre>
          </details>
        </section>
        """
    else:
        benchmark_panel = """
        <section class="panel muted-panel" id="task-benchmark">
          <h2>Task Benchmark</h2>
          <p>No task benchmark yet. Run it after the persona has been generated.</p>
        </section>
        """

    if has_stability_result(case):
        stability_panel = f"""
        <section class="panel" id="stability-test">
          <h2>Stability Test</h2>
          {stability_dashboard}
          <div class="markdown">{stability_md}</div>
          <details>
            <summary>View stability JSON</summary>
            <pre><code>{stability_json}</code></pre>
          </details>
        </section>
        """
    else:
        stability_panel = """
        <section class="panel muted-panel" id="stability-test">
          <h2>Stability Test</h2>
          <p>No stability test yet. Full Evaluation will run it after Judge and Task Benchmark.</p>
        </section>
        """

    if has_combined_result(case):
        combined_panel = f"""
        <section class="panel" id="overall-evaluation">
          <h2>Overall Evaluation</h2>
          {combined_dashboard}
          <div class="markdown">{combined_md}</div>
          <details>
            <summary>View overall JSON</summary>
            <pre><code>{combined_json}</code></pre>
          </details>
        </section>
        """
    else:
        combined_panel = """
        <section class="panel muted-panel" id="overall-evaluation">
          <h2>Overall Evaluation</h2>
          <p>No combined result yet. It appears after the evaluation components finish.</p>
        </section>
        """

    if job_status.get("status") == "running":
        steps = job_status.get("steps", {})
        step_html = "".join(
            f"<span class='chip'>{html.escape(name)}: {html.escape(str(value))}</span>"
            for name, value in steps.items()
        )
        job_panel = f"""
        <section class="panel running-panel" id="evaluation-progress">
          <h2>Full Evaluation Running</h2>
          <p>Partial results will appear as soon as each component finishes. This page auto-refreshes while the job is running.</p>
          <div class="chips">{step_html}</div>
        </section>
        """
    elif job_status.get("status") == "failed":
        job_panel = f"""
        <section class="panel error-panel" id="evaluation-progress">
          <h2>Full Evaluation Failed</h2>
          <p>{html.escape(job_status.get("error", "Unknown error"))}</p>
        </section>
        """

    return f"""
    <section class="result-head">
      <h1>{html.escape(case_name)}</h1>
      <div class="badges">{status_badges(case)}</div>
      <div class="links">{render_download_links(case_name)}</div>
      <form class="inline-form primary-action" method="post" action="/full-evaluation" data-loading-title="Full Evaluation Running" data-loading-message="AI Interview -> Judge -> Task Benchmark -> Stability -> Overall. Partial results appear as each step finishes.">
        <input type="hidden" name="case" value="{html.escape(case_name)}">
        <button type="submit">Run Full Evaluation</button>
      </form>
      <details class="advanced-actions">
        <summary>Advanced controls</summary>
        <div class="advanced-action-grid">
      <form class="inline-form" method="post" action="/interview" data-loading-title="Running AI Interview" data-loading-message="The AI persona is answering the fixed Block 1-6 interview protocol.">
        <input type="hidden" name="case" value="{html.escape(case_name)}">
        <button type="submit">Run AI Interview</button>
      </form>
      <form class="inline-form" method="post" action="/evaluate" data-loading-title="Running Judge" data-loading-message="Comparing the human interview PDF with the AI persona interview output using the qualitative rubric.">
        <input type="hidden" name="case" value="{html.escape(case_name)}">
        <button type="submit">Run Judge</button>
      </form>
      <form class="inline-form" method="post" action="/benchmark" data-loading-title="Running Task Benchmark" data-loading-message="Generating and scoring matched decision tasks for the human case and AI persona.">
        <input type="hidden" name="case" value="{html.escape(case_name)}">
        <button type="submit">Run Task Benchmark</button>
      </form>
      <form class="inline-form" method="post" action="/stability" data-loading-title="Running Stability Test" data-loading-message="Repeating the same task set to see whether the AI persona keeps stable decisions.">
        <input type="hidden" name="case" value="{html.escape(case_name)}">
        <button type="submit">Run Stability Test</button>
      </form>
        </div>
      </details>
    </section>

    <nav class="section-nav" aria-label="Case sections">
      <a href="#evaluation-suite">Evaluation Suite</a>
      <a href="#overall-evaluation">Overall</a>
      <a href="#persona-card">Persona Card</a>
      <a href="#simulation-prompt">Simulation Prompt</a>
      <a href="#schema">Schema</a>
      <a href="#ai-interview-transcript">Interview Transcript</a>
      {"<a href='#ai-interview-summary'>Interview Summary</a>" if has_interview_result(case) else ""}
      <a href="#evaluation-report">Judge</a>
      <a href="#task-benchmark">Benchmark</a>
      <a href="#stability-test">Stability</a>
    </nav>

    {render_evaluation_suite(case)}
    {job_panel}
    {combined_panel}
    <section class="panel" id="persona-card">
      <h2>Persona Card</h2>
      <div class="markdown">{persona}</div>
    </section>
    <section class="panel" id="simulation-prompt">
      <h2>Simulation Prompt</h2>
      <div class="markdown">{simulation}</div>
    </section>
    <section class="panel" id="schema">
      <h2>Schema</h2>
      <pre><code>{schema}</code></pre>
    </section>
    {interview_panel}
    {evaluation_panel}
    {benchmark_panel}
    {stability_panel}
    """


def render_page(selected: str | None = None, error: str | None = None, notice: str | None = None) -> bytes:
    cases = list_cases()
    selected_case = None
    if selected:
        candidate = RESULTS_DIR / selected
        if candidate.exists() and candidate.is_dir():
            selected_case = candidate
    if selected_case is None and cases:
        selected_case = cases[0]

    history_items = []
    for case in cases:
        active = " active" if selected_case and case.name == selected_case.name else ""
        modified = datetime.fromtimestamp(case.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        if is_job_running(case):
            mini_badge = "running"
        elif has_combined_result(case):
            mini_badge = "overall ready"
        elif has_stability_result(case):
            mini_badge = "stability tested"
        elif has_benchmark_result(case):
            mini_badge = "benchmarked"
        elif has_evaluation_result(case):
            mini_badge = "evaluated"
        elif has_interview_result(case):
            mini_badge = "interviewed"
        else:
            mini_badge = "persona only"
        history_items.append(
            f"<a class='history-item{active}' href='/?case={quote(case.name)}'>"
            f"<span>{html.escape(case.name)}</span>"
            f"<small>{html.escape(modified)} · {mini_badge}</small>"
            "</a>"
        )

    has_key = bool(os.getenv("PPIO_API_KEY") or os.getenv("OPENAI_API_KEY"))
    warning = "" if has_key else "<div class='warning'>Set PPIO_API_KEY or OPENAI_API_KEY before generating results.</div>"
    error_html = f"<div class='error'>{html.escape(error)}</div>" if error else ""
    notice_html = f"<div class='notice'>{html.escape(notice)}</div>" if notice else ""

    content = "<section class='empty'>Upload an interview PDF to generate a persona package.</section>"
    if selected_case:
        content = render_case_content(selected_case)
    refresh_meta = "<meta http-equiv='refresh' content='5'>" if selected_case and is_job_running(selected_case) else ""
    initial_running = bool(selected_case and is_job_running(selected_case))
    initial_loading_title = "Full Evaluation Running"
    initial_loading_message = "AI Interview -> Judge -> Task Benchmark -> Stability -> Overall. Partial results appear as each step finishes."

    page = f"""<!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      {refresh_meta}
      <title>AI Persona Evaluation Lab</title>
      <style>
        * {{ box-sizing: border-box; }}
        html {{ scroll-behavior: smooth; }}
        body {{
          margin: 0;
          font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #f7f7f5;
          color: #1e2329;
        }}
        .app {{ display: grid; grid-template-columns: 340px 1fr; min-height: 100vh; }}
        aside {{
          border-right: 1px solid #deded8;
          background: #ffffff;
          padding: 24px;
          position: sticky;
          top: 0;
          height: 100vh;
          overflow: auto;
        }}
        main {{ padding: 28px; max-width: 1160px; width: 100%; }}
        h1, h2, h3 {{ margin: 0; letter-spacing: 0; }}
        aside h1 {{ font-size: 22px; margin-bottom: 6px; }}
        aside p {{ color: #687076; font-size: 14px; line-height: 1.5; margin: 0 0 20px; }}
        .upload-form, .inline-form {{ border: 1px solid #deded8; border-radius: 8px; padding: 16px; background: #fbfbfa; }}
        .inline-form {{ padding: 0; border: 0; background: transparent; }}
        input[type="file"] {{ width: 100%; margin-bottom: 14px; }}
        input[type="hidden"] {{ display: none; }}
        button {{
          border: 0;
          border-radius: 8px;
          background: #2563eb;
          color: white;
          font-size: 15px;
          padding: 11px 14px;
          cursor: pointer;
        }}
        .upload-form button {{ width: 100%; }}
        button:hover {{ background: #1d4ed8; }}
        button:disabled {{
          cursor: wait;
          opacity: 0.72;
        }}
        .hint {{ font-size: 12px; color: #687076; margin-top: 10px; }}
        .warning, .error, .notice {{
          border-radius: 8px;
          padding: 11px 12px;
          margin: 14px 0;
          font-size: 13px;
          line-height: 1.45;
        }}
        .warning {{ background: #fff7d6; border: 1px solid #e6c96f; }}
        .error {{ background: #ffe8e8; border: 1px solid #ef9a9a; }}
        .notice {{ background: #e9f7ef; border: 1px solid #8dd0a8; }}
        .history-title {{ margin: 26px 0 10px; font-size: 13px; color: #687076; text-transform: uppercase; }}
        .history {{ display: grid; gap: 8px; }}
        .history-item {{
          display: block;
          padding: 10px 12px;
          border: 1px solid #e2e2dc;
          border-radius: 8px;
          color: #1e2329;
          text-decoration: none;
          background: #fff;
        }}
        .history-item.active {{ border-color: #2563eb; background: #eef4ff; }}
        .history-item span {{ display: block; font-size: 14px; overflow-wrap: anywhere; }}
        .history-item small {{ display: block; color: #7a8288; margin-top: 4px; font-size: 11px; }}
        .result-head {{
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 10px;
          margin-bottom: 18px;
        }}
        .result-head h1 {{ flex-basis: 100%; font-size: 24px; overflow-wrap: anywhere; }}
        .primary-action {{
          flex-basis: 100%;
        }}
        .primary-action button {{
          width: min(360px, 100%);
          background: #111827;
        }}
        .primary-action button:hover {{
          background: #1f2937;
        }}
        .advanced-actions {{
          flex-basis: 100%;
          border: 1px solid #deded8;
          border-radius: 8px;
          background: #fbfbfa;
          padding: 10px 12px;
        }}
        .advanced-actions summary {{
          cursor: pointer;
          color: #4b5563;
          font-size: 13px;
        }}
        .advanced-action-grid {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          margin-top: 12px;
        }}
        .advanced-action-grid button {{
          background: #2563eb;
        }}
        .badges, .links {{ display: flex; flex-wrap: wrap; gap: 8px; }}
        .section-nav {{
          position: sticky;
          top: 0;
          z-index: 5;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          align-items: center;
          margin: 0 0 18px;
          padding: 10px;
          background: rgba(247, 247, 245, 0.94);
          border: 1px solid #deded8;
          border-radius: 8px;
          backdrop-filter: blur(8px);
        }}
        .section-nav a {{
          color: #1e2329;
          text-decoration: none;
          font-size: 13px;
          border: 1px solid #d5dbe7;
          background: #ffffff;
          border-radius: 8px;
          padding: 7px 10px;
        }}
        .section-nav a:hover {{
          color: #2563eb;
          border-color: #9db7ef;
          background: #eef4ff;
        }}
        .badge {{
          border-radius: 999px;
          padding: 5px 9px;
          font-size: 12px;
          border: 1px solid #d5dbe7;
          background: #fff;
        }}
        .badge.ok {{ border-color: #8dd0a8; background: #e9f7ef; }}
        .badge.idle {{ border-color: #d5dbe7; color: #687076; }}
        .badge.running {{ border-color: #8bb7ff; background: #eef4ff; color: #1d4ed8; }}
        .links a {{
          color: #2563eb;
          background: #ffffff;
          border: 1px solid #d5dbe7;
          border-radius: 8px;
          padding: 7px 10px;
          text-decoration: none;
          font-size: 13px;
        }}
        .panel {{
          background: white;
          border: 1px solid #deded8;
          border-radius: 8px;
          padding: 22px;
          margin-bottom: 18px;
          scroll-margin-top: 74px;
        }}
        .evaluation-dashboard {{
          border: 1px solid #dce4ee;
          background: #fbfdff;
          border-radius: 8px;
          padding: 18px;
          margin: 0 0 22px;
        }}
        .combined-dashboard {{
          border-color: #b6c8ee;
          background: #f8fbff;
        }}
        .suite-panel p {{
          color: #4b5563;
          line-height: 1.55;
          margin: 0 0 14px;
        }}
        .suite-grid {{
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
        }}
        .suite-card {{
          border: 1px solid #e1e7ef;
          border-radius: 8px;
          background: #ffffff;
          padding: 12px;
        }}
        .suite-card span {{
          display: block;
          color: #687076;
          font-size: 12px;
          margin-bottom: 8px;
        }}
        .suite-card strong {{
          font-size: 18px;
        }}
        .suite-card.done {{
          border-color: #8dd0a8;
          background: #f2fbf5;
        }}
        .suite-card.running {{
          border-color: #9db7ef;
          background: #eef4ff;
        }}
        .dashboard-head {{
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 18px;
          align-items: center;
          margin-bottom: 16px;
        }}
        .eyebrow {{
          display: inline-block;
          color: #687076;
          font-size: 12px;
          text-transform: uppercase;
          margin-bottom: 5px;
        }}
        .dashboard-head h3 {{
          font-size: 22px;
          margin-bottom: 8px;
        }}
        .dashboard-head p {{
          color: #4b5563;
          line-height: 1.55;
          margin: 0;
        }}
        .overall-score {{
          display: grid;
          justify-items: center;
          gap: 6px;
        }}
        .score-ring {{
          width: 104px;
          height: 104px;
          border-radius: 50%;
          display: grid;
          place-items: center;
          background:
            radial-gradient(circle at center, #ffffff 0 57%, transparent 58%),
            conic-gradient(#2563eb var(--score), #e5e7eb 0);
          border: 1px solid #d5dbe7;
        }}
        .score-ring span {{
          font-size: 21px;
          font-weight: 750;
        }}
        .overall-score small {{
          color: #687076;
          font-size: 12px;
        }}
        .metric-grid {{
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
          margin: 16px 0;
        }}
        .metric-card {{
          border: 1px solid #e1e7ef;
          border-radius: 8px;
          background: #ffffff;
          padding: 12px;
          min-height: 120px;
        }}
        .metric-card.compact {{
          min-height: 96px;
        }}
        .metric-card span {{
          display: block;
          color: #687076;
          font-size: 12px;
          margin-bottom: 8px;
        }}
        .metric-card strong {{
          display: block;
          font-size: 24px;
          margin-bottom: 8px;
        }}
        .metric-card p {{
          color: #4b5563;
          font-size: 12px;
          line-height: 1.45;
          margin: 0;
          display: -webkit-box;
          -webkit-line-clamp: 3;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }}
        .chart-card {{
          border: 1px solid #e1e7ef;
          border-radius: 8px;
          background: #ffffff;
          padding: 14px;
        }}
        .chart-card h3 {{
          font-size: 15px;
          margin-bottom: 12px;
        }}
        .score-row {{
          margin-bottom: 14px;
        }}
        .score-row:last-child {{
          margin-bottom: 0;
        }}
        .score-row-head {{
          display: flex;
          justify-content: space-between;
          gap: 10px;
          font-size: 13px;
          margin-bottom: 6px;
        }}
        .score-row-head span {{
          color: #1e2329;
          font-weight: 600;
        }}
        .score-row-head strong {{
          color: #2563eb;
        }}
        .score-bar {{
          height: 10px;
          border-radius: 999px;
          background: #e5e7eb;
          overflow: hidden;
        }}
        .score-bar-fill {{
          height: 100%;
          border-radius: 999px;
          background: linear-gradient(90deg, #60a5fa, #2563eb);
        }}
        .score-row p {{
          color: #687076;
          font-size: 12px;
          line-height: 1.45;
          margin: 6px 0 0;
        }}
        .metric-note {{
          color: #687076;
          font-size: 12px;
          margin: 12px 0 0;
        }}
        .insight-grid {{
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 10px;
          margin-top: 14px;
        }}
        .insight-grid > div {{
          border: 1px solid #e1e7ef;
          border-radius: 8px;
          background: #ffffff;
          padding: 12px;
        }}
        .insight-grid h3 {{
          font-size: 14px;
          margin-bottom: 10px;
        }}
        .chips {{
          display: flex;
          flex-wrap: wrap;
          gap: 7px;
        }}
        .chip {{
          border-radius: 999px;
          border: 1px solid #d5dbe7;
          background: #f8fafc;
          padding: 6px 9px;
          font-size: 12px;
          color: #374151;
        }}
        .chip.muted {{
          color: #687076;
        }}
        .muted-panel {{ color: #687076; }}
        .running-panel {{
          border-color: #9db7ef;
          background: #f4f8ff;
        }}
        .error-panel {{
          border-color: #ef9a9a;
          background: #fff6f6;
        }}
        .panel > h2 {{ font-size: 18px; margin-bottom: 14px; }}
        .markdown h1 {{ font-size: 22px; margin: 0 0 14px; }}
        .markdown h2 {{ font-size: 16px; margin: 18px 0 8px; }}
        .markdown h3 {{ font-size: 14px; margin: 14px 0 7px; }}
        .markdown p {{ margin: 7px 0; line-height: 1.65; }}
        .bullet {{ padding-left: 10px; }}
        .spacer {{ height: 8px; }}
        pre {{
          background: #111827;
          color: #f8fafc;
          border-radius: 8px;
          padding: 14px;
          overflow: auto;
          line-height: 1.5;
        }}
        code {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: 13px; }}
        details {{ margin-top: 16px; }}
        summary {{ cursor: pointer; color: #2563eb; }}
        .empty {{
          background: #fff;
          border: 1px dashed #c8c8c1;
          border-radius: 8px;
          padding: 40px;
          color: #687076;
        }}
        .run-modal-backdrop {{
          position: fixed;
          inset: 0;
          z-index: 100;
          display: none;
          align-items: center;
          justify-content: center;
          padding: 24px;
          background: rgba(17, 24, 39, 0.52);
          backdrop-filter: blur(3px);
        }}
        .run-modal-backdrop.visible {{
          display: flex;
        }}
        .run-modal {{
          width: min(440px, 100%);
          border: 1px solid #d5dbe7;
          border-radius: 8px;
          background: #ffffff;
          padding: 24px;
          box-shadow: 0 22px 70px rgba(17, 24, 39, 0.28);
        }}
        .run-modal-head {{
          display: flex;
          align-items: center;
          gap: 14px;
          margin-bottom: 12px;
        }}
        .run-modal h2 {{
          font-size: 20px;
        }}
        .run-modal p {{
          color: #4b5563;
          line-height: 1.55;
          margin: 0 0 14px;
        }}
        .run-modal small {{
          display: block;
          color: #687076;
          line-height: 1.45;
        }}
        .spinner {{
          width: 30px;
          height: 30px;
          flex: 0 0 30px;
          border-radius: 50%;
          border: 3px solid #dbeafe;
          border-top-color: #2563eb;
          animation: spin 0.8s linear infinite;
        }}
        @keyframes spin {{
          to {{ transform: rotate(360deg); }}
        }}
        @media (max-width: 860px) {{
          .app {{ grid-template-columns: 1fr; }}
          aside {{ position: relative; height: auto; }}
          main {{ padding: 18px; }}
          .dashboard-head, .metric-grid, .insight-grid, .suite-grid {{ grid-template-columns: 1fr; }}
          .overall-score {{ justify-items: start; }}
        }}
      </style>
    </head>
    <body>
      <div class="app">
        <aside>
          <h1>AI Persona Evaluation Lab</h1>
          <p>Upload an interview PDF, generate persona artifacts, then run the fixed Block 1-6 AI interview.</p>
          {warning}
          {error_html}
          {notice_html}
          <form class="upload-form" method="post" action="/upload" enctype="multipart/form-data" data-loading-title="Generating Persona" data-loading-message="Extracting the PDF and generating the structured schema, persona card, and simulation prompt.">
            <input type="file" name="pdf" accept="application/pdf,.pdf" required>
            <button type="submit">Generate Persona</button>
            <div class="hint">Generation waits for the API response. It can take a minute.</div>
          </form>
          <div class="history-title">History</div>
          <nav class="history">{''.join(history_items) or '<p>No history yet.</p>'}</nav>
        </aside>
        <main>{content}</main>
      </div>
      <div
        class="run-modal-backdrop"
        id="run-modal"
        role="status"
        aria-live="polite"
        aria-hidden="true"
        data-initial-running="{str(initial_running).lower()}"
        data-initial-title="{html.escape(initial_loading_title)}"
        data-initial-message="{html.escape(initial_loading_message)}"
      >
        <div class="run-modal" aria-label="Task is running">
          <div class="run-modal-head">
            <div class="spinner" aria-hidden="true"></div>
            <h2 id="run-modal-title">Running</h2>
          </div>
          <p id="run-modal-message">This may take a few minutes. Please keep this page open.</p>
          <small>The page will update when the current step finishes.</small>
        </div>
      </div>
      <script>
        const runModal = document.getElementById("run-modal");
        const runModalTitle = document.getElementById("run-modal-title");
        const runModalMessage = document.getElementById("run-modal-message");

        function showRunModal(title, message) {{
          if (!runModal) return;
          runModalTitle.textContent = title || "Running";
          runModalMessage.textContent = message || "This may take a few minutes. Please keep this page open.";
          runModal.classList.add("visible");
          runModal.setAttribute("aria-hidden", "false");
        }}

        document.querySelectorAll("form[data-loading-title]").forEach((form) => {{
          form.addEventListener("submit", () => {{
            const submitButton = form.querySelector("button[type='submit']");
            if (submitButton) {{
              submitButton.disabled = true;
              submitButton.textContent = form.dataset.loadingTitle || "Running";
            }}
            showRunModal(form.dataset.loadingTitle, form.dataset.loadingMessage);
          }});
        }});

        if (runModal && runModal.dataset.initialRunning === "true") {{
          showRunModal(runModal.dataset.initialTitle, runModal.dataset.initialMessage);
        }}
      </script>
    </body>
    </html>"""
    return page.encode("utf-8")


class PersonaHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            query = parse_qs(parsed.query)
            selected = query.get("case", [None])[0]
            notice = query.get("notice", [None])[0]
            self.respond_html(render_page(selected=selected, notice=notice))
            return
        if parsed.path.startswith("/download/"):
            self.handle_download(parsed.path)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/upload":
                selected = self.handle_upload()
                self.redirect(selected, notice="Persona generated.")
                return
            if parsed.path == "/interview":
                selected = self.handle_interview()
                self.redirect(selected, notice="AI interview completed.")
                return
            if parsed.path == "/evaluate":
                selected = self.handle_evaluate()
                self.redirect(selected, notice="Evaluation completed.")
                return
            if parsed.path == "/benchmark":
                selected = self.handle_benchmark()
                self.redirect(selected, notice="Task benchmark completed.")
                return
            if parsed.path == "/stability":
                selected = self.handle_stability()
                self.redirect(selected, notice="Stability test completed.")
                return
            if parsed.path == "/full-evaluation":
                selected = self.handle_full_evaluation()
                self.redirect(selected, notice="Full evaluation started.")
                return
        except Exception as exc:
            self.respond_html(render_page(error=str(exc)), status=500)
            return
        self.send_error(404)

    def redirect(self, selected: str, notice: str | None = None) -> None:
        query = f"?case={quote(selected)}"
        if notice:
            query += f"&notice={quote(notice)}"
        self.send_response(303)
        self.send_header("Location", "/" + query)
        self.end_headers()

    def handle_upload(self) -> str:
        ensure_api_key()
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        file_item = form["pdf"] if "pdf" in form else None
        if file_item is None or not file_item.filename:
            raise RuntimeError("No PDF file was uploaded.")
        if not file_item.filename.lower().endswith(".pdf"):
            raise RuntimeError("Please upload a PDF file.")

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = Path(file_item.filename).name
        result_dir = unique_dir(RESULTS_DIR / slugify(safe_name))
        upload_path = UPLOADS_DIR / f"{result_dir.name}.pdf"

        with upload_path.open("wb") as target:
            shutil.copyfileobj(file_item.file, target)

        generate_persona_package(upload_path, result_dir, current_model())
        return result_dir.name

    def handle_interview(self) -> str:
        ensure_api_key()
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8")
        case_name = parse_qs(body).get("case", [None])[0]
        if not case_name:
            raise RuntimeError("Missing case name.")
        case_dir = safe_case_dir(case_name)
        if not has_core_result(case_dir):
            raise RuntimeError("This case does not have persona files yet.")
        run_ai_interview(case_dir, current_model())
        return case_dir.name

    def handle_evaluate(self) -> str:
        ensure_api_key()
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8")
        case_name = parse_qs(body).get("case", [None])[0]
        if not case_name:
            raise RuntimeError("Missing case name.")
        case_dir = safe_case_dir(case_name)
        if not has_core_result(case_dir):
            raise RuntimeError("This case does not have persona files yet.")
        if not has_interview_result(case_dir):
            raise RuntimeError("Run AI Interview before evaluation.")
        run_evaluation(case_dir, current_model())
        if has_benchmark_result(case_dir) and has_stability_result(case_dir):
            compute_combined(case_dir)
        return case_dir.name

    def handle_benchmark(self) -> str:
        ensure_api_key()
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8")
        case_name = parse_qs(body).get("case", [None])[0]
        if not case_name:
            raise RuntimeError("Missing case name.")
        case_dir = safe_case_dir(case_name)
        if not has_core_result(case_dir):
            raise RuntimeError("This case does not have persona files yet.")
        run_task_benchmark(case_dir, current_model())
        if has_evaluation_result(case_dir) and has_stability_result(case_dir):
            compute_combined(case_dir)
        return case_dir.name

    def handle_stability(self) -> str:
        ensure_api_key()
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8")
        case_name = parse_qs(body).get("case", [None])[0]
        if not case_name:
            raise RuntimeError("Missing case name.")
        case_dir = safe_case_dir(case_name)
        if not has_core_result(case_dir):
            raise RuntimeError("This case does not have persona files yet.")
        run_stability_test(case_dir, current_model())
        if has_evaluation_result(case_dir) and has_benchmark_result(case_dir):
            compute_combined(case_dir)
        return case_dir.name

    def handle_full_evaluation(self) -> str:
        ensure_api_key()
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8")
        case_name = parse_qs(body).get("case", [None])[0]
        if not case_name:
            raise RuntimeError("Missing case name.")
        case_dir = safe_case_dir(case_name)
        if not has_core_result(case_dir):
            raise RuntimeError("This case does not have persona files yet.")
        start_full_evaluation_job(case_dir, current_model())
        return case_dir.name

    def handle_download(self, path: str) -> None:
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 3:
            self.send_error(404)
            return
        _, case_name, file_name = parts
        if file_name not in DOWNLOADABLE_FILES:
            self.send_error(404)
            return
        case_dir = safe_case_dir(case_name)
        file_path = case_dir / file_name
        if not file_path.exists():
            self.send_error(404)
            return

        content_type = "application/json; charset=utf-8" if file_name.endswith(".json") else "text/markdown; charset=utf-8"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_html(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {format % args}")


def start_full_evaluation_job(case_dir: Path, model: str) -> None:
    case_key = case_dir.name
    with JOB_LOCK:
        if case_key in ACTIVE_JOBS or is_job_running(case_dir):
            return
        ACTIVE_JOBS.add(case_key)

    initial_status = {
        "status": "running",
        "current_step": "starting",
        "steps": {
            "ai_interview": "pending" if not has_interview_result(case_dir) else "done",
            "qualitative_judge": "pending" if not has_evaluation_result(case_dir) else "done",
            "task_benchmark": "pending" if not has_benchmark_result(case_dir) else "done",
            "stability_test": "pending" if not has_stability_result(case_dir) else "done",
            "overall": "pending",
        },
    }
    write_job_status(case_dir, initial_status)

    thread = threading.Thread(
        target=run_full_evaluation_job,
        args=(case_dir, model, case_key),
        daemon=True,
    )
    thread.start()


def update_step(case_dir: Path, step: str, value: str) -> None:
    status = read_job_status(case_dir) or {"status": "running", "steps": {}}
    status["status"] = "running"
    status["current_step"] = step
    status.setdefault("steps", {})[step] = value
    write_job_status(case_dir, status)


def run_full_evaluation_job(case_dir: Path, model: str, case_key: str) -> None:
    try:
        if not has_interview_result(case_dir):
            update_step(case_dir, "ai_interview", "running")
            run_ai_interview(case_dir, model)
            update_step(case_dir, "ai_interview", "done")

        if not has_evaluation_result(case_dir):
            update_step(case_dir, "qualitative_judge", "running")
            run_evaluation(case_dir, model)
            update_step(case_dir, "qualitative_judge", "done")

        if not has_benchmark_result(case_dir):
            update_step(case_dir, "task_benchmark", "running")
            run_task_benchmark(case_dir, model)
            update_step(case_dir, "task_benchmark", "done")

        if not has_stability_result(case_dir):
            update_step(case_dir, "stability_test", "running")
            run_stability_test(case_dir, model)
            update_step(case_dir, "stability_test", "done")

        update_step(case_dir, "overall", "running")
        compute_combined(case_dir)
        status = read_job_status(case_dir)
        status["status"] = "completed"
        status["current_step"] = "completed"
        status.setdefault("steps", {})["overall"] = "done"
        write_job_status(case_dir, status)
    except Exception as exc:
        status = read_job_status(case_dir) or {}
        status["status"] = "failed"
        status["error"] = str(exc)
        write_job_status(case_dir, status)
    finally:
        with JOB_LOCK:
            ACTIVE_JOBS.discard(case_key)


def current_model() -> str:
    return os.getenv("PPIO_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek/deepseek-v3-turbo"


def ensure_api_key() -> None:
    if not os.getenv("PPIO_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set PPIO_API_KEY or OPENAI_API_KEY before generating results.")


def safe_case_dir(case_name: str) -> Path:
    case_dir = (RESULTS_DIR / case_name).resolve()
    try:
        case_dir.relative_to(RESULTS_DIR.resolve())
    except ValueError as exc:
        raise RuntimeError("Invalid case path.") from exc
    if not case_dir.exists() or not case_dir.is_dir():
        raise RuntimeError("Case not found.")
    return case_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local web UI for AI persona generation and interview.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), PersonaHandler)
    print(f"Open http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

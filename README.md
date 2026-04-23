# Atypica Evaluation

A local web app for generating AI persona packages from interview PDFs and evaluating how well the generated persona preserves decision-making behavior.

The workflow supports:

- Uploading an interview PDF
- Generating a persona schema, persona card, and simulation prompt
- Running an AI interview against the generated persona
- Evaluating persona fidelity against source interview material
- Running task benchmarks and stability checks
- Viewing and downloading generated reports locally

## Repository Contents

- `web_app.py` - local web interface
- `persona_from_pdf.py` - extract interview text and generate persona artifacts
- `ai_interview.py` - generate an AI interview transcript and summary
- `evaluation.py` - evaluate generated persona outputs against source material
- `task_benchmark.py` - compare human/source answers with AI persona answers
- `stability.py` - run repeated benchmark checks
- `combined_evaluation.py` - combine evaluation outputs into a summary report
- `prompts/` - prompt templates used by the evaluation pipeline
- `benchmark_tasks.json` - default benchmark task set

Interview PDFs, uploaded files, and generated results are intentionally excluded from Git.

## Requirements

- Python 3.10+
- `pypdf`
- Either a PPIO-compatible API key or an OpenAI API key

Install the Python dependency:

```powershell
pip install pypdf
```

## Configuration

Set one of the following API keys before running the app.

For PPIO:

```powershell
$env:PPIO_API_KEY="your_api_key"
```

Optional PPIO settings:

```powershell
$env:PPIO_BASE_URL="https://api.ppio.com/openai"
$env:PPIO_MODEL="deepseek/deepseek-v3-turbo"
```

For OpenAI:

```powershell
$env:OPENAI_API_KEY="your_api_key"
$env:OPENAI_MODEL="gpt-4.1"
```

If no model variable is set, the Python pipeline defaults to `deepseek/deepseek-v3-turbo`.

## Run the Web App

Start the local server:

```powershell
python web_app.py
```

Then open:

```text
http://127.0.0.1:8765
```

You can also choose a custom port:

```powershell
python web_app.py --port 9000
```

## Command-Line Usage

The individual pipeline steps can also be run from the command line.

Generate persona artifacts from a PDF:

```powershell
python persona_from_pdf.py path\to\interview.pdf --outdir results
```

Run the AI interview:

```powershell
python ai_interview.py results\case_folder
```

Run evaluation:

```powershell
python evaluation.py results\case_folder
```

Run task benchmark:

```powershell
python task_benchmark.py results\case_folder
```

Run stability checks:

```powershell
python stability.py results\case_folder --runs 3
```

Combine reports:

```powershell
python combined_evaluation.py results\case_folder
```

## Data Privacy

This repository ignores:

- `*.pdf`
- `uploads/`
- `results/`
- `.env`

That keeps interview source files, uploaded PDFs, generated transcripts, and evaluation outputs out of GitHub by default.


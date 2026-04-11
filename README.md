# UK Charity Document Extraction — Multi-Model Benchmark

Extract structured fields from UK charity financial PDFs using LLMs via [OpenRouter](https://openrouter.ai/), the [Doubleword Batch API](https://docs.doubleword.ai/batches/getting-started-with-batched-api), or [V7 Go](https://docs.go.v7labs.com/) (agent/entity API), then score and rank the results across every extracted run in `data/` (dozens of models across OpenRouter, Doubleword, and optional V7). V7 is an optional third backend for product-style runs (e.g. Doc Risk Auditor).

**Jump to:** [Key Findings](#key-findings) | [Setup](#setup) | [Workflow](#end-to-end-workflow) | [Results](#results) | [Repo Reference](#whats-in-this-repo) | [Dataset](#dataset)

> **Who is this for?**
>
> - **Playgroup attendees** — start with [QUICKSTART.md](QUICKSTART.md), then follow the [Workflow](#end-to-end-workflow) section below.
> - **Curious explorers** — read the [Key Findings](#key-findings) and open the [interactive playground](which-models-extracted-playground.html) to browse results without running any code.
> - **Contributors / extenders** — see [Repo Reference](#whats-in-this-repo) for the full file map and how pieces connect.
> - **Doubleword team** — see [Key Findings](#key-findings) for benchmark results, the [Doubleword Batch API](#doubleword-batch-api-configmodelsdoublewordpy) tier table, and note the [timing and cost](#doubleword-batch-api--timing-and-cost) details.

---

## Key Findings

> **Snapshot below:** 2026-03-31 — 52 models (40 OpenRouter, 12 Doubleword), before large V7 Go sweeps. The repo’s `data/` and `extraction_stats.csv` may list many more runs (including V7); run `python score.py` and open the [playground](which-models-extracted-playground.html) for current counts and rankings. Doubleword model pricing is auto-synced from their docs site at each `extractor.py` run.

**Provider summary** (active = models with F1 > 0):

| Provider | Models | Active | Failed | Avg F1 | Best F1 | Best Model | Avg Fields | Avg Time(s) | Avg Cost($) |
|----------|--------|--------|--------|--------|---------|------------|------------|-------------|-------------|
| Doubleword | 12 | 10 | 2 | 0.775 | 0.927 | dw-qwen3.5-9b | 60.0/85 (71%) | 5,336.2 | 0.0216 |
| OpenRouter | 40 | 27 | 13 | 0.753 | 0.946 | gemini-3-pro | 56.0/85 (66%) | 2,029.7 | 0.0922 |

Doubleword has a higher average F1 (0.872 vs 0.753) and a much lower failure rate (11% vs 32%), though OpenRouter's best model (`gemini-3-pro`) holds the overall top score. OpenRouter's average is dragged down by free-tier models that universally failed on this task. Doubleword's average cost per active model ($0.03) is ~3.6× cheaper than OpenRouter's ($0.09).

**Top 5 models by F1 score:**

| Rank | Model | Provider | F1 | Precision | Recall | Fields Found |
|------|-------|----------|----|-----------|--------|-------------|
| 1 | gemini-3-pro | OpenRouter | 0.946 | 0.975 | 0.918 | 78/85 (92%) |
| 2 | qwen3-235b | OpenRouter | 0.937 | 0.975 | 0.902 | 77/85 (90%) |
| 3 | dw-qwen3.5-9b | Doubleword | 0.927 | 0.974 | 0.885 | 75/85 (88%) |
| 4 | gemini-3-flash | OpenRouter | 0.926 | 0.962 | 0.893 | 76/85 (89%) |
| 5 | gemini-2.5-flash | OpenRouter | 0.922 | 0.962 | 0.885 | 75/85 (88%) |

**Takeaways:**

- **Doubleword's cheapest model topped the value chart.** `dw-qwen3.5-9b` (ultra_cheap tier, $0.04/M input) ranked 3rd overall at 0.927 F1, outperforming premium models like `mistral-large` and `claude-3.5-haiku`.
- **10 of 12 Doubleword models produced usable results.** The 8 standard LLMs score F1 0.844–0.927. Three new OCR-specialist models were benchmarked: `dw-olmocr-2-7b-1025-fp8` (F1=0.607, but 3/11 docs errored and hallucinated cross-document data), `dw-lightonocr-2-1b-bbox-soup` (F1=0.029, nearly all docs failed), and `dw-deepseek-ocr-2` (F1=0.000, complete failure). Two models returned empty results: `dw-qwen3.5-397b` and `dw-deepseek-ocr-2`.
- **Free-tier models universally failed** on this task — all 14 zero-score models are either free-tier or had context/format issues. This includes `llama-3.3-70b-free`, `gemma-3-27b-free`, `gemma-3n-free`, and others.
- **Precision is consistently high across scoring models** (0.96–0.97), meaning when models extract a field, they're usually correct. The differentiator is recall — whether they find all fields.
- **The hardest fields** are `income_annually_in_british_pounds` and `spending_annually_in_british_pounds` — even top models miss these on some documents.

For the full interactive breakdown (field heatmaps, per-document analysis, error patterns, provider comparisons), open the **[Model Extraction Playground](which-models-extracted-playground.html)** locally in a browser. It has 8 tabs: Rankings, Field Heatmap, Document Analysis, Error Breakdown, Deep Dive, Recommendations, Provider Analysis, and Project Evolution.

### Doubleword Batch API — Timing and Cost

Doubleword batch stats (elapsed time, tokens, cost) were backfilled by querying batch metadata via `batches.list()`. The pipeline now uses API-reported `created_at`/`completed_at` timestamps for accurate elapsed time and stores `batch_id` for traceability. Per-request cost is computed from token counts and config pricing. The only model without stats is `dw-qwen3.5-397b`, which returned empty results.

### Auto-Sync Pricing

Model pricing is automatically synced from Doubleword's [agent-friendly docs endpoint](https://docs.doubleword.ai/inference-api/model-pricing.md) (`llms.txt` enabled) at the start of each `extractor.py` run via `sync_doubleword_models.py`. This means `config_models_doubleword.py` is auto-generated — no manual edits needed. If nothing has changed, the sync is skipped silently.

---

## Results

Results are generated by `score.py` and stored in `data/`. To reproduce or update:

```bash
# Full leaderboard (all extracted models)
python score.py

# Verbose diff for one model
python score.py data/playgroup_dev_extracted__openrouter__gemini-2.0-flash.tsv
```

The key result files:

| File | What it shows |
|---|---|
| `data/extraction_stats.csv` | One row per model run: provider, tier, row counts, per-field hit rates, time, cost |
| [which-models-extracted-playground.html](which-models-extracted-playground.html) | Interactive playground — open in browser for charts, heatmaps, and recommendations |

The leaderboard printed by `score.py` is ranked by F1 and includes precision, recall, field counts, time, and cost. For readability, the printed **Model** column (and the playground’s tables and chart labels) **shortens** ids when every model name that contains `__` shares the same `agent__` prefix — for example `v7-go-agent-v2__gpt4-1` is shown as `gpt4-1`. Names without `__`, or mixed `__` prefixes, stay full-length so rows stay distinct. **Canonical ids** (for filenames, `extraction_stats.csv`, and lookups) are always the full string.

```
Provider     Model                     Mod    Docs     F1   Prec  Recall          Fields    Time(s)    Cost($)
--------------------------------------------------------------------------------------------------------------
openrouter   gemini-3-pro              MM       11  0.946  0.975   0.918   78.1/85 (92%)    ~2273.3    ~0.3780
openrouter   qwen3-235b                text     11  0.937  0.975   0.902   76.7/85 (90%)    ~2273.3    ~0.0258
doubleword   dw-qwen3.5-9b             text     11  0.927  0.974   0.885   75.2/85 (88%)      353.0     0.0354
...
```

> **To update results:** run `python extractor.py` to extract with any new/missing models, then `python score.py` to regenerate the leaderboard. Regenerate the playground HTML with `python playground.py` (or `uv run python playground.py`).

---

## Setup

See [`QUICKSTART.md`](QUICKSTART.md) for the full pre-event setup checklist (Python version, venv, pip install, `.env` with API keys).

---

## End-to-End Workflow

### 1. Smoke test

Verify your setup works before running anything else:

```bash
python llm_openrouter.py
```

Expected output — a JSON block with a charity number extracted from canned text:

```json
{"Registered Charity Number": "1132766"}
```

### 2. Try a simple prompt on the dataset

```bash
python extraction_and_prompt_example.py
```

Reads `data/playgroup_dev_in.tsv`, sends each row to `claude-3.5-haiku`, and prints the raw extracted JSON. Good for experimenting with prompts.

### 3. Run extraction across one or more models

Pass one or more model names as arguments, or omit to run all registered models. The backend is **auto-detected from the model registries** in `config_models_*.py`: keys in `DOUBLEWORD_MODELS` use the Doubleword Batch API (async), keys in `V7_MODELS` use the V7 Go entity API (async), and keys in `OPENROUTER_MODELS` use OpenRouter (sync). Runs are idempotent — if the output file already exists for a model, that model is skipped.

```bash
# One OpenRouter model
python extractor.py gemini-2.0-flash

# Several OpenRouter models
python extractor.py gemini-2.0-flash deepseek-v3 llama-3.3-70b-free

# All models from both providers (default)
python extractor.py

# All OpenRouter models only
python extractor.py --all-openrouter

# All V7 Go models only (see config_models_v7.py and llm_v7.py)
python extractor.py --all-v7

# All V7 models using a specific Go Agent v2 export JSON for this run (overrides per-model agent_template_json in config)
python extractor.py --all-v7 --v7-agent-template path/to/your_project_export.json

# Same template override when retrying failed V7 rows
python extractor.py --all-v7 --v7-agent-template ./v7_go_agent_v2_template.json --retry-failed

# One Doubleword model (registry key dw-*)
python extractor.py dw-qwen3-vl-30b

# One V7 model (registry key v7-* — requires agent + env; see README “V7 Go” below)
python extractor.py v7-charity-extract

# Mix backends in one command
python extractor.py gemini-2.0-flash dw-qwen3-14b v7-charity-extract

# All Doubleword models with 24h window (cheapest)
python extractor.py --all-doubleword --completion-window 24h

# Re-submit only rows that failed in the previous run (merges back into existing output files)
python extractor.py --retry-failed

# Retry failed rows for specific Doubleword models only
python extractor.py dw-olmocr-2-7b-1025-fp8 dw-lightonocr-2-1b-bbox-soup --retry-failed

# Retry failed rows for a V7 model (uses data/.v7_failed_rows.json)
python extractor.py v7-charity-extract --retry-failed
```

**`--v7-agent-template PATH`** — Optional. Path to a Go Agent v2 **project export JSON**. For every V7 model in that run, it sets `agent_template_json` to this file, overriding the value in `config_models_v7.py`. Use with `--all-v7`, explicit `v7-*` model names, or `--retry-failed` whenever V7 models are included. Relative paths resolve from the **repository root** (same rule as filenames in config). If the run has no V7 models, the flag is ignored with a warning.

Each run auto-syncs Doubleword model pricing first, then prints a per-provider plan (which models will run, skip, or resume) and executes extraction. Ctrl-C during Doubleword or V7 polling triggers a graceful shutdown — checkpoints are preserved and jobs resume on next run. On completion it prints a combined summary with completed/skipped/interrupted/failed counts. When a Doubleword batch completes with partial failures, the DW error file is automatically downloaded and the per-row rejection reasons (e.g. `context_length_exceeded`) are logged to the console and recorded. Use `--retry-failed` on a subsequent run to re-submit only those rows and merge the results back into the existing output file (Doubleword and V7 each maintain their own failed-row manifests). If a model is unavailable (e.g. `PermissionDenied` on submit), it is automatically recorded in the provider-specific unavailable-models file and skipped on future runs. For V7, skips also log a **resolved settings snapshot** (workspace, agent, file-field source, mode) and **actionable hints** derived from the stored failure reason (e.g. file-upload 404, DNS, parent entity mix-ups).

**Output and state files**

| Pattern | Purpose |
|--------|---------|
| `data/playgroup_dev_extracted__openrouter__<model>.tsv` | OpenRouter extraction output |
| `data/playgroup_dev_extracted__doubleword__<model>.tsv` | Doubleword batch output |
| `data/playgroup_dev_extracted__v7__<model>.tsv` | V7 Go entity-run output |
| `data/extraction_stats.csv` | Cumulative run stats (provider, row counts, fields, time, cost, `batch_id` where applicable) |
| `data/extraction_call_log.csv` | Per-row call log |
| `data/.doubleword_checkpoints.json` | Doubleword batch resume state |
| `data/.doubleword_failed_rows.json` | Failed row indices for `--retry-failed` (Doubleword) |
| `data/.doubleword_unavailable_models.json` | Doubleword models that failed on submit |
| `data/.v7_checkpoints.json` | V7 synthetic batch / entity map for resume |
| `data/.v7_failed_rows.json` | Failed row indices for `--retry-failed` (V7) |
| `data/.v7_unavailable_models.json` | V7 models that failed on submit; delete an entry (or the file) to retry after fixing config |

### V7 Go (optional backend)

V7 runs use `llm_v7.py`: each input row creates an **entity** on your agent with the combined prompt + OCR text in an input field (single-output agents), or follows the **Go Agent v2** flow (empty entity, PDF upload, then polling tool-backed output fields — see below). Configure the agent in [V7 Go](https://go.v7labs.com); API overview: [Create Entities Programmatically](https://docs.go.v7labs.com/reference/create-entities-programmatically).

Set in `.env` (or override per model in `config_models_v7.py`):

| Variable | Purpose |
|----------|---------|
| `V7_GO_API_KEY` or `V7_API_KEY` | API key (`X-API-KEY` header) |
| `V7_GO_WORKSPACE_ID` | Workspace UUID |
| `V7_GO_AGENT_ID` | Agent (project) UUID |
| `V7_GO_INPUT_FIELD_SLUG` | Input property slug (default `document-text`; single-output / non–v2-template agents) |
| `V7_GO_OUTPUT_FIELD_SLUG` | Output property slug to read (default `extracted-json`; single-output agents) |
| `V7_GO_FILE_FIELD_SLUG` | File property **slug or id** for multimodal PDF upload. For **single-output** multimodal agents, default is `document-pdf` if unset. For **Go Agent v2** (`agent_template_json` set), prefer **omitting** this so the File property id from the template export is used — see [File property for Go Agent v2](#file-property-for-go-agent-v2). |
| `V7_GO_PARENT_ENTITY_ID` | For **collection (child)** projects only: parent **entity** UUID from the parent project — **not** the same as `V7_GO_AGENT_ID` (project id). Omit for standalone agents. If env equals the agent id, the client logs a warning and ignores it (avoids broken `POST /entities`). |
| `V7_GO_BASE_URL` | API base (default `https://go.v7labs.com`). Prefer this host; `https://api.go.v7labs.com` often fails DNS — unset a bad `V7_GO_BASE_URL` rather than guessing. |

**Go Agent v2** — Set `agent_template_json` on the model entry (e.g. `v7_go_agent_v2_template.json`) and `multimodal: True`. The runner creates entities with **no** `fields` key when the payload is empty (matches V7’s empty-entity shape); sending `{"fields": {}}` could return HTTP 500 on some API versions. It uploads each PDF to the resolved File property, then polls output tool fields and merges them into one JSON object (property names mapped in `llm_v7._V7_GO_AGENT_V2_PROPERTY_NAME_TO_KEY`).

#### File property for Go Agent v2

Property ids in a template JSON export are **per-project**. If `V7_GO_AGENT_ID` matches the project that produced the export, the File property id embedded in `agent_template_json` is usually correct.

**Precedence** for which File property receives the PDF:

1. Per-model `file_field_slug` in `config_models_v7.py` (if set).
2. `V7_GO_FILE_FIELD_SLUG` — **unless** it is exactly the legacy default `document-pdf` while the template names a **different** File property id (e.g. `property_…`). In that case the client **ignores** the env value and uses the template id (many `.env` files set `document-pdf` for non-v2 models; applying it blindly to v2 caused `start_file_upload` 404).
3. Otherwise the File property id parsed from `agent_template_json`.

If your agent lives in a **different** project than the JSON export, set `file_field_slug` or `V7_GO_FILE_FIELD_SLUG` to the File property **id** copied from the V7 UI for **that** agent. Do not set `V7_GO_FILE_FIELD_SLUG=document-pdf` for v2 unless that slug actually exists on the agent.

#### Unavailable models and retries

Failed submit paths record the model in `data/.v7_unavailable_models.json` with a reason string. Later runs skip that model and log **resolved settings** (no secrets) plus **hints** (file-upload 404, workspace/agent unset, DNS, parent entity vs project id). To retry after fixing configuration, remove that model’s entry from the file or delete the file, then re-run.

Token usage is not returned by this API path in the client; costs in stats may be zero until you add pricing manually in the config.

### 4. Score and rank all models

```bash
# Ranked leaderboard across all extracted files
python score.py

# Verbose diff for one model
python score.py data/playgroup_dev_extracted__openrouter__gemini-2.0-flash.tsv
```

---

## What's in This Repo

### Scripts

| File | Purpose |
|---|---|
| `llm_openrouter.py` | LLM client for OpenRouter (synchronous). Run directly for a smoke test. |
| `llm_doubleword.py` | LLM client for Doubleword Batch API (async, direct batch management with checkpoint/resume). |
| `llm_v7.py` | LLM client for [V7 Go](https://docs.go.v7labs.com/) (async HTTP: create entity per row, poll until output field ready; Go Agent v2: empty entity body, PDF upload, multi-field merge). Resolves file field and parent entity with guardrails; logs diagnostics for unavailable-model skips. Same orchestration hooks as `llm_doubleword.py` (`submit_batch`, `poll_batch`, `download_results`, checkpoints). |
| `extraction_and_prompt_example.py` | Simple single-model extraction loop, good for prompt experiments. |
| `extractor.py` | Unified extraction runner. Auto-detects backend from registries (`DOUBLEWORD_MODELS`, `V7_MODELS`, `OPENROUTER_MODELS`). Auto-syncs Doubleword pricing at startup. Doubleword and V7 use async polling with checkpoint/resume; OpenRouter is sync per row. Graceful Ctrl-C preserves checkpoints. Doubleword: downloads DW error files for pre-processing rejections. Flags: `--completion-window`, `--all-doubleword`, `--all-openrouter`, `--all-v7`, `--v7-agent-template`, `--retry-failed`. |
| `sync_doubleword_models.py` | Auto-syncs Doubleword model pricing from their [docs markdown endpoint](https://docs.doubleword.ai/inference-api/model-pricing.md). Regenerates `config_models_doubleword.py`. Skips save when nothing changed. Called by `extractor.py` at startup; can also run standalone. |
| `score.py` | Scorer with F1/Precision/Recall. No args → ranked leaderboard; pass a filename → verbose field-by-field diff. Leaderboard **Model** column uses the same short display rule as the playground when shared `agent__` prefixes apply (see [Results](#results)). |
| `utils.py` | Shared helpers (`extract_from_triple_backticks`, `sanitize_error_message`). |
| `config_models_openrouter.py` | OpenRouter model registry — 33 models organised by tier. |
| `config_models_doubleword.py` | Doubleword model registry — 12 extraction models (auto-generated by `sync_doubleword_models.py`). |
| `config_models_v7.py` | V7 Go model registry — short names (e.g. `v7-charity-extract`) mapped to display metadata; agent IDs and field slugs usually come from env (see “V7 Go” above). |
| `playground.py` | Generates `which-models-extracted-playground.html` from extraction results. Chart/table **labels** use short model names when safe (shared `agent__` prefix); embedded JSON keys stay full ids. |

### Model Tiers

#### OpenRouter (`config_models_openrouter.py`)

Models are grouped into four tiers by cost (per million input tokens):

| Tier | Cost | Examples |
|---|---|---|
| `free` | $0 | `llama-3.3-70b-free`, `gemma-3-27b-free`, `gemma-3n-free` |
| `ultra_cheap` | < $0.30 | `gemini-2.0-flash`, `deepseek-v3`, `qwen-2.5-vl-7b` |
| `great_value` | $0.30–$1.00 | `claude-3.5-haiku`, `qwen-2.5-vl-72b`, `deepseek-r1` |
| `premium` | > $1.00 | `gemini-3-pro`, `pixtral-large`, `mistral-large` |

#### Doubleword Batch API (`config_models_doubleword.py`)

Prefixed with `dw-`. Auto-generated by `sync_doubleword_models.py` from the [Doubleword pricing page](https://docs.doubleword.ai/inference-api/model-pricing.md). Pricing is for the 1h batch tier (24h is 30-50% cheaper). Embedding models are excluded (not used for extraction).

| Tier | Cost (in+out/M) | Examples |
|---|---|---|
| `ultra_cheap` | ≤ $0.40 combined | `dw-qwen3.5-4b`, `dw-qwen3.5-9b`, `dw-qwen3-14b`, `dw-gpt-oss-20b`, `dw-qwen3.5-35b`, `dw-qwen3-vl-30b`, `dw-deepseek-ocr-2`, `dw-olmocr-2-7b-1025-fp8`, `dw-lightonocr-2-1b-bbox-soup` |
| `premium` | > $0.50 combined | `dw-nemotron-120b`, `dw-qwen3.5-397b`, `dw-qwen3-vl-235b` |

Each model entry includes: model ID, `multimodal` flag, supported modalities, context length, and notes.

#### V7 Go (`config_models_v7.py`)

Registry keys are typically prefixed with `v7-`. Each entry mirrors the shape used by other configs (`model`, `multimodal`, `tier`, `ctx`, pricing keys). Agent connection is via environment variables or optional per-model `workspace_id`, `agent_id`, `input_field_slug`, and `output_field_slug`. See **V7 Go (optional backend)** under the workflow section.

### Frontend (Doc Risk Auditor prototype)

| Path | Purpose |
|------|---------|
| `web/src/components/DocRiskResultsPanel.tsx` | React + TypeScript panel: extracted fields, risk flags, approve / review / reject actions (no UI libraries). |
| `web/src/components/DocRiskResultsPanel.css` | Styles (IBM Plex–oriented dark theme). Wire into a Vite app when you scaffold the full UI. |

### Data (`data/`)

| File | Description |
|---|---|
| `playgroup_dev_in.tsv` | Input: 11 PDFs × 6 columns (filename, keys, 3 OCR text variants, combined text) |
| `playgroup_dev_expected.tsv` | Ground truth field values |
| `pdf_names.txt` | PDF filenames in row order |
| `playgroup_dev_extracted__<provider>__<model>.tsv` | Per-model extraction output (`openrouter`, `doubleword`, or `v7`) |
| `extraction_stats.csv` | Cumulative run stats: provider, model, row counts, per-field hit rates, time, cost, `batch_id` (Doubleword batch id or V7 synthetic id) |
| `extraction_call_log.csv` | Per-row call log: provider, model, row, status, elapsed time, tokens, cost |
| `.doubleword_checkpoints.json` | Doubleword batch checkpoint: maps model → batch_id for resume on cancel/re-run |
| `.doubleword_failed_rows.json` | Failed-row index (Doubleword); consumed by `--retry-failed` |
| `.doubleword_unavailable_models.json` | Doubleword models that failed to submit; skipped on future runs |
| `.v7_checkpoints.json` | V7 checkpoint: maps model → entity ids / synthetic batch id for resume |
| `.v7_failed_rows.json` | Failed-row index (V7); consumed by `--retry-failed` |
| `.v7_unavailable_models.json` | V7 models that failed to submit; skipped on future runs with expanded log hints |
| `*.pdf` | 11 UK charity financial PDFs (≤ 200 pages each) |

### Visualisations

| File | Description |
|---|---|
| [which-models-extracted-playground.html](which-models-extracted-playground.html) | Interactive leaderboard — open in browser for rankings, field heatmap, document analysis, error breakdown, deep dive, recommendations, provider analysis, and project evolution. Regenerate after scoring with `python playground.py`. |

### Utility Scripts (`utility/`)

| File | Description |
|---|---|
| `process_pdf.py` | PDF processing helper |
| `extract_copy_kleister_charity.sh` | Shell script to copy/prepare data from the full Kleister Charity dataset |

---

## Dataset

A small export from the [Kleister Charity dataset](https://github.com/applicaai/kleister-charity) (`dev-0` folder), using PDFs and pre-extracted OCR text (djvu2hocr, tesseract 4.11, tesseract March 2020, combined).

PDFs are drawn from ~3,000 UK charity financial documents, up to 200 pages each. The 11 in this set start smaller and get longer — a useful proxy for scale testing.

**Fields to extract:**

- `charity_number` — registered charity number
- `charity_name` — full charity name
- `report_date` — period end date (YYYY-MM-DD)
- `income_annually_in_british_pounds` — total annual income
- `spending_annually_in_british_pounds` — total annual expenditure
- `address__postcode` — UK postcode
- `address__post_town` — town/city
- `address__street_line` — street address

---

## License

Data is UK open data — see [Kleister Charity license](https://github.com/applicaai/kleister-charity/issues/2).

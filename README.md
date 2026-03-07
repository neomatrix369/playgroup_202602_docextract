# UK Charity Document Extraction — Multi-Model Benchmark

Extract structured fields from UK charity financial PDFs using LLMs via [OpenRouter](https://openrouter.ai/) or the [Doubleword Batch API](https://docs.doubleword.ai/batches/getting-started-with-batched-api), then score and rank the results across 40+ models.

---

## Setup

See [`QUICKSTART.md`](QUICKSTART.md) for the full pre-event setup checklist (Python version check, venv, pip install, `.env` with OpenRouter API key).

---

## Smoke Test

Verify your setup works before running anything else:

```bash
python llm_openrouter.py
```

Expected output — a JSON block with a charity number extracted from canned text:

```json
{"Registered Charity Number": "1132766"}
```

---

## End-to-End Workflow

### 1. Try a simple prompt on the dataset

```bash
python extraction_and_prompt_example.py
```

Reads `data/playgroup_dev_in.tsv`, sends each row to `claude-3.5-haiku`, and prints the raw extracted JSON. Good for experimenting with prompts.

### 2. Run extraction across one or more models

Pass one or more model names as arguments, or omit to run all models. The backend is auto-detected: `dw-*` models use the Doubleword Batch API (async, parallel), all others use OpenRouter (sync, sequential). Runs are idempotent — if the output file already exists for a model, that model is skipped.

```bash
# One OpenRouter model
python extractor.py gemini-2.0-flash

# Several OpenRouter models
python extractor.py gemini-2.0-flash deepseek-v3 llama-3.3-70b-free

# All models from both providers (default)
python extractor.py

# All OpenRouter models only
python extractor.py --all-openrouter

# One Doubleword model (auto-detected by dw- prefix)
python extractor.py dw-qwen3-vl-30b

# Mix both backends in one command
python extractor.py gemini-2.0-flash dw-qwen3-14b

# All Doubleword models with 24h window (cheapest)
python extractor.py --all-doubleword --completion-window 24h
```

Each run prints a per-provider plan (which models will run, skip, or resume) then executes extraction. On completion it prints a combined summary with completed/skipped/failed counts. Output files: `data/playgroup_dev_extracted__<provider>__<model-name>.tsv`, `data/extraction_stats.csv` (provider, row counts, per-field hit rates, time and cost), and `data/extraction_call_log.csv` (per-row details).

### 3. Score and rank all models

Pass a filename to see a verbose field-by-field diff for one model, or omit to score all extracted files and print a ranked leaderboard.

```bash
# Ranked leaderboard across all extracted files
python score.py

# Verbose diff for one model
python score.py data/playgroup_dev_extracted__openrouter__gemini-2.0-flash.tsv
```

The leaderboard is ranked by F1 and includes precision, recall, field counts, time, and cost:

```
Provider     Model                     Mod    Docs     F1   Prec  Recall          Fields    Time(s)    Cost($)
--------------------------------------------------------------------------------------------------------------
openrouter   gemini-3-pro              MM       11  0.906  0.973   0.847     72/85 (85%)     ~629.1    ~0.3780
openrouter   qwen3-235b                text     11  0.892  0.972   0.824     70/85 (82%)     ~629.1    ~0.0258
doubleword   dw-qwen3.5-35b            text     11  0.877  0.971   0.800     68/85 (80%)     ~629.1    ~0.0131
...
```

---

## What's in This Repo

### Scripts

| File | Purpose |
|---|---|
| `llm_openrouter.py` | LLM client for OpenRouter (synchronous). Run directly for a smoke test. |
| `llm_doubleword.py` | LLM client for Doubleword Batch API (async, direct batch management with checkpoint/resume). |
| `extraction_and_prompt_example.py` | Simple single-model extraction loop, good for prompt experiments. |
| `extractor.py` | Unified extraction runner. Auto-detects backend from model prefix (`dw-*` → Doubleword batch, others → OpenRouter). Doubleword models are submitted in parallel and polled with checkpoint/resume. Prints a per-provider run plan at start and a combined summary at end (completed/skipped/failed counts). Supports `--completion-window`, `--all-doubleword`, and `--all-openrouter` flags. |
| `score.py` | Scorer with F1/Precision/Recall. No args → ranked leaderboard; pass a filename → verbose field-by-field diff. |
| `utils.py` | Shared helpers (`extract_from_triple_backticks`, `sanitize_error_message`). |
| `config_models_openrouter.py` | OpenRouter model registry — 40+ models organised by tier. |
| `config_models_doubleword.py` | Doubleword model registry — 8 models with batch pricing from [docs](https://docs.doubleword.ai/batches/model-pricing). |
| `playground.py` | Interactive HTML playground with time/cost estimation and project evolution tabs. |

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

Prefixed with `dw-`. Pricing is for the 1h batch tier (24h is 30-50% cheaper):

| Tier | Cost | Examples |
|---|---|---|
| `ultra_cheap` | < $0.05 | `dw-qwen3.5-9b`, `dw-qwen3-14b`, `dw-gpt-oss-20b` |
| `great_value` | $0.05–$0.15 | `dw-qwen3.5-35b`, `dw-qwen3-vl-30b` |
| `premium` | > $0.15 | `dw-qwen3.5-397b`, `dw-qwen3-vl-235b` |

Each model entry includes: model ID, `multimodal` flag, supported modalities, context length, and notes.

### Data (`data/`)

| File | Description |
|---|---|
| `playgroup_dev_in.tsv` | Input: 11 PDFs × 6 columns (filename, keys, 3 OCR text variants, combined text) |
| `playgroup_dev_expected.tsv` | Ground truth field values |
| `pdf_names.txt` | PDF filenames in row order |
| `playgroup_dev_extracted__<provider>__<model>.tsv` | Per-model extraction output (one file per run) |
| `extraction_stats.csv` | Cumulative run stats: provider, model, row counts, per-field hit rates, time, cost |
| `extraction_call_log.csv` | Per-row call log: provider, model, row, status, elapsed time, tokens, cost |
| `.doubleword_checkpoints.json` | Doubleword batch checkpoint: maps model → batch_id for resume on cancel/re-run |
| `*.pdf` | 11 UK charity financial PDFs (≤ 200 pages each) |

### Visualisations

| File | Description |
|---|---|
| `which-models-extracted-playground.html` | Interactive leaderboard with time/cost estimation and project evolution tabs |
| `architecture_animated.svg` | Animated pipeline architecture diagram |
| `performance_animated.svg` | Animated performance comparison |

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

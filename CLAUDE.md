# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **multi-model LLM benchmark** that extracts structured fields from UK charity financial PDFs. It compares dozens of models across three backends:
- **OpenRouter** (~33 models, sync)
- **Doubleword Batch API** (21 models, async with checkpoints)
- **V7 Go** (32 models, async entity API with checkpoints)

The benchmark scores each model using F1/Precision/Recall and generates an interactive HTML playground for analysis.

## Development Commands

### Setup
```bash
# Python 3.13 required (pinned in .python-version)
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Or use uv (faster):
uv venv
. .venv/bin/activate
uv pip install -r requirements.txt
```

### Smoke test
```bash
python llm_openrouter.py  # Should output JSON with charity_number
```

### Running extractions
```bash
# Single model (backend auto-detected from registry)
python extractor.py gemini-2.0-flash

# Multiple models
python extractor.py gemini-2.0-flash dw-qwen3.5-9b v7-go-agent-v2/claude-sonnet

# All models from all backends (idempotent)
python extractor.py

# Provider-specific runs
python extractor.py --all-openrouter
python extractor.py --all-doubleword
python extractor.py --all-v7

# Retry failed rows from previous run
python extractor.py --retry-failed

# V7: override template JSON for a run
python extractor.py --all-v7 --v7-agent-template path/to/export.json
```

### Scoring and analysis
```bash
# Ranked leaderboard across all models
python score.py

# Verbose field-by-field diff for one model
python score.py data/playgroup_dev_extracted__openrouter__gemini-2.0-flash.tsv
python score.py data/playgroup_dev_extracted__v7__v7-go-agent-v2__claude-sonnet.tsv

# Regenerate interactive playground HTML
python playground.py
```

### Syncing configs
```bash
# Manual Doubleword sync (auto-sync DISABLED via SKIP_DOUBLEWORD_SYNC=1)
# config_models_doubleword.py contains manual corrections for API model identifiers
# Doubleword's docs are out of sync with their API — model names corrected manually
python sync_doubleword_models.py  # Only run if you want to reset to docs version

# Refresh V7 Go Agent v2 template from API
python sync_v7_go_agent_template.py
```

## Architecture

### Backend Auto-Detection

`extractor.py` merges three model registries and auto-detects the backend:
- `dw-*` keys → Doubleword Batch API (`llm_doubleword.py`)
- `v7-*` keys → V7 Go entity API (`llm_v7.py`)
- Everything else → OpenRouter (`llm_openrouter.py`)

All backends share a common interface in `extractor.py` but have different execution patterns:
- **OpenRouter**: Synchronous per-row requests
- **Doubleword**: Async batch submission → poll completion → download results
- **V7 Go**: Async entity creation per row (or Go Agent v2 flow: empty entity + PDF upload) → poll output fields

### Model Registries

| File | Backend | Auto-sync? | Model Count |
|------|---------|------------|-------------|
| `config_models_openrouter.py` | OpenRouter | ❌ Manual | ~33 |
| `config_models_doubleword.py` | Doubleword | ❌ **Manual override** | 21 |
| `config_models_v7.py` | V7 Go | ❌ Manual | 32 |

**Doubleword auto-sync is DISABLED** (`SKIP_DOUBLEWORD_SYNC=1`) because:
- Doubleword's docs endpoint lists model identifiers that don't match their batch API
- `config_models_doubleword.py` contains **manual corrections** to use actual working identifiers
- Example: docs show `DeepSeek/DeepSeek-V4-Pro` but API expects `deepseek-ai/DeepSeek-V4-Pro`
- To re-enable auto-sync: remove `SKIP_DOUBLEWORD_SYNC` from `.env` (will overwrite manual edits)

**V7 Go pricing** (`price_in`/`price_out`) is manual — costs often show as `$0` in stats until set.

### Model Name Normalization

V7 registry keys can contain `/` (e.g., `v7-go-agent-v2/claude-sonnet`), but TSV filenames use `__`:
- Registry key: `v7-go-agent-v2/claude-sonnet`
- Output file: `data/playgroup_dev_extracted__v7__v7-go-agent-v2__claude-sonnet.tsv`

The scorer and playground **shorten** display names when all models share the same `agent__` prefix (e.g., `gpt4-1` instead of `v7-go-agent-v2__gpt4-1`), but filenames and `extraction_stats.csv` always use full ids.

### Data Flow

```
data/playgroup_dev_in.tsv  (input: 11 charity PDFs with ground truth)
    ↓
extractor.py  (auto-detects backend, runs extraction)
    ↓
data/playgroup_dev_extracted__<provider>__<model>.tsv  (one per model)
data/extraction_stats.csv  (cumulative: provider, tier, F1, time, cost, batch_id)
data/extraction_call_log.csv  (per-row call log)
    ↓
score.py  (computes F1/Precision/Recall)
    ↓
playground.py  (generates interactive HTML)
    ↓
which-models-extracted-playground.html  (8 tabs: Rankings, Heatmap, Errors, etc.)
```

### Checkpoint and Resume

**Doubleword** and **V7 Go** use async polling with graceful Ctrl-C handling. State files under `data/`:

| File | Purpose |
|------|---------|
| `.doubleword_checkpoints.json` | Batch resume state |
| `.doubleword_failed_rows.json` | Failed row indices for `--retry-failed` |
| `.doubleword_unavailable_models.json` | Models that failed on submit |
| `.v7_checkpoints.json` | V7 entity/run map for resume |
| `.v7_failed_rows.json` | V7 failed row indices for `--retry-failed` |
| `.v7_unavailable_models.json` | V7 submit failures (delete entry to retry) |

When a Doubleword batch has partial failures, `extractor.py` downloads the error file and logs rejection reasons (e.g., `context_length_exceeded`). Use `--retry-failed` to re-submit those rows and merge results back.

V7 unavailable-model skips log **resolved settings** and **actionable hints** (e.g., file-upload 404, DNS issues, parent entity confusion).

### V7 Go Modes

V7 runs have two modes based on registry config:

| Mode | When | Behavior |
|------|------|----------|
| **Go Agent v2** | Entry has `agent_template_json` and `multimodal: True` | Empty entity → upload PDF to File property → poll tool-backed fields → merge into one JSON |
| **Single-output (legacy)** | No v2 template | Create entity with prompt+OCR text (or simple file upload) → poll one output property |

Most `config_models_v7.py` entries are Go Agent v2 variants sharing `v7_go_agent_v2_template.json`, differing only by `v7_property_model` (which model id drives the template tools).

**File property precedence** (Go Agent v2):
1. Per-model `file_field_slug` in config
2. `V7_GO_FILE_FIELD_SLUG` env var (ignored if it's the legacy default `document-pdf` while template names a different property)
3. File property id parsed from `agent_template_json`

If your agent lives in a different V7 project than the JSON export, set `file_field_slug` or `V7_GO_FILE_FIELD_SLUG` to the actual File property **id** from the V7 UI.

### Scoring Methodology

`score.py` uses field-level similarity scoring:

| Field Type | Scoring |
|------------|---------|
| **Exact** (`charity_number`, `report_date`) | 1.0 if equal, 0.0 otherwise |
| **Numeric** (`income_annually_in_british_pounds`, `spending_annually_in_british_pounds`) | 1.0 if within 0.5% tolerance, 0.0 otherwise |
| **Text** (address fields) | `SequenceMatcher` ratio on normalized strings (lowercase, collapse underscores/spaces) |

Per-document F1 is computed from field-level TP/FP/FN, then averaged across all documents.

**Provider aggregates** in `python score.py` tail output and README come from averaging F1/time/cost across **active** models only (F1 > 0). Doubleword `batch_id` is the real batch id; V7 `batch_id` is **synthetic** (checkpoint map key), not a Doubleword-style batch.

## Key Files

| File | Purpose |
|------|---------|
| `extractor.py` | Unified orchestrator: auto-detects backend, handles checkpoints (Doubleword auto-sync disabled by default) |
| `llm_openrouter.py` | OpenRouter HTTP client (sync per-row) |
| `llm_doubleword.py` | Doubleword Batch API client (async batch: submit → poll → download) |
| `llm_v7.py` | V7 Go entity API client (async: create entity per row or Go Agent v2 flow with PDF upload) |
| `score.py` | F1/Precision/Recall scorer with field-level similarity. No args → leaderboard; pass filename → verbose diff |
| `playground.py` | Generates `which-models-extracted-playground.html` from `data/` |
| `config_models_*.py` | Model registries (OpenRouter manual, Doubleword manually corrected, V7 manual) |
| `sync_doubleword_models.py` | Sync Doubleword pricing from docs endpoint (disabled by default via `SKIP_DOUBLEWORD_SYNC=1`) |
| `sync_v7_go_agent_template.py` | Refresh `v7_go_agent_v2_template.json` from V7 API after UI property changes |
| `utils.py` | Shared helpers: `get_logger`, `extract_from_triple_backticks` (strips `<think>` blocks from reasoning models), `sanitize_error_message` |
| `v7_go_ensure.py` | V7 Go configuration validation utilities |

## Environment Variables

### Required for OpenRouter
```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

### Required for Doubleword
```bash
DOUBLEWORD_API_KEY=your-doubleword-api-key
```

### Required for V7 Go
```bash
V7_GO_API_KEY=your-v7-api-key  # or V7_API_KEY
V7_GO_WORKSPACE_ID=workspace-uuid
V7_GO_AGENT_ID=agent-project-uuid
```

### Optional V7 Go overrides
```bash
V7_GO_BASE_URL=https://go.v7labs.com  # default; avoid api.go.v7labs.com (DNS issues)
V7_GO_INPUT_FIELD_SLUG=document-text  # single-output agents
V7_GO_OUTPUT_FIELD_SLUG=extracted-json  # single-output agents
V7_GO_FILE_FIELD_SLUG=...  # File property for PDFs; for Go Agent v2 often omit
V7_GO_PARENT_ENTITY_ID=...  # Only for collection (child) projects — parent *entity* id (not project id)
V7_GO_PDF_DIR=data  # directory containing PDF files for multimodal upload
V7_GO_AUTO_ENSURE_PROPERTIES=1  # auto-create missing properties on the V7 agent
```

### Optional Doubleword overrides
```bash
SKIP_DOUBLEWORD_SYNC=1  # disable auto-sync of model registry (preserves manual identifier corrections)
```

See `docs/v7-go.md` for V7-specific setup details and `QUICKSTART.md` for full environment setup.

## Notes

- **Runs are idempotent**: `extractor.py` skips models whose output files already exist under `data/`
- **Graceful shutdown**: Ctrl-C during Doubleword or V7 polling preserves checkpoints and resumes on next run
- **All providers scored together**: `score.py` and `playground.py` automatically include any `data/playgroup_dev_extracted__*.tsv` files regardless of backend
- **Short labels in UI**: When all `__`-suffixed models share the same agent prefix, leaderboards and playground show shortened names (e.g., `gpt4-1`), but filenames and CSV stay full-length
- **OpenRouter tiers** (in `config_models_openrouter.py`): `free`, `ultra_cheap` (<$0.30/M), `great_value` ($0.30–$1.00/M), `premium` (>$1.00/M)
- **Doubleword tiers** (in `config_models_doubleword.py`): `budget`, `standard`, `premium`; pricing is for 1h batch (24h is 30-50% cheaper via `--completion-window 24h`)
- **Doubleword config metadata**: Each entry has `intelligence` score, `quantization`, `apis` (batch/async/realtime), `params_total`/`params_active`, `thinking_default`, `dottxt` flag (structured gen), `ocr` flag with `ocr_prompt`/`ocr_max_image_dim`, `description`, and `usage_notes`
- **Reasoning model handling**: `<think>` blocks from reasoning models (GLM-5.1, Qwen3.5 family) are stripped by `utils.extract_from_triple_backticks` before JSON extraction
- **OCR models**: Receive PDF pages as base64-encoded JPEG images via PyMuPDF (not OCR text); configured with `ocr: True` and model-specific prompts in the registry
- **Hardest fields** (even top models struggle): `income_annually_in_british_pounds`, `spending_annually_in_british_pounds`

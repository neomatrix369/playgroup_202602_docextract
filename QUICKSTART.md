# Quickstart

Do the following before attending playgroup please.

> Once setup is done, head to the [README](README.md) for the full workflow, results, and key findings.

---

## 1. Python

The project requires Python 3.13 (pinned in `.python-version`). Choose either route below.

### Option A — venv + pip

```bash
$ python -c "import sys; print(sys.version)"  # confirm >= 3.13
$ python -m venv .venv
$ . .venv/bin/activate
$ pip install -r requirements.txt
```

### Option B — uv (faster)

```bash
$ uv venv                          # auto-picks Python 3.13 from .python-version
$ . .venv/bin/activate
$ uv pip install -r requirements.txt
```

If `uv` isn't installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## 2. API Keys

Create a `.env` file in the project root:

```
OPENROUTER_API_KEY=sk-or-v1-...
DOUBLEWORD_API_KEY=your-doubleword-api-key-here   # optional, for Doubleword batch extraction

# Optional — V7 Go (only if you run models from config_models_v7.py, e.g. v7-charity-extract)
V7_GO_API_KEY=your-v7-go-api-key
V7_GO_WORKSPACE_ID=your-workspace-uuid
V7_GO_AGENT_ID=your-agent-uuid
# Optional overrides (defaults shown):
# V7_GO_INPUT_FIELD_SLUG=document-text
# V7_GO_OUTPUT_FIELD_SLUG=extracted-json
# V7_GO_BASE_URL=https://go.v7labs.com
# V7_GO_FILE_FIELD_SLUG=…        # multimodal / file upload; for Go Agent v2 often omit (see README)
# V7_GO_PARENT_ENTITY_ID=…       # collection agents only — parent *entity* id, not project/agent id
```

The OpenRouter key is required for OpenRouter models. The Doubleword key is only needed for `DOUBLEWORD_MODELS` entries (e.g. `dw-qwen3.5-9b`). The V7 variables are only needed for `V7_MODELS` entries. For V7, read [README.md](README.md) — **V7 Go (optional backend)** — especially **File property for Go Agent v2** and **V7_GO_PARENT_ENTITY_ID** if you use `agent_template_json` or child projects.

---

## 3. Smoke Test

Run this to confirm everything is working:

```bash
$ python llm_openrouter.py
```

Expected output — JSON extracted from a canned text snippet:

```
Openrouter API key: %s sk-or-v1-8...
Using model: anthropic/claude-3.5-haiku
{
    "Registered Charity Number": "1132766"
}
```

If you see the JSON block, you're ready.

---

## Next Steps

Head to [README.md](README.md) for the full end-to-end workflow. The key commands follow a consistent pattern:

- **Pass a model name** → run that model only (e.g. `python extractor.py gemini-2.0-flash`)
- **Pass multiple model names** → run each in turn (backend auto-detected per model)
- **Pass no args** → run all models from every registry (OpenRouter, Doubleword, and V7 if any are defined); already-completed runs are skipped (idempotent)
- **Use `--all-openrouter`** → run only OpenRouter models
- **Use `--all-doubleword`** → run only Doubleword batch models
- **Use `--all-v7`** → run only V7 Go models from `config_models_v7.py`
- **Use `--v7-agent-template PATH`** together with any run that includes V7 models (e.g. `--all-v7`) to override `agent_template_json` with a Go export JSON for that run; see [README.md](README.md) examples

The same applies to `score.py`: no args scores all models and prints a leaderboard; pass a filename for a verbose diff of one model.

After scoring, regenerate the static playground with `python playground.py` or `uv run python playground.py` so [which-models-extracted-playground.html](which-models-extracted-playground.html) matches `data/`. Long V7-style ids such as `v7-go-agent-v2__gpt4-1` are shown in shortened form in the printed leaderboard and playground **where every `__`-suffixed id shares the same prefix**; filenames and `extraction_stats.csv` always use the full id (see [README — Results](README.md#results)).

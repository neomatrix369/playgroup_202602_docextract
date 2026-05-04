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
# Disable auto-sync to preserve manual model identifier corrections (recommended)
SKIP_DOUBLEWORD_SYNC=1

# Optional — V7 Go (only if you run models from config_models_v7.py, e.g. v7-go-agent-v2/claude-sonnet)
V7_GO_API_KEY=your-v7-go-api-key
V7_GO_WORKSPACE_ID=your-workspace-uuid
V7_GO_AGENT_ID=your-agent-uuid
V7_GO_PDF_DIR=data
# Optional overrides (defaults shown):
# V7_GO_INPUT_FIELD_SLUG=document-text
# V7_GO_OUTPUT_FIELD_SLUG=extracted-json
# V7_GO_BASE_URL=https://go.v7labs.com
# V7_GO_FILE_FIELD_SLUG=…        # multimodal / file upload; for Go Agent v2 often omit (see README)
# V7_GO_PARENT_ENTITY_ID=…       # collection agents only — parent *entity* id, not project/agent id
# V7_GO_AUTO_ENSURE_PROPERTIES=1  # auto-create missing properties on the V7 agent
```

The OpenRouter key is required for OpenRouter models. The Doubleword key is only needed for `DOUBLEWORD_MODELS` entries (e.g. `dw-qwen3.5-9b`). The V7 variables are only needed for `V7_MODELS` entries. **Registry sizes (for mental model):** ~33 OpenRouter models, 21 Doubleword extraction models (auto-sync **disabled** via `SKIP_DOUBLEWORD_SYNC=1` — model identifiers are manually corrected), 32 optional V7 keys — see [README — Key Findings](README.md#key-findings) and [Auto-Sync Pricing](README.md#auto-sync-pricing). For V7 setup detail, read [README.md](README.md) — **V7 Go (optional backend)** — especially **File property for Go Agent v2** and **V7_GO_PARENT_ENTITY_ID** if you use `agent_template_json` or child projects. A compact V7-only checklist is in [docs/v7-go.md](docs/v7-go.md).

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

## 4. Optional — V7 Go (no OpenRouter substitute)

There is no tiny `llm_v7.py` “one-shot” smoke script in this repo; V7 is exercised through **`extractor.py`** against your real workspace and agent.

**Checklist**

1. Fill in `V7_GO_API_KEY` (or `V7_API_KEY`), `V7_GO_WORKSPACE_ID`, and `V7_GO_AGENT_ID` in `.env`.
2. Ensure your Go project matches the expected **Go Agent v2** shape (or adjust `v7_go_agent_v2_template.json` — refresh from the API with `python sync_v7_go_agent_template.py` after property changes in the V7 UI).
3. Run a single registry key (slashes are fine in most shells):

   ```bash
   python extractor.py v7-go-agent-v2/claude-sonnet
   ```

4. Output path: `data/playgroup_dev_extracted__v7__v7-go-agent-v2__claude-sonnet.tsv` (`/` in the model key → `__` in the filename).
5. Score it like any other provider: `python score.py` (all models) or pass that `.tsv` path for a verbose diff.

If submit fails, check console hints and `data/.v7_unavailable_models.json`. Full behaviour, flags (`--all-v7`, `--v7-agent-template`, `--retry-failed`), and the env table are in [README.md — V7 Go](README.md#v7-go-optional-backend).

---

## Next Steps

Head to [README.md](README.md) for the full end-to-end workflow. The key commands follow a consistent pattern:

- **Pass a model name** → run that model only (e.g. `python extractor.py gemini-2.0-flash`)
- **Pass multiple model names** → run each in turn (backend auto-detected per model)
- **Pass no args** → run all models from every registry (OpenRouter, Doubleword, and V7 if any are defined); already-completed runs are skipped (idempotent)
- **Use `--all-openrouter`** → run only OpenRouter models
- **Use `--all-doubleword`** → run only Doubleword batch models
- **Use `--all-doubleword`** → run only Doubleword batch models (21 keys; auto-sync disabled — see [README — Auto-Sync Pricing](README.md#auto-sync-pricing))
- **Use `--all-v7`** → run only V7 Go models from `config_models_v7.py` (32 keys; check with `python -c "from config_models_v7 import V7_MODELS; print(len(V7_MODELS))"`)
- **Use `--v7-agent-template PATH`** together with any run that includes V7 models (e.g. `--all-v7`) to override `agent_template_json` with a Go export JSON for that run; see [README.md](README.md) examples
- **V7 summary doc** → [docs/v7-go.md](docs/v7-go.md)

The same applies to `score.py`: no args scores all models and prints a leaderboard; pass a filename for a verbose diff of one model.

After scoring, regenerate the static playground with `python playground.py` or `uv run python playground.py` so [which-models-extracted-playground.html](which-models-extracted-playground.html) embeds the same results as `data/` (all providers, including V7). V7 rows use short leaderboard labels such as **`gpt4-1`** when every `__`-suffixed model shares the same agent prefix; filenames and `extraction_stats.csv` keep the full id (e.g. `v7-go-agent-v2__gpt4-1`) — see [README — Results](README.md#results). When you change `data/`, update the README **Key Findings** provider table from the **Provider summary** block at the end of `python score.py` if you want the doc to stay in sync.

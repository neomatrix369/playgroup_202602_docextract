Do the following before attending playgroup please.

# Setup

The project requires Python 3.13 (pinned in `.python-version`). Choose either route below.

---

## Option A — venv + pip

```bash
$ python -c "import sys; print(sys.version)"  # confirm >= 3.13
# $ conda activate python313                  # Ian's route if needed
$ python -m venv .venv
$ . .venv/bin/activate
$ pip install -r requirements.txt
```

## Option B — uv (faster)

```bash
$ uv venv                          # auto-picks Python 3.13 from .python-version
$ . .venv/bin/activate
$ uv pip install -r requirements.txt
```

If `uv` isn't installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

# .env

You'll need a `.env` file with your API keys:

```
OPENROUTER_API_KEY=sk-or-v1-...
DOUBLEWORD_API_KEY=your-doubleword-api-key-here   # optional, for batch extraction
```

The OpenRouter key is required. The Doubleword key is only needed if you want to run `dw-*` models via `extractor.py`.

---

# Smoke Test

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

# Next Steps

See `README.md` for the full end-to-end workflow. The key commands follow a consistent pattern:

- **Pass a model name** → run that model only (e.g. `python extractor.py gemini-2.0-flash`)
- **Pass multiple model names** → run each in turn (backend auto-detected per model)
- **Pass no args** → run all models from both providers; already-completed runs are skipped (idempotent)
- **Use `--all-openrouter`** → run only OpenRouter models
- **Use `--all-doubleword`** → run only Doubleword batch models

The same applies to `score.py`: no args scores all models and prints a leaderboard; pass a filename for a verbose diff of one model.

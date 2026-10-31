# Project Invariants
> Self-contained reference — key constraints extracted here at planning time.
> Truth sources linked for updates; update those files and re-extract here when they change.

## Key constraints
- Python 3.13 runtime via uv / venv.
- Direct Google DeepMind Gemini API support via OpenAI-compatible endpoint with existing `openai` client.
- Output format: Tab-separated key-value pairs (`key=value`) per row matching `ALL_FIELDS`.
- Model naming convention: `google-*` prefix for direct provider auto-detection.
- Synchronous per-row extraction over `data/playgroup_dev_in.tsv` matching OpenRouter parity.
→ Source: docs/plan/interview_summary.md § Constraints

## Provider Ideas & Constraints Learned from OpenRouter, Doubleword, and V7 Go
1. **Model Identifier Disambiguation & Safe Naming**:
   - Registry keys use `google-*` prefix (e.g. `google-gemini-4-argon`) mapping to official API model IDs (`gemini-4-argon`).
   - Output TSVs use standard naming: `data/playgroup_dev_extracted__google__<model_short_name>.tsv`.
2. **Context Window Checks & Safe Truncation**:
   - Check model `ctx` limit. For huge context models (1M+ for Argon/Flash), truncation is rarely needed, but context bounding formula `(max_ctx_tokens - 2000) * 4 - len(prompt_template)` is enforced as defense-in-depth.
3. **Robust Rate-Limit Handling (429 & ResourceExhausted)**:
   - Google AI Studio / Gemini endpoints enforce strict RPM/TPM quotas.
   - Implement 5-attempt exponential backoff (`wait = 2 ** attempt * 10`s, with jitter) for `429`, `ResourceExhausted`, or transient `503`.
4. **Extraction Cleaning & Triple-Backtick Extraction**:
   - Models wrap output in ` ```json ... ``` ` or append thoughts.
   - Reuse `utils.extract_from_triple_backticks()` and `_parse_llm_response()` for whitespace, currency stripping, and uppercase address normalization.
5. **Usage Telemetry & Cost Accounting**:
   - Track `prompt_tokens`, `completion_tokens`, and calculate `total_cost_usd` via model `price_in` and `price_out`.
   - Record call telemetry to `data/extraction_call_log.csv` and dedicated `llm_google_calls.log`.
6. **Execution Idempotency & Pre-run Planning**:
   - Extractor inspects existing TSV files before running (`_print_provider_plan`). Existing runs are skipped unless explicitly targeted or retried.
7. **Scoring & Leaderboard Parity**:
   - `score.py` automatically parses `playgroup_dev_extracted__google__*.tsv`.
   - `playground.py` groups `google` with distinct provider label (`Google DeepMind`) and badge (`badge-blue`) across all 8 tabs.
8. **Decision ownership SSOT** → `docs/plan/DECISION-OWNERSHIP.md`.
→ Source: docs/plan/DECISIONS.md

## Tech stack & runtime
- Python 3.13 (.python-version).
- Key packages: `openai`, `httpx`, `python-dotenv`, `loguru`, `pytest`, `pytest-cov`.
- Model split — Planning: claude-opus-5-5 · Execution: claude-sonnet-5-5.
→ Source: docs/plan/TRAIL.md § Original Material

## Project rules
- No direct commits to main or master — always work on a named branch (`slice/<N>-<name>`).
- TDD-first — automated tests and smoke test verification before marking slice passed.
- Reuse first: compose existing public helpers and registries before creating parallel structures.
- Preserve existing comments and docstrings across modified files.
→ Source: CLAUDE.md + ~/.claude/CLAUDE.md

# Interview Summary
> Generated: 2026-10-31 | Scenario: Small requirement | Flow: Flow C

## What was provided (explicit inputs)
- Goal: Add direct GEMINI model support from provider Google DeepMind to existing providers in `playgroup_202602_docextract`.
- API key for Google DeepMind / Gemini is already available.
- Specific model focus: Test Gemini 4 Argon and other recent models.
- Apply `/enhanced-flow-planner`.
- Requirement: Use all existing ideas and constraints other providers (OpenRouter, Doubleword, V7 Go) have been dealing with.

## What was inferred
- Architecture follows existing provider patterns: `config_models_*.py`, `llm_*.py`, auto-detection in `extractor.py`, TSV outputs, `score.py`, and `playground.py`.
- Model naming convention: Use `google-*` prefix (e.g. `google-gemini-4-argon`, `google-gemini-2.5-flash`) to disambiguate from OpenRouter models.
- API protocol: Use Google's OpenAI-compatible endpoint with the existing `openai` client to avoid adding new dependencies.
- Initial model lineup: `google-gemini-4-argon`, `google-gemini-2.5-flash`, `google-gemini-2.5-pro`, `google-gemini-3.8-flash`.
- Environment variable: `GEMINI_API_KEY` (with fallback to `GOOGLE_API_KEY`).
- Hardened provider patterns incorporated:
  - 429 / ResourceExhausted exponential backoff retry loop (from OpenRouter).
  - Context window safe truncation calculation (from OpenRouter).
  - Triple-backtick markdown stripping & robust field normalization (from OpenRouter/Doubleword).
  - Execution idempotency: check existing TSVs and skip completed runs (from extractor).
  - Provider telemetry logging: `llm_google_calls.log`, `extraction_call_log.csv`, and `extraction_stats.csv`.
  - Full leaderboard, color badges (`badge-blue`), and provider analytics in playground (from playground).

## What is missing / assumed
- Pricing details for Gemini 4 Argon and recent models: initial entries set with public/approximate rates and marked for manual review.
- API key must be placed in `.env` before running live extractions.

## Constraints
- Python 3.13 via uv/venv runtime.
- Reuse existing `openai` client and error handling patterns; no unnecessary dependencies.
- No direct commits to `main`; branch-per-slice discipline (`slice/<N>-<name>`).
- Output format: Tab-separated key-value pairs (`key=value`) per row matching `ALL_FIELDS`.

## Simplest shape
- Direct text-based extraction over `data/playgroup_dev_in.tsv` using the standard UK charity prompt, producing TSVs and updating stats and playground. Multimodal PDF uploads and async batching deferred.

## Non-goals (explicit out-of-scope)
- Native multimodal PDF upload (keep OCR text input identical to OpenRouter for apples-to-apples comparison).
- Asynchronous batch API integration (run synchronous per-row requests first).
- Auto-sync script for Google models (maintain curated registry manually).

## Observable outcomes (per capability)
- Direct Gemini API Client: `python llm_google.py` exits 0 and outputs structured charity JSON.
- Extractor Integration: `python extractor.py google-gemini-4-argon` produces `data/playgroup_dev_extracted__google__google-gemini-4-argon.tsv`.
- Scoring & Visualization: `python score.py` scores Google TSVs, and `python playground.py` includes Google DeepMind on the leaderboard.

## Divergence result
- Greenfield provider addition; no divergence detected against existing codebase or specs.

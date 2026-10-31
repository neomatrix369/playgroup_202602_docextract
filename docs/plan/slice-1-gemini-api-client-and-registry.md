# Slice 1: Gemini API Client and Model Registry

> Scenario: Small requirement | MoSCoW: Must

## Session bootstrap
> Re-read CLAUDE.md before starting — use values there, not hardcoded commands here.
- **Runtime source**: → CLAUDE.md § Environment
- **Test source**: → CLAUDE.md § Testing
- **Load first**: CLAUDE.md → docs/plan/invariants.md → this stub

## Context
> Read before any implementation. Do not rely on conversation history alone.
- **Stage objective**: Create the direct Google DeepMind model registry (`config_models_google.py`) and API caller module (`llm_google.py`) incorporating all provider-hardened patterns (backoff, context checks, triple-backtick extraction, logging) with unit test verification.
- **Depends on**: none
- **Global invariants**: → `docs/plan/invariants.md`

## Non-goals
> Out of scope for this slice — do not implement here.
- Modifying `extractor.py` or running batch extraction (deferred to Slice 2).
- Multimodal PDF direct image token handling.
- Asynchronous batch polling or auto-sync scripts.

## Output contract
> Observable shape of completion (shape only — not exact file paths).
- **Baseline**: `test -f config_models_google.py && test -f llm_google.py || echo "absent"`
- `python llm_google.py` outputs structured charity JSON when `GEMINI_API_KEY` is present.
- Unit test file `tests/test_llm_google.py` passes with automated mocks for request payload, rate limit (429) backoff, and error recovery.

## Slice Workflow Bundle
- Slice name: slice-1-gemini-api-client-and-registry
- Files: `config_models_google.py`, `llm_google.py`, `tests/test_llm_google.py`
- Exit criteria: Model registry defined with Gemini 4 Argon and recent models; API caller successfully requests, handles backoff, and parses JSON; unit tests pass.
- Commit pattern: `feat(slice-1): add direct google deepmind gemini api client and registry`

## Branch
`feat/slice-1-gemini-api-client-and-registry`

## Spec (GWT / User Story)
**Given** a valid Google Gemini API key configured in `.env` as `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)  
**When** `llm_google.call_llm` is called with `google-gemini-4-argon` and charity extraction prompt  
**Then** it sends a request to Google's OpenAI-compatible endpoint, handles 429/ResourceExhausted with exponential backoff if encountered, extracts JSON from triple backticks, and returns text, timing, and token metrics.

## Executable Public Oracle (DISTILL)
- **Registry Oracle**: `python -c "import config_models_google; assert 'google-gemini-4-argon' in config_models_google.GOOGLE_MODELS; print('REGISTRY_OK')"` exits 0 and prints `REGISTRY_OK`.
- **Smoke Oracle**: `python llm_google.py` exits 0 and prints structured JSON with `charity_number`, `charity_name`, and `report_date`.
- **Unit Test Oracle**: `pytest tests/test_llm_google.py` exits 0 with all tests passing.

## Before-Checks [GATE]
- [ ] Branch created: `slice/1-gemini-api-client-and-registry`
- [ ] Baseline test runner verified (`pytest tests/`)
- [ ] `docs/plan/invariants.md` loaded and verified

## TDD Execution
Execution sequence: RED → GREEN → REFACTOR PROD → REFACTOR TESTS → VERIFY+COVERAGE
1. Author test `tests/test_llm_google.py` verifying client initialization, model lookup, prompt formatting, 429 exponential backoff, and error handling.
2. Implement `config_models_google.py` defining `GOOGLE_MODELS` with:
   - `google-gemini-4-argon`
   - `google-gemini-2.5-flash`
   - `google-gemini-2.5-pro`
   - `google-gemini-3.8-flash`
   Including tier, pricing, modalities, and context limits.
3. Implement `llm_google.py` with:
   - OpenAI client configured for `https://generativelanguage.googleapis.com/v1beta/openai/`
   - `add_file_logger("llm_google_calls.log")`
   - `max_ctx_tokens` calculation and safe truncation
   - 429 / 503 retry loop with exponential backoff
   - `utils.extract_from_triple_backticks` parsing
4. Run `pytest tests/test_llm_google.py` and smoke test `python llm_google.py`.

## After-Checks [GATE]
- [ ] Code committed with `feat(slice-1): ...` message
- [ ] Automated tests pass with 100% GWT clause coverage
- [ ] Complexity within threshold (CC ≤ 10)
- [ ] Zero type errors and dead code
- [ ] Doc audit completed

### Closing Gates
- [ ] `nw-at-completeness-check` — AT completeness audit (slice close gate #8)
- [ ] `nw-software-crafter-reviewer` — code quality + TDD discipline review (slice close gate #9)
- [ ] `nw-solution-architect-reviewer` + `nw-system-designer-reviewer` — data flow review (gate #9)
- [ ] `nw-gate-evidence-validator` — all 9 gate-evidence conditions pass
- [ ] `/verify-slice` — holistic evidence verdict COMPLETE (final closing gate)

## Doc Audit (14-row checklist)
| # | Item | Check |
|---|------|-------|
| 1 | README updated | — |
| 2 | Inline comments added where non-obvious | — |
| 3 | Function signatures documented | — |
| 4 | Error paths documented | — |
| 5 | CHANGELOG entry written | — |
| 6 | Architecture doc updated | — |
| 7 | API doc updated | — |
| 8 | Config/env vars documented (`GEMINI_API_KEY`) | — |
| 9 | Examples added or updated | — |
| 10 | Deprecated features marked | — |
| 11 | Migration guide written | — |
| 12 | Troubleshooting section added | — |
| 13 | Related links cross-referenced | — |
| 14 | No orphaned file references | — |

## Gate Status
🔀 ON BRANCH — all three oracles pass (2026-10-31). Closing reviewer gates not yet run.

## What Changed
| File | Type | Reason |
|------|------|--------|
| `config_models_google.py` | Create | Google DeepMind model registry (Argon, Flash, Pro) |
| `llm_google.py` | Create | Direct Gemini API caller with backoff, logging, and extraction |
| `tests/test_llm_google.py` | Create | Unit test suite for Google Gemini caller |
| `utils.py` | Edit | Shared sync-client primitives: `truncate_to_ctx`, `call_with_backoff`, `read_usage` |
| `llm_openrouter.py` | Edit | Uses the shared primitives instead of its own copies (no behaviour change; now also logs errors before re-raising) |

## Session Metrics
| Metric | Value |
|--------|-------|
| Estimated Pomos | 2 (~50 min) [Walking Skeleton] |
| Execution time | — |
| Blockers encountered | — |
| Next-session notes | — |

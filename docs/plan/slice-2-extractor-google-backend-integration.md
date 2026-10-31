# Slice 2: Extractor Google Backend Integration

> Scenario: Small requirement | MoSCoW: Must

## Session bootstrap
> Re-read CLAUDE.md before starting — use values there, not hardcoded commands here.
- **Runtime source**: → CLAUDE.md § Environment
- **Test source**: → CLAUDE.md § Testing
- **Load first**: CLAUDE.md → docs/plan/invariants.md → this stub

## Context
> Read before any implementation. Do not rely on conversation history alone.
- **Stage objective**: Integrate the Google backend into `extractor.py` with auto-detection for `google-*` models, support `--all-google`, idempotency planning, `--retry-failed` recovery, and live extraction telemetry.
- **Depends on**:
  - Slice 1 (Gemini API Client and Model Registry): `test -f config_models_google.py && test -f llm_google.py`
- **Global invariants**: → `docs/plan/invariants.md`

## Non-goals
> Out of scope for this slice — do not implement here.
- Altering existing OpenRouter, Doubleword, or V7 Go execution paths.
- Asynchronous batch polling (synchronous per-row extraction matches OpenRouter pattern).
- Updating scoring rankings or HTML playground (deferred to Slice 3).

## Output contract
> Observable shape of completion (shape only — not exact file paths).
- **Baseline**: `grep -q "GOOGLE_MODELS" extractor.py || echo "absent"`
- `python extractor.py google-gemini-4-argon` executes row-by-row extraction and outputs `data/playgroup_dev_extracted__google__google-gemini-4-argon.tsv`.
- `data/extraction_stats.csv` and `data/extraction_call_log.csv` receive rows with `provider=Google`.
- `python extractor.py --help` shows `--all-google` option.
- Running the command a second time shows `Skipping : google-gemini-4-argon (output exists)` proving idempotency.

## Slice Workflow Bundle
- Slice name: slice-2-extractor-google-backend-integration
- Files: `extractor.py`, `tests/test_extractor_google.py`
- Exit criteria: `extractor.py` auto-detects `google-*` models and dispatches to `llm_google`; `--all-google` flag supported; output TSV generated and formatted correctly; telemetry logged; idempotency enforced.
- Commit pattern: `feat(slice-2): integrate google backend into extractor and execute benchmark`

## Branch
`slice/2-extractor-google-backend-integration`

## Spec (GWT / User Story)
**Given** `extractor.py` invoked with a direct Google model (e.g. `python extractor.py google-gemini-4-argon`) or `--all-google`  
**When** the extraction loop processes rows from `data/playgroup_dev_in.tsv`  
**Then** it detects the `google-*` prefix, plans runs idempotently (skipping existing TSVs), calls `llm_google.call_llm`, parses charity fields, writes `data/playgroup_dev_extracted__google__<model>.tsv`, and logs telemetry to call log and stats CSV.

## Executable Public Oracle (DISTILL)
- **CLI Oracle**: `python extractor.py --help` exits 0 and includes `--all-google` in help text.
- **Run Oracle**: `python extractor.py google-gemini-4-argon`
  - Exits 0.
  - Generates `data/playgroup_dev_extracted__google__google-gemini-4-argon.tsv`.
  - File contains 11 lines matching format `address__post_town=... \t charity_name=...`.
  - Appends rows to `data/extraction_stats.csv` and `data/extraction_call_log.csv` with `provider=Google` and `model_short_name=google-gemini-4-argon`.
- **Idempotency Oracle**: Running `python extractor.py google-gemini-4-argon` again exits 0 without re-extracting already completed rows.
- **Unit Test Oracle**: `pytest tests/test_extractor_google.py` exits 0 with all tests passing.

## Before-Checks [GATE]
- [ ] Branch created: `slice/2-extractor-google-backend-integration`
- [ ] Slice 1 files confirmed present
- [ ] Unit tests from Slice 1 passing

## TDD Execution
Execution sequence: RED → GREEN → REFACTOR PROD → REFACTOR TESTS → VERIFY+COVERAGE
1. Author tests in `tests/test_extractor_google.py` validating CLI argument parsing (`--all-google`), backend auto-detection for `google-*`, output path formatting, and idempotency check.
2. Update `extractor.py`:
   - Import `config_models_google.GOOGLE_MODELS` and `llm_google`.
   - Add `GOOGLE_MODELS` to `ALL_MODELS`.
   - Add `--all-google` argument to CLI argument parser.
   - Add Google execution branch in `extractor.py` with `_print_provider_plan`, per-row timing/cost tracking, error sanitization, and output writer.
3. Run extraction test with `google-gemini-4-argon` on `playgroup_dev_in.tsv`.
4. Run `pytest tests/test_extractor_google.py`.

## After-Checks [GATE]
- [ ] Code committed with `feat(slice-2): ...` message
- [ ] Automated tests pass
- [ ] Output TSVs generated with valid key-value pairs matching `ALL_FIELDS`
- [ ] Extraction call logs recorded in `data/extraction_call_log.csv` and `data/extraction_stats.csv`
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
| 8 | Config/env vars documented | — |
| 9 | Examples added or updated (`python extractor.py --all-google`) | — |
| 10 | Deprecated features marked | — |
| 11 | Migration guide written | — |
| 12 | Troubleshooting section added | — |
| 13 | Related links cross-referenced | — |
| 14 | No orphaned file references | — |

## Gate Status
📋 PLANNED

## What Changed
| File | Type | Reason |
|------|------|--------|
| `extractor.py` | Modify | Auto-detect Google backend, add `--all-google`, write Google TSVs, idempotency |
| `tests/test_extractor_google.py` | Create | Unit tests for Google model dispatch and CLI args |

## Session Metrics
| Metric | Value |
|--------|-------|
| Estimated Pomos | 1 (~25 min) |
| Execution time | — |
| Blockers encountered | — |
| Next-session notes | — |

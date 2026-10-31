# Slice 3: Scoring, Playground and Documentation

> Scenario: Small requirement | MoSCoW: Should

## Session bootstrap
> Re-read CLAUDE.md before starting — use values there, not hardcoded commands here.
- **Runtime source**: → CLAUDE.md § Environment
- **Test source**: → CLAUDE.md § Testing
- **Load first**: CLAUDE.md → docs/plan/invariants.md → this stub

## Context
> Read before any implementation. Do not rely on conversation history alone.
- **Stage objective**: Integrate Google DeepMind models into `score.py` and `playground.py` (with full provider badge, labeling, and aggregation parity across all 8 tabs) and update documentation (`README.md`, `CLAUDE.md`, `.env.example`).
- **Depends on**:
  - Slice 2 (Extractor Google Backend Integration): `test -f extractor.py` and presence of at least one `data/playgroup_dev_extracted__google__*.tsv`
- **Global invariants**: → `docs/plan/invariants.md`

## Non-goals
> Out of scope for this slice — do not implement here.
- Altering existing ground truth data or scoring metrics (F1/Precision/Recall formulas remain untouched).
- Overhauling playground layout or core visual theme.

## Output contract
> Observable shape of completion (shape only — not exact file paths).
- **Baseline**: `grep -i "gemini_api_key" .env.example || echo "absent"`
- `python score.py` ranks Google DeepMind model(s) on the leaderboard with valid F1 scores.
- `python playground.py` generates `which-models-extracted-playground.html` including Google DeepMind under Provider Analysis, Provider dropdown filters, and model badges.
- `.env.example`, `CLAUDE.md`, and `README.md` document Google provider setup and commands.

## Slice Workflow Bundle
- Slice name: slice-3-scoring-playground-and-documentation
- Files: `score.py`, `playground.py`, `README.md`, `CLAUDE.md`, `.env.example`
- Exit criteria: Google DeepMind model extractions scored; playground updated with Google provider metrics; all documentation updated.
- Commit pattern: `feat(slice-3): score google models, update playground, and document provider`

## Branch
`slice/3-scoring-playground-and-documentation`

## Spec (GWT / User Story)
**Given** extracted Google TSV files in `data/playgroup_dev_extracted__google__*.tsv`  
**When** `python score.py` and `python playground.py` are executed  
**Then** the leaderboard and HTML playground reflect Google DeepMind models alongside existing providers with proper badges, labels, and tier analysis, and `README.md` / `CLAUDE.md` accurately document the new provider commands.

## Executable Public Oracle (DISTILL)
- **Scoring Oracle**: `python score.py data/playgroup_dev_extracted__google__google-gemini-4-argon.tsv` exits 0 and prints calculated F1, Precision, and Recall scores.
- **Leaderboard Oracle**: `python score.py` exits 0 and displays `google-gemini-4-argon` grouped under provider `google`.
- **Playground Oracle**: `python playground.py` exits 0, updates `which-models-extracted-playground.html`, and embeds `Google DeepMind` in `providerAggRows` and `model_providers`.
- **Documentation Oracle**: `grep -q "GEMINI_API_KEY" .env.example` and `grep -q "google-gemini-4-argon" README.md` both exit 0.

## Before-Checks [GATE]
- [ ] Branch created: `slice/3-scoring-playground-and-documentation`
- [ ] Extracted TSV from Slice 2 exists
- [ ] All prior tests passing

## TDD Execution
Execution sequence: RED → GREEN → REFACTOR PROD → REFACTOR TESTS → VERIFY+COVERAGE
1. Update `score.py` to import `config_models_google.GOOGLE_MODELS` into `ALL_MODELS`, ensuring provider grouping resolves `google`.
2. Update `playground.py`:
   - Import `GOOGLE_MODELS` in `load_model_meta()`
   - Add prefix check `name.startswith("google-")` -> `"google"` in provider backfill
   - Add `providerLabel` and `providerChartLabel` entry: `if (p === 'google') return 'Google DeepMind'`
   - Add `providerBadge` entry: `else if (p === 'google') cls = 'badge-blue'`
3. Run `python score.py` and `python playground.py`.
4. Update `README.md`, `CLAUDE.md`, and `.env.example`.
5. Run doc audit and full test suite.

## After-Checks [GATE]
- [ ] Code committed with `feat(slice-3): ...` message
- [ ] `score.py` output verified
- [ ] `which-models-extracted-playground.html` generated without errors
- [ ] Documentation updated across README, CLAUDE.md, and .env.example
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
| `score.py` | Modify | Import GOOGLE_MODELS into ALL_MODELS, support google provider |
| `playground.py` | Modify | Support Google DeepMind in badges, labels, catalog, and provider analysis |
| `README.md` | Update | Add Google DeepMind provider commands and architecture notes |
| `CLAUDE.md` | Update | Document Google DeepMind provider commands and models |
| `.env.example` | Update | Add `GEMINI_API_KEY` configuration example |

## Session Metrics
| Metric | Value |
|--------|-------|
| Estimated Pomos | 1 (~25 min) |
| Execution time | — |
| Blockers encountered | — |
| Next-session notes | — |

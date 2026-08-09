---
name: docextract-workflow
description: >-
  Project-specific orientation and workflow map for the playgroup_202602_docextract
  multi-model LLM benchmark. Invoke manually (/docextract-workflow) at the start of
  a session or task — detects the current stage and tells you exactly where to continue.
metadata:
  author: Mani Sarkar
  surfaces: [claude-code]
---

## Orientation

This project benchmarks 90+ LLM models across three backends against 11 UK charity
financial PDFs. Each model extracts structured fields and is scored with F1/Precision/Recall.
Results feed into an interactive HTML playground (`which-models-extracted-playground.html`).

**Three backends, one orchestrator:**
- `dw-*` keys → Doubleword Batch API (async: submit → poll → download)
- `v7-*` keys → V7 Go entity API (async: create entity per row, or Go Agent v2 with PDF upload)
- Everything else → OpenRouter (sync, per-row)

**Core pipeline:** `extractor.py` → `score.py` → `playground.py`

Full architecture, scoring methodology, and V7 detail: **CLAUDE.md**.

---

## Stage Detection

When invoked, run these checks **in order** to find where the session should resume:

### Step 1 — Check git status
```bash
git status
git diff --stat HEAD
```
- Uncommitted changes → determine what changed and pick up from the right stage below
- Clean tree → look at recent commits (`git log --oneline -10`) to infer last completed stage

### Step 2 — Check for pending extractions
```bash
ls data/.doubleword_checkpoints.json data/.v7_checkpoints.json 2>/dev/null
```
- Checkpoint file exists → a batch was submitted but may not have finished; re-run the same
  extractor command to resume polling
- Also check: `data/.doubleword_failed_rows.json` and `data/.v7_failed_rows.json` — if non-empty,
  failed rows are waiting for `--retry-failed`

### Step 3 — Check for unscored TSVs
```bash
# TSVs newer than extraction_stats.csv indicate results that haven't fed into the leaderboard yet
ls -lt data/playgroup_dev_extracted__*.tsv | head -5
ls -lt data/extraction_stats.csv
```
- New TSVs present but not yet reflected in stats → run `python score.py` to confirm F1

### Step 4 — Check playground freshness
```bash
ls -lt which-models-extracted-playground.html data/playgroup_dev_extracted__*.tsv | head -10
```
- Playground older than any TSV → run `python playground.py`

### Step 5 — Check docs drift
- README Key Findings stats (scored runs count, provider table, top-5 table) out of sync with
  current `python score.py` output → run `/sync-docs`

### Step 6 — Check commit/push state
```bash
git log --oneline origin/HEAD..HEAD
```
- Commits ahead of remote → run `/update-pr`

**Resume from the earliest incomplete stage** — don't skip ahead.

If the checks above are inconclusive (e.g., clean tree with no obvious signal, ambiguous
timestamps, mid-run state that's hard to read), fall through to the **Wizard Fallback** below.

---

## Wizard Fallback

When stage detection is inconclusive, ask the user one question at a time — stop as soon as the
stage is clear. Do not ask all questions at once.

---

**Q1 — Where are you in the workflow right now?**

Present these options:

```
1. Starting fresh — haven't run any models yet (or want to run new ones)
2. Models are running / just submitted a batch — waiting or just got results back
3. Have finished results (TSVs) — need to score, update playground, or update docs
4. Everything is scored and docs are up to date — need to commit and/or push
5. Not sure / something went wrong — help me figure it out
```

Route based on answer:
- **1** → go to Q2 (which backend?)
- **2** → go to Q3 (batch state?)
- **3** → go to Q4 (what's been done so far?)
- **4** → confirm with `git status`, then `/clean-commit` → `/update-pr`
- **5** → run all Stage Detection steps explicitly and report findings before asking Q2

---

**Q2 — Which backend are you targeting?**  
*(Only ask if answer to Q1 was 1 or 5)*

```
1. Doubleword (dw-* models)
2. OpenRouter (everything else)
3. V7 Go (v7-* models)
4. All backends / not sure
```

Route:
- **1** → `python extractor.py --all-doubleword` (or specific model keys)
- **2** → `python extractor.py --all-openrouter` (or specific model keys)
- **3** → `python extractor.py --all-v7`
- **4** → `python extractor.py` (runs all)

After routing, remind: runs are idempotent — existing TSVs are skipped.

---

**Q3 — What's the state of the batch?**  
*(Only ask if answer to Q1 was 2)*

```
1. Still polling / waiting for results
2. Results just came back — TSV should be there now
3. Some rows failed (saw context_length_exceeded or similar errors)
4. The run was interrupted (Ctrl-C or crash)
```

Route:
- **1** → re-run the same extractor command to resume polling (checkpoint will pick up)
- **2** → `python score.py` to verify F1, then continue cadence (playground → sync-docs → commit)
- **3** → `python extractor.py --retry-failed` to resubmit failed rows and merge results
- **4** → re-run the same extractor command; checkpoint file will resume where it left off

---

**Q4 — What have you already done with the finished results?**  
*(Only ask if answer to Q1 was 3)*

```
1. Nothing yet — just noticed the TSVs are there
2. Ran score.py — have the F1 numbers
3. Ran score.py and regenerated the playground
4. Done all that — just need to update docs (README/CLAUDE.md stats)
```

Route:
- **1** → start from top of cadence: `python score.py`
- **2** → `python playground.py`, then `/sync-docs`
- **3** → `/sync-docs`
- **4** → `/clean-commit` (data files first, docs second) → `/update-pr`

---

## Task → Command Map

| Task | Command / Skill |
|---|---|
| Run one model | `python extractor.py <model-key>` |
| Run multiple models | `python extractor.py model-a model-b` |
| Run all Doubleword models | `python extractor.py --all-doubleword` |
| Run all OpenRouter models | `python extractor.py --all-openrouter` |
| Run all V7 Go models | `python extractor.py --all-v7` |
| Run all backends | `python extractor.py` |
| Retry failed rows (DW or V7) | `python extractor.py --retry-failed` |
| Leaderboard (all models) | `python score.py` |
| Verbose diff for one model | `python score.py data/playgroup_dev_extracted__<provider>__<model>.tsv` |
| Regenerate playground HTML | `python playground.py` |
| Check DW API vs local diff | `python sync_doubleword_models.py --diff` |
| List raw DW API models | `python sync_doubleword_models.py --probe-api` |
| Commit changes cleanly | `/clean-commit` |
| Sync docs after changes | `/sync-docs` |
| Push and refresh PR | `/update-pr` |
| Merge PR to main | `/merge-pr-to-main` |

---

## Standard Cadence: New Model Results

When new model extractions complete, follow this sequence:

1. **Score** — `python score.py` to verify F1 and confirm results look sane
2. **Playground** — `python playground.py` to regenerate `which-models-extracted-playground.html`
3. **Sync docs** — `/sync-docs` + README audit (see section below) to update stats, counts, tables
4. **Commit** — `/clean-commit` for data files first, then docs (separate logical commits)
5. **Push + PR** — `/update-pr` to push branch and refresh PR title/body

Always commit data TSVs and stats CSVs before docs — they are the evidence the docs describe.

---

## README: Sections That Must Reflect Current Results

`/sync-docs` provides the methodology. This section tells it **what to audit** in `README.md`
for this project. After every benchmark run, verify and update all sections below against live
`python score.py` output and `data/extraction_stats.csv`.

### 1 — Key Findings metadata note
Located near the top of the Key Findings section. Update:
- Date of snapshot (e.g., `2026-07-22`)
- Total scored runs count
- Number of Doubleword TSVs / registry size

### 2 — Provider summary table
One row per backend (OpenRouter / Doubleword / V7 Go). Columns to keep current:
`all models` · `active` · `failed` · `avg F1` · `best F1 (model name)` · `fields extracted` · `avg time` · `avg cost`

Derive from `python score.py` tail output. DW row is most likely to change.

### 3 — Top 5 / Top N leaderboard table
Lists the highest-scoring models across all backends. Update ranks, F1 scores, and model names
whenever a new model enters or displaces an existing entry.

### 4 — Key Takeaways bullets
Prose bullets below the tables — update counts and superlatives:
- "N of M Doubleword models produced usable results"
- "Doubleword now holds N of global top 10"
- Any new best-in-class model or notable failure

### 5 — Registry / tier counts
In the Doubleword section: update total model count (e.g., `21 → 25`) and per-tier counts
(budget / standard / premium) when new models are added to `config_models_doubleword.py`.

### 6 — Leaderboard sample (if present)
Expanded leaderboard excerpt — extend or reorder if new models enter the top rows.

**Verification command** — run this before and after updating README stats to confirm alignment:
```bash
python score.py 2>/dev/null | tail -40
```
Every number in README Key Findings should trace directly to this output or `extraction_stats.csv`.

---

## Doubleword-Specific Gotchas

**Auto-sync is disabled** (`SKIP_DOUBLEWORD_SYNC=1` in `.env`). Do not remove this — it prevents
the full pricing sync from overwriting manual identifier corrections in `config_models_doubleword.py`.
New models are auto-appended as stubs by `extractor.py` at startup.

**Manual identifier corrections** — Doubleword docs identifiers often differ from what the Batch
API actually accepts. Verify via `--probe-api` before editing the registry.

**Batch URL** — every submission logs a trackable URL at submission and at completion/failure:
`https://app.doubleword.ai/batches/{batch_id}`

**Checkpoint resume** — Ctrl-C during polling saves state. Re-run the same command to resume.
Do not delete `data/.doubleword_checkpoints.json` mid-run.

**Partial failures** — failed rows (e.g., `context_length_exceeded`) go to
`data/.doubleword_failed_rows.json`. Run `python extractor.py --retry-failed` to resubmit and merge.

**Unavailable models** — submit failures go to `data/.doubleword_unavailable_models.json`.
Delete the entry to retry on next run.

---

## Data File Conventions

**TSV naming pattern:**
```
data/playgroup_dev_extracted__<provider>__<model-key-slashes-become-double-underscores>.tsv
```

**Idempotent runs** — `extractor.py` skips any model whose TSV already exists.
To re-run a model, delete its TSV first.

**Cumulative stats:**
- `data/extraction_stats.csv` — per-model F1, time, cost, batch_id
- `data/extraction_call_log.csv` — per-row call log

**Checkpoint state files** (do not commit):
- `data/.doubleword_checkpoints.json`, `data/.v7_checkpoints.json`
- `data/.doubleword_failed_rows.json`, `data/.v7_failed_rows.json`
- `data/.doubleword_unavailable_models.json`, `data/.v7_unavailable_models.json`

---

## Environment Variables (Quick Reference)

| Backend | Required Keys |
|---|---|
| OpenRouter | `OPENROUTER_API_KEY` |
| Doubleword | `DOUBLEWORD_API_KEY` |
| V7 Go | `V7_GO_API_KEY` (or `V7_API_KEY`), `V7_GO_WORKSPACE_ID`, `V7_GO_AGENT_ID` |

`SKIP_DOUBLEWORD_SYNC=1` must remain set. Full variable reference: **CLAUDE.md §Environment Variables**.

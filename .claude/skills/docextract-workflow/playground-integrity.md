# Playground integrity — detailed audit

Companion to the **Playground Data Integrity Gate** in `SKILL.md`.
Use this after every `python playground.py` (or when auditing existing HTML).

**Mandate:** check **every tab** for number correctness and table↔visual sync.
On any failure, **correct** `playground.py` (then regenerate HTML) — do not only report,
and never hand-edit the HTML to paper over drift.

## Design invariants (do not "fix")

`playground.py` intentionally embeds **two** scoring views:

| View | How computed | Used in |
|---|---|---|
| **Semantic F1** | `score.py` — exact IDs/dates, 0.5% numeric tolerance, SequenceMatcher for text | Rankings, Provider Analysis F1 columns/charts |
| **Exact-match** | Strict `==` of extracted TSV vs `playgroup_dev_expected.tsv` | Field Heatmap, Document Analysis, Errors, Deep Dive |

A model can have high F1 and lower exact-match %. That is correct. Do not change
scoring to force them equal. Do not edit HTML by hand.

## Source files

| File | Role |
|---|---|
| `data/playgroup_dev_expected.tsv` | Ground truth |
| `data/playgroup_dev_extracted__*.tsv` | Per-model extractions |
| `data/extraction_stats.csv` | Time, cost, tokens, fill counts |
| `data/extraction_call_log.csv` | Fallback when stats row lacks time/cost |
| `python score.py` | Authoritative F1 / Precision / Recall |
| `which-models-extracted-playground.html` | Generated; must be regenerated, not patched |

## Extract embedded `RAW` safely

Naive `re.search(r'\{.*?\}')` **breaks** on nested JSON. Always brace-match:

```python
from pathlib import Path
import json

html = Path("which-models-extracted-playground.html").read_text()
idx = html.find("const RAW = ")
i = html.find("{", idx)
depth = 0
for j, ch in enumerate(html[i:], start=i):
    if ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
        if depth == 0:
            raw = json.loads(html[i : j + 1])
            break
```

## All-tabs pair matrix (must stay in sync)

| Tab | Table / primary view | Chart / secondary | Shared data builder | Sync rules |
|---|---|---|---|---|
| Rankings | Model Leaderboard | F1 Score Overview | `rankRows()` → `renderRankingsViews()` | Same models, order, F1; filters refresh both; `autoSkip:false` + dynamic height |
| Field Heatmap | Field heatmap + Best Model per Field | Field Difficulty Ranking | Heatmap from filter; best/difficulty from `activeModels()` exact-match | Best/difficulty use functional models by design (labels say so); difficulty chart `autoSkip:false` |
| Document Analysis | Doc × model heatmap | Document Difficulty | Heatmap from filter; difficulty from `activeModels()` | Difficulty chart labels = docs ranked by avg exact-match; `autoSkip:false` |
| Errors | Error Category Breakdown table | Stacked share chart | `errorBreakdownRows()` → `renderErrorBreakdownViews()` | Same models, order, C/W/M %; `autoSkip:false` + dynamic height |
| Deep Dive | Per-doc field expected/got table | (none) | Selected model + doc index | Rows match expected + extracted TSV for that index |
| Recommendations | Decision Helper cards | Insights / Improvements | `RAW.f1_scores` + stats | Quoted F1/cost match Rankings sources |
| Provider Analysis | Cost efficiency + modality tables | Provider F1 + tier charts | Same `allProviders()` / `activeModels()` | Chart avg/best F1 match provider aggregates; small N (providers) |
| Evolution | Cost/speed table | Timeline narrative | `extraction_stats` | Table rows match CSV |

## Failure modes to hunt (and fix)

| Symptom | Likely cause | Corrective action in `playground.py` |
|---|---|---|
| Chart labels look like different models than the table | Chart.js `ticks.autoSkip` (default true) in a short fixed-height canvas | Shared `*Views()` helper; `sizeCategoryChartWrap`; `autoSkip: false` |
| After changing sort/filter, table updates but chart does not | `onchange` calls only the table renderer | Point controls at a shared `renderXViews()` that rebuilds both from one row array |
| Chart has far fewer/more bars than table rows | Separate model lists or different filters | One builder function; pass the same `rows` into both renderers |
| F1 in Rankings ≠ heatmap cell % | Comparing semantic F1 to exact-match (expected) | Do **not** equalize; document both. Only fix if Rankings F1 ≠ `score.py` or heatmap ≠ TSV exact-match |
| Provider avg F1 ≠ mean of active models | Aggregation bug or stale HTML | Fix aggregation; regenerate |

## Static scan (run before PASS)

```bash
python - <<'PY'
from pathlib import Path
src = Path("playground.py").read_text()
assert "sizeCategoryChartWrap" in src
assert "renderRankingsViews()" in src
assert "renderErrorBreakdownViews()" in src
assert "renderFieldTabViews()" in src
assert "renderDocTabViews()" in src
assert "providerAggRows()" in src
assert "fieldDifficultyRows()" in src
assert "docDifficultyRows()" in src
assert 'onchange="renderRankTable()"' not in src
assert 'onchange="renderFieldHeatmap()"' not in src
assert 'onchange="renderDocHeatmap()"' not in src
n_autoskip = src.count("autoSkip:false") + src.count("autoSkip: false")
assert n_autoskip >= 4, f"expected >=4 autoSkip:false, got {n_autoskip}"
print("PASS: playground.py all-tab chart sync guards present")
PY
```

## Per-tab checklist

Walk every tab. For each: table numbers ↔ adjacent chart/visual ↔ source of truth.
**If any box fails → fix `playground.py`, regenerate, re-check.**

### 1. Rankings

- [ ] Stat cards match `len(RAW.models)`, active count, providers, docs, fields
- [ ] Table F1 / Precision / Recall match `RAW.f1_scores` / `python score.py` for ≥3 models
- [ ] Chart bar *i* = table row *i* (model + F1×100)
- [ ] Sort / filter / provider call `renderRankingsViews()` (both sides)
- [ ] Time / cost match `extraction_stats.csv`

### 2. Field Heatmap

- [ ] Cell % = exact-match `correct/(correct+missing+wrong)` from `RAW.models[m].per_field`
- [ ] Spot-check one cell vs expected + extracted TSV
- [ ] Best-per-field table uses same exact-match rates as heatmap cells for functional models
- [ ] Field Difficulty chart: one bar per field, `autoSkip:false`, averages match functional-model heatmap columns

### 3. Document Analysis

- [ ] Heatmap cell = `RAW.models[m].per_doc[i].accuracy`
- [ ] Doc labels = `RAW.doc_names` order
- [ ] Document Difficulty chart order/values = avg exact-match across functional models; `autoSkip:false`

### 4. Errors

- [ ] Table Correct/Wrong/Missing % derived from exact-match per-field counts
- [ ] Chart label *i* and stacked % = table row *i* (`errorBreakdownRows` / `renderErrorBreakdownViews`)
- [ ] Do not compare these rates to Rankings F1

### 5. Deep Dive

- [ ] expected/got/status match TSV pair for selected model + doc index
- [ ] Summary % is exact-match, consistent with Heatmap for that model

### 6. Recommendations

- [ ] Quoted F1 / cost from `RAW.f1_scores` / `extraction_stats`
- [ ] No recommendations for models absent from TSVs and stats

### 7. Provider Analysis

- [ ] Active = F1 > 0; Failed = all − active
- [ ] Avg / best F1 = mean / max of that provider’s active `RAW.f1_scores`
- [ ] Cost-efficiency table F1 and cost from same RAW entries
- [ ] Provider F1 chart matches those aggregates

### 8. Evolution

- [ ] Cost / speed table matches `extraction_stats.csv`
- [ ] Narrative counts do not contradict Rankings provider totals

## Cross-checks that catch regressions

```bash
# A. Model set: every extracted TSV should appear in RAW.models (after provider__ strip)
python - <<'PY'
import json
from pathlib import Path

html = Path("which-models-extracted-playground.html").read_text()
idx = html.find("const RAW = ")
i = html.find("{", idx)
depth = 0
for j, ch in enumerate(html[i:], start=i):
    if ch == "{": depth += 1
    elif ch == "}":
        depth -= 1
        if depth == 0:
            raw = json.loads(html[i:j+1]); break

def model_from_tsv(p: Path) -> str:
    after = p.stem.replace("playgroup_dev_extracted__", "", 1)
    return after.split("__", 1)[1] if "__" in after else after

tsv_models = {model_from_tsv(p) for p in Path("data").glob("playgroup_dev_extracted__*.tsv")}
raw_models = set(raw["models"])
missing = sorted(tsv_models - raw_models)
print("tsv", len(tsv_models), "raw.models", len(raw_models))
assert not missing, f"FAIL: TSV models missing from playground RAW.models: {missing[:20]}"
print("PASS: all extraction TSVs present in RAW.models")
PY
```

```bash
# B. F1 parity for all models present in both score.py and RAW
python - <<'PY'
import json
from pathlib import Path
from score import score_all_models

html = Path("which-models-extracted-playground.html").read_text()
idx = html.find("const RAW = ")
i = html.find("{", idx)
depth = 0
for j, ch in enumerate(html[i:], start=i):
    if ch == "{": depth += 1
    elif ch == "}":
        depth -= 1
        if depth == 0:
            raw = json.loads(html[i:j+1]); break

scored = {r["model_name"]: r for r in score_all_models("data/playgroup_dev_expected.tsv", verbose=False)}
mismatches = []
for name, emb in raw["f1_scores"].items():
    if name not in scored:
        continue
    if abs(emb["f1"] - scored[name]["f1"]) > 1e-9:
        mismatches.append((name, emb["f1"], scored[name]["f1"]))
print("compared", len(raw["f1_scores"]), "mismatches", len(mismatches))
assert not mismatches, f"FAIL: embedded F1 != score.py: {mismatches[:5]}"
print("PASS: all embedded F1 values match score.py")
PY
```

```bash
# C. Generated HTML still has paired-view helpers (post-regenerate)
rg -n "renderRankingsViews|renderErrorBreakdownViews|autoSkip:false|sizeCategoryChartWrap" which-models-extracted-playground.html | head -20
```

## Repair path

1. Prefer `python playground.py` after confirming CSV/TSV/`score.py` are correct.
2. If regenerate still wrong → fix `playground.py` (shared row builders, control wiring,
   Chart.js `autoSkip` / height), then regenerate.
3. Never commit a hand-patched `which-models-extracted-playground.html` that disagrees with sources.
4. Re-run static scan + cross-checks + per-tab checklist until PASS.

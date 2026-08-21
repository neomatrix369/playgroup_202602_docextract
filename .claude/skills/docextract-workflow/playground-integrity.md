# Playground integrity — detailed audit

Companion to the **Playground Data Integrity Gate** in `SKILL.md`.
Use this after every `python playground.py` (or when auditing existing HTML).

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

## Per-tab checklist

Walk every tab. For each: table numbers ↔ adjacent chart/visual ↔ source of truth.

### 1. Rankings

- [ ] Stat cards (model count, docs, fields) match `len(RAW.models)`, `RAW.doc_names`, `RAW.fields`
- [ ] Table F1 / Precision / Recall match `RAW.f1_scores` and `python score.py` for ≥3 models (top, mid, a `dw-*` / `v7-*`)
- [ ] Horizontal bar chart values = same F1 × 100 as the table for the same filtered/sorted set
- [ ] Time / cost columns match `RAW.extraction_stats` → `extraction_stats.csv` (respect `~` estimated flag)
- [ ] Provider / tier filters update **both** table and chart together

### 2. Field Heatmap

- [ ] Cell percentages = exact-match `correct / (correct+missing+wrong)` from `RAW.models[m].per_field`
- [ ] Spot-check one cell against expected + extracted TSV for that model/field (exact string compare)
- [ ] “Best model / runner-up” table uses the same per-field exact-match rates as the heatmap
- [ ] Field-average chart (if present) averages the same per-field rates shown in the table

### 3. Document Analysis

- [ ] Per-document accuracy = `RAW.models[m].per_doc[i].accuracy`
- [ ] Doc labels match `RAW.doc_names` order (same index as expected TSV rows)
- [ ] Chart and table agree for the selected model

### 4. Errors

- [ ] Missing / wrong counts sum from `RAW.models[*].per_field` (exact-match statuses)
- [ ] Error breakdown chart and table use the same aggregated counts
- [ ] Do not compare these rates to Rankings F1

### 5. Deep Dive

- [ ] Selected model’s field-level expected/got/status match the TSV pair for that doc index
- [ ] Any summary % shown here is exact-match, consistent with Heatmap for that model

### 6. Recommendations

- [ ] Suggested models’ F1 / cost figures come from the same `RAW.f1_scores` / `extraction_stats` as Rankings
- [ ] No orphan recommendations for models absent from both TSVs and stats

### 7. Provider Analysis

- [ ] Active = F1 > 0; Failed = all − active (same definition as Rankings notes)
- [ ] Avg / best F1 match mean / max of `RAW.f1_scores` for that provider’s models
- [ ] Avg time / cost match means over active models with positive values in `extraction_stats`
- [ ] Provider F1 chart and summary table stay in sync under the same provider set
- [ ] Cost-efficiency table uses F1 and cost from the same RAW entries (no mixed units)

### 8. Evolution

- [ ] Cost / speed table rows match `extraction_stats.csv` for listed models
- [ ] Narrative counts (if any) do not contradict Rankings provider totals

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
extra = sorted(raw_models - tsv_models)
print("tsv", len(tsv_models), "raw.models", len(raw_models))
print("missing from HTML:", missing[:20], ("..." if len(missing)>20 else ""))
print("in HTML but no TSV:", extra[:20], ("..." if len(extra)>20 else ""))
assert not missing, "FAIL: TSV models missing from playground RAW.models"
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
for row in mismatches[:10]:
    print(" ", row)
assert not mismatches, "FAIL: embedded F1 != score.py"
print("PASS: all embedded F1 values match score.py")
PY
```

## Repair path

1. Prefer `python playground.py` after confirming CSV/TSV/`score.py` are correct.
2. If regenerate still wrong → fix `playground.py` (data load or JS render), then regenerate.
3. Never commit a hand-patched `which-models-extracted-playground.html` that disagrees with sources.
4. Re-run this checklist + the SKILL.md minimum verification until PASS.

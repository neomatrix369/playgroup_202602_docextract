#!/usr/bin/env python3
"""
playground.py — Generate an interactive HTML analysis playground for model extraction results.

Usage: uv run python playground.py
Output: playground.html  (open in any browser, fully self-contained)
"""

import csv
import json
from pathlib import Path
from utils import get_logger

log = get_logger("playground")

DATA_DIR = Path("data")
EXPECTED_FILE = DATA_DIR / "playgroup_dev_expected.tsv"
OUTPUT_FILE = Path("which-models-extracted-playground.html")

FIELDS = [
    "charity_number",
    "charity_name",
    "report_date",
    "income_annually_in_british_pounds",
    "spending_annually_in_british_pounds",
    "address__postcode",
    "address__post_town",
    "address__street_line",
]

FIELD_LABELS = {
    "charity_number": "Charity No.",
    "charity_name": "Charity Name",
    "report_date": "Report Date",
    "income_annually_in_british_pounds": "Income (£)",
    "spending_annually_in_british_pounds": "Spending (£)",
    "address__postcode": "Postcode",
    "address__post_town": "Post Town",
    "address__street_line": "Street Line",
}

FIELD_GROUPS = {
    "identity": ["charity_number", "charity_name", "report_date"],
    "financial": ["income_annually_in_british_pounds", "spending_annually_in_british_pounds"],
    "address": ["address__postcode", "address__post_town", "address__street_line"],
}


def load_model_meta() -> dict:
    """Read tier, pricing and modality info from all model configs."""
    try:
        from config_models_openrouter import OPENROUTER_MODELS
        from config_models_doubleword import DOUBLEWORD_MODELS
    except ImportError:
        return {}
    all_models = {**OPENROUTER_MODELS, **DOUBLEWORD_MODELS}
    meta = {}
    for short_name, cfg in all_models.items():
        if not isinstance(cfg, dict):
            continue
        raw_tier = cfg.get("tier", "unknown")
        # normalise underscore tiers → hyphen for display consistency
        tier = raw_tier.replace("_", "-")
        meta[short_name] = {
            "tier":       tier,
            "price_in":   cfg.get("price_in"),
            "price_out":  cfg.get("price_out"),
            "multimodal": cfg.get("multimodal", False),
            "modalities": cfg.get("modalities", []),
            "ctx":        cfg.get("ctx"),
            "notes":      cfg.get("notes", ""),
        }
    return meta


def load_extraction_stats() -> dict:
    """Load time/cost/token data using same 3-tier logic as score.py _load_stats().

    Priority:
    1. extraction_stats.csv (has totals directly)
    2. extraction_call_log.csv (aggregate per-row entries)
    3. config pricing x avg tokens (estimate, marked with estimated=true)
    """
    stats = {}
    field_names = [
        "charity_number", "charity_name", "report_date",
        "income_annually_in_british_pounds", "spending_annually_in_british_pounds",
        "address__postcode", "address__post_town", "address__street_line",
    ]

    # 1. Primary: stats CSV
    stats_file = DATA_DIR / "extraction_stats.csv"
    if stats_file.exists():
        with open(stats_file) as f:
            for row in csv.DictReader(f):
                name = row.get("model_short_name", "")
                if not name:
                    continue
                elapsed = float(row.get("total_elapsed_secs", 0))
                cost = float(row.get("total_cost_usd", 0))
                total = int(row.get("total", 0))
                rows_with = int(row.get("rows_with_values", 0))
                rows_empty = int(row.get("rows_empty", 0))
                field_counts = {f: int(row.get(f, 0)) for f in field_names}
                stats[name] = {
                    "total_elapsed_secs": elapsed,
                    "total_cost_usd": cost,
                    "total_prompt_tokens": int(row.get("total_prompt_tokens", 0)),
                    "total_completion_tokens": int(row.get("total_completion_tokens", 0)),
                    "rows_with_values": rows_with,
                    "rows_empty": rows_empty,
                    "total_rows": total or (rows_with + rows_empty),
                    "avg_secs_per_row": float(row.get("avg_secs_per_row", 0)),
                    "avg_cost_per_row": float(row.get("avg_cost_per_row", 0)),
                    "field_counts": field_counts,
                    "estimated": False,
                }
                # Only keep elapsed/cost if non-zero (for estimation fallback)
                if not elapsed and not cost:
                    stats[name]["estimated"] = True

    # 2. Fallback: aggregate from call log
    call_log_file = DATA_DIR / "extraction_call_log.csv"
    if call_log_file.exists():
        with open(call_log_file) as f:
            agg: dict[str, dict] = {}
            for row in csv.DictReader(f):
                name = row.get("model_short_name", "")
                if not name or name in stats or row.get("status") == "error":
                    continue
                if name not in agg:
                    agg[name] = {"elapsed": 0.0, "prompt": 0, "completion": 0, "cost": 0.0, "rows": 0}
                agg[name]["elapsed"] += float(row.get("elapsed_secs", 0))
                agg[name]["prompt"] += int(row.get("prompt_tokens", 0))
                agg[name]["completion"] += int(row.get("completion_tokens", 0))
                agg[name]["cost"] += float(row.get("cost_usd", 0))
                agg[name]["rows"] += 1
            for name, a in agg.items():
                if a["elapsed"] or a["cost"]:
                    n = max(a["rows"], 1)
                    stats[name] = {
                        "total_elapsed_secs": a["elapsed"],
                        "total_cost_usd": a["cost"],
                        "total_prompt_tokens": a["prompt"],
                        "total_completion_tokens": a["completion"],
                        "rows_with_values": a["rows"],
                        "rows_empty": 0,
                        "total_rows": a["rows"],
                        "avg_secs_per_row": a["elapsed"] / n,
                        "avg_cost_per_row": a["cost"] / n,
                        "field_counts": {},
                        "estimated": False,
                    }

    # 3. Estimate for remaining models using config pricing x avg tokens
    known_elapsed = [s["total_elapsed_secs"] for s in stats.values() if s["total_elapsed_secs"] > 0]
    if known_elapsed:
        avg_elapsed = sum(known_elapsed) / len(known_elapsed)
        avg_prompt = 180_000   # typical total prompt tokens across 11 rows
        avg_completion = 1_500
        try:
            from config_models_openrouter import OPENROUTER_MODELS
            from config_models_doubleword import DOUBLEWORD_MODELS
            all_models = {**OPENROUTER_MODELS, **DOUBLEWORD_MODELS}
        except ImportError:
            all_models = {}
        for model_name, cfg in all_models.items():
            if model_name not in stats:
                price_in = cfg.get("price_in", 0)
                price_out = cfg.get("price_out", 0)
                est_cost = (avg_prompt * price_in + avg_completion * price_out) / 1_000_000
                if est_cost > 0:
                    n = 11  # expected rows
                    stats[model_name] = {
                        "total_elapsed_secs": avg_elapsed,
                        "total_cost_usd": est_cost,
                        "total_prompt_tokens": avg_prompt,
                        "total_completion_tokens": avg_completion,
                        "rows_with_values": 0,
                        "rows_empty": 0,
                        "total_rows": 0,
                        "avg_secs_per_row": avg_elapsed / n,
                        "avg_cost_per_row": est_cost / n,
                        "field_counts": {},
                        "estimated": True,
                    }

    return stats


# ── Parsing ──────────────────────────────────────────────────────────────────

def _parse_kv_parts(parts: list[str], target: dict) -> None:
    for part in parts:
        if "=" in part:
            key, _, val = part.partition("=")
            target[key.strip()] = val.strip()


def parse_tsv(filepath: Path) -> list[dict]:
    """Parse extracted TSV, handling:
    - Blank lines  → empty document row {} (model skipped that doc)
    - Error lines  → {'__error__': True}
    - Continuation → first token has no '=', merged into previous row
    - Normal lines → new document row
    """
    rows = []
    pending: dict | None = None
    try:
        lines = filepath.read_text(encoding="utf-8").split("\n")
        # strip trailing blank lines so they don't create phantom empty rows
        while lines and not lines[-1].strip():
            lines.pop()

        for raw in lines:
            line = raw.strip()

            if not line:
                # blank = explicitly skipped document
                if pending is not None:
                    rows.append(pending)
                    pending = None
                rows.append({})
                continue

            parts = line.split("\t")
            first = parts[0]

            if first.startswith("error="):
                if pending is not None:
                    rows.append(pending)
                    pending = None
                rows.append({"__error__": True})
                continue

            if "=" not in first:
                # continuation line (model put a newline inside a field value)
                if pending is not None:
                    _parse_kv_parts(parts, pending)
                continue

            # new document row
            if pending is not None:
                rows.append(pending)
            pending = {}
            _parse_kv_parts(parts, pending)

    except Exception:
        pass

    if pending is not None:
        rows.append(pending)
    return rows


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_model(expected_rows: list, extracted_rows: list) -> dict:
    per_field = {f: {"correct": 0, "missing": 0, "wrong": 0} for f in FIELDS}
    per_doc = []
    total_correct = 0
    total_expected = 0

    for row_idx, expected_row in enumerate(expected_rows):
        extracted_row = extracted_rows[row_idx] if row_idx < len(extracted_rows) else {}
        is_error = bool(extracted_row.get("__error__"))

        doc = {"correct": 0, "total": 0, "accuracy": 0.0, "is_error": is_error, "fields": {}}

        for field, expected_val in expected_row.items():
            if field.startswith("__"):
                continue
            doc["total"] += 1
            total_expected += 1

            if is_error or field not in extracted_row:
                per_field.setdefault(field, {"correct": 0, "missing": 0, "wrong": 0})["missing"] += 1
                doc["fields"][field] = {"expected": expected_val, "got": None, "status": "missing"}
            elif extracted_row[field] == expected_val:
                per_field.setdefault(field, {"correct": 0, "missing": 0, "wrong": 0})["correct"] += 1
                doc["correct"] += 1
                total_correct += 1
                doc["fields"][field] = {"expected": expected_val, "got": extracted_row[field], "status": "correct"}
            else:
                per_field.setdefault(field, {"correct": 0, "missing": 0, "wrong": 0})["wrong"] += 1
                doc["fields"][field] = {"expected": expected_val, "got": extracted_row[field], "status": "wrong"}

        doc["accuracy"] = doc["correct"] / doc["total"] if doc["total"] > 0 else 0.0
        per_doc.append(doc)

    return {
        "total_correct": total_correct,
        "total_expected": total_expected,
        "accuracy": total_correct / total_expected if total_expected > 0 else 0.0,
        "per_field": per_field,
        "per_doc": per_doc,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    expected_rows = parse_tsv(EXPECTED_FILE)

    doc_names = []
    for i, row in enumerate(expected_rows):
        name = row.get("charity_name", f"Document {i + 1}").replace("_", " ")
        doc_names.append(name)

    model_meta = load_model_meta()
    extraction_stats = load_extraction_stats()
    models_data = {}
    model_providers = {}
    for model_file in sorted(DATA_DIR.glob("playgroup_dev_extracted__*.tsv")):
        after_prefix = model_file.stem.replace("playgroup_dev_extracted__", "")
        # New format: {provider}__{model} or legacy: {model}
        if "__" in after_prefix:
            provider, model_name = after_prefix.split("__", 1)
        else:
            provider, model_name = "openrouter", after_prefix
        extracted_rows = parse_tsv(model_file)
        scores = score_model(expected_rows, extracted_rows)
        models_data[model_name] = scores
        model_providers[model_name] = provider
        mm_tag = "MM" if model_meta.get(model_name, {}).get("multimodal") else "text"
        log.info("  [{}] {}  {}  {:.1f}%  ({}/{})",
                 provider, f"{model_name:35s}", f"{mm_tag:<6}",
                 scores['accuracy'] * 100, scores['total_correct'], scores['total_expected'])

    # F1/Precision/Recall from score.py (semantic scoring)
    from score import score_all_models as _score_all
    f1_results = _score_all(str(EXPECTED_FILE), verbose=False)
    f1_data = {}
    for r in f1_results:
        f1_data[r["model_name"]] = {
            "f1": r["f1"], "precision": r["precision"], "recall": r["recall"],
            "fields_found": r["fields_found"], "fields_total": r["fields_total"],
        }

    payload = {
        "models": models_data,
        "f1_scores": f1_data,
        "fields": FIELDS,
        "field_labels": FIELD_LABELS,
        "field_groups": FIELD_GROUPS,
        "model_meta": model_meta,
        "model_providers": model_providers,
        "extraction_stats": extraction_stats,
        "doc_names": doc_names,
        "expected": expected_rows,
    }

    html = HTML_TEMPLATE.replace("/*__DATA__*/null", json.dumps(payload))
    OUTPUT_FILE.write_text(html)
    log.info("Wrote {}  —  open in your browser", OUTPUT_FILE)


# ── HTML Template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Model Extraction Playground</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#f8fafc;--surface:#fff;--surface2:#f1f5f9;--border:#e2e8f0;
  --text:#0f172a;--muted:#64748b;--accent:#6366f1;
  --green:#10b981;--yellow:#f59e0b;--orange:#f97316;--red:#ef4444;--blue:#3b82f6;
  --correct:#10b981;--wrong:#f97316;--missing:#ef4444;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5}
header{background:var(--accent);color:#fff;padding:18px 28px}
header h1{font-size:22px;font-weight:700}
header p{font-size:13px;opacity:.85;margin-top:2px}
.tabs{display:flex;gap:2px;background:var(--surface2);padding:8px 28px 0;border-bottom:1px solid var(--border);overflow-x:auto}
.tab-btn{padding:8px 16px;border:none;background:transparent;cursor:pointer;font-size:13px;font-weight:500;color:var(--muted);border-radius:6px 6px 0 0;white-space:nowrap;transition:all .15s}
.tab-btn.active{background:var(--surface);color:var(--accent);border-bottom:2px solid var(--accent);margin-bottom:-1px}
.tab-btn:hover:not(.active){background:var(--surface);color:var(--text)}
.tab-panel{display:none;padding:24px 28px}
.tab-panel.active{display:block}
.stats-bar{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 20px;min-width:140px}
.stat-card .val{font-size:26px;font-weight:700;color:var(--accent)}
.stat-card .lbl{font-size:12px;color:var(--muted);margin-top:2px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:20px}
.card h2{font-size:15px;font-weight:600;margin-bottom:14px;color:var(--text)}
.card h3{font-size:13px;font-weight:600;margin-bottom:10px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 10px;background:var(--surface2);border-bottom:1px solid var(--border);font-weight:600;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--surface2)}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
.badge-green{background:#dcfce7;color:#166534}
.badge-blue{background:#dbeafe;color:#1e40af}
.badge-yellow{background:#fef9c3;color:#854d0e}
.badge-orange{background:#ffedd5;color:#9a3412}
.badge-red{background:#fee2e2;color:#991b1b}
.badge-gray{background:#f1f5f9;color:#475569}
.heatmap{overflow-x:auto}
.heatmap table td,.heatmap table th{padding:5px 6px;text-align:center;font-size:12px;white-space:nowrap}
.heatmap table th{font-size:11px;background:var(--surface2)}
.hm-cell{border-radius:4px;width:48px;height:28px;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:11px;color:#fff;cursor:default}
.chart-wrap{position:relative;height:340px}
.chart-wrap-lg{position:relative;height:460px}
.chart-wrap-sm{position:relative;height:240px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:768px){.two-col{grid-template-columns:1fr}}
select,button.ctrl{padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--surface);font-size:13px;cursor:pointer}
.ctrl-row{display:flex;gap:10px;align-items:center;margin-bottom:16px;flex-wrap:wrap}
.diff-table td{font-family:monospace;font-size:12px}
.diff-correct{background:#dcfce7}
.diff-wrong{background:#ffedd5}
.diff-missing{background:#fee2e2}
.insight{background:var(--surface2);border-left:3px solid var(--accent);padding:10px 14px;border-radius:0 6px 6px 0;margin-bottom:10px;font-size:13px}
.insight strong{color:var(--accent)}
.insight-warn{border-color:var(--orange)}
.insight-warn strong{color:var(--orange)}
.insight-tip{border-color:var(--green)}
.insight-tip strong{color:var(--green)}
.rank-bar-wrap{background:var(--surface2);border-radius:4px;height:18px;overflow:hidden;min-width:120px}
.rank-bar{height:100%;border-radius:4px;transition:width .4s ease}
.sort-btn{background:none;border:none;cursor:pointer;font-size:12px;color:var(--muted);padding:0 4px}
.sort-btn.asc::after{content:" ▲"}
.sort-btn.desc::after{content:" ▼"}
.legend{display:flex;gap:14px;margin-bottom:12px;flex-wrap:wrap}
.legend-item{display:flex;align-items:center;gap:5px;font-size:12px}
.legend-dot{width:12px;height:12px;border-radius:50%}
</style>
</head>
<body>

<header>
  <h1>Model Extraction Playground</h1>
  <p>Interactive analysis of LLM performance on charity document data extraction</p>
</header>

<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('rankings')">Rankings</button>
  <button class="tab-btn" onclick="switchTab('field-heatmap')">Field Heatmap</button>
  <button class="tab-btn" onclick="switchTab('doc-analysis')">Document Analysis</button>
  <button class="tab-btn" onclick="switchTab('errors')">Error Breakdown</button>
  <button class="tab-btn" onclick="switchTab('deepdive')">Deep Dive</button>
  <button class="tab-btn" onclick="switchTab('recommendations')">Recommendations</button>
  <button class="tab-btn" onclick="switchTab('provider-analysis')">Provider Analysis</button>
  <button class="tab-btn" onclick="switchTab('evolution')">Project Evolution</button>
</div>

<!-- ═══════════════════════════════ RANKINGS ═══════════════════════════════ -->
<div id="tab-rankings" class="tab-panel active">
  <div class="stats-bar" id="stats-bar"></div>
  <div class="two-col">
    <div class="card" style="min-width:0">
      <h2>Model Leaderboard</h2>
      <div class="ctrl-row">
        <label>Sort by:
          <select id="rank-sort" onchange="renderRankTable()">
            <option value="f1">F1 Score</option>
            <option value="accuracy">Exact-Match Accuracy</option>
            <option value="correct">Correct Extractions</option>
            <option value="wrong">Wrong (fewest)</option>
            <option value="missing">Missing (fewest)</option>
          </select>
        </label>
        <label>Filter:
          <select id="rank-filter" onchange="renderRankTable()">
            <option value="all">All Models</option>
            <option value="active">Functional Only</option>
            <option value="free">Free tier only</option>
            <option value="ultra-cheap">≤ Ultra-cheap</option>
            <option value="great-value">≤ Great Value</option>
          </select>
        </label>
        <label>Provider:
          <select id="rank-provider" onchange="renderRankTable()">
            <option value="all">All Providers</option>
          </select>
        </label>
      </div>
      <div id="rank-table-wrap" style="overflow-x:auto"></div>
    </div>
    <div class="card" style="min-width:0">
      <h2>F1 Score Overview</h2>
      <div class="chart-wrap"><canvas id="chart-accuracy"></canvas></div>
    </div>
  </div>
  <div class="card">
    <h2>Provider Summary</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">Aggregated stats per provider (active models only, F1 &gt; 0). Fields and cost are averages per model.</p>
    <div id="provider-summary" style="overflow-x:auto"></div>
    <div id="provider-notes" style="margin-top:10px"></div>
  </div>
  <div class="card">
    <h2>Scoring Methodology</h2>
    <div id="scoring-notes"></div>
  </div>
</div>

<!-- ════════════════════════════ FIELD HEATMAP ════════════════════════════ -->
<div id="tab-field-heatmap" class="tab-panel">
  <div class="card">
    <h2>Field-Level Accuracy Heatmap</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:14px">Each cell shows how accurately a model extracted that field across all 11 documents. Click a cell for details.</p>
    <div class="ctrl-row">
      <label>Show:
        <select id="hm-filter" onchange="renderFieldHeatmap()">
          <option value="all">All models</option>
          <option value="active">Functional only</option>
        </select>
      </label>
    </div>
    <div class="heatmap" id="field-heatmap"></div>
  </div>
  <div class="two-col">
    <div class="card">
      <h2>Best Model per Field</h2>
      <div id="best-per-field"></div>
    </div>
    <div class="card">
      <h2>Field Difficulty Ranking</h2>
      <p style="font-size:12px;color:var(--muted);margin-bottom:12px">Average accuracy across all functional models</p>
      <div class="chart-wrap-sm"><canvas id="chart-field-diff"></canvas></div>
    </div>
  </div>
</div>

<!-- ══════════════════════════ DOCUMENT ANALYSIS ══════════════════════════ -->
<div id="tab-doc-analysis" class="tab-panel">
  <div class="card">
    <h2>Document × Model Accuracy Heatmap</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:14px">Each cell shows accuracy for a specific document/model pair.</p>
    <div class="ctrl-row">
      <label>Models:
        <select id="doc-hm-filter" onchange="renderDocHeatmap()">
          <option value="active">Functional only</option>
          <option value="all">All</option>
        </select>
      </label>
    </div>
    <div class="heatmap" id="doc-heatmap"></div>
  </div>
  <div class="card">
    <h2>Document Difficulty (avg accuracy across functional models)</h2>
    <div class="chart-wrap-sm"><canvas id="chart-doc-diff"></canvas></div>
  </div>
</div>

<!-- ══════════════════════════ ERROR BREAKDOWN ════════════════════════════ -->
<div id="tab-errors" class="tab-panel">
  <div class="card">
    <h2>Error Category Breakdown per Model</h2>
    <div class="legend">
      <div class="legend-item"><div class="legend-dot" style="background:var(--correct)"></div>Correct</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--wrong)"></div>Wrong value</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--missing)"></div>Missing</div>
    </div>
    <div class="chart-wrap-lg"><canvas id="chart-errors"></canvas></div>
  </div>
  <div class="card">
    <h2>Common Error Patterns</h2>
    <div id="error-patterns"></div>
  </div>
</div>

<!-- ═════════════════════════════ DEEP DIVE ═══════════════════════════════ -->
<div id="tab-deepdive" class="tab-panel">
  <div class="card">
    <h2>Per-Document Field Comparison</h2>
    <div class="ctrl-row">
      <label>Model:
        <select id="dd-model" onchange="renderDeepDive()"></select>
      </label>
      <label>Document:
        <select id="dd-doc" onchange="renderDeepDive()"></select>
      </label>
    </div>
    <div id="dd-output"></div>
  </div>
</div>

<!-- ══════════════════════════ RECOMMENDATIONS ════════════════════════════ -->
<div id="tab-recommendations" class="tab-panel">
  <div class="card">
    <h2>Decision Helper</h2>
    <div class="ctrl-row">
      <label>Use case:
        <select id="rec-usecase" onchange="renderRecommendations()">
          <option value="all">All fields — full extraction</option>
          <option value="identity">Identity fields only (number, name, date)</option>
          <option value="financial">Financial fields only (income, spending)</option>
          <option value="address">Address fields only (postcode, town, street)</option>
        </select>
      </label>
      <label>Budget:
        <select id="rec-budget" onchange="renderRecommendations()">
          <option value="any">Any cost</option>
          <option value="free">Free only</option>
          <option value="ultra-cheap">≤ Ultra-cheap</option>
          <option value="great-value">≤ Great Value</option>
          <option value="premium">All (incl. Premium)</option>
        </select>
      </label>
    </div>
    <div id="rec-output"></div>
  </div>
  <div class="card">
    <h2>Key Insights</h2>
    <div id="insights"></div>
  </div>
  <div class="card">
    <h2>Improvement Suggestions</h2>
    <div id="improvements"></div>
  </div>
</div>

<!-- ═════════════════════════ PROVIDER ANALYSIS ═════════════════════════ -->
<div id="tab-provider-analysis" class="tab-panel">
  <div class="stats-bar" id="provider-stats-bar"></div>
  <div class="two-col">
    <div class="card">
      <h2>Provider Comparison</h2>
      <p style="font-size:12px;color:var(--muted);margin-bottom:12px">Side-by-side comparison across all providers (active models only).</p>
      <div class="chart-wrap"><canvas id="chart-provider-f1"></canvas></div>
    </div>
    <div class="card">
      <h2>Tier Distribution by Provider</h2>
      <p style="font-size:12px;color:var(--muted);margin-bottom:12px">How models are distributed across pricing tiers per provider.</p>
      <div class="chart-wrap"><canvas id="chart-provider-tiers"></canvas></div>
    </div>
  </div>
  <div class="two-col">
    <div class="card">
      <h2>Cost Efficiency (F1 per $)</h2>
      <p style="font-size:12px;color:var(--muted);margin-bottom:12px">Higher is better — F1 score achieved per dollar spent (active models with cost data).</p>
      <div id="cost-efficiency-table" style="overflow-x:auto"></div>
    </div>
    <div class="card">
      <h2>Modality Breakdown</h2>
      <p style="font-size:12px;color:var(--muted);margin-bottom:12px">Text-only vs multimodal model distribution and performance per provider.</p>
      <div id="modality-breakdown" style="overflow-x:auto"></div>
    </div>
  </div>
  <div class="card">
    <h2>Model Catalog</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">All configured models with capabilities, pricing, and performance. Filter by provider.</p>
    <div class="ctrl-row">
      <label>Provider:
        <select id="catalog-provider" onchange="renderModelCatalog()">
          <option value="all">All Providers</option>
        </select>
      </label>
      <label>Status:
        <select id="catalog-status" onchange="renderModelCatalog()">
          <option value="all">All</option>
          <option value="active">Active Only</option>
          <option value="failed">Failed Only</option>
        </select>
      </label>
    </div>
    <div id="model-catalog" style="overflow-x:auto"></div>
  </div>
</div>

<!-- ══════════════════════════ PROJECT EVOLUTION ════════════════════════════ -->
<div id="tab-evolution" class="tab-panel">
  <div class="card">
    <h2>Project Evolution Timeline</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:16px">How this extraction benchmark evolved — from raw data preparation to a multi-provider, multi-model scored leaderboard.</p>
    <div id="evolution-timeline"></div>
  </div>
  <div class="two-col">
    <div class="card">
      <h2>Numbers at a Glance</h2>
      <div id="evolution-stats"></div>
    </div>
    <div class="card">
      <h2>Cost & Speed Summary</h2>
      <p style="font-size:12px;color:var(--muted);margin-bottom:12px">From extraction_stats.csv — actual observed time and cost per model (where available).</p>
      <div id="cost-speed-table" style="overflow-x:auto"></div>
    </div>
  </div>
</div>

<script>
const RAW = /*__DATA__*/null;

// ── Helpers ───────────────────────────────────────────────────────────────

function pct(n){ return (n*100).toFixed(1)+'%' }
function hsl(v){ // 0→red, 0.5→yellow, 1→green
  const h = v < 0.5 ? v*120 : 60 + (v-0.5)*120;
  return `hsl(${h.toFixed(0)},70%,42%)`
}
function bgAlpha(v){ // for cell backgrounds
  const h = v < 0.5 ? v*120 : 60 + (v-0.5)*120;
  return `hsla(${h.toFixed(0)},70%,42%,${(0.15 + v*0.75).toFixed(2)})`
}
function tier(v){
  if(v>=0.8) return {cls:'badge-green',label:'Excellent'}
  if(v>=0.6) return {cls:'badge-blue',label:'Good'}
  if(v>=0.4) return {cls:'badge-yellow',label:'Fair'}
  if(v>=0.1) return {cls:'badge-orange',label:'Poor'}
  return {cls:'badge-red',label:'Failed'}
}
function isActive(m){
  return RAW.models[m].accuracy > 0
}
function activeModels(){
  return Object.keys(RAW.models).filter(isActive)
}
function allModels(){
  return Object.keys(RAW.models)
}
const TIER_ORDER = ['free','ultra-cheap','great-value','premium']
function tierLabel(t){
  return {'free':'Free','ultra-cheap':'Ultra-cheap','great-value':'Great Value','premium':'Premium'}[t]||t
}
function tierBadgeCls(t){
  return {'free':'badge-gray','ultra-cheap':'badge-blue','great-value':'badge-green','premium':'badge-yellow'}[t]||'badge-gray'
}
function costTierBadge(m){
  const t = RAW.model_meta?.[m]?.tier || 'unknown'
  return `<span class="badge ${tierBadgeCls(t)}">${tierLabel(t)}</span>`
}
function providerLabel(m){
  const p = RAW.model_providers?.[m] || 'unknown'
  return p.charAt(0).toUpperCase() + p.slice(1)
}
function providerBadge(m){
  const p = RAW.model_providers?.[m] || 'unknown'
  const cls = {'openrouter':'badge-blue','doubleword':'badge-yellow'}[p]||'badge-gray'
  const label = p.charAt(0).toUpperCase() + p.slice(1)
  return `<span class="badge ${cls}">${label}</span>`
}
function allProviders(){
  return [...new Set(Object.values(RAW.model_providers||{}))]
}

// ── Tab switching ─────────────────────────────────────────────────────────

const initialized = new Set()
function switchTab(id){
  document.querySelectorAll('.tab-btn').forEach((b,i)=>{
    b.classList.toggle('active', b.getAttribute('onclick').includes("'"+id+"'"))
  })
  document.querySelectorAll('.tab-panel').forEach(p=>{
    p.classList.toggle('active', p.id === 'tab-'+id)
  })
  if(!initialized.has(id)){
    initialized.add(id)
    if(id==='rankings') renderRankings()
    if(id==='field-heatmap') renderFieldHeatmap(), renderBestPerField(), renderFieldDifficulty()
    if(id==='doc-analysis') renderDocHeatmap(), renderDocDifficulty()
    if(id==='errors') renderErrorChart(), renderErrorPatterns()
    if(id==='deepdive') initDeepDive()
    if(id==='recommendations') renderRecommendations(), renderInsights(), renderImprovements()
    if(id==='provider-analysis') renderProviderAnalysis()
    if(id==='evolution') renderEvolution()
  }
}

// ── ① Rankings ────────────────────────────────────────────────────────────

let chartAccuracy = null

function f1Score(m){ return RAW.f1_scores?.[m]?.f1 || 0 }
function bestF1(){
  return activeModels().reduce((best,m)=>Math.max(best, f1Score(m)), 0)
}

function renderRankings(){
  // Stats bar
  const mods = allModels()
  const active = activeModels()
  const providers = allProviders()
  const topF1 = bestF1()
  const topModel = active.reduce((best,m)=>f1Score(m)>f1Score(best)?m:best, active[0])
  document.getElementById('stats-bar').innerHTML = `
    <div class="stat-card"><div class="val">${mods.length}</div><div class="lbl">Models tested</div></div>
    <div class="stat-card"><div class="val">${active.length}</div><div class="lbl">Functional models</div></div>
    <div class="stat-card"><div class="val">${providers.length}</div><div class="lbl">Providers</div></div>
    <div class="stat-card"><div class="val">${RAW.doc_names.length}</div><div class="lbl">Documents</div></div>
    <div class="stat-card"><div class="val">${RAW.fields.length}</div><div class="lbl">Fields per doc</div></div>
    <div class="stat-card"><div class="val">${topF1.toFixed(3)}</div><div class="lbl">Best F1 (${topModel})</div></div>
    <div class="stat-card"><div class="val">${mods.length - active.length}</div><div class="lbl">Failed (F1=0)</div></div>
  `
  // Populate provider dropdown
  const provSel = document.getElementById('rank-provider')
  providers.forEach(p=>{
    const opt = document.createElement('option')
    opt.value = p; opt.text = p.charAt(0).toUpperCase()+p.slice(1)
    provSel.appendChild(opt)
  })
  renderRankTable()
  renderAccuracyChart()
  renderProviderSummary()
  renderScoringNotes()
}

function rankRows(){
  const sort = document.getElementById('rank-sort').value
  const filter = document.getElementById('rank-filter').value
  const provFilter = document.getElementById('rank-provider')?.value || 'all'
  const tierBudgets = {'free':['free'],'ultra-cheap':['free','ultra-cheap'],'great-value':['free','ultra-cheap','great-value']}
  let models = allModels()
  if(filter==='active') models = activeModels()
  else if(tierBudgets[filter]) models = models.filter(m=>tierBudgets[filter].includes(RAW.model_meta?.[m]?.tier))
  if(provFilter!=='all') models = models.filter(m=>(RAW.model_providers?.[m]||'unknown')===provFilter)
  return models.map(m=>{
    const d = RAW.models[m]
    const f1s = RAW.f1_scores?.[m] || {}
    let correct=0,wrong=0,missing=0
    for(const f of Object.values(d.per_field)){
      correct+=f.correct; wrong+=f.wrong; missing+=f.missing
    }
    return {m, acc:d.accuracy, f1:f1s.f1||0, precision:f1s.precision||0, recall:f1s.recall||0,
            fields_found:f1s.fields_found||0, fields_total:f1s.fields_total||0,
            correct, wrong, missing, total:d.total_expected}
  }).sort((a,b)=>{
    if(sort==='f1') return b.f1 - a.f1
    if(sort==='accuracy') return b.acc - a.acc
    if(sort==='correct') return b.correct - a.correct
    if(sort==='wrong') return a.wrong - b.wrong
    if(sort==='missing') return a.missing - b.missing
    return 0
  })
}

function fmtTime(secs, est){
  if(!secs) return '<span style="color:var(--muted)">—</span>'
  const prefix = est ? '~' : ''
  if(secs < 60) return prefix+secs.toFixed(0)+'s'
  return prefix+(secs/60).toFixed(1)+'m'
}
function fmtCost(usd, est){
  if(!usd) return '<span style="color:var(--muted)">—</span>'
  const prefix = est ? '~' : ''
  if(usd < 0.01) return prefix+'<$0.01'
  return prefix+'$'+usd.toFixed(3)
}
function renderRankTable(){
  const rows = rankRows()
  const bestF1Val = rows[0]?.f1 || 1
  let html = `<table><thead><tr>
    <th>#</th><th>Model</th><th>Provider</th><th>F1</th><th>Prec</th><th>Recall</th><th>Score bar</th>
    <th>Fields</th><th>Time</th><th>Cost</th><th>Perf.</th><th>Tier</th>
  </tr></thead><tbody>`
  rows.forEach((r,i)=>{
    const t = tier(r.f1)
    const st = RAW.extraction_stats?.[r.m]
    const fieldsStr = r.fields_total > 0 ? `${r.fields_found.toFixed(1)}/${r.fields_total.toFixed(0)}` : '—'
    html += `<tr>
      <td style="color:var(--muted)">${i+1}</td>
      <td><strong>${r.m}</strong></td>
      <td>${providerBadge(r.m)}</td>
      <td><strong style="color:${hsl(r.f1)}">${r.f1.toFixed(3)}</strong></td>
      <td style="color:var(--muted)">${r.precision.toFixed(3)}</td>
      <td style="color:var(--muted)">${r.recall.toFixed(3)}</td>
      <td>
        <div class="rank-bar-wrap">
          <div class="rank-bar" style="width:${(r.f1/Math.max(bestF1Val,0.01)*100).toFixed(1)}%;background:${hsl(r.f1)}"></div>
        </div>
      </td>
      <td style="color:var(--muted);font-size:12px">${fieldsStr}</td>
      <td>${fmtTime(st?.total_elapsed_secs, st?.estimated)}</td>
      <td>${fmtCost(st?.total_cost_usd, st?.estimated)}</td>
      <td><span class="badge ${t.cls}">${t.label}</span></td>
      <td>${costTierBadge(r.m)}</td>
    </tr>`
  })
  html += '</tbody></table>'
  document.getElementById('rank-table-wrap').innerHTML = html
}

function renderAccuracyChart(){
  const rows = rankRows()
  const ctx = document.getElementById('chart-accuracy').getContext('2d')
  if(chartAccuracy) chartAccuracy.destroy()
  chartAccuracy = new Chart(ctx, {
    type:'bar',
    data:{
      labels: rows.map(r=>r.m),
      datasets:[{
        label:'F1 Score',
        data: rows.map(r=>+(r.f1*100).toFixed(1)),
        backgroundColor: rows.map(r=>bgAlpha(r.f1)),
        borderColor: rows.map(r=>hsl(r.f1)),
        borderWidth:1,
        borderRadius:4,
      }]
    },
    options:{
      indexAxis:'y',
      responsive:true,
      maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>`F1: ${(ctx.parsed.x/100).toFixed(3)}`}}},
      scales:{
        x:{min:0,max:100,ticks:{callback:v=>v+'%'},grid:{color:'#e2e8f0'}},
        y:{ticks:{font:{size:11}}}
      }
    }
  })
}

function renderProviderSummary(){
  const providers = allProviders()
  let html = `<table><thead><tr>
    <th>Provider</th><th>All</th><th>Active</th><th>Failed</th>
    <th>Avg F1</th><th>Best F1</th><th>Best Model</th>
    <th>Avg Fields</th><th>Avg Time</th><th>Avg Cost</th>
  </tr></thead><tbody>`
  providers.sort().forEach(p=>{
    const models = allModels().filter(m=>(RAW.model_providers?.[m]||'unknown')===p)
    const active = models.filter(m=>f1Score(m)>0)
    const failed = models.length - active.length
    const avgF1 = active.length ? active.reduce((s,m)=>s+f1Score(m),0)/active.length : 0
    const best = models.reduce((b,m)=>f1Score(m)>f1Score(b)?m:b, models[0])
    const avgFF = active.length ? active.reduce((s,m)=>s+(RAW.f1_scores?.[m]?.fields_found||0),0)/active.length : 0
    const avgFT = active.length ? active.reduce((s,m)=>s+(RAW.f1_scores?.[m]?.fields_total||0),0)/active.length : 0
    const fieldsStr = avgFT > 0 ? `${avgFF.toFixed(1)}/${avgFT.toFixed(0)} (${(100*avgFF/avgFT).toFixed(0)}%)` : '—'
    const times = active.map(m=>RAW.extraction_stats?.[m]?.total_elapsed_secs||0).filter(t=>t>0)
    const avgTime = times.length ? times.reduce((s,t)=>s+t,0)/times.length : 0
    const allEst = times.length>0 && active.every(m=>RAW.extraction_stats?.[m]?.estimated)
    const costs = active.map(m=>RAW.extraction_stats?.[m]?.total_cost_usd||0).filter(c=>c>0)
    const avgCost = costs.length ? costs.reduce((s,c)=>s+c,0)/costs.length : 0
    const allCostEst = costs.length>0 && active.filter(m=>(RAW.extraction_stats?.[m]?.total_cost_usd||0)>0).every(m=>RAW.extraction_stats?.[m]?.estimated)
    html += `<tr>
      <td>${providerBadge(models[0])}</td>
      <td>${models.length}</td>
      <td style="color:var(--correct);font-weight:600">${active.length}</td>
      <td style="color:${failed?'var(--red)':'var(--muted)'}">${failed}</td>
      <td><strong style="color:${hsl(avgF1)}">${avgF1.toFixed(3)}</strong></td>
      <td style="color:${hsl(f1Score(best))};font-weight:600">${f1Score(best).toFixed(3)}</td>
      <td><strong>${best}</strong></td>
      <td style="font-size:12px">${fieldsStr}</td>
      <td>${fmtTime(avgTime, allEst)}</td>
      <td>${fmtCost(avgCost, allCostEst)}</td>
    </tr>`
  })
  html += '</tbody></table>'
  document.getElementById('provider-summary').innerHTML = html

  // Notes
  let notes = '<div style="font-size:12px;color:var(--muted)">'
  notes += '<p>~ = estimated from config pricing × avg tokens. '
  notes += 'Failed = models with F1=0 (extraction failed or no parseable output). '
  notes += 'Fields = avg fields found/total per model (out of '+RAW.fields.length+' per doc × '+RAW.doc_names.length+' docs).</p>'
  notes += '</div>'
  document.getElementById('provider-notes').innerHTML = notes
}

function renderScoringNotes(){
  let html = ''
  html += '<div class="insight insight-tip"><strong>Semantic scoring (F1)</strong> — score.py uses field-type-aware comparison: '
  html += 'exact match for IDs and dates (charity_number, report_date), '
  html += 'numeric tolerance (0.5%) for financial fields (income, spending), '
  html += 'and fuzzy string similarity (SequenceMatcher) for text fields (names, addresses). '
  html += 'F1 = harmonic mean of precision and recall.</div>'
  html += '<div class="insight"><strong>Exact-match accuracy</strong> — the playground\'s per-field heatmaps and error breakdowns use strict exact matching. '
  html += 'This is more conservative than F1 scoring — a model may score well on F1 but lower on exact match if values are close but not identical.</div>'
  html += '<div class="insight"><strong>Two scoring views</strong> — the leaderboard ranks by F1 (semantic), while heatmaps and error patterns show exact-match detail. '
  html += 'Both are useful: F1 reflects real-world utility, exact match reveals normalisation issues to fix in prompts or post-processing.</div>'
  document.getElementById('scoring-notes').innerHTML = html
}

// ── ② Field Heatmap ───────────────────────────────────────────────────────

function renderFieldHeatmap(){
  const filter = document.getElementById('hm-filter').value
  const models = filter==='active' ? activeModels() : allModels()
  const fields = RAW.fields
  const labels = RAW.field_labels

  let html = '<table><thead><tr><th>Model</th>'
  for(const f of fields) html += `<th title="${f}">${labels[f]}</th>`
  html += '</tr></thead><tbody>'

  for(const m of models){
    html += `<tr><td style="font-size:12px;font-weight:600;white-space:nowrap">${m} <span style="font-weight:400;color:var(--muted);font-size:10px">${providerLabel(m)}</span></td>`
    const pf = RAW.models[m].per_field
    for(const f of fields){
      const fd = pf[f] || {correct:0,missing:0,wrong:0}
      const total = fd.correct + fd.missing + fd.wrong
      const acc = total > 0 ? fd.correct/total : 0
      const txt = total > 0 ? pct(acc) : '—'
      const tooltip = `Correct: ${fd.correct}, Wrong: ${fd.wrong}, Missing: ${fd.missing}`
      html += `<td title="${tooltip}">
        <div class="hm-cell" style="background:${total>0?bgAlpha(acc):'#f1f5f9'};color:${total>0?hsl(acc):'#94a3b8'}">${txt}</div>
      </td>`
    }
    html += '</tr>'
  }
  html += '</tbody></table>'
  document.getElementById('field-heatmap').innerHTML = html
}

function renderBestPerField(){
  const models = activeModels()
  const fields = RAW.fields
  let html = '<table><thead><tr><th>Field</th><th>Best Model</th><th>Accuracy</th><th>Runner-up</th></tr></thead><tbody>'
  for(const f of fields){
    const scores = models.map(m=>{
      const fd = RAW.models[m].per_field[f] || {correct:0,missing:0,wrong:0}
      const total = fd.correct+fd.missing+fd.wrong
      return {m, acc: total>0 ? fd.correct/total : 0}
    }).sort((a,b)=>b.acc-a.acc)
    const best = scores[0]
    const runner = scores[1]
    html += `<tr>
      <td>${RAW.field_labels[f]}</td>
      <td><strong>${best.m}</strong></td>
      <td style="color:${hsl(best.acc)};font-weight:600">${pct(best.acc)}</td>
      <td style="color:var(--muted)">${runner?`${runner.m} (${pct(runner.acc)})`:'—'}</td>
    </tr>`
  }
  html += '</tbody></table>'
  document.getElementById('best-per-field').innerHTML = html
}

let chartFieldDiff = null
function renderFieldDifficulty(){
  const models = activeModels()
  const fields = RAW.fields
  const avgAcc = fields.map(f=>{
    const accs = models.map(m=>{
      const fd = RAW.models[m].per_field[f]||{correct:0,missing:0,wrong:0}
      const total = fd.correct+fd.missing+fd.wrong
      return total>0 ? fd.correct/total : 0
    })
    return {f, avg: accs.reduce((s,v)=>s+v,0)/accs.length}
  }).sort((a,b)=>a.avg-b.avg)

  const ctx = document.getElementById('chart-field-diff').getContext('2d')
  if(chartFieldDiff) chartFieldDiff.destroy()
  chartFieldDiff = new Chart(ctx,{
    type:'bar',
    data:{
      labels: avgAcc.map(x=>RAW.field_labels[x.f]),
      datasets:[{
        label:'Avg accuracy',
        data: avgAcc.map(x=>+(x.avg*100).toFixed(1)),
        backgroundColor: avgAcc.map(x=>bgAlpha(x.avg)),
        borderColor: avgAcc.map(x=>hsl(x.avg)),
        borderWidth:1, borderRadius:4
      }]
    },
    options:{
      indexAxis:'y', responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${c.parsed.x.toFixed(1)}%`}}},
      scales:{
        x:{min:0,max:100,ticks:{callback:v=>v+'%'},grid:{color:'#e2e8f0'}},
        y:{ticks:{font:{size:11}}}
      }
    }
  })
}

// ── ③ Document Analysis ───────────────────────────────────────────────────

function renderDocHeatmap(){
  const filter = document.getElementById('doc-hm-filter').value
  const models = filter==='active' ? activeModels() : allModels()
  const docs = RAW.doc_names

  let html = '<table><thead><tr><th>Document</th>'
  for(const m of models) html += `<th style="writing-mode:vertical-lr;transform:rotate(180deg);height:80px;font-size:10px">${m}</th>`
  html += '</tr></thead><tbody>'

  for(let di=0; di<docs.length; di++){
    html += `<tr><td style="font-size:12px;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${docs[di]}">${docs[di]}</td>`
    for(const m of models){
      const pd = RAW.models[m].per_doc[di]
      if(!pd){html += `<td><div class="hm-cell" style="background:#f1f5f9;color:#94a3b8">—</div></td>`;continue}
      const acc = pd.accuracy
      const txt = pd.is_error ? 'ERR' : pct(acc)
      const tooltip = pd.is_error ? 'Rate limit error' : `${pd.correct}/${pd.total}`
      html += `<td title="${tooltip}"><div class="hm-cell" style="background:${pd.is_error?'#fee2e2':bgAlpha(acc)};color:${pd.is_error?'#991b1b':hsl(acc)}">${txt}</div></td>`
    }
    html += '</tr>'
  }
  html += '</tbody></table>'
  document.getElementById('doc-heatmap').innerHTML = html
}

let chartDocDiff = null
function renderDocDifficulty(){
  const models = activeModels()
  const docs = RAW.doc_names
  const avgs = docs.map((name,di)=>{
    const accs = models.map(m=>{
      const pd = RAW.models[m].per_doc[di]
      return (pd && !pd.is_error) ? pd.accuracy : 0
    })
    return {name, avg: accs.reduce((s,v)=>s+v,0)/accs.length}
  })
  const sorted = [...avgs].sort((a,b)=>a.avg-b.avg)
  const ctx = document.getElementById('chart-doc-diff').getContext('2d')
  if(chartDocDiff) chartDocDiff.destroy()
  chartDocDiff = new Chart(ctx,{
    type:'bar',
    data:{
      labels: sorted.map(x=>x.name.length>30?x.name.slice(0,28)+'…':x.name),
      datasets:[{
        label:'Avg accuracy',
        data: sorted.map(x=>+(x.avg*100).toFixed(1)),
        backgroundColor: sorted.map(x=>bgAlpha(x.avg)),
        borderColor: sorted.map(x=>hsl(x.avg)),
        borderWidth:1, borderRadius:4
      }]
    },
    options:{
      indexAxis:'y', responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${c.parsed.x.toFixed(1)}%`}}},
      scales:{
        x:{min:0,max:100,ticks:{callback:v=>v+'%'},grid:{color:'#e2e8f0'}},
        y:{ticks:{font:{size:10}}}
      }
    }
  })
}

// ── ④ Error Breakdown ─────────────────────────────────────────────────────

let chartErrors = null
function renderErrorChart(){
  const models = Object.keys(RAW.models).sort((a,b)=>{
    const da = RAW.models[a], db = RAW.models[b]
    let ca=0,cb=0
    for(const f of Object.values(da.per_field)) ca+=f.correct
    for(const f of Object.values(db.per_field)) cb+=f.correct
    return cb-ca
  })

  const corrects=[], wrongs=[], missings=[], totals=[]
  for(const m of models){
    let c=0,w=0,ms=0
    for(const f of Object.values(RAW.models[m].per_field)){c+=f.correct;w+=f.wrong;ms+=f.missing}
    corrects.push(c); wrongs.push(w); missings.push(ms)
    totals.push(c+w+ms)
  }

  const ctx = document.getElementById('chart-errors').getContext('2d')
  if(chartErrors) chartErrors.destroy()
  chartErrors = new Chart(ctx,{
    type:'bar',
    data:{
      labels: models,
      datasets:[
        {label:'Correct', data:corrects.map((c,i)=>totals[i]>0?(c/totals[i]*100).toFixed(1):0), backgroundColor:'rgba(16,185,129,0.7)', borderRadius:4},
        {label:'Wrong value', data:wrongs.map((w,i)=>totals[i]>0?(w/totals[i]*100).toFixed(1):0), backgroundColor:'rgba(249,115,22,0.7)'},
        {label:'Missing', data:missings.map((ms,i)=>totals[i]>0?(ms/totals[i]*100).toFixed(1):0), backgroundColor:'rgba(239,68,68,0.7)'},
      ]
    },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${c.parsed.y}%`}}},
      scales:{
        x:{stacked:true,ticks:{font:{size:10},maxRotation:45}},
        y:{stacked:true,max:100,ticks:{callback:v=>v+'%'},grid:{color:'#e2e8f0'}}
      }
    }
  })
}

function renderErrorPatterns(){
  const models = activeModels()
  // Find fields that are consistently wrong (high wrong rate vs missing)
  const fieldStats = RAW.fields.map(f=>{
    let totalWrong=0, totalMissing=0, totalCorrect=0
    for(const m of models){
      const fd = RAW.models[m].per_field[f]||{correct:0,wrong:0,missing:0}
      totalWrong+=fd.wrong; totalMissing+=fd.missing; totalCorrect+=fd.correct
    }
    const total = totalWrong+totalMissing+totalCorrect
    return {f, wrongRate:totalWrong/total, missingRate:totalMissing/total, correctRate:totalCorrect/total}
  })

  let html = ''
  const highWrong = fieldStats.filter(x=>x.wrongRate>0.15).sort((a,b)=>b.wrongRate-a.wrongRate)
  const highMissing = fieldStats.filter(x=>x.missingRate>0.3).sort((a,b)=>b.missingRate-a.missingRate)

  if(highWrong.length){
    html += '<h3 style="margin-bottom:8px">Fields with frequent wrong values (model extracts but gets wrong)</h3>'
    html += '<table><thead><tr><th>Field</th><th>Wrong rate</th><th>Likely cause</th></tr></thead><tbody>'
    const causes = {
      'income_annually_in_british_pounds':'Decimal precision, year mismatch, or format (e.g. .39 vs .00)',
      'spending_annually_in_british_pounds':'Same as income',
      'charity_name':'Capitalisation, punctuation, or abbreviation differences',
      'address__street_line':'Multi-line addresses joined differently',
    }
    for(const x of highWrong){
      html+=`<tr><td>${RAW.field_labels[x.f]}</td><td style="color:var(--orange);font-weight:600">${pct(x.wrongRate)}</td><td style="color:var(--muted)">${causes[x.f]||'Formatting/normalisation mismatch'}</td></tr>`
    }
    html += '</tbody></table>'
  }
  if(highMissing.length){
    html += '<h3 style="margin:16px 0 8px">Fields frequently omitted entirely</h3>'
    html += '<table><thead><tr><th>Field</th><th>Missing rate</th></tr></thead><tbody>'
    for(const x of highMissing){
      html+=`<tr><td>${RAW.field_labels[x.f]}</td><td style="color:var(--red);font-weight:600">${pct(x.missingRate)}</td></tr>`
    }
    html += '</tbody></table>'
  }
  if(!html) html = '<p style="color:var(--muted)">No significant error patterns detected.</p>'
  document.getElementById('error-patterns').innerHTML = html
}

// ── ⑤ Deep Dive ───────────────────────────────────────────────────────────

function initDeepDive(){
  const modelSel = document.getElementById('dd-model')
  const docSel = document.getElementById('dd-doc')
  for(const m of Object.keys(RAW.models)){
    const opt = document.createElement('option'); opt.value=m; opt.text=m
    modelSel.appendChild(opt)
  }
  for(let i=0;i<RAW.doc_names.length;i++){
    const opt = document.createElement('option'); opt.value=i; opt.text=`${i+1}. ${RAW.doc_names[i]}`
    docSel.appendChild(opt)
  }
  renderDeepDive()
}

function renderDeepDive(){
  const m = document.getElementById('dd-model').value
  const di = parseInt(document.getElementById('dd-doc').value||'0')
  if(!m){document.getElementById('dd-output').innerHTML='<p style="color:var(--muted)">Select a model above.</p>';return}
  const pd = RAW.models[m]?.per_doc[di]
  const expected = RAW.expected[di]

  let html = ''
  if(pd?.is_error){
    html = `<div class="insight insight-warn"><strong>Rate limit error</strong> — This model returned an API error for this document. No extraction was attempted.</div>`
  } else {
    const acc = pd?.accuracy||0
    html = `<div style="margin-bottom:12px">
      <span class="badge ${tier(acc).cls}">${tier(acc).label}</span>
      <strong style="margin-left:8px;color:${hsl(acc)}">${pct(acc)} accuracy</strong>
      <span style="color:var(--muted);margin-left:8px">${pd?.correct||0} of ${pd?.total||0} fields correct</span>
    </div>`
    html += `<table class="diff-table"><thead><tr>
      <th>Field</th><th>Expected</th><th>Extracted</th><th>Status</th>
    </tr></thead><tbody>`
    for(const f of RAW.fields){
      if(!(f in (expected||{}))) continue
      const fs = pd?.fields[f]
      const status = fs?.status || 'missing'
      const got = fs?.got ?? '—'
      const exp = fs?.expected ?? expected[f]
      html += `<tr class="diff-${status}">
        <td style="font-weight:600">${RAW.field_labels[f]}</td>
        <td>${exp?.replace(/_/g,' ')||'—'}</td>
        <td>${got===null?'<em style="color:var(--muted)">not extracted</em>':(got?.replace(/_/g,' ')||'—')}</td>
        <td><span class="badge ${status==='correct'?'badge-green':status==='wrong'?'badge-orange':'badge-red'}">${status}</span></td>
      </tr>`
    }
    html += '</tbody></table>'
  }
  document.getElementById('dd-output').innerHTML = html
}

// ── ⑥ Recommendations ─────────────────────────────────────────────────────

function renderRecommendations(){
  const usecase = document.getElementById('rec-usecase').value
  const budget  = document.getElementById('rec-budget').value
  const relevantFields = usecase==='all' ? RAW.fields : RAW.field_groups[usecase]
  const budgetTiers = {'free':['free'],'ultra-cheap':['free','ultra-cheap'],'great-value':['free','ultra-cheap','great-value'],'premium':TIER_ORDER}
  const allowed = budget==='any' ? null : budgetTiers[budget]
  const models = activeModels().filter(m=> !allowed || allowed.includes(RAW.model_meta?.[m]?.tier))

  const scores = models.map(m=>{
    let correct=0, total=0
    for(const f of relevantFields){
      const fd = RAW.models[m].per_field[f]||{correct:0,wrong:0,missing:0}
      correct+=fd.correct; total+=fd.correct+fd.wrong+fd.missing
    }
    return {m, acc: total>0?correct/total:0, correct, total}
  }).sort((a,b)=>b.acc-a.acc)

  let budgetNote = budget==='any' ? '' : ` <span style="color:var(--muted)">(budget: ${tierLabel(budget)} and below)</span>`
  let html = `<p style="font-size:12px;color:var(--muted);margin-bottom:14px">Ranking models by accuracy on: <strong>${relevantFields.map(f=>RAW.field_labels[f]).join(', ')}</strong>${budgetNote}</p>`
  if(!models.length){html+='<p style="color:var(--muted)">No functional models match this budget filter.</p>'; document.getElementById('rec-output').innerHTML=html; return}
  html += '<table><thead><tr><th>#</th><th>Model</th><th>Provider</th><th>Accuracy on selected fields</th><th>Correct</th><th>Perf.</th><th>Cost</th></tr></thead><tbody>'
  scores.forEach((r,i)=>{
    const t = tier(r.acc)
    html += `<tr>
      <td style="color:var(--muted)">${i+1}</td>
      <td><strong>${r.m}</strong></td>
      <td>${providerBadge(r.m)}</td>
      <td>
        <span style="color:${hsl(r.acc)};font-weight:700">${pct(r.acc)}</span>
        <div class="rank-bar-wrap" style="margin-top:3px;width:120px">
          <div class="rank-bar" style="width:${(r.acc*100).toFixed(1)}%;background:${hsl(r.acc)}"></div>
        </div>
      </td>
      <td style="color:var(--muted)">${r.correct}/${r.total}</td>
      <td><span class="badge ${t.cls}">${t.label}</span></td>
      <td>${costTierBadge(r.m)}</td>
    </tr>`
  })
  html += '</tbody></table>'

  if(scores.length){
    const top = scores[0]
    const bestFree = scores.find(r=>(RAW.model_meta?.[r.m]?.tier)==='free')
    html += `<div class="insight insight-tip" style="margin-top:16px">
      <strong>Recommended:</strong> <strong>${top.m}</strong> (${costTierBadge(top.m)}) achieves ${pct(top.acc)} on the selected fields.
      ${scores[1] && scores[1].m!==top.m?`Runner-up: <strong>${scores[1].m}</strong> at ${pct(scores[1].acc)}.`:''}
    </div>`
    if(bestFree && bestFree.m!==top.m){
      html += `<div class="insight" style="margin-top:8px"><strong>Best free option:</strong> <strong>${bestFree.m}</strong> at ${pct(bestFree.acc)}.</div>`
    }
  }

  document.getElementById('rec-output').innerHTML = html
}

function renderInsights(){
  const models = activeModels()
  const allM = allModels()
  const failedModels = allM.filter(m=>!isActive(m))
  const fields = RAW.fields

  // Best overall
  const sorted = models.map(m=>({m,acc:RAW.models[m].accuracy})).sort((a,b)=>b.acc-a.acc)
  const best = sorted[0], second = sorted[1]

  // Hardest field (lowest avg across active models)
  const fieldAvg = fields.map(f=>{
    const accs = models.map(m=>{const fd=RAW.models[m].per_field[f]||{correct:0,wrong:0,missing:0};const t=fd.correct+fd.wrong+fd.missing;return t>0?fd.correct/t:0})
    return {f, avg:accs.reduce((s,v)=>s+v,0)/accs.length}
  })
  const hardest = fieldAvg.sort((a,b)=>a.avg-b.avg)[0]
  const easiest = [...fieldAvg].sort((a,b)=>b.avg-a.avg)[0]

  // Financial consistency — std dev of income/spending accuracy
  const financialConsistency = models.map(m=>{
    const inc = RAW.models[m].per_field['income_annually_in_british_pounds']||{correct:0,wrong:0,missing:0}
    const sp = RAW.models[m].per_field['spending_annually_in_british_pounds']||{correct:0,wrong:0,missing:0}
    const t1=inc.correct+inc.wrong+inc.missing, t2=sp.correct+sp.wrong+sp.missing
    const a1=t1>0?inc.correct/t1:0, a2=t2>0?sp.correct/t2:0
    return {m, financialAcc:(a1+a2)/2}
  }).sort((a,b)=>b.financialAcc-a.financialAcc)

  let html = ''
  html += `<div class="insight insight-tip"><strong>Top performer:</strong> ${best.m} leads with ${pct(best.acc)} overall accuracy. ${second?`${second.m} follows at ${pct(second.acc)}.`:''}</div>`
  html += `<div class="insight"><strong>Hardest field:</strong> "${RAW.field_labels[hardest.f]}" averages only ${pct(hardest.avg)} accuracy across functional models — indicating consistent extraction difficulty.</div>`
  html += `<div class="insight insight-tip"><strong>Easiest field:</strong> "${RAW.field_labels[easiest.f]}" is most reliably extracted at ${pct(easiest.avg)} average accuracy.</div>`
  html += `<div class="insight"><strong>Financial data leader:</strong> ${financialConsistency[0].m} is best for income/spending extraction at ${pct(financialConsistency[0].financialAcc)} combined accuracy.</div>`
  if(failedModels.length){
    html += `<div class="insight insight-warn"><strong>Failed models (${failedModels.length}):</strong> ${failedModels.join(', ')} — F1=0, extraction failed or returned no parseable output. May be rate-limited, misconfigured, or unable to handle the document format.</div>`
  }

  // Check if any model is better on smaller tasks
  const smallModelBest = models.filter(m=>m.includes('7b')||m.includes('8b'))
  if(smallModelBest.length){
    const bestSmall = smallModelBest.map(m=>({m,acc:RAW.models[m].accuracy})).sort((a,b)=>b.acc-a.acc)[0]
    if(bestSmall.acc > 0.5){
      html += `<div class="insight insight-tip"><strong>Small model worth noting:</strong> ${bestSmall.m} achieves ${pct(bestSmall.acc)} — a cost-effective option for high-throughput pipelines.</div>`
    }
  }

  document.getElementById('insights').innerHTML = html
}

function renderImprovements(){
  const models = activeModels()
  const fields = RAW.fields

  // Find patterns in wrong values
  const streetWrong = models.reduce((s,m)=>{const fd=RAW.models[m].per_field['address__street_line']||{wrong:0};return s+fd.wrong},0)
  const incomeWrong = models.reduce((s,m)=>{const fd=RAW.models[m].per_field['income_annually_in_british_pounds']||{wrong:0};return s+fd.wrong},0)
  const nameWrong = models.reduce((s,m)=>{const fd=RAW.models[m].per_field['charity_name']||{wrong:0};return s+fd.wrong},0)

  let html = ''
  html += `<div class="insight insight-tip"><strong>Prompt: normalise numbers</strong> — Income and spending show high "wrong" rates due to decimal/rounding differences (e.g. <code>122836.39</code> vs <code>122836.00</code>). Add explicit instruction: <em>"Round amounts to 2 decimal places. Use the exact figure from the accounts, not a rounded total."</em></div>`
  html += `<div class="insight insight-tip"><strong>Prompt: canonical charity name</strong> — Charity names vary in case and punctuation. Instruct: <em>"Use the official registered name exactly as shown on the document header."</em></div>`
  html += `<div class="insight insight-tip"><strong>Prompt: street line normalisation</strong> — Multi-line addresses are collapsed inconsistently. Instruct: <em>"Join multiple address lines with a single space. Omit building names unless the street number is absent."</em></div>`
  html += `<div class="insight"><strong>Consider few-shot examples</strong> — Models that got 100% on some docs but 0% on others are likely sensitive to document format variations. Adding 1-2 in-context examples from different document layouts will reduce variance.</div>`
  html += `<div class="insight"><strong>Post-processing</strong> — Apply deterministic cleaning after extraction: uppercase postcodes, strip trailing/leading whitespace, normalise decimal places. This can close the gap between "wrong" and "correct" for formatting-only errors.</div>`
  const failedNames = allModels().filter(m=>!isActive(m)).join(', ')
  if(failedNames) html += `<div class="insight insight-warn"><strong>Re-test failed models</strong> — These models scored F1=0: ${failedNames}. They may have been rate-limited, returned errors, or produced unparseable output. Re-run with proper API keys or rate limiting before drawing conclusions.</div>`

  document.getElementById('improvements').innerHTML = html
}

// ── ⑦ Provider Analysis ──────────────────────────────────────────────────────

let chartProviderF1 = null, chartProviderTiers = null

function renderProviderAnalysis(){
  const providers = allProviders().sort()
  const mods = allModels()

  // Stats bar
  const totalConfigured = Object.keys(RAW.model_meta||{}).length
  const totalRun = mods.length
  const totalActive = activeModels().length
  const dwCount = mods.filter(m=>(RAW.model_providers?.[m]||'')==='doubleword').length
  const orCount = mods.filter(m=>(RAW.model_providers?.[m]||'')==='openrouter').length
  document.getElementById('provider-stats-bar').innerHTML = `
    <div class="stat-card"><div class="val">${providers.length}</div><div class="lbl">Providers</div></div>
    <div class="stat-card"><div class="val">${totalConfigured}</div><div class="lbl">Models configured</div></div>
    <div class="stat-card"><div class="val">${totalRun}</div><div class="lbl">Models run</div></div>
    <div class="stat-card"><div class="val">${totalActive}</div><div class="lbl">Active (F1 > 0)</div></div>
    <div class="stat-card"><div class="val">${orCount}</div><div class="lbl">OpenRouter</div></div>
    <div class="stat-card"><div class="val">${dwCount}</div><div class="lbl">Doubleword</div></div>
  `

  // Provider F1 comparison chart
  const provData = providers.map(p=>{
    const pModels = activeModels().filter(m=>(RAW.model_providers?.[m]||'')=== p)
    const f1s = pModels.map(m=>f1Score(m))
    const avg = f1s.length ? f1s.reduce((s,v)=>s+v,0)/f1s.length : 0
    const best = f1s.length ? Math.max(...f1s) : 0
    return {p, avg, best, count: pModels.length}
  })

  const ctx1 = document.getElementById('chart-provider-f1').getContext('2d')
  if(chartProviderF1) chartProviderF1.destroy()
  chartProviderF1 = new Chart(ctx1,{
    type:'bar',
    data:{
      labels: provData.map(d=>d.p.charAt(0).toUpperCase()+d.p.slice(1)),
      datasets:[
        {label:'Avg F1', data:provData.map(d=>+(d.avg*100).toFixed(1)), backgroundColor:'rgba(99,102,241,0.6)', borderRadius:4},
        {label:'Best F1', data:provData.map(d=>+(d.best*100).toFixed(1)), backgroundColor:'rgba(16,185,129,0.6)', borderRadius:4}
      ]
    },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${(c.parsed.y/100).toFixed(3)}`}}},
      scales:{y:{min:0,max:100,ticks:{callback:v=>v+'%'},grid:{color:'#e2e8f0'}}}
    }
  })

  // Tier distribution chart
  const tierColors = {'free':'#94a3b8','ultra-cheap':'#3b82f6','great-value':'#10b981','premium':'#f59e0b'}
  const tierLabels = ['free','ultra-cheap','great-value','premium']
  const datasets = tierLabels.map(t=>({
    label: tierLabel(t),
    data: providers.map(p=>{
      return mods.filter(m=>(RAW.model_providers?.[m]||'')=== p && (RAW.model_meta?.[m]?.tier||'')=== t).length
    }),
    backgroundColor: tierColors[t],
    borderRadius:4
  }))
  const ctx2 = document.getElementById('chart-provider-tiers').getContext('2d')
  if(chartProviderTiers) chartProviderTiers.destroy()
  chartProviderTiers = new Chart(ctx2,{
    type:'bar',
    data:{labels: providers.map(p=>p.charAt(0).toUpperCase()+p.slice(1)), datasets},
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{legend:{position:'top'}},
      scales:{x:{stacked:true},y:{stacked:true,ticks:{stepSize:1},grid:{color:'#e2e8f0'}}}
    }
  })

  // Cost efficiency table
  const effModels = activeModels().filter(m=>{
    const st = RAW.extraction_stats?.[m]
    return st && st.total_cost_usd > 0
  }).map(m=>{
    const st = RAW.extraction_stats[m]
    const f1 = f1Score(m)
    const efficiency = st.total_cost_usd > 0 ? f1 / st.total_cost_usd : 0
    return {m, f1, cost: st.total_cost_usd, efficiency, estimated: st.estimated}
  }).sort((a,b)=>b.efficiency - a.efficiency)

  let effHtml = `<table><thead><tr><th>#</th><th>Model</th><th>Provider</th><th>F1</th><th>Cost</th><th>F1/$</th><th>Tier</th></tr></thead><tbody>`
  effModels.forEach((r,i)=>{
    effHtml += `<tr>
      <td style="color:var(--muted)">${i+1}</td>
      <td><strong>${r.m}</strong></td>
      <td>${providerBadge(r.m)}</td>
      <td style="color:${hsl(r.f1)};font-weight:600">${r.f1.toFixed(3)}</td>
      <td>${fmtCost(r.cost, r.estimated)}</td>
      <td style="font-weight:700;color:var(--accent)">${r.efficiency.toFixed(1)}</td>
      <td>${costTierBadge(r.m)}</td>
    </tr>`
  })
  effHtml += '</tbody></table>'
  if(!effModels.length) effHtml = '<p style="color:var(--muted)">No cost data available.</p>'
  document.getElementById('cost-efficiency-table').innerHTML = effHtml

  // Modality breakdown
  let modHtml = `<table><thead><tr><th>Provider</th><th>Text-only</th><th>Multimodal</th><th>Text Avg F1</th><th>MM Avg F1</th><th>Modalities</th></tr></thead><tbody>`
  providers.forEach(p=>{
    const pMods = mods.filter(m=>(RAW.model_providers?.[m]||'')=== p)
    const textOnly = pMods.filter(m=>!RAW.model_meta?.[m]?.multimodal)
    const mm = pMods.filter(m=>RAW.model_meta?.[m]?.multimodal)
    const textActive = textOnly.filter(m=>f1Score(m)>0)
    const mmActive = mm.filter(m=>f1Score(m)>0)
    const textAvg = textActive.length ? textActive.reduce((s,m)=>s+f1Score(m),0)/textActive.length : 0
    const mmAvg = mmActive.length ? mmActive.reduce((s,m)=>s+f1Score(m),0)/mmActive.length : 0
    const allModalities = new Set()
    pMods.forEach(m=>(RAW.model_meta?.[m]?.modalities||[]).forEach(mod=>allModalities.add(mod)))
    modHtml += `<tr>
      <td>${providerBadge(pMods[0])}</td>
      <td>${textOnly.length} (${textActive.length} active)</td>
      <td>${mm.length} (${mmActive.length} active)</td>
      <td style="color:${hsl(textAvg)};font-weight:600">${textAvg?textAvg.toFixed(3):'—'}</td>
      <td style="color:${hsl(mmAvg)};font-weight:600">${mmAvg?mmAvg.toFixed(3):'—'}</td>
      <td style="font-size:11px">${[...allModalities].sort().join(', ')}</td>
    </tr>`
  })
  modHtml += '</tbody></table>'
  document.getElementById('modality-breakdown').innerHTML = modHtml

  // Populate catalog provider dropdown
  const catSel = document.getElementById('catalog-provider')
  providers.forEach(p=>{
    const opt = document.createElement('option')
    opt.value = p; opt.text = p.charAt(0).toUpperCase()+p.slice(1)
    catSel.appendChild(opt)
  })
  renderModelCatalog()
}

function renderModelCatalog(){
  const provFilter = document.getElementById('catalog-provider').value
  const statusFilter = document.getElementById('catalog-status').value
  let models = allModels()
  if(provFilter!=='all') models = models.filter(m=>(RAW.model_providers?.[m]||'')=== provFilter)
  if(statusFilter==='active') models = models.filter(m=>f1Score(m)>0)
  else if(statusFilter==='failed') models = models.filter(m=>f1Score(m)===0)

  // Sort by F1 desc
  models.sort((a,b)=>f1Score(b)-f1Score(a))

  let html = `<table><thead><tr>
    <th>Model</th><th>Provider</th><th>F1</th><th>Tier</th><th>Modalities</th>
    <th>Context</th><th>Price (in/out)</th><th>Notes</th>
  </tr></thead><tbody>`
  models.forEach(m=>{
    const meta = RAW.model_meta?.[m]||{}
    const f1 = f1Score(m)
    const mods = (meta.modalities||[]).join(', ')
    const ctx = meta.ctx ? (meta.ctx>=1000000 ? (meta.ctx/1000000).toFixed(0)+'M' : (meta.ctx/1000).toFixed(0)+'K') : '—'
    const priceIn = meta.price_in!=null ? '$'+meta.price_in.toFixed(2) : '—'
    const priceOut = meta.price_out!=null ? '$'+meta.price_out.toFixed(2) : '—'
    html += `<tr>
      <td><strong>${m}</strong></td>
      <td>${providerBadge(m)}</td>
      <td style="color:${hsl(f1)};font-weight:600">${f1?f1.toFixed(3):'<span style="color:var(--red)">0</span>'}</td>
      <td>${costTierBadge(m)}</td>
      <td style="font-size:11px">${mods||'—'}</td>
      <td style="font-size:12px">${ctx}</td>
      <td style="font-size:11px">${priceIn} / ${priceOut}</td>
      <td style="font-size:11px;color:var(--muted);max-width:220px">${meta.notes||''}</td>
    </tr>`
  })
  html += '</tbody></table>'
  if(!models.length) html = '<p style="color:var(--muted)">No models match the filter.</p>'
  document.getElementById('model-catalog').innerHTML = html
}

// ── ⑧ Evolution ──────────────────────────────────────────────────────────────

function renderEvolution(){
  const timeline = [
    {phase:'Data Preparation', commits:'8482875, bda4127, 3c4a94a', detail:'Automated Kleister-Charity data extraction. Collected 11 PDF documents (5→10→11). Built utility scripts for data prep.', icon:'📦'},
    {phase:'Format Standardisation', commits:'56eebd2', detail:'Converted expected/predicted TSV files to proper tab-delimited format. Enabled delimiter validation in score.py.', icon:'🔧'},
    {phase:'Multi-Model Leaderboard', commits:'5523528', detail:'Added config_models_openrouter.py with 40+ model configs (tiers, pricing, multimodal flags). Built extractor.py, score.py leaderboard, and this interactive playground. Generated extraction results for 33+ models via OpenRouter.', icon:'🏆'},
    {phase:'Documentation', commits:'013826d', detail:'Rewrote README and QUICKSTART to cover full pipeline: extractor.py → score.py → playground.py. Documented model tiers, CLI patterns, and output files.', icon:'📖'},
    {phase:'Model Cleanup & Refactor', commits:'66dd9d5', detail:'Removed 8 unavailable models (deepseek-r1-free, gpt-oss-120b-free, gemini-flash-free, etc.). Deleted stale TSVs. Added extraction call log tracking. Refactored LLM provider selection.', icon:'🧹'},
    {phase:'Security Hardening', commits:'1fad564', detail:'Added sanitize_error_message() to scrub user_id/API keys from all logs and TSV outputs before writing to disk.', icon:'🔒'},
    {phase:'Extended Results', commits:'5d92ce5', detail:'Ran extractions for 8 additional models (claude-3.5-haiku, command-r-plus, gemma-3-27b-free, etc.). Added extraction_stats.csv with per-model timing and cost data.', icon:'📊'},
    {phase:'Cost & Speed Tracking', commits:'5b13d98, f640b10', detail:'Added time and cost columns to the scoring leaderboard and playground. Reads actual elapsed time and API cost from extraction stats. Estimates costs for models without stats using config pricing. Added Project Evolution tab.', icon:'💰'},
    {phase:'Doubleword Batch API', commits:'05ed52c, 2777ca6', detail:'Added Doubleword as a second provider with batch API extraction pipeline. Created config_models_doubleword.py with 8 models (Qwen3, GPT-OSS). Updated pricing from official Doubleword docs.', icon:'🔗'},
    {phase:'Unified Multi-Provider Extractor', commits:'777f280, cffb225, e707ad2', detail:'Combined separate OpenRouter/Doubleword extractors into a single unified extractor.py with auto-detected backend. Renamed legacy files with provider suffixes (config_models_openrouter.py, llm_openrouter_calls.log).', icon:'⚙️'},
    {phase:'Provider-Aware Pipeline', commits:'7297e92, 5cb5fef', detail:'Added provider name to all prints, logs, filenames, and CSV columns. Defaults to running all providers. Added --all-openrouter flag for OpenRouter-only runs. Updated docs for the multi-provider workflow.', icon:'🏷️'},
    {phase:'Doubleword Extraction Results', commits:'c7d5a37', detail:'Ran extraction for 7 Doubleword models (dw-qwen3.5-9b, dw-qwen3.5-35b, dw-qwen3-14b, dw-gpt-oss-20b, dw-qwen3-vl-30b, dw-qwen3-vl-235b, dw-qwen3.5-397b). Added checkpoint/resume and parallel batch submission for Doubleword pipeline.', icon:'📊'},
    {phase:'F1 / Semantic Scoring', commits:'7c97b16, c61e75b', detail:'Replaced simple exact-match accuracy with field-type-aware F1 scoring: exact match for IDs/dates, numeric tolerance (0.5%) for financials, fuzzy string similarity (SequenceMatcher) for text fields like names and addresses. Leaderboard now shows F1, Precision, Recall.', icon:'🎯'},
    {phase:'Provider Summary & Leaderboard', commits:'cfa9c66', detail:'Added per-provider aggregated stats to the scoring leaderboard: All/Active/Failed counts, avg F1, best model, avg fields, time, and cost. Estimated values marked with ~. Provider summary helps compare OpenRouter vs Doubleword at a glance.', icon:'📋'},
    {phase:'Loguru Migration', commits:'13adfd2', detail:'Switched from stdlib logging to loguru across all scripts. Unified log format with module name binding, file sinks for LLM call logs, and level colors matching autobatcher defaults (blue DEBUG, bold INFO, yellow WARNING, red ERROR).', icon:'🪵'},
  ]

  let html = '<div style="position:relative;padding-left:28px;border-left:3px solid var(--accent)">'
  timeline.forEach((t,i)=>{
    const isLast = i===timeline.length-1
    html += `<div style="margin-bottom:${isLast?0:20}px;position:relative">
      <div style="position:absolute;left:-38px;top:0;width:22px;height:22px;border-radius:50%;background:${isLast?'var(--accent)':'var(--surface)'};border:2px solid var(--accent);display:flex;align-items:center;justify-content:center;font-size:12px">${t.icon}</div>
      <div style="font-weight:700;font-size:14px;color:var(--text)">${t.phase}</div>
      <div style="font-size:12px;color:var(--muted);margin:2px 0">Commits: <code>${t.commits}</code></div>
      <div style="font-size:13px">${t.detail}</div>
    </div>`
  })
  html += '</div>'
  document.getElementById('evolution-timeline').innerHTML = html

  // Numbers at a glance
  const active = activeModels()
  const failed = allModels().length - active.length
  const totalExtractions = active.reduce((s,m)=>s+RAW.models[m].total_expected,0)
  const totalCorrect = active.reduce((s,m)=>s+RAW.models[m].total_correct,0)
  const bestModelF1 = active.reduce((best,m)=>f1Score(m)>f1Score(best)?m:best, active[0])
  const avgF1 = active.reduce((s,m)=>s+f1Score(m),0)/active.length
  const avgAcc = active.reduce((s,m)=>s+RAW.models[m].accuracy,0)/active.length

  let statsHtml = `
    <table>
      <tr><td style="font-weight:600">Documents in corpus</td><td>${RAW.doc_names.length} charity PDFs (UK, 100+ pages each)</td></tr>
      <tr><td style="font-weight:600">Fields extracted per doc</td><td>${RAW.fields.length} (identity, financial, address)</td></tr>
      <tr><td style="font-weight:600">Models configured</td><td>${allModels().length} total, ${active.length} functional, ${failed} failed (F1=0)</td></tr>
      <tr><td style="font-weight:600">API providers</td><td>${allProviders().map(p=>p.charAt(0).toUpperCase()+p.slice(1)).join(', ')} (${allProviders().length} providers)</td></tr>
      <tr><td style="font-weight:600">Total field comparisons</td><td>${totalExtractions} expected values scored</td></tr>
      <tr><td style="font-weight:600">Best model (F1)</td><td><strong>${bestModelF1}</strong> at F1=${f1Score(bestModelF1).toFixed(3)}</td></tr>
      <tr><td style="font-weight:600">Average F1</td><td>${avgF1.toFixed(3)} across ${active.length} functional models</td></tr>
      <tr><td style="font-weight:600">Average exact-match accuracy</td><td>${pct(avgAcc)} across ${active.length} functional models</td></tr>
      <tr><td style="font-weight:600">Scoring</td><td>F1 (semantic: exact for IDs, numeric tolerance for financials, fuzzy for text)</td></tr>
      <tr><td style="font-weight:600">Model tiers</td><td>Free → Ultra-cheap → Great Value → Premium</td></tr>
    </table>`
  document.getElementById('evolution-stats').innerHTML = statsHtml

  // Cost & Speed table from extraction_stats
  const stats = RAW.extraction_stats || {}
  const statModels = Object.keys(stats).filter(m=>stats[m].total_elapsed_secs > 0)
  if(statModels.length === 0){
    document.getElementById('cost-speed-table').innerHTML = '<p style="color:var(--muted)">No extraction stats available.</p>'
    return
  }
  statModels.sort((a,b)=>stats[a].total_elapsed_secs - stats[b].total_elapsed_secs)
  let tbl = `<table><thead><tr>
    <th>Model</th><th>Provider</th><th>Total Time</th><th>Avg/Doc</th><th>Total Cost</th><th>Avg/Doc</th><th>Prompt Tokens</th><th>Completion Tokens</th>
  </tr></thead><tbody>`
  statModels.forEach(m=>{
    const s = stats[m]
    tbl += `<tr>
      <td><strong>${m}</strong></td>
      <td>${providerBadge(m)}</td>
      <td>${fmtTime(s.total_elapsed_secs, s.estimated)}</td>
      <td>${fmtTime(s.avg_secs_per_row, s.estimated)}</td>
      <td>${fmtCost(s.total_cost_usd, s.estimated)}</td>
      <td>${fmtCost(s.avg_cost_per_row, s.estimated)}</td>
      <td>${s.total_prompt_tokens.toLocaleString()}</td>
      <td>${s.total_completion_tokens.toLocaleString()}</td>
    </tr>`
  })
  tbl += '</tbody></table>'
  const hasEstimates = statModels.some(m=>stats[m].estimated)
  if(hasEstimates) tbl += '<p style="font-size:11px;color:var(--muted);margin-top:8px">~ = estimated from config pricing × avg tokens</p>'
  document.getElementById('cost-speed-table').innerHTML = tbl
}

// ── Boot ─────────────────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', ()=>{
  initialized.add('rankings')
  renderRankings()
})
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()

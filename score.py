import csv
import glob
import sys
from difflib import SequenceMatcher

from config_models_doubleword import DOUBLEWORD_MODELS
from config_models_openrouter import OPENROUTER_MODELS
from utils import get_logger

log = get_logger("score")

ALL_MODELS = {**OPENROUTER_MODELS, **DOUBLEWORD_MODELS}

# Fields where exact match is required (no fuzzy scoring)
EXACT_FIELDS = {"charity_number", "report_date"}
# Fields compared as numbers (tolerance-based)
NUMERIC_FIELDS = {"income_annually_in_british_pounds", "spending_annually_in_british_pounds"}
# All other fields use semantic (fuzzy string) comparison
NUMERIC_TOLERANCE = 0.005  # 0.5% relative tolerance


def _normalize(value):
    """Normalize a string for semantic comparison: lowercase, collapse underscores/spaces."""
    return value.lower().replace("_", " ").strip()


def _field_similarity(key, expected_val, predicted_val):
    """Return a similarity score between 0.0 and 1.0 for a field pair.

    - Exact fields: 1.0 if equal, 0.0 otherwise
    - Numeric fields: 1.0 if within tolerance, 0.0 otherwise
    - Text fields: SequenceMatcher ratio on normalized strings
    """
    if predicted_val is None:
        return 0.0

    if key in EXACT_FIELDS:
        return 1.0 if predicted_val == expected_val else 0.0

    if key in NUMERIC_FIELDS:
        try:
            exp_num = float(expected_val.replace(",", "").replace("_", ""))
            pred_num = float(predicted_val.replace(",", "").replace("_", ""))
            if exp_num == 0:
                return 1.0 if pred_num == 0 else 0.0
            return 1.0 if abs(exp_num - pred_num) / abs(exp_num) <= NUMERIC_TOLERANCE else 0.0
        except (ValueError, TypeError):
            return 0.0

    # Text fields: semantic similarity
    return SequenceMatcher(None, _normalize(expected_val), _normalize(predicted_val)).ratio()


def _mod_tag(model_name):
    cfg = ALL_MODELS.get(model_name)
    return "MM" if cfg and cfg.get("multimodal") else "text"


def get_all_items(filename):
    items = []
    with open(filename, 'r') as tsvfile:
        reader = csv.reader(tsvfile, delimiter='\t', quoting=csv.QUOTE_NONE)
        for item in reader:
            k_v_pairs = dict([itm.split('=', 1) for itm in item if '=' in itm])
            items.append(k_v_pairs)
    return items


def score(expected_items, predicted_items, verbose=True):
    """Score predicted vs expected using semantic similarity with precision, recall, F1.

    Uses field-type-aware comparison: exact match for IDs/dates, numeric tolerance for
    financial fields, and fuzzy string similarity for text fields (names, addresses).

    Returns dict with: tp, fp, fn, precision, recall, f1, fields_found, fields_total, docs.
    """
    tp = 0.0   # sum of similarity scores for matched fields
    fp = 0     # predicted but not in expected (spurious)
    fn = 0.0   # sum of (1 - similarity) for expected fields

    for row_num, expected_row in enumerate(expected_items):
        predicted_row = predicted_items[row_num] if row_num < len(predicted_items) else {}

        # Check expected fields (recall side)
        for key, expected_val in expected_row.items():
            predicted_val = predicted_row.get(key)
            sim = _field_similarity(key, expected_val, predicted_val)
            tp += sim
            fn += (1.0 - sim)
            if verbose and sim < 1.0:
                sim_str = f" (sim={sim:.2f})" if 0 < sim < 1 else ""
                log.info("  Row {}: {} expected='{}' predicted='{}'{}",
                         row_num, key, expected_val, predicted_val, sim_str)

        # Check predicted fields not in expected (precision side)
        for key in predicted_row:
            if key not in expected_row:
                fp += 1
                if verbose:
                    log.info("  Row {}: {} spurious='{}' (not in expected)",
                             row_num, key, predicted_row[key])

    fields_total = tp + fn   # total expected fields (always integer, but float for consistency)
    fields_found = tp        # correctly matched fields (sum of similarities)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "fields_found": fields_found, "fields_total": fields_total,
        "docs": len(expected_items),
    }


def _load_stats(stats_filename="data/extraction_stats.csv",
                 call_log_filename="data/extraction_call_log.csv"):
    """Load extraction stats keyed by model_short_name.

    Sources (in priority order):
    1. extraction_stats.csv (has totals directly)
    2. extraction_call_log.csv (aggregate per-row entries)
    3. config_models.py pricing × avg tokens (estimate, marked with ~)
    """
    stats = {}
    # 1. Primary: stats CSV
    try:
        with open(stats_filename, 'r') as f:
            for row in csv.DictReader(f):
                elapsed = float(row.get("total_elapsed_secs", 0))
                cost = float(row.get("total_cost_usd", 0))
                if elapsed or cost:
                    stats[row["model_short_name"]] = {
                        "elapsed_secs": elapsed, "cost_usd": cost, "estimated": False,
                    }
    except FileNotFoundError:
        pass

    # 2. Fallback: aggregate from call log
    try:
        with open(call_log_filename, 'r') as f:
            agg = {}
            for row in csv.DictReader(f):
                name = row["model_short_name"]
                if name in stats or row.get("status") == "error":
                    continue
                if name not in agg:
                    agg[name] = {"elapsed": 0.0, "prompt": 0, "completion": 0, "cost": 0.0}
                agg[name]["elapsed"] += float(row.get("elapsed_secs", 0))
                agg[name]["prompt"] += int(row.get("prompt_tokens", 0))
                agg[name]["completion"] += int(row.get("completion_tokens", 0))
                agg[name]["cost"] += float(row.get("cost_usd", 0))
            for name, a in agg.items():
                if a["elapsed"] or a["cost"]:
                    stats[name] = {
                        "elapsed_secs": a["elapsed"], "cost_usd": a["cost"],
                        "estimated": False,
                    }
    except FileNotFoundError:
        pass

    # 3. Estimate for remaining models using config pricing × avg tokens
    known_tokens = [(s["elapsed_secs"], s["cost_usd"])
                    for s in stats.values() if s["elapsed_secs"] > 0]
    if known_tokens:
        avg_elapsed = sum(t for t, _ in known_tokens) / len(known_tokens)
        avg_prompt = 180_000  # typical total prompt tokens across 11 rows
        avg_completion = 1_500
        for model_name, cfg in ALL_MODELS.items():
            if model_name not in stats:
                price_in = cfg.get("price_in", 0)
                price_out = cfg.get("price_out", 0)
                est_cost = (avg_prompt * price_in + avg_completion * price_out) / 1_000_000
                if est_cost > 0:
                    stats[model_name] = {
                        "elapsed_secs": avg_elapsed, "cost_usd": est_cost,
                        "estimated": True,
                    }

    return stats


def score_all_models(expected_filename, verbose=False):
    expected_items = get_all_items(expected_filename)
    stats = _load_stats()
    results = []
    for predicted_filename in sorted(glob.glob("data/*_dev_extracted__*.tsv")):
        # Filename: playgroup_dev_extracted__{provider}__{model}.tsv (new)
        #       or: playgroup_dev_extracted__{model}.tsv (legacy, no provider)
        after_prefix = predicted_filename.split("__", 1)[1].removesuffix(".tsv")
        if "__" in after_prefix:
            provider, model_name = after_prefix.split("__", 1)
        else:
            provider = "openrouter"
            model_name = after_prefix
        predicted_items = get_all_items(predicted_filename)
        if verbose:
            log.info("--- [{}] {} [{}] ---", provider, model_name, _mod_tag(model_name))
        scores = score(expected_items, predicted_items, verbose=verbose)
        model_stats = stats.get(model_name, {})
        results.append({
            "provider": provider,
            "model_name": model_name,
            **scores,
            "elapsed_secs": model_stats.get("elapsed_secs", 0),
            "cost_usd": model_stats.get("cost_usd", 0),
            "estimated": model_stats.get("estimated", False),
        })
    return results


if __name__ == "__main__":
    expected_filename = "data/playgroup_dev_expected.tsv"

    if len(sys.argv) > 1:
        # Score a single specified file
        predicted_filename = sys.argv[1]
        expected_items = get_all_items(expected_filename)
        predicted_items = get_all_items(predicted_filename)
        s = score(expected_items, predicted_items, verbose=True)
        ft = s['fields_total']
        ff = s['fields_found']
        pct = 100 * ff / ft if ft else 0
        print(f"\nF1: {s['f1']:.3f}  Precision: {s['precision']:.3f}  Recall: {s['recall']:.3f}"
              f"  Fields: {ff:.1f}/{ft:.0f} ({pct:.0f}%)  Docs: {s['docs']}")
    else:
        # Score all models — leaderboard ranked by F1
        results = score_all_models(expected_filename, verbose=False)
        header = (f"{'Provider':<12} {'Model':<25} {'Mod':<6} {'Docs':>4}"
                  f"  {'F1':>5}  {'Prec':>5}  {'Recall':>6}"
                  f"  {'Fields':>14}  {'Time(s)':>9}  {'Cost($)':>9}")
        print(f"\n{header}")
        print("-" * len(header))
        results.sort(key=lambda r: r["f1"], reverse=True)
        for r in results:
            prefix = "~" if r["estimated"] else ""
            time_str = f"{prefix}{r['elapsed_secs']:.1f}" if r["elapsed_secs"] else "-"
            cost_str = f"{prefix}{r['cost_usd']:.4f}" if r["cost_usd"] else "-"
            ft = r["fields_total"]
            ff = r["fields_found"]
            fields_str = f"{ff:.1f}/{ft:.0f} ({100*ff/ft:.0f}%)" if ft else "-"
            print(f"{r['provider']:<12} {r['model_name']:<25} {_mod_tag(r['model_name']):<6} {r['docs']:>4}"
                  f"  {r['f1']:>5.3f}  {r['precision']:>5.3f}  {r['recall']:>6.3f}"
                  f"  {fields_str:>14}  {time_str:>9}  {cost_str:>9}")
        # Provider summary
        by_provider = {}
        for r in results:
            p = r["provider"]
            by_provider.setdefault(p, []).append(r)

        print(f"\n  Provider Summary (active models only, F1 > 0)")
        print(f"  {'Provider':<12} {'All':>4} {'Active':>6} {'Fail':>4}  {'Avg F1':>6}  {'Best F1':>7}  {'Best Model':<25}  {'Avg Fields':>14}  {'Time(s)':>9}  {'Cost($)':>9}")
        print(f"  {'-'*112}")
        for p, models in sorted(by_provider.items()):
            active = [m for m in models if m["f1"] > 0]
            failed = len(models) - len(active)
            avg_f1 = sum(m["f1"] for m in active) / len(active) if active else 0
            best = max(models, key=lambda m: m["f1"])
            avg_ff = sum(m["fields_found"] for m in active) / len(active) if active else 0
            avg_ft = sum(m["fields_total"] for m in active) / len(active) if active else 0
            fields_str = f"{avg_ff:.1f}/{avg_ft:.0f} ({100*avg_ff/avg_ft:.0f}%)" if avg_ft else "-"
            times = [m["elapsed_secs"] for m in active if m["elapsed_secs"] > 0]
            avg_time = sum(times) / len(times) if times else 0
            time_str = f"~{avg_time:.1f}" if avg_time and all(m.get("estimated") for m in active if m["elapsed_secs"] > 0) else f"{avg_time:.1f}" if avg_time else "-"
            costs = [m["cost_usd"] for m in active if m["cost_usd"] > 0]
            avg_cost = sum(costs) / len(costs) if costs else 0
            est_cost_count = sum(1 for m in active if m["cost_usd"] > 0 and m.get("estimated"))
            cost_prefix = "~" if est_cost_count == len(costs) and costs else ""
            avg_cost_str = f"{cost_prefix}{avg_cost:.4f}" if avg_cost else "-"
            print(f"  {p:<12} {len(models):>4} {len(active):>6} {failed:>4}  {avg_f1:>6.3f}  {best['f1']:>7.3f}  {best['model_name']:<25}  {fields_str:>14}  {time_str:>9}  {avg_cost_str:>9}")

        print(f"\n  ~ = estimated from config pricing x avg tokens")
        print(f"  Fail = models with F1=0 (extraction failed or no parseable output)")
        print(f"  Scoring: exact match for IDs/dates, numeric tolerance for financials, fuzzy similarity for text")
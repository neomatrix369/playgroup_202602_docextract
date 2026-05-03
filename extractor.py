"""Unified extraction orchestrator — OpenRouter (sync), Doubleword Batch API (async), V7 Go (async).

Backend is auto-detected from model registry: Doubleword (dw-*), V7 Go (v7-*), else OpenRouter.
Doubleword and V7 runs use checkpoint/resume; V7 maps each TSV row to a V7 entity (see llm_v7.py).
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime

import llm_openrouter
from config_models_doubleword import DOUBLEWORD_MODELS
from config_models_openrouter import OPENROUTER_MODELS
from config_models_v7 import V7_MODELS
from utils import get_logger, sanitize_error_message

log = get_logger("extractor")

IN_FILENAME = "data/playgroup_dev_in.tsv"
STATS_FILENAME = "data/extraction_stats.csv"
CALL_LOG_FILENAME = "data/extraction_call_log.csv"

ALL_FIELDS = [
    "charity_number",
    "charity_name",
    "report_date",
    "income_annually_in_british_pounds",
    "spending_annually_in_british_pounds",
    "address__postcode",
    "address__post_town",
    "address__street_line",
]

PROMPT_TEMPLATE = """You are an expert at extracting information from UK charity financial documents.
You are given a block of text extracted from a UK charity financial document.
Extract the following fields and output them as a JSON block:

- charity_number: the registered charity number (digits only, e.g. "1132766")
- charity_name: the full name of the charity (e.g. "The Sanata Charitable Trust")
- report_date: the reporting period end date in YYYY-MM-DD format
- income_annually_in_british_pounds: total annual income as a number (e.g. 255653.00)
- spending_annually_in_british_pounds: total annual expenditure/outgoings as a number (e.g. 258287.00)
- address__postcode: UK postcode (e.g. "SY3 7PQ")
- address__post_town: the town/city of the charity address (e.g. "SHREWSBURY")
- address__street_line: the street address line (e.g. "58 TRINITY STREET")

Only include fields you are confident about. Output ONLY the JSON block, nothing else.

```
{
    "charity_number": "1132766",
    "charity_name": "The Sanata Charitable Trust",
    "report_date": "2015-12-31",
    "income_annually_in_british_pounds": 255653.00,
    "spending_annually_in_british_pounds": 258287.00,
    "address__postcode": "SY3 7PQ",
    "address__post_town": "SHREWSBURY",
    "address__street_line": "58 TRINITY STREET"
}
```

The raw text from the document follows:

"""

ADDRESS_FIELDS = {"address__postcode", "address__post_town", "address__street_line"}
NUMERIC_FIELDS = {"income_annually_in_british_pounds", "spending_annually_in_british_pounds"}

ALL_MODELS = {**OPENROUTER_MODELS, **DOUBLEWORD_MODELS, **V7_MODELS}


def _mod_tag(multimodal):
    return "[MM]" if multimodal else "[text]"


def _format_value(key, value):
    if value is None:
        return None
    if key in NUMERIC_FIELDS:
        try:
            num = float(str(value).replace(",", "").replace("£", "").strip())
            return f"{num:.2f}"
        except (ValueError, TypeError):
            return None
    str_val = str(value).strip()
    str_val = str_val.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    if key in ADDRESS_FIELDS:
        str_val = str_val.upper()
    return str_val.replace(" ", "_")


def _parse_llm_response(response_text):
    if not response_text:
        return {}
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return {}
    result = {}
    for key, value in data.items():
        formatted = _format_value(key, value)
        if formatted is not None and formatted != "":
            result[key] = formatted
    return result


def _row_to_tsv_line(fields):
    sorted_pairs = sorted(f"{k}={v}" for k, v in fields.items())
    return "\t".join(sorted_pairs)


CALL_LOG_FIELDS = ["datetime", "provider", "model_short_name", "model_full_name", "tier", "multimodal",
                    "row_num", "pdf_filename", "status", "elapsed_secs",
                    "prompt_tokens", "completion_tokens", "cost_usd", "fields_extracted", "error"]


def _append_call_log(row_data):
    write_header = not os.path.exists(CALL_LOG_FILENAME)
    with open(CALL_LOG_FILENAME, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CALL_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row_data)


def _append_stats(provider, model_short_name, model_cfg, total, rows_with_values, rows_empty, field_counts,
                   total_elapsed_secs=0.0, total_prompt_tokens=0, total_completion_tokens=0, total_cost_usd=0.0,
                   batch_id=""):
    fieldnames = (["datetime", "provider", "model_short_name", "model_full_name", "tier", "multimodal",
                   "price_in", "price_out", "ctx",
                   "total", "rows_with_values", "rows_empty",
                   "total_elapsed_secs", "total_prompt_tokens", "total_completion_tokens", "total_cost_usd",
                   "avg_secs_per_row", "avg_cost_per_row"] + ALL_FIELDS + ["batch_id"])
    row = {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provider": provider,
        "model_short_name": model_short_name,
        "model_full_name": model_cfg["model"],
        "tier": model_cfg.get("tier", ""),
        "multimodal": model_cfg.get("multimodal", False),
        "price_in": model_cfg.get("price_in", 0),
        "price_out": model_cfg.get("price_out", 0),
        "ctx": model_cfg.get("ctx", 0),
        "total": total,
        "rows_with_values": rows_with_values,
        "rows_empty": rows_empty,
        "total_elapsed_secs": round(total_elapsed_secs, 2),
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_cost_usd": round(total_cost_usd, 6),
        "avg_secs_per_row": round(total_elapsed_secs / total, 2) if total else 0,
        "avg_cost_per_row": round(total_cost_usd / total, 6) if total else 0,
        **{f: field_counts.get(f, 0) for f in ALL_FIELDS},
        "batch_id": batch_id,
    }
    write_header = not os.path.exists(STATS_FILENAME)
    with open(STATS_FILENAME, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    log.debug("Stats appended to {}", STATS_FILENAME)


def _print_summary(provider, model_short_name, multimodal, rows_with_values, rows_empty, field_counts,
                    total_elapsed_secs=None, total_prompt_tokens=None, total_completion_tokens=None,
                    total_cost_usd=None, rows_error=0):
    total = rows_with_values + rows_empty
    log.info("[{}] {} {} summary", provider, model_short_name, _mod_tag(multimodal))
    log.info("  Rows with values : {}/{}", rows_with_values, total)
    rows_no_values = rows_empty - rows_error
    if rows_error:
        log.error("  Rows errored     : {}/{}", rows_error, total)
        log.info("  Rows empty       : {}/{}", rows_no_values, total)
    else:
        log.info("  Rows empty       : {}/{}", rows_empty, total)
    if total_elapsed_secs is not None:
        log.info("  Total time       : {:.1f}s", total_elapsed_secs)
    if total_prompt_tokens is not None:
        log.info("  Total tokens     : {} in / {} out", total_prompt_tokens, total_completion_tokens)
    if total_cost_usd is not None:
        log.info("  Total cost       : ${:.6f}", total_cost_usd)
    if field_counts:
        log.info("  Fields found (out of rows with values):")
        for field, count in sorted(field_counts.items()):
            log.info("    {}: {}/{}", field, count, rows_with_values)


# ═══════════════════════════════════════════════════════════════════
#  OpenRouter backend (synchronous, one row at a time)
# ═══════════════════════════════════════════════════════════════════

def _run_openrouter(model_short_name):
    """Run extraction for one OpenRouter model. Returns status: 'completed', 'skipped', or 'failed'."""
    model_cfg = OPENROUTER_MODELS[model_short_name]
    model = model_cfg["model"]
    multimodal = model_cfg["multimodal"]
    max_ctx_tokens = model_cfg.get("ctx")
    out_filename = f"data/playgroup_dev_extracted__openrouter__{model_short_name}.tsv"

    if os.path.exists(out_filename):
        log.warning("[OpenRouter] Skipping {} {}: {} already exists", model_short_name, _mod_tag(multimodal), out_filename)
        return "skipped"

    log.info("[OpenRouter] Model: {} ({}) {}", model_short_name, model, _mod_tag(multimodal))
    log.info("[OpenRouter] Output: {}", out_filename)

    price_in = model_cfg.get("price_in", 0)
    price_out = model_cfg.get("price_out", 0)

    rows_with_values = 0
    rows_empty = 0
    field_counts = {}
    total_elapsed_secs = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost_usd = 0.0

    csv.field_size_limit(10 * 1024 * 1024)
    with open(IN_FILENAME, "r") as infile, open(out_filename, "w") as outfile:
        reader = csv.reader(infile, delimiter="\t", quoting=csv.QUOTE_NONE)
        for row_num, row in enumerate(reader):
            assert len(row) == 6, f"Expected 6 cols, got {len(row)} in row {row_num}"
            pdf_filename, _keys, text_djvu2hocr, text_tesseract411, text_tesseractmarch2020, text_combined = row

            log.info("[OpenRouter] Processing row {}: {}", row_num, pdf_filename)
            call_log_base = {
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "provider": "OpenRouter",
                "model_short_name": model_short_name,
                "model_full_name": model,
                "tier": model_cfg.get("tier", ""),
                "multimodal": multimodal,
                "row_num": row_num,
                "pdf_filename": pdf_filename,
            }
            try:
                result = llm_openrouter.call_llm(model, PROMPT_TEMPLATE, text_combined, max_ctx_tokens=max_ctx_tokens)
                fields = _parse_llm_response(result["text"])
            except Exception as e:
                error_msg = sanitize_error_message(str(e)).replace("\t", " ").replace("\n", " ")
                line = f"error={error_msg}"
                outfile.write(line + "\n")
                rows_empty += 1
                log.error("[OpenRouter] -> ERROR: {}", error_msg[:120])
                _append_call_log({**call_log_base, "status": "error", "elapsed_secs": 0,
                                  "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0,
                                  "fields_extracted": 0, "error": error_msg[:500]})
                continue

            row_cost = (result["prompt_tokens"] * price_in + result["completion_tokens"] * price_out) / 1_000_000
            total_elapsed_secs += result["elapsed_secs"]
            total_prompt_tokens += result["prompt_tokens"]
            total_completion_tokens += result["completion_tokens"]
            total_cost_usd += row_cost

            line = _row_to_tsv_line(fields)
            outfile.write(line + "\n")

            if fields:
                rows_with_values += 1
                log.info("  [OpenRouter] -> {}  [{}s, ${:.6f}]", line[:100], result['elapsed_secs'], row_cost)
                for key in fields:
                    field_counts[key] = field_counts.get(key, 0) + 1
            else:
                rows_empty += 1
                log.warning("  [OpenRouter] -> (no values extracted)  [{}s]", result['elapsed_secs'])

            _append_call_log({**call_log_base, "status": "ok" if fields else "empty",
                              "elapsed_secs": result["elapsed_secs"],
                              "prompt_tokens": result["prompt_tokens"],
                              "completion_tokens": result["completion_tokens"],
                              "cost_usd": round(row_cost, 6),
                              "fields_extracted": len(fields), "error": ""})

    _print_summary("OpenRouter", model_short_name, multimodal, rows_with_values, rows_empty, field_counts,
                   total_elapsed_secs, total_prompt_tokens, total_completion_tokens, total_cost_usd)
    _append_stats("OpenRouter", model_short_name, model_cfg, rows_with_values + rows_empty, rows_with_values, rows_empty,
                  field_counts, total_elapsed_secs, total_prompt_tokens, total_completion_tokens, total_cost_usd)
    return "completed"


# ═══════════════════════════════════════════════════════════════════
#  Doubleword backend (batch API with checkpoint/resume support)
#  Two-phase: submit all models first, then poll all until complete.
# ═══════════════════════════════════════════════════════════════════

DOUBLEWORD_POLL_INTERVAL = 10  # seconds between poll cycles
V7_POLL_INTERVAL = 5  # V7 entity polling (lighter than DW batch file generation)


_PROMPT_OVERHEAD_TOKENS = 500   # system + user prompt template + JSON response budget
_CHARS_PER_TOKEN = 3            # conservative for whitespace-heavy OCR text


def _truncate_rows_to_ctx(rows, model_cfg) -> list:
    """Return rows with text_combined truncated to fit within the model's context window.

    Uses a conservative 3 chars/token estimate (OCR text has lots of whitespace).
    Logs a warning for each row that gets truncated.
    """
    ctx = model_cfg.get("ctx", 262_000)
    max_chars = (ctx - _PROMPT_OVERHEAD_TOKENS) * _CHARS_PER_TOKEN
    model_name = model_cfg.get("model", "?")
    truncated = []
    for row_num, pdf_filename, text_combined in rows:
        if len(text_combined) > max_chars:
            log.warning(
                "[Ctx] Truncating row {} ({}) for {}: {} chars → {} (ctx={:,})",
                row_num, pdf_filename, model_name,
                len(text_combined), max_chars, ctx,
            )
            truncated.append((row_num, pdf_filename, text_combined[:max_chars]))
        else:
            truncated.append((row_num, pdf_filename, text_combined))
    return truncated


def _dw_submit_rows(rows, model_cfg):
    """Rows for Doubleword submit_batch: OCR models skip text truncation (they receive images)."""
    if model_cfg.get("ocr"):
        return rows
    return _truncate_rows_to_ctx(rows, model_cfg)


def _v7_submit_rows(rows, model_cfg):
    """Rows passed to V7 submit_batch: PDF path skips OCR truncation (multimodal)."""
    if model_cfg.get("multimodal"):
        return rows
    return _truncate_rows_to_ctx(rows, model_cfg)


def _resolve_v7_agent_template_cli_path(path: str) -> str:
    """Match llm_v7._resolve_template_path: cwd-relative names resolve against this repo root."""
    p = path.strip()
    if os.path.isabs(p):
        return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), p)


def _v7_model_cfg_for_run(model_short_name: str, agent_template_json_override: str | None) -> dict:
    cfg = dict(V7_MODELS[model_short_name])
    # Only a non-empty path overrides — empty string used to mean "clear" would wipe registry
    # agent_template_json and force legacy multimodal + document-text (wrong for Go Agent v2).
    if agent_template_json_override is not None and str(agent_template_json_override).strip():
        cfg["agent_template_json"] = str(agent_template_json_override).strip()
    return cfg


def _v7_sync_templates_when_all_v7(
    v7_models: list[str], agent_template_override: str | None
) -> None:
    """``--all-v7`` only: refresh each distinct ``agent_template_json`` from the V7 API (idempotent).

    Writes e.g. ``v7_go_agent_v2_template.json`` before submit so Go Agent v2 runs do not require a
    pre-checked-in export. Per-PDF property gaps are handled in ``llm_v7`` (preflight + optional auto-ensure).
    """
    import sync_v7_go_agent_template as sync_tpl

    seen: set[str] = set()
    for model_short_name in v7_models:
        cfg = _v7_model_cfg_for_run(model_short_name, agent_template_override)
        rel = cfg.get("agent_template_json")
        if not rel:
            continue
        out = _resolve_v7_agent_template_cli_path(str(rel))
        if out in seen:
            continue
        seen.add(out)
        changed = sync_tpl.sync_v7_go_agent_template_to_path(out, validate_parse=True)
        import llm_v7

        llm_v7.invalidate_go_agent_template_cache(out)
        log.info(
            "[V7] --all-v7: synced agent template {} ({})",
            out,
            "wrote or updated" if changed else "unchanged",
        )


def _log_v7_skipped_marked_unavailable(model_short_name: str, reason: str, model_cfg: dict) -> None:
    """Log expanded context when a model is skipped because it is listed in .v7_unavailable_models.json."""
    import llm_v7

    log.warning("[V7] Skipping {} — marked unavailable: {}", model_short_name, reason)
    try:
        ctx = llm_v7.resolved_v7_settings_for_log(model_cfg)
        log.warning("[V7]   Resolved settings (no secrets):\n{}", json.dumps(ctx, indent=2, default=str))
    except Exception as e:
        log.warning("[V7]   (could not build settings snapshot: {})", e)
    for hint in llm_v7.hints_for_v7_unavailable_reason(model_short_name, reason, model_cfg):
        log.warning("[V7]   Hint: {}", hint)


def _load_input_rows():
    """Load all input rows from the TSV. Returns list of (row_num, pdf_filename, text_combined)."""
    csv.field_size_limit(10 * 1024 * 1024)
    rows = []
    with open(IN_FILENAME, "r") as infile:
        reader = csv.reader(infile, delimiter="\t", quoting=csv.QUOTE_NONE)
        for row_num, row in enumerate(reader):
            assert len(row) == 6, f"Expected 6 cols, got {len(row)} in row {row_num}"
            rows.append((row_num, row[0], row[5]))
    return rows


def _write_doubleword_results(model_short_name, results, rows, elapsed_secs, batch_id=""):
    """Write batch results to TSV, per-row call logs, and model stats.

    Uses atomic write (temp file + rename) so a partial file is never left behind on cancel.
    Also saves a failed-rows manifest so --retry-failed can re-submit only the failed row indices.
    """
    model_cfg = DOUBLEWORD_MODELS[model_short_name]
    model = model_cfg["model"]
    multimodal = model_cfg["multimodal"]
    price_in = model_cfg.get("price_in", 0)
    price_out = model_cfg.get("price_out", 0)
    out_filename = f"data/playgroup_dev_extracted__doubleword__{model_short_name}.tsv"
    tmp_filename = out_filename + ".tmp"

    rows_with_values = 0
    rows_empty = 0
    rows_error = 0
    field_counts = {}
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost_usd = 0.0

    with open(tmp_filename, "w") as outfile:
        for row_num, pdf_filename, _text in rows:
            result = results.get(row_num)
            call_log_base = {
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "provider": "Doubleword",
                "model_short_name": model_short_name,
                "model_full_name": model,
                "tier": model_cfg.get("tier", ""),
                "multimodal": multimodal,
                "row_num": row_num,
                "pdf_filename": pdf_filename,
            }

            if result is None or "error" in result:
                error_msg = result["error"][:500] if result else "No result returned"
                outfile.write(f"error={error_msg}\n")
                rows_empty += 1
                rows_error += 1
                log.error("  [Doubleword] {} row {} -> ERROR: {}", model_short_name, row_num, error_msg[:200])
                _append_call_log({**call_log_base, "status": "error", "elapsed_secs": 0,
                                  "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0,
                                  "fields_extracted": 0, "error": error_msg[:500]})
                continue

            fields = _parse_llm_response(result["text"])
            line = _row_to_tsv_line(fields)
            outfile.write(line + "\n")

            prompt_tokens = result.get("prompt_tokens", 0)
            completion_tokens = result.get("completion_tokens", 0)
            row_cost = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
            total_prompt_tokens += prompt_tokens
            total_completion_tokens += completion_tokens
            total_cost_usd += row_cost

            if fields:
                rows_with_values += 1
                log.info("  [Doubleword] {} row {} -> {}  [${:.6f}]", model_short_name, row_num, line[:100], row_cost)
                for key in fields:
                    field_counts[key] = field_counts.get(key, 0) + 1
            else:
                rows_empty += 1
                log.warning("  [Doubleword] {} row {} -> (no values extracted)", model_short_name, row_num)

            _append_call_log({**call_log_base, "status": "ok" if fields else "empty",
                              "elapsed_secs": 0, "prompt_tokens": prompt_tokens,
                              "completion_tokens": completion_tokens,
                              "cost_usd": round(row_cost, 6),
                              "fields_extracted": len(fields), "error": ""})

    os.replace(tmp_filename, out_filename)

    _print_summary("Doubleword", model_short_name, multimodal, rows_with_values, rows_empty, field_counts,
                   elapsed_secs, total_prompt_tokens, total_completion_tokens, total_cost_usd,
                   rows_error=rows_error)
    _append_stats("Doubleword", model_short_name, model_cfg,
                  rows_with_values + rows_empty, rows_with_values, rows_empty, field_counts,
                  elapsed_secs, total_prompt_tokens, total_completion_tokens, total_cost_usd,
                  batch_id=batch_id)

    # ── Failed rows manifest ────────────────────────────────────────
    import llm_doubleword
    failed_row_nums = [
        row_num for row_num, _pdf, _text in rows
        if results.get(row_num) is None or "error" in results.get(row_num, {})
    ]
    if failed_row_nums:
        llm_doubleword.update_failed_rows_entry(model_short_name, failed_row_nums)
        # Cat A detection: ALL rows failed — likely model not available to this account
        if len(failed_row_nums) == len(rows):
            sample_error = (results.get(rows[0][0]) or {}).get("error", "")
            if any(kw in sample_error.lower() for kw in ("not configured", "not available")):
                log.warning("=" * 60)
                log.warning("[Doubleword] !! ALL {} rows for '{}' failed with: {}",
                            len(rows), model_short_name, sample_error[:200])
                log.warning("[Doubleword] !! This model may not be available on your account.")
                log.warning("[Doubleword] !! Consider setting 'deprecated': True for '{}' in config.",
                            model_short_name)
                log.warning("=" * 60)
            else:
                log.warning("[Doubleword] All {} rows failed for '{}' — check errors above.",
                            len(rows), model_short_name)
    else:
        llm_doubleword.remove_failed_rows_entry(model_short_name)


def _write_v7_results(model_short_name, results, rows, elapsed_secs, batch_id=""):
    """Write V7 entity results to TSV, per-row call logs, and model stats (mirrors _write_doubleword_results)."""
    import llm_v7

    model_cfg = V7_MODELS[model_short_name]
    model = model_cfg["model"]
    multimodal = model_cfg["multimodal"]
    price_in = model_cfg.get("price_in", 0)
    price_out = model_cfg.get("price_out", 0)
    safe_name = model_short_name.replace("/", "__")
    out_filename = f"data/playgroup_dev_extracted__v7__{safe_name}.tsv"
    tmp_filename = out_filename + ".tmp"

    rows_with_values = 0
    rows_empty = 0
    rows_error = 0
    field_counts = {}
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost_usd = 0.0

    with open(tmp_filename, "w") as outfile:
        for row_num, pdf_filename, _text in rows:
            result = results.get(row_num)
            call_log_base = {
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "provider": "V7",
                "model_short_name": model_short_name,
                "model_full_name": model,
                "tier": model_cfg.get("tier", ""),
                "multimodal": multimodal,
                "row_num": row_num,
                "pdf_filename": pdf_filename,
            }

            if result is None or "error" in result:
                error_msg = (result or {}).get("error", "No result returned")[:500]
                outfile.write(f"error={error_msg}\n")
                rows_empty += 1
                rows_error += 1
                log.error("  [V7] {} row {} -> ERROR: {}", model_short_name, row_num, error_msg[:200])
                _append_call_log({**call_log_base, "status": "error", "elapsed_secs": 0,
                                  "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0,
                                  "fields_extracted": 0, "error": error_msg[:500]})
                continue

            fields = _parse_llm_response(result["text"])
            line = _row_to_tsv_line(fields)
            outfile.write(line + "\n")

            prompt_tokens = result.get("prompt_tokens", 0)
            completion_tokens = result.get("completion_tokens", 0)
            row_cost = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
            total_prompt_tokens += prompt_tokens
            total_completion_tokens += completion_tokens
            total_cost_usd += row_cost

            if fields:
                rows_with_values += 1
                log.info("  [V7] {} row {} -> {}  [${:.6f}]", model_short_name, row_num, line[:100], row_cost)
                for key in fields:
                    field_counts[key] = field_counts.get(key, 0) + 1
            else:
                rows_empty += 1
                log.warning("  [V7] {} row {} -> (no values extracted)", model_short_name, row_num)

            _append_call_log({**call_log_base, "status": "ok" if fields else "empty",
                              "elapsed_secs": 0, "prompt_tokens": prompt_tokens,
                              "completion_tokens": completion_tokens,
                              "cost_usd": round(row_cost, 6),
                              "fields_extracted": len(fields), "error": ""})

    os.replace(tmp_filename, out_filename)

    _print_summary("V7", model_short_name, multimodal, rows_with_values, rows_empty, field_counts,
                   elapsed_secs, total_prompt_tokens, total_completion_tokens, total_cost_usd,
                   rows_error=rows_error)
    _append_stats("V7", model_short_name, model_cfg,
                  rows_with_values + rows_empty, rows_with_values, rows_empty, field_counts,
                  elapsed_secs, total_prompt_tokens, total_completion_tokens, total_cost_usd,
                  batch_id=batch_id)

    failed_row_nums = [
        row_num for row_num, _pdf, _text in rows
        if results.get(row_num) is None or "error" in results.get(row_num, {})
    ]
    if failed_row_nums:
        llm_v7.update_failed_rows_entry(model_short_name, failed_row_nums)
        if len(failed_row_nums) == len(rows):
            sample_error = (results.get(rows[0][0]) or {}).get("error", "")
            log.warning("[V7] All {} rows failed for '{}' — sample: {}", len(rows), model_short_name, sample_error[:200])
    else:
        llm_v7.remove_failed_rows_entry(model_short_name)


def _merge_doubleword_results(model_short_name, new_results, rows):
    """Merge retry results into an existing output TSV for a Doubleword model.

    Reads the existing file (one line per row, positional), replaces lines for
    the retried row_nums with recomputed values, then writes back atomically.
    Updates the failed-rows manifest: removes rows that now succeed, keeps still-failing ones.

    Returns (rows_fixed, still_failed) counts.
    """
    import llm_doubleword

    model_cfg = DOUBLEWORD_MODELS[model_short_name]
    model = model_cfg["model"]
    multimodal = model_cfg["multimodal"]
    price_in = model_cfg.get("price_in", 0)
    price_out = model_cfg.get("price_out", 0)
    out_filename = f"data/playgroup_dev_extracted__doubleword__{model_short_name}.tsv"
    tmp_filename = out_filename + ".tmp"

    with open(out_filename) as f:
        lines = f.read().splitlines()

    rows_fixed = 0
    still_failed = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for row_num, pdf_filename, _text in rows:
        if row_num not in new_results:
            continue
        result = new_results[row_num]
        call_log_base = {
            "datetime": now,
            "provider": "Doubleword",
            "model_short_name": model_short_name,
            "model_full_name": model,
            "tier": model_cfg.get("tier", ""),
            "multimodal": multimodal,
            "row_num": row_num,
            "pdf_filename": pdf_filename,
        }
        if "error" in result:
            error_msg = result["error"][:500]
            lines[row_num] = f"error={error_msg}"
            still_failed.append(row_num)
            log.error("  [Doubleword] {} row {} retry -> ERROR: {}", model_short_name, row_num, error_msg[:200])
            _append_call_log({**call_log_base, "status": "error", "elapsed_secs": 0,
                              "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0,
                              "fields_extracted": 0, "error": error_msg})
        else:
            fields = _parse_llm_response(result["text"])
            line = _row_to_tsv_line(fields)
            lines[row_num] = line
            prompt_tokens = result.get("prompt_tokens", 0)
            completion_tokens = result.get("completion_tokens", 0)
            row_cost = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
            status = "ok" if fields else "empty"
            if fields:
                rows_fixed += 1
                log.info("  [Doubleword] {} row {} FIXED -> {}  [${:.6f}]",
                         model_short_name, row_num, line[:100], row_cost)
            else:
                still_failed.append(row_num)
                log.warning("  [Doubleword] {} row {} retry: still no values extracted", model_short_name, row_num)
            _append_call_log({**call_log_base, "status": status, "elapsed_secs": 0,
                              "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                              "cost_usd": round(row_cost, 6), "fields_extracted": len(fields), "error": ""})

    with open(tmp_filename, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp_filename, out_filename)

    # Update manifest
    if still_failed:
        llm_doubleword.update_failed_rows_entry(model_short_name, still_failed)
    else:
        llm_doubleword.remove_failed_rows_entry(model_short_name)

    log.info("[Doubleword] {} retry: {} row(s) fixed, {} still failing",
             model_short_name, rows_fixed, len(still_failed))
    return rows_fixed, len(still_failed)


def _merge_v7_results(model_short_name, new_results, rows):
    """Merge V7 retry results into an existing output TSV (same positional contract as Doubleword)."""
    import llm_v7

    model_cfg = V7_MODELS[model_short_name]
    model = model_cfg["model"]
    multimodal = model_cfg["multimodal"]
    price_in = model_cfg.get("price_in", 0)
    price_out = model_cfg.get("price_out", 0)
    safe_name = model_short_name.replace("/", "__")
    out_filename = f"data/playgroup_dev_extracted__v7__{safe_name}.tsv"
    tmp_filename = out_filename + ".tmp"

    with open(out_filename) as f:
        lines = f.read().splitlines()

    rows_fixed = 0
    still_failed = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for row_num, pdf_filename, _text in rows:
        if row_num not in new_results:
            continue
        result = new_results[row_num]
        call_log_base = {
            "datetime": now,
            "provider": "V7",
            "model_short_name": model_short_name,
            "model_full_name": model,
            "tier": model_cfg.get("tier", ""),
            "multimodal": multimodal,
            "row_num": row_num,
            "pdf_filename": pdf_filename,
        }
        if "error" in result:
            error_msg = result["error"][:500]
            lines[row_num] = f"error={error_msg}"
            still_failed.append(row_num)
            log.error("  [V7] {} row {} retry -> ERROR: {}", model_short_name, row_num, error_msg[:200])
            _append_call_log({**call_log_base, "status": "error", "elapsed_secs": 0,
                              "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0,
                              "fields_extracted": 0, "error": error_msg})
        else:
            fields = _parse_llm_response(result["text"])
            line = _row_to_tsv_line(fields)
            lines[row_num] = line
            prompt_tokens = result.get("prompt_tokens", 0)
            completion_tokens = result.get("completion_tokens", 0)
            row_cost = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
            status = "ok" if fields else "empty"
            if fields:
                rows_fixed += 1
                log.info("  [V7] {} row {} FIXED -> {}  [${:.6f}]",
                         model_short_name, row_num, line[:100], row_cost)
            else:
                still_failed.append(row_num)
                log.warning("  [V7] {} row {} retry: still no values extracted", model_short_name, row_num)
            _append_call_log({**call_log_base, "status": status, "elapsed_secs": 0,
                              "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                              "cost_usd": round(row_cost, 6), "fields_extracted": len(fields), "error": ""})

    with open(tmp_filename, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp_filename, out_filename)

    if still_failed:
        llm_v7.update_failed_rows_entry(model_short_name, still_failed)
    else:
        llm_v7.remove_failed_rows_entry(model_short_name)

    log.info("[V7] {} retry: {} row(s) fixed, {} still failing",
             model_short_name, rows_fixed, len(still_failed))
    return rows_fixed, len(still_failed)


async def _retry_failed_rows_doubleword(models_to_retry, completion_window="1h"):
    """Re-submit only the failed rows from previous DW batch runs, then merge into existing TSVs.

    Reads the failed-rows manifest to determine which row indices to re-submit for each model.
    Polls the new mini-batches, then merges results back into the existing output TSV positionally.

    Returns dict of {model_short_name: status} where status is 'fixed', 'partial', 'still_failed', or 'skipped'.
    """
    import time
    import llm_doubleword

    all_rows = _load_input_rows()
    failed_manifest = llm_doubleword.load_failed_rows()
    client = llm_doubleword.create_client()
    statuses = {}

    # Filter to models that actually have failed rows recorded
    pending = {}       # model_short_name -> batch_id
    submitted_at = {}
    row_subsets = {}   # model_short_name -> list of (row_num, pdf, text) for failed rows only

    unavailable = llm_doubleword.load_unavailable_models()

    for model_short_name in models_to_retry:
        if model_short_name not in DOUBLEWORD_MODELS:
            log.warning("[Retry] '{}' not in Doubleword models, skipping", model_short_name)
            statuses[model_short_name] = "skipped"
            continue

        if model_short_name in unavailable:
            log.warning("[Retry] Skipping '{}' — marked unavailable: {}", model_short_name, unavailable[model_short_name])
            statuses[model_short_name] = "skipped"
            continue

        failed_row_nums = failed_manifest.get(model_short_name)
        if not failed_row_nums:
            log.info("[Retry] No failed rows recorded for '{}', skipping", model_short_name)
            statuses[model_short_name] = "skipped"
            continue

        out_filename = f"data/playgroup_dev_extracted__doubleword__{model_short_name}.tsv"
        if not os.path.exists(out_filename):
            log.warning("[Retry] No existing output for '{}' — run normally first", model_short_name)
            statuses[model_short_name] = "skipped"
            continue

        failed_set = set(failed_row_nums)
        subset = [(rn, pdf, text) for rn, pdf, text in all_rows if rn in failed_set]
        row_subsets[model_short_name] = subset

        model_cfg = DOUBLEWORD_MODELS[model_short_name]
        log.info("[Retry] Submitting {} failed row(s) for '{}' ({}) window={}",
                 len(subset), model_short_name, model_cfg["model"], completion_window)

        try:
            batch_id = await llm_doubleword.submit_batch(
                client, model_short_name, model_cfg["model"],
                PROMPT_TEMPLATE, _dw_submit_rows(subset, model_cfg), completion_window,
                extra_params=model_cfg.get("extra_params"),
                model_cfg=model_cfg,
            )
        except Exception as e:
            reason = str(e)
            log.error("[Retry] Failed to submit batch for '{}': {} — skipping", model_short_name, reason)
            llm_doubleword.mark_model_unavailable(model_short_name, reason)
            statuses[model_short_name] = "skipped"
            continue
        log.info("[Retry] Submitted {}: batch {}", model_short_name, batch_id)
        pending[model_short_name] = batch_id
        submitted_at[model_short_name] = time.time()

    if not pending:
        log.info("[Retry] Nothing to retry")
        await client.close()
        return statuses

    # Poll loop — same pattern as _run_all_doubleword
    log.info("[Retry] Polling {} batch(es)... (Ctrl-C to stop gracefully)", len(pending))
    interrupted = False
    try:
        while pending:
            await asyncio.sleep(DOUBLEWORD_POLL_INTERVAL)
            done = []
            poll_summary = []

            for model_short_name, batch_id in pending.items():
                try:
                    status, output_file_id, error_file_id, counts = await llm_doubleword.poll_batch(client, batch_id)
                except Exception as e:
                    log.error("[Retry][{}] Poll error: {}", model_short_name, e)
                    poll_summary.append(f"{model_short_name}:error")
                    continue

                poll_summary.append(f"{model_short_name}: {counts['completed']}/{counts['total']}")

                if status == "completed":
                    new_results = await llm_doubleword.download_results(client, output_file_id)
                    if error_file_id:
                        pre_errors = await llm_doubleword.download_error_file(client, error_file_id)
                        if pre_errors:
                            log.warning("[Retry][{}] {} row(s) still rejected before processing:",
                                        model_short_name, len(pre_errors))
                            for rn, emsg in sorted(pre_errors.items()):
                                log.warning("  row {}: {}", rn, emsg[:200])
                            for rn, emsg in pre_errors.items():
                                if rn not in new_results:
                                    new_results[rn] = {"error": emsg}
                            import sync_doubleword_models as _sync
                            for emsg in pre_errors.values():
                                detected_ctx = _sync.extract_ctx_from_error(emsg)
                                if detected_ctx:
                                    cfg_ctx = DOUBLEWORD_MODELS[model_short_name].get("ctx", 0)
                                    if detected_ctx != cfg_ctx:
                                        log.warning("[Retry][{}] DW reports actual ctx: {:,} "
                                                    "(config has {:,}) — auto-correcting",
                                                    model_short_name, detected_ctx, cfg_ctx)
                                        _sync.update_model_ctx(model_short_name, detected_ctx)
                                    break
                    rows_fixed, still_failed = _merge_doubleword_results(
                        model_short_name, new_results, row_subsets[model_short_name]
                    )
                    llm_doubleword.remove_checkpoint_entry(model_short_name)
                    done.append(model_short_name)
                    if still_failed == 0:
                        statuses[model_short_name] = "fixed"
                    elif rows_fixed > 0:
                        statuses[model_short_name] = "partial"
                    else:
                        statuses[model_short_name] = "still_failed"
                elif status in ("failed", "expired", "cancelled"):
                    if status == "expired":
                        log.error("[Retry][{}] Batch expired — consider --completion-window 24h",
                                  model_short_name)
                    elif status == "failed":
                        log.error("[Retry][{}] Batch failed (DW server-side) — try again",
                                  model_short_name)
                    else:
                        log.error("[Retry][{}] Batch cancelled", model_short_name)
                    if error_file_id:
                        pre_errors = await llm_doubleword.download_error_file(client, error_file_id)
                        if pre_errors:
                            log.error("[Retry][{}] {} row(s) in DW error file:",
                                      model_short_name, len(pre_errors))
                            for rn, emsg in sorted(pre_errors.items()):
                                log.error("  row {}: {}", rn, str(emsg)[:200])
                    llm_doubleword.remove_checkpoint_entry(model_short_name)
                    done.append(model_short_name)
                    statuses[model_short_name] = status

            for m in done:
                del pending[m]

            remaining = len(pending)
            log.debug("[Retry] {} pending  |  {}", remaining, "  ".join(poll_summary))

    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        log.warning("Interrupted — checkpoints saved, pending retries can resume next run")
        for model_short_name in pending:
            statuses[model_short_name] = "interrupted"

    await client.close()
    if not interrupted:
        log.info("[Retry] Done: {}", {m: s for m, s in statuses.items() if s != "skipped"})
    return statuses


async def _retry_failed_rows_v7(models_to_retry, v7_agent_template: str | None = None):
    """Re-submit failed rows for V7 models and merge into existing TSVs (Doubleword-shaped flow)."""
    import llm_v7

    all_rows = _load_input_rows()
    failed_manifest = llm_v7.load_failed_rows()
    client = llm_v7.create_client()
    statuses = {}

    pending = {}
    row_subsets = {}
    unavailable = llm_v7.load_unavailable_models()

    for model_short_name in models_to_retry:
        if model_short_name not in V7_MODELS:
            log.warning("[V7 Retry] '{}' not in V7_MODELS, skipping", model_short_name)
            statuses[model_short_name] = "skipped"
            continue
        if model_short_name in unavailable:
            _log_v7_skipped_marked_unavailable(
                model_short_name,
                unavailable[model_short_name],
                _v7_model_cfg_for_run(model_short_name, v7_agent_template),
            )
            statuses[model_short_name] = "skipped"
            continue
        failed_row_nums = failed_manifest.get(model_short_name)
        if not failed_row_nums:
            log.info("[V7 Retry] No failed rows for '{}', skipping", model_short_name)
            statuses[model_short_name] = "skipped"
            continue
        out_filename = f"data/playgroup_dev_extracted__v7__{model_short_name}.tsv"
        if not os.path.exists(out_filename):
            log.warning("[V7 Retry] No output for '{}' — run full extraction first", model_short_name)
            statuses[model_short_name] = "skipped"
            continue

        failed_set = set(failed_row_nums)
        subset = [(rn, pdf, text) for rn, pdf, text in all_rows if rn in failed_set]
        row_subsets[model_short_name] = subset
        model_cfg = _v7_model_cfg_for_run(model_short_name, v7_agent_template)
        log.info("[V7 Retry] Submitting {} failed row(s) for '{}' ({})",
                 len(subset), model_short_name, model_cfg["model"])
        try:
            batch_id = await llm_v7.submit_batch(
                client, model_short_name, model_cfg["model"],
                PROMPT_TEMPLATE, _v7_submit_rows(subset, model_cfg),
                extra_params=model_cfg.get("extra_params"),
                model_cfg=model_cfg,
            )
        except Exception as e:
            reason = str(e)
            log.error("[V7 Retry] Submit failed for '{}': {}", model_short_name, reason)
            llm_v7.mark_model_unavailable(model_short_name, reason)
            statuses[model_short_name] = "skipped"
            continue
        pending[model_short_name] = batch_id
        log.info("[V7 Retry] Submitted {}: batch {}", model_short_name, batch_id)

    if not pending:
        log.info("[V7 Retry] Nothing to retry")
        await client.aclose()
        return statuses

    log.info("[V7 Retry] Polling {} batch(es)...", len(pending))
    interrupted = False
    try:
        while pending:
            await asyncio.sleep(V7_POLL_INTERVAL)
            done = []
            for model_short_name, batch_id in pending.items():
                try:
                    status, output_file_id, _err_fid, counts = await llm_v7.poll_batch(client, batch_id)
                except Exception as e:
                    log.error("[V7 Retry][{}] Poll error: {}", model_short_name, e)
                    continue
                log.debug("[V7 Retry] {} {}/{}", model_short_name, counts.get("completed"), counts.get("total"))
                if status == "completed":
                    new_results = await llm_v7.download_results(client, output_file_id)
                    rows_fixed, still_failed = _merge_v7_results(
                        model_short_name, new_results, row_subsets[model_short_name]
                    )
                    llm_v7.remove_checkpoint_entry(model_short_name)
                    done.append(model_short_name)
                    if still_failed == 0:
                        statuses[model_short_name] = "fixed"
                    elif rows_fixed > 0:
                        statuses[model_short_name] = "partial"
                    else:
                        statuses[model_short_name] = "still_failed"
                elif status == "failed":
                    llm_v7.remove_checkpoint_entry(model_short_name)
                    done.append(model_short_name)
                    statuses[model_short_name] = "failed"
            for m in done:
                del pending[m]
    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        for model_short_name in pending:
            statuses[model_short_name] = "interrupted"

    await client.aclose()
    if not interrupted:
        log.info("[V7 Retry] Done: {}", {m: s for m, s in statuses.items() if s != "skipped"})
    return statuses


async def _run_all_doubleword(models_to_run, completion_window="1h"):
    """Submit all Doubleword models, then poll all batches until complete.

    Returns dict of {model_short_name: status} where status is
    'completed', 'failed', or 'skipped'.
    """
    import time
    import llm_doubleword

    rows = _load_input_rows()
    checkpoint = llm_doubleword.load_checkpoint()
    unavailable = llm_doubleword.load_unavailable_models()
    client = llm_doubleword.create_client()
    statuses = {}  # model_short_name -> status

    # ── Phase 1: Triage models into new vs resumable ───────────
    pending = {}  # model_short_name -> batch_id (ordered: resumed first, then new)
    submitted_at = {}  # model_short_name -> epoch timestamp
    to_submit = []  # models needing fresh submission
    to_resume = []  # (model_short_name, batch_id, submitted_at) from checkpoint

    for model_short_name in models_to_run:
        model_cfg = DOUBLEWORD_MODELS[model_short_name]
        multimodal = model_cfg["multimodal"]
        out_filename = f"data/playgroup_dev_extracted__doubleword__{model_short_name}.tsv"

        if model_short_name in unavailable:
            log.warning("[Doubleword] Skipping {} — marked unavailable: {}", model_short_name, unavailable[model_short_name])
            statuses[model_short_name] = "skipped"
            continue

        if os.path.exists(out_filename):
            log.warning("[Doubleword] Skipping {} {}: {} already exists", model_short_name, _mod_tag(multimodal), out_filename)
            statuses[model_short_name] = "skipped"
            continue

        if model_short_name in checkpoint:
            to_resume.append(model_short_name)
        else:
            to_submit.append(model_short_name)

    # ── Phase 2: Submit new models first (get them queued ASAP) ──
    for model_short_name in to_submit:
        model_cfg = DOUBLEWORD_MODELS[model_short_name]
        multimodal = model_cfg["multimodal"]
        log.info("[Doubleword] Submitting {} ({}) {}, {} rows, window={}",
                 model_short_name, model_cfg['model'], _mod_tag(multimodal), len(rows), completion_window)
        try:
            batch_id = await llm_doubleword.submit_batch(
                client, model_short_name, model_cfg["model"],
                PROMPT_TEMPLATE, _dw_submit_rows(rows, model_cfg), completion_window,
                extra_params=model_cfg.get("extra_params"),
                model_cfg=model_cfg,
            )
        except Exception as e:
            reason = str(e)
            log.error("[Doubleword] Failed to submit '{}': {} — skipping", model_short_name, reason)
            llm_doubleword.mark_model_unavailable(model_short_name, reason)
            statuses[model_short_name] = "skipped"
            continue
        log.info("[Doubleword] Submitted {}: batch {}", model_short_name, batch_id)
        pending[model_short_name] = batch_id
        submitted_at[model_short_name] = time.time()

    # ── Phase 3: Verify and resume checkpointed models ───────────
    #   These were submitted earlier, so they're closer to completion.
    #   Added to pending AFTER new submissions so poll order is: resumed (oldest) first.
    resumed_pending = {}
    for model_short_name in to_resume:
        cp_entry = checkpoint[model_short_name]
        batch_id = cp_entry["batch_id"]
        try:
            status, _, _err_fid, counts = await llm_doubleword.poll_batch(client, batch_id)
        except Exception as e:
            log.warning("[Doubleword] Batch {} for {} not found ({}), resubmitting",
                        batch_id, model_short_name, e)
            llm_doubleword.remove_checkpoint_entry(model_short_name)
            model_cfg = DOUBLEWORD_MODELS[model_short_name]
            multimodal = model_cfg["multimodal"]
            log.info("[Doubleword] Submitting {} ({}) {}, {} rows, window={}",
                     model_short_name, model_cfg['model'], _mod_tag(multimodal), len(rows), completion_window)
            try:
                batch_id = await llm_doubleword.submit_batch(
                    client, model_short_name, model_cfg["model"],
                    PROMPT_TEMPLATE, _dw_submit_rows(rows, model_cfg), completion_window,
                    extra_params=model_cfg.get("extra_params"),
                    model_cfg=model_cfg,
                )
            except Exception as sub_e:
                reason = str(sub_e)
                log.error("[Doubleword] Failed to resubmit '{}': {} — skipping", model_short_name, reason)
                llm_doubleword.mark_model_unavailable(model_short_name, reason)
                statuses[model_short_name] = "skipped"
                continue
            log.info("[Doubleword] Submitted {}: batch {}", model_short_name, batch_id)
            pending[model_short_name] = batch_id
            submitted_at[model_short_name] = time.time()
            continue

        if status in ("completed", "in_progress", "validating", "finalizing"):
            multimodal = DOUBLEWORD_MODELS[model_short_name]["multimodal"]
            log.info("[Doubleword] Resuming {} {}: batch {} ({}, {}/{})",
                     model_short_name, _mod_tag(multimodal), batch_id, status, counts['completed'], counts['total'])
            resumed_pending[model_short_name] = batch_id
            submitted_at[model_short_name] = cp_entry.get("submitted_at", time.time())
        else:
            log.warning("[Doubleword] Batch {} for {} is {}, resubmitting", batch_id, model_short_name, status)
            llm_doubleword.remove_checkpoint_entry(model_short_name)
            model_cfg = DOUBLEWORD_MODELS[model_short_name]
            multimodal = model_cfg["multimodal"]
            log.info("[Doubleword] Submitting {} ({}) {}, {} rows, window={}",
                     model_short_name, model_cfg['model'], _mod_tag(multimodal), len(rows), completion_window)
            try:
                batch_id = await llm_doubleword.submit_batch(
                    client, model_short_name, model_cfg["model"],
                    PROMPT_TEMPLATE, _dw_submit_rows(rows, model_cfg), completion_window,
                    extra_params=model_cfg.get("extra_params"),
                    model_cfg=model_cfg,
                )
            except Exception as sub_e:
                reason = str(sub_e)
                log.error("[Doubleword] Failed to resubmit '{}': {} — skipping", model_short_name, reason)
                llm_doubleword.mark_model_unavailable(model_short_name, reason)
                statuses[model_short_name] = "skipped"
                continue
            log.info("[Doubleword] Submitted {}: batch {}", model_short_name, batch_id)
            pending[model_short_name] = batch_id
            submitted_at[model_short_name] = time.time()

    # Merge: resumed first (oldest, most likely to complete soon), then newly submitted
    pending = {**resumed_pending, **pending}

    if not pending:
        log.info("[Doubleword] All models already complete, nothing to do")
        await client.close()
        return statuses

    # ── Phase 4: Poll all batches until every one completes ──────
    #   Order: resumed (oldest) first, then newly submitted.
    #   Ctrl-C triggers a clean shutdown: checkpoints are preserved so
    #   the next run can resume where we left off.
    total_models = len(pending)
    completed_models = 0
    failed_models = 0
    log.info("[Doubleword] Polling {} batch(es)... (Ctrl-C to stop gracefully)", total_models)

    interrupted = False
    try:
        while pending:
            await asyncio.sleep(DOUBLEWORD_POLL_INTERVAL)
            done = []
            poll_summary = []

            for model_short_name, batch_id in pending.items():
                try:
                    status, output_file_id, error_file_id, counts = await llm_doubleword.poll_batch(client, batch_id)
                except Exception as e:
                    log.error("[{}] Poll error: {}", model_short_name, e)
                    poll_summary.append(f"{model_short_name}:error")
                    continue

                poll_summary.append(f"{model_short_name}:{counts['completed']}/{counts['total']}")

                if status == "completed":
                    api_created = counts.get("created_at")
                    api_completed = counts.get("completed_at")
                    if api_created and api_completed:
                        elapsed = api_completed - api_created
                    else:
                        elapsed = time.time() - submitted_at[model_short_name]
                    results = await llm_doubleword.download_results(client, output_file_id)
                    # Download error file for rows rejected before processing (e.g. context_length_exceeded)
                    if error_file_id:
                        pre_errors = await llm_doubleword.download_error_file(client, error_file_id)
                        if pre_errors:
                            log.warning("[{}] {} row(s) failed before processing (DW error file):",
                                        model_short_name, len(pre_errors))
                            for rn, emsg in sorted(pre_errors.items()):
                                log.warning("  row {}: {}", rn, emsg[:200])
                            # Inject into results so they appear as errors in call log
                            for rn, emsg in pre_errors.items():
                                if rn not in results:
                                    results[rn] = {"error": emsg}
                            # Parse ctx limit from error messages and auto-correct config
                            import sync_doubleword_models as _sync
                            for emsg in pre_errors.values():
                                detected_ctx = _sync.extract_ctx_from_error(emsg)
                                if detected_ctx:
                                    cfg_ctx = DOUBLEWORD_MODELS[model_short_name].get("ctx", 0)
                                    if detected_ctx != cfg_ctx:
                                        log.warning("[{}] DW reports actual ctx limit: {:,} tokens "
                                                    "(config has {:,}) — auto-correcting",
                                                    model_short_name, detected_ctx, cfg_ctx)
                                        _sync.update_model_ctx(model_short_name, detected_ctx)
                                    break  # one correction per model per batch
                    _write_doubleword_results(model_short_name, results, rows, elapsed, batch_id=batch_id)
                    llm_doubleword.remove_checkpoint_entry(model_short_name)
                    done.append(model_short_name)
                    completed_models += 1
                    statuses[model_short_name] = "completed"
                elif status in ("failed", "expired", "cancelled"):
                    if status == "expired":
                        log.error("[{}] Batch expired — next run will resubmit; "
                                  "consider --completion-window 24h if this recurs", model_short_name)
                    elif status == "failed":
                        log.error("[{}] Batch failed (DW server-side error) — "
                                  "next run will resubmit automatically", model_short_name)
                    else:
                        log.error("[{}] Batch was cancelled — resubmit manually or re-run", model_short_name)
                    if error_file_id:
                        pre_errors = await llm_doubleword.download_error_file(client, error_file_id)
                        if pre_errors:
                            log.error("[{}] {} row(s) in DW error file:", model_short_name, len(pre_errors))
                            for rn, emsg in sorted(pre_errors.items()):
                                log.error("  row {}: {}", rn, str(emsg)[:200])
                    llm_doubleword.remove_checkpoint_entry(model_short_name)
                    done.append(model_short_name)
                    failed_models += 1
                    statuses[model_short_name] = status

            for m in done:
                del pending[m]

            # Big-picture progress (debug-level to reduce noise during polling)
            remaining = len(pending)
            log.debug("[Polling] {}/{} done, {} pending, {} failed  |  {}",
                      completed_models, total_models, remaining, failed_models, "  ".join(poll_summary))

    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        log.warning("")
        log.warning("=" * 60)
        log.warning("Interrupted — shutting down gracefully")
        log.warning("  Completed so far: {}/{}", completed_models, total_models)
        log.warning("  Still pending   : {} (checkpoints saved, will resume next run)",
                     ", ".join(pending.keys()))
        log.warning("=" * 60)
        for model_short_name in pending:
            statuses[model_short_name] = "interrupted"

    await client.close()
    if not interrupted:
        log.info("[Doubleword] All batches complete ({} succeeded, {} failed)", completed_models, failed_models)
    return statuses


async def _run_all_v7(models_to_run, v7_agent_template: str | None = None):
    """Submit V7 entity jobs for each model, poll until outputs settle (checkpoint/resume like Doubleword)."""
    import time
    import llm_v7

    rows = _load_input_rows()
    checkpoint = llm_v7.load_checkpoint()
    unavailable = llm_v7.load_unavailable_models()
    client = llm_v7.create_client()
    statuses = {}

    pending = {}
    submitted_at = {}
    to_submit = []
    to_resume = []

    for model_short_name in models_to_run:
        model_cfg = _v7_model_cfg_for_run(model_short_name, v7_agent_template)
        multimodal = model_cfg["multimodal"]
        out_filename = f"data/playgroup_dev_extracted__v7__{model_short_name}.tsv"

        if model_short_name in unavailable:
            _log_v7_skipped_marked_unavailable(
                model_short_name,
                unavailable[model_short_name],
                model_cfg,
            )
            statuses[model_short_name] = "skipped"
            continue

        if os.path.exists(out_filename):
            log.warning("[V7] Skipping {} {}: {} already exists", model_short_name, _mod_tag(multimodal), out_filename)
            statuses[model_short_name] = "skipped"
            continue

        if model_short_name in checkpoint:
            to_resume.append(model_short_name)
        else:
            to_submit.append(model_short_name)

    for model_short_name in to_submit:
        model_cfg = _v7_model_cfg_for_run(model_short_name, v7_agent_template)
        multimodal = model_cfg["multimodal"]
        log.info("[V7] Submitting {} ({}) {}, {} rows",
                 model_short_name, model_cfg["model"], _mod_tag(multimodal), len(rows))
        try:
            batch_id = await llm_v7.submit_batch(
                client, model_short_name, model_cfg["model"],
                PROMPT_TEMPLATE, _v7_submit_rows(rows, model_cfg),
                extra_params=model_cfg.get("extra_params"),
                model_cfg=model_cfg,
            )
        except Exception as e:
            reason = str(e)
            log.error("[V7] Failed to submit '{}': {} — skipping", model_short_name, reason)
            llm_v7.mark_model_unavailable(model_short_name, reason)
            statuses[model_short_name] = "skipped"
            continue
        log.info("[V7] Submitted {}: batch {}", model_short_name, batch_id)
        pending[model_short_name] = batch_id
        submitted_at[model_short_name] = time.time()

    resumed_pending = {}
    for model_short_name in to_resume:
        model_cfg = _v7_model_cfg_for_run(model_short_name, v7_agent_template)
        multimodal = model_cfg["multimodal"]
        cp_entry = checkpoint[model_short_name]
        batch_id = cp_entry["batch_id"]
        try:
            status, _, _err_fid, counts = await llm_v7.poll_batch(client, batch_id)
        except Exception as e:
            log.warning("[V7] Batch {} for {} poll failed ({}), resubmitting", batch_id, model_short_name, e)
            llm_v7.remove_checkpoint_entry(model_short_name)
            log.info("[V7] Submitting {} ({}) {}, {} rows",
                     model_short_name, model_cfg["model"], _mod_tag(multimodal), len(rows))
            try:
                batch_id = await llm_v7.submit_batch(
                    client, model_short_name, model_cfg["model"],
                    PROMPT_TEMPLATE, _v7_submit_rows(rows, model_cfg),
                    extra_params=model_cfg.get("extra_params"),
                    model_cfg=model_cfg,
                )
            except Exception as sub_e:
                reason = str(sub_e)
                log.error("[V7] Failed to resubmit '{}': {} — skipping", model_short_name, reason)
                llm_v7.mark_model_unavailable(model_short_name, reason)
                statuses[model_short_name] = "skipped"
                continue
            pending[model_short_name] = batch_id
            submitted_at[model_short_name] = time.time()
            continue

        if status in ("completed", "in_progress"):
            log.info("[V7] Resuming {} {}: batch {} ({}, {}/{})",
                     model_short_name, _mod_tag(multimodal), batch_id, status, counts["completed"], counts["total"])
            resumed_pending[model_short_name] = batch_id
            submitted_at[model_short_name] = cp_entry.get("submitted_at", time.time())
        else:
            log.warning("[V7] Batch {} for {} is {}, resubmitting", batch_id, model_short_name, status)
            llm_v7.remove_checkpoint_entry(model_short_name)
            model_cfg = _v7_model_cfg_for_run(model_short_name, v7_agent_template)
            multimodal = model_cfg["multimodal"]
            log.info("[V7] Submitting {} ({}) {}, {} rows",
                     model_short_name, model_cfg["model"], _mod_tag(multimodal), len(rows))
            try:
                batch_id = await llm_v7.submit_batch(
                    client, model_short_name, model_cfg["model"],
                    PROMPT_TEMPLATE, _v7_submit_rows(rows, model_cfg),
                    extra_params=model_cfg.get("extra_params"),
                    model_cfg=model_cfg,
                )
            except Exception as sub_e:
                reason = str(sub_e)
                log.error("[V7] Failed to resubmit '{}': {} — skipping", model_short_name, reason)
                llm_v7.mark_model_unavailable(model_short_name, reason)
                statuses[model_short_name] = "skipped"
                continue
            pending[model_short_name] = batch_id
            submitted_at[model_short_name] = time.time()

    pending = {**resumed_pending, **pending}

    if not pending:
        log.info("[V7] All models already complete, nothing to do")
        await client.aclose()
        return statuses

    total_models = len(pending)
    completed_models = 0
    failed_models = 0
    log.info("[V7] Polling {} job(s)... (Ctrl-C stops gracefully)", total_models)

    interrupted = False
    try:
        while pending:
            await asyncio.sleep(V7_POLL_INTERVAL)
            done = []
            poll_summary = []

            for model_short_name, batch_id in pending.items():
                try:
                    status, output_file_id, _err_fid, counts = await llm_v7.poll_batch(client, batch_id)
                except Exception as e:
                    log.error("[{}] Poll error: {}", model_short_name, e)
                    poll_summary.append(f"{model_short_name}:error")
                    continue

                poll_summary.append(f"{model_short_name}:{counts['completed']}/{counts['total']}")

                if status == "completed":
                    api_created = counts.get("created_at")
                    api_completed = counts.get("completed_at")
                    if api_created and api_completed:
                        elapsed = float(api_completed) - float(api_created)
                    else:
                        elapsed = time.time() - submitted_at[model_short_name]
                    results = await llm_v7.download_results(client, output_file_id)
                    _write_v7_results(model_short_name, results, rows, elapsed, batch_id=batch_id)
                    llm_v7.remove_checkpoint_entry(model_short_name)
                    done.append(model_short_name)
                    completed_models += 1
                    statuses[model_short_name] = "completed"
                elif status == "failed":
                    llm_v7.remove_checkpoint_entry(model_short_name)
                    done.append(model_short_name)
                    failed_models += 1
                    statuses[model_short_name] = "failed"

            for m in done:
                del pending[m]

            remaining = len(pending)
            log.debug("[V7 Polling] {} pending  |  {}", remaining, "  ".join(poll_summary))

    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        log.warning("Interrupted — V7 checkpoints saved; re-run to resume")
        for model_short_name in pending:
            statuses[model_short_name] = "interrupted"

    await client.aclose()
    if not interrupted:
        log.info("[V7] All jobs settled ({} succeeded, {} failed)", completed_models, failed_models)
    return statuses


# ═══════════════════════════════════════════════════════════════════
#  Run summary
# ═══════════════════════════════════════════════════════════════════

def _print_provider_plan(provider, models, checkpoint=None):
    """Print pre-run plan for a provider group showing what will run/skip/resume."""
    to_run = []
    to_skip = []
    to_resume = []
    for m in models:
        out_filename = f"data/playgroup_dev_extracted__{provider}__{m}.tsv"
        if os.path.exists(out_filename):
            to_skip.append(m)
        elif checkpoint and m in checkpoint:
            to_resume.append(m)
        else:
            to_run.append(m)

    log.info("[{}] {} models", provider.capitalize(), len(models))
    if to_run:
        log.info("  Will run  : {}", ", ".join(to_run))
    if to_resume:
        log.info("  Resuming  : {}", ", ".join(to_resume))
    if to_skip:
        log.warning("  Skipping  : {} (output exists)", ", ".join(to_skip))
    if not to_run and not to_resume:
        log.warning("  Nothing to do (all skipped)")


def _print_run_summary(all_statuses):
    """Print a final summary table grouped by provider and status."""
    if not all_statuses:
        return

    # Group by status
    by_status = {}
    for (provider, model), status in all_statuses.items():
        by_status.setdefault(status, []).append((provider, model))

    log.info("=" * 60)
    log.info("Run Summary")
    log.info("=" * 60)
    for status in ("completed", "skipped", "interrupted", "failed", "cancelled", "expired", "unknown"):
        models = by_status.get(status, [])
        if not models:
            continue
        label = status.capitalize().ljust(10)
        model_list = ", ".join(f"{m} ({p})" for p, m in models)
        level = "ERROR" if status in ("failed", "cancelled", "expired", "unknown") else "INFO"
        log.log(level, "  {}: {}", label, model_list)

    total = len(all_statuses)
    completed = len(by_status.get("completed", []))
    skipped = len(by_status.get("skipped", []))
    failed_count = sum(len(by_status.get(s, [])) for s in ("failed", "cancelled", "expired", "unknown"))
    log.info("  Total: {}  |  Completed: {}  |  Skipped: {}  |  Failed: {}", total, completed, skipped, failed_count)
    log.info("=" * 60)


# ═══════════════════════════════════════════════════════════════════
#  CLI — auto-detects backend from model prefix
# ═══════════════════════════════════════════════════════════════════

def _resolve_model(model_short_name):
    """Return backend string ('doubleword', 'v7', or 'openrouter') or exit with error.

    potentially_deprecated models are NOT skipped — they still run normally.
    Only a manually set 'deprecated': True flag would retire a model (if that
    logic is ever added in future).
    """
    _v7_prefixes = {k.split("/")[0] for k in V7_MODELS if "/" in k}
    if model_short_name in V7_MODELS or model_short_name.split("/")[0] in _v7_prefixes:
        return "v7"
    if model_short_name in DOUBLEWORD_MODELS:
        cfg = DOUBLEWORD_MODELS[model_short_name]
        if cfg.get("potentially_deprecated"):
            first_seen = cfg.get("first_noticed_missing", "unknown")
            log.warning(
                "[Extractor] ⚠  '{}' is potentially_deprecated (first noticed missing: {}). "
                "Running it anyway — confirm manually to fully retire.",
                model_short_name, first_seen,
            )
        return "doubleword"
    if model_short_name in OPENROUTER_MODELS:
        return "openrouter"
    available_or = ", ".join(f"{k}{_mod_tag(OPENROUTER_MODELS[k]['multimodal'])}" for k in OPENROUTER_MODELS)
    available_dw = ", ".join(f"{k}{_mod_tag(DOUBLEWORD_MODELS[k]['multimodal'])}" for k in DOUBLEWORD_MODELS)
    available_v7 = ", ".join(f"{k}{_mod_tag(V7_MODELS[k]['multimodal'])}" for k in V7_MODELS)
    log.error("Unknown model '{}'.", model_short_name)
    log.error("  OpenRouter models: {}", available_or)
    log.error("  Doubleword models: {}", available_dw)
    log.error("  V7 Go models: {}", available_v7)
    sys.exit(1)


async def main():
    # Sync Doubleword model pricing before anything else (unless disabled)
    if not os.getenv("SKIP_DOUBLEWORD_SYNC"):
        import sync_doubleword_models
        sync_doubleword_models.sync()
        # Reload the config after sync so we pick up any changes
        import importlib
        import config_models_doubleword as _cfg_dw
        importlib.reload(_cfg_dw)
        global DOUBLEWORD_MODELS, ALL_MODELS
        DOUBLEWORD_MODELS = _cfg_dw.DOUBLEWORD_MODELS
        ALL_MODELS = {**OPENROUTER_MODELS, **DOUBLEWORD_MODELS, **V7_MODELS}
    else:
        log.info("[Main] Skipping Doubleword auto-sync (SKIP_DOUBLEWORD_SYNC set)")

    parser = argparse.ArgumentParser(
        description="Extract charity data via OpenRouter, Doubleword Batch API, or V7 Go agents. "
                    "Backend is auto-detected from model registry keys (see config_models_*.py)."
    )
    parser.add_argument("models", nargs="*",
                        help="Model short names to run (default: all models from both providers)")
    parser.add_argument("--completion-window", default="1h", choices=["1h", "24h"],
                        help="Doubleword batch completion window (default: 1h)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Re-submit only failed rows from previous Doubleword or V7 runs and merge results")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all-doubleword", action="store_true",
                       help="Run only Doubleword models")
    group.add_argument("--all-openrouter", action="store_true",
                       help="Run only OpenRouter models")
    group.add_argument("--all-v7", action="store_true",
                       help="Run only V7 Go models; refresh agent_template_json from the API before submit, "
                            "then use preflight + auto-ensure for missing properties per Go Agent v2 run")
    parser.add_argument(
        "--v7-agent-template",
        metavar="PATH",
        default=None,
        help="Go Agent v2 project export JSON: sets agent_template_json for every V7 model in this run "
             "(overrides config_models_v7); relative paths resolve from repo root like the default filename",
    )
    args = parser.parse_args()

    if args.v7_agent_template:
        _v7_t = _resolve_v7_agent_template_cli_path(args.v7_agent_template)
        if not os.path.isfile(_v7_t) and not args.all_v7:
            parser.error(
                f"--v7-agent-template: not a file: {_v7_t} (omit the flag or use --all-v7 to sync from the API first)"
            )
        args.v7_agent_template = _v7_t

    # Announce potentially_deprecated models (informational — they still run)
    pdep_dw = {k: v for k, v in DOUBLEWORD_MODELS.items() if v.get("potentially_deprecated")}
    if pdep_dw:
        log.warning("=" * 60)
        log.warning("⚠  {} POTENTIALLY DEPRECATED Doubleword model(s) — still running:",
                    len(pdep_dw))
        for short_name, cfg in pdep_dw.items():
            first_seen = cfg.get("first_noticed_missing", "unknown")
            log.warning("    • {} ({}) — first noticed missing: {}",
                        short_name, cfg["model"], first_seen)
        log.warning("  These models are included in runs — flag is informational only.")
        log.warning("  Confirm and set 'deprecated': True manually to fully retire.")
        log.warning("=" * 60)

    if args.models:
        models_to_run = args.models
    elif args.all_doubleword:
        models_to_run = list(DOUBLEWORD_MODELS)   # includes potentially_deprecated
    elif args.all_openrouter:
        models_to_run = list(OPENROUTER_MODELS)
    elif args.all_v7:
        models_to_run = list(V7_MODELS)
    else:
        models_to_run = list(ALL_MODELS)           # includes potentially_deprecated

    # Partition models by backend
    dw_models = []
    v7_models = []
    or_models = []
    for model_short_name in models_to_run:
        backend = _resolve_model(model_short_name)
        if backend == "doubleword":
            dw_models.append(model_short_name)
        elif backend == "v7":
            v7_models.append(model_short_name)
        else:
            or_models.append(model_short_name)

    # Print run plan
    log.info("=" * 60)
    log.info("Extraction run: {} OpenRouter + {} Doubleword + {} V7 models",
             len(or_models), len(dw_models), len(v7_models))
    log.info("=" * 60)

    if or_models:
        _print_provider_plan("openrouter", or_models)
    if dw_models:
        from llm_doubleword import load_checkpoint
        _print_provider_plan("doubleword", dw_models, checkpoint=load_checkpoint())
    if v7_models:
        from llm_v7 import load_checkpoint as _v7_load_checkpoint
        _print_provider_plan("v7", v7_models, checkpoint=_v7_load_checkpoint())
        if args.v7_agent_template:
            log.info("[V7] Using --v7-agent-template: {}", args.v7_agent_template)
    elif args.v7_agent_template:
        log.warning("--v7-agent-template ignored: no V7 models in this run")

    all_statuses = {}  # (provider, model) -> status

    # Run OpenRouter models sequentially (sync, one row at a time)
    if or_models:
        log.info("-" * 60)
        log.info("Starting OpenRouter ({} models)", len(or_models))
        log.info("-" * 60)
        for model_short_name in or_models:
            status = _run_openrouter(model_short_name)
            all_statuses[("openrouter", model_short_name)] = status or "failed"

    # Run Doubleword models — either full run or retry-failed-rows only
    if dw_models:
        log.info("-" * 60)
        if args.retry_failed:
            log.info("Doubleword retry-failed ({} model(s) to check)", len(dw_models))
            log.info("-" * 60)
            dw_statuses = await _retry_failed_rows_doubleword(dw_models, args.completion_window) or {}
        else:
            log.info("Starting Doubleword ({} models)", len(dw_models))
            log.info("-" * 60)
            dw_statuses = await _run_all_doubleword(dw_models, args.completion_window) or {}
        for model_short_name in dw_models:
            all_statuses[("doubleword", model_short_name)] = dw_statuses.get(model_short_name, "unknown")

    if v7_models:
        log.info("-" * 60)
        if args.all_v7:
            try:
                _v7_sync_templates_when_all_v7(v7_models, args.v7_agent_template)
            except Exception as e:
                log.error("[V7] --all-v7 template sync failed: {}", e)
                for model_short_name in v7_models:
                    all_statuses[("v7", model_short_name)] = "failed"
            else:
                if args.retry_failed:
                    log.info("V7 retry-failed ({} model(s) to check)", len(v7_models))
                    log.info("-" * 60)
                    v7_statuses = await _retry_failed_rows_v7(v7_models, args.v7_agent_template) or {}
                else:
                    log.info("Starting V7 ({} models)", len(v7_models))
                    log.info("-" * 60)
                    v7_statuses = await _run_all_v7(v7_models, args.v7_agent_template) or {}
                for model_short_name in v7_models:
                    all_statuses[("v7", model_short_name)] = v7_statuses.get(model_short_name, "unknown")
        else:
            if args.retry_failed:
                log.info("V7 retry-failed ({} model(s) to check)", len(v7_models))
                log.info("-" * 60)
                v7_statuses = await _retry_failed_rows_v7(v7_models, args.v7_agent_template) or {}
            else:
                log.info("Starting V7 ({} models)", len(v7_models))
                log.info("-" * 60)
                v7_statuses = await _run_all_v7(v7_models, args.v7_agent_template) or {}
            for model_short_name in v7_models:
                all_statuses[("v7", model_short_name)] = v7_statuses.get(model_short_name, "unknown")

    # Final summary
    _print_run_summary(all_statuses)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("\nShutdown complete.")

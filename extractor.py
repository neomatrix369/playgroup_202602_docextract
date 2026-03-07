"""Unified extraction orchestrator — supports OpenRouter (sync) and Doubleword Batch API (async).

Backend is auto-detected from model prefix: dw-* models use Doubleword, all others use OpenRouter.
Doubleword batches are submitted in parallel and polled with checkpoint/resume support.
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from datetime import datetime

import llm_openrouter
from config_models_doubleword import DOUBLEWORD_MODELS
from config_models_openrouter import OPENROUTER_MODELS
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

ALL_MODELS = {**OPENROUTER_MODELS, **DOUBLEWORD_MODELS}


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
                   total_elapsed_secs=0.0, total_prompt_tokens=0, total_completion_tokens=0, total_cost_usd=0.0):
    fieldnames = (["datetime", "provider", "model_short_name", "model_full_name", "tier", "multimodal",
                   "price_in", "price_out", "ctx",
                   "total", "rows_with_values", "rows_empty",
                   "total_elapsed_secs", "total_prompt_tokens", "total_completion_tokens", "total_cost_usd",
                   "avg_secs_per_row", "avg_cost_per_row"] + ALL_FIELDS)
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
    }
    write_header = not os.path.exists(STATS_FILENAME)
    with open(STATS_FILENAME, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    log.debug("Stats appended to %s", STATS_FILENAME)


def _print_summary(provider, model_short_name, multimodal, rows_with_values, rows_empty, field_counts,
                    total_elapsed_secs=None, total_prompt_tokens=None, total_completion_tokens=None, total_cost_usd=None):
    total = rows_with_values + rows_empty
    log.info("[%s] %s %s summary", provider, model_short_name, _mod_tag(multimodal))
    log.info("  Rows with values : %d/%d", rows_with_values, total)
    log.info("  Rows empty       : %d/%d", rows_empty, total)
    if total_elapsed_secs is not None:
        log.info("  Total time       : %.1fs", total_elapsed_secs)
    if total_prompt_tokens is not None:
        log.info("  Total tokens     : %d in / %d out", total_prompt_tokens, total_completion_tokens)
    if total_cost_usd is not None:
        log.info("  Total cost       : $%.6f", total_cost_usd)
    if field_counts:
        log.info("  Fields found (out of rows with values):")
        for field, count in sorted(field_counts.items()):
            log.info("    %s: %d/%d", field, count, rows_with_values)


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
        log.warning("[OpenRouter] Skipping %s %s: %s already exists", model_short_name, _mod_tag(multimodal), out_filename)
        return "skipped"

    log.info("[OpenRouter] Model: %s (%s) %s", model_short_name, model, _mod_tag(multimodal))
    log.info("[OpenRouter] Output: %s", out_filename)

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

            log.info("[OpenRouter] Processing row %d: %s", row_num, pdf_filename)
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
                log.error("[OpenRouter] -> ERROR: %s", error_msg[:120])
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
                log.info("  [OpenRouter] -> %s  [%ss, $%.6f]", line[:100], result['elapsed_secs'], row_cost)
                for key in fields:
                    field_counts[key] = field_counts.get(key, 0) + 1
            else:
                rows_empty += 1
                log.warning("  [OpenRouter] -> (no values extracted)  [%ss]", result['elapsed_secs'])

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


def _write_doubleword_results(model_short_name, results, rows, elapsed_secs):
    """Write batch results to TSV, per-row call logs, and model stats.

    Uses atomic write (temp file + rename) so a partial file is never left behind on cancel.
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
                log.info("  [Doubleword] %s row %d -> %s  [$%.6f]", model_short_name, row_num, line[:100], row_cost)
                for key in fields:
                    field_counts[key] = field_counts.get(key, 0) + 1
            else:
                rows_empty += 1
                log.warning("  [Doubleword] %s row %d -> (no values extracted)", model_short_name, row_num)

            _append_call_log({**call_log_base, "status": "ok" if fields else "empty",
                              "elapsed_secs": 0, "prompt_tokens": prompt_tokens,
                              "completion_tokens": completion_tokens,
                              "cost_usd": round(row_cost, 6),
                              "fields_extracted": len(fields), "error": ""})

    os.replace(tmp_filename, out_filename)

    _print_summary("Doubleword", model_short_name, multimodal, rows_with_values, rows_empty, field_counts,
                   elapsed_secs, total_prompt_tokens, total_completion_tokens, total_cost_usd)
    _append_stats("Doubleword", model_short_name, model_cfg,
                  rows_with_values + rows_empty, rows_with_values, rows_empty, field_counts,
                  elapsed_secs, total_prompt_tokens, total_completion_tokens, total_cost_usd)


async def _run_all_doubleword(models_to_run, completion_window="1h"):
    """Submit all Doubleword models, then poll all batches until complete.

    Returns dict of {model_short_name: status} where status is
    'completed', 'failed', or 'skipped'.
    """
    import time
    import llm_doubleword

    rows = _load_input_rows()
    checkpoint = llm_doubleword.load_checkpoint()
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

        if os.path.exists(out_filename):
            log.warning("[Doubleword] Skipping %s %s: %s already exists", model_short_name, _mod_tag(multimodal), out_filename)
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
        log.info("[Doubleword] Submitting %s (%s) %s, %d rows, window=%s",
                 model_short_name, model_cfg['model'], _mod_tag(multimodal), len(rows), completion_window)
        batch_id = await llm_doubleword.submit_batch(
            client, model_short_name, model_cfg["model"],
            PROMPT_TEMPLATE, rows, completion_window,
        )
        log.info("[Doubleword] Submitted %s: batch %s", model_short_name, batch_id)
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
            status, _, counts = await llm_doubleword.poll_batch(client, batch_id)
        except Exception as e:
            log.error("[Doubleword] Could not retrieve batch %s for %s: %s", batch_id, model_short_name, e)
            llm_doubleword.remove_checkpoint_entry(model_short_name)
            continue

        if status in ("completed", "in_progress", "validating", "finalizing"):
            multimodal = DOUBLEWORD_MODELS[model_short_name]["multimodal"]
            log.info("[Doubleword] Resuming %s %s: batch %s (%s, %s/%s)",
                     model_short_name, _mod_tag(multimodal), batch_id, status, counts['completed'], counts['total'])
            resumed_pending[model_short_name] = batch_id
            submitted_at[model_short_name] = cp_entry.get("submitted_at", time.time())
        else:
            log.warning("[Doubleword] Batch %s for %s is %s, resubmitting", batch_id, model_short_name, status)
            llm_doubleword.remove_checkpoint_entry(model_short_name)
            model_cfg = DOUBLEWORD_MODELS[model_short_name]
            multimodal = model_cfg["multimodal"]
            log.info("[Doubleword] Submitting %s (%s) %s, %d rows, window=%s",
                     model_short_name, model_cfg['model'], _mod_tag(multimodal), len(rows), completion_window)
            batch_id = await llm_doubleword.submit_batch(
                client, model_short_name, model_cfg["model"],
                PROMPT_TEMPLATE, rows, completion_window,
            )
            log.info("[Doubleword] Submitted %s: batch %s", model_short_name, batch_id)
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
    total_models = len(pending)
    completed_models = 0
    failed_models = 0
    log.info("[Doubleword] Polling %d batch(es)...", total_models)

    while pending:
        await asyncio.sleep(DOUBLEWORD_POLL_INTERVAL)
        done = []
        poll_summary = []

        for model_short_name, batch_id in pending.items():
            try:
                status, output_file_id, counts = await llm_doubleword.poll_batch(client, batch_id)
            except Exception as e:
                log.error("[%s] Poll error: %s", model_short_name, e)
                poll_summary.append(f"{model_short_name}:error")
                continue

            poll_summary.append(f"{model_short_name}:{counts['completed']}/{counts['total']}")

            if status == "completed":
                elapsed = time.time() - submitted_at[model_short_name]
                results = await llm_doubleword.download_results(client, output_file_id)
                _write_doubleword_results(model_short_name, results, rows, elapsed)
                llm_doubleword.remove_checkpoint_entry(model_short_name)
                done.append(model_short_name)
                completed_models += 1
                statuses[model_short_name] = "completed"
            elif status in ("failed", "expired", "cancelled"):
                log.error("[%s] Batch %s — will need manual resubmission", model_short_name, status)
                llm_doubleword.remove_checkpoint_entry(model_short_name)
                done.append(model_short_name)
                failed_models += 1
                statuses[model_short_name] = status

        for m in done:
            del pending[m]

        # Big-picture progress (debug-level to reduce noise during polling)
        remaining = len(pending)
        log.debug("[Polling] %d/%d done, %d pending, %d failed  |  %s",
                  completed_models, total_models, remaining, failed_models, "  ".join(poll_summary))

    await client.close()
    log.info("[Doubleword] All batches complete (%d succeeded, %d failed)", completed_models, failed_models)
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

    log.info("[%s] %d models", provider.capitalize(), len(models))
    if to_run:
        log.info("  Will run  : %s", ", ".join(to_run))
    if to_resume:
        log.info("  Resuming  : %s", ", ".join(to_resume))
    if to_skip:
        log.warning("  Skipping  : %s (output exists)", ", ".join(to_skip))
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
    for status in ("completed", "skipped", "failed", "cancelled", "expired", "unknown"):
        models = by_status.get(status, [])
        if not models:
            continue
        label = status.capitalize().ljust(10)
        model_list = ", ".join(f"{m} ({p})" for p, m in models)
        level = logging.ERROR if status in ("failed", "cancelled", "expired", "unknown") else logging.INFO
        log.log(level, "  %s: %s", label, model_list)

    total = len(all_statuses)
    completed = len(by_status.get("completed", []))
    skipped = len(by_status.get("skipped", []))
    failed_count = sum(len(by_status.get(s, [])) for s in ("failed", "cancelled", "expired", "unknown"))
    log.info("  Total: %d  |  Completed: %d  |  Skipped: %d  |  Failed: %d", total, completed, skipped, failed_count)
    log.info("=" * 60)


# ═══════════════════════════════════════════════════════════════════
#  CLI — auto-detects backend from model prefix
# ═══════════════════════════════════════════════════════════════════

def _resolve_model(model_short_name):
    """Return (model_cfg, backend) or exit with error."""
    if model_short_name in DOUBLEWORD_MODELS:
        return "doubleword"
    if model_short_name in OPENROUTER_MODELS:
        return "openrouter"
    available_or = ", ".join(f"{k}{_mod_tag(OPENROUTER_MODELS[k]['multimodal'])}" for k in OPENROUTER_MODELS)
    available_dw = ", ".join(f"{k}{_mod_tag(DOUBLEWORD_MODELS[k]['multimodal'])}" for k in DOUBLEWORD_MODELS)
    log.error("Unknown model '%s'.", model_short_name)
    log.error("  OpenRouter models: %s", available_or)
    log.error("  Doubleword models: %s", available_dw)
    sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(
        description="Extract charity data using OpenRouter or Doubleword Batch API. "
                    "Backend is auto-detected: dw-* models use Doubleword, others use OpenRouter."
    )
    parser.add_argument("models", nargs="*",
                        help="Model short names to run (default: all models from both providers)")
    parser.add_argument("--completion-window", default="1h", choices=["1h", "24h"],
                        help="Doubleword batch completion window (default: 1h)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all-doubleword", action="store_true",
                       help="Run only Doubleword models")
    group.add_argument("--all-openrouter", action="store_true",
                       help="Run only OpenRouter models")
    args = parser.parse_args()

    if args.models:
        models_to_run = args.models
    elif args.all_doubleword:
        models_to_run = list(DOUBLEWORD_MODELS)
    elif args.all_openrouter:
        models_to_run = list(OPENROUTER_MODELS)
    else:
        models_to_run = list(ALL_MODELS)

    # Partition models by backend
    dw_models = []
    or_models = []
    for model_short_name in models_to_run:
        backend = _resolve_model(model_short_name)
        if backend == "doubleword":
            dw_models.append(model_short_name)
        else:
            or_models.append(model_short_name)

    # Print run plan
    log.info("=" * 60)
    log.info("Extraction run: %d OpenRouter + %d Doubleword models", len(or_models), len(dw_models))
    log.info("=" * 60)

    if or_models:
        _print_provider_plan("openrouter", or_models)
    if dw_models:
        from llm_doubleword import load_checkpoint
        _print_provider_plan("doubleword", dw_models, checkpoint=load_checkpoint())

    all_statuses = {}  # (provider, model) -> status

    # Run OpenRouter models sequentially (sync, one row at a time)
    if or_models:
        log.info("-" * 60)
        log.info("Starting OpenRouter (%d models)", len(or_models))
        log.info("-" * 60)
        for model_short_name in or_models:
            status = _run_openrouter(model_short_name)
            all_statuses[("openrouter", model_short_name)] = status or "failed"

    # Run all Doubleword models as one batch: submit all, then poll all
    if dw_models:
        log.info("-" * 60)
        log.info("Starting Doubleword (%d models)", len(dw_models))
        log.info("-" * 60)
        dw_statuses = await _run_all_doubleword(dw_models, args.completion_window) or {}
        for model_short_name in dw_models:
            all_statuses[("doubleword", model_short_name)] = dw_statuses.get(model_short_name, "unknown")

    # Final summary
    _print_run_summary(all_statuses)


if __name__ == "__main__":
    asyncio.run(main())

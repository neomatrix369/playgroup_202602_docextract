"""Retroactively update local stats for completed Doubleword batches.

Queries the Doubleword Batch API to discover completed batches, downloads
their results to get token counts, and patches extraction_stats.csv and
extraction_call_log.csv with actual elapsed time, tokens, and cost.
"""

import asyncio
import csv
import json
import os

import llm_doubleword
from config_models_doubleword import DOUBLEWORD_MODELS

STATS_FILENAME = "data/extraction_stats.csv"
CALL_LOG_FILENAME = "data/extraction_call_log.csv"


def _model_full_to_short(model_full_name: str) -> str | None:
    """Reverse-lookup: model full name -> model short name."""
    for short_name, cfg in DOUBLEWORD_MODELS.items():
        if cfg["model"] == model_full_name:
            return short_name
    return None


async def _get_model_from_input_file(client, input_file_id: str) -> str | None:
    """Download a batch's input file and extract the model name from the first request."""
    try:
        content = await client.files.content(input_file_id)
        first_line = content.text.strip().split("\n")[0]
        entry = json.loads(first_line)
        return entry.get("body", {}).get("model")
    except Exception as e:
        print(f"  Could not read input file {input_file_id}: {e}")
        return None


async def _get_batch_token_totals(client, output_file_id: str) -> dict:
    """Download batch output JSONL and aggregate token counts.

    Parses directly instead of reusing download_results() to handle
    varied custom_id formats from older batches.
    """
    content = await client.files.content(output_file_id)
    text = content.text

    total_prompt = 0
    total_completion = 0
    row_results = {}

    for i, line in enumerate(text.strip().split("\n")):
        if not line:
            continue
        entry = json.loads(line)
        custom_id = entry.get("custom_id", f"row_{i}")

        # Extract row_num from custom_id (format: "row_N" or just use index)
        if "_" in custom_id:
            try:
                row_num = int(custom_id.split("_", 1)[1])
            except (ValueError, IndexError):
                row_num = i
        else:
            row_num = i

        error_data = entry.get("error")
        response_data = entry.get("response", {})

        if error_data:
            row_results[row_num] = {"error": str(error_data)}
        else:
            body = response_data.get("body", {})
            usage = body.get("usage", {})
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            total_prompt += pt
            total_completion += ct
            row_results[row_num] = {"prompt_tokens": pt, "completion_tokens": ct}

    return {
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "row_results": row_results,
    }


def _update_stats_csv(updates: dict[str, dict]):
    """Rewrite extraction_stats.csv, patching Doubleword rows with actual data.

    updates: {model_short_name: {total_elapsed_secs, total_prompt_tokens,
              total_completion_tokens, total_cost_usd, batch_id}}
    """
    rows = []
    fieldnames = None
    with open(STATS_FILENAME, "r", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        for row in reader:
            rows.append(row)

    # Add batch_id column if not present
    if "batch_id" not in fieldnames:
        fieldnames.append("batch_id")

    patched = 0
    for row in rows:
        if row["provider"] != "Doubleword":
            continue
        model = row["model_short_name"]
        if model not in updates:
            continue
        u = updates[model]
        total = int(row.get("total", 0)) or 1
        row["total_elapsed_secs"] = str(round(u["total_elapsed_secs"], 2))
        row["total_prompt_tokens"] = str(u["total_prompt_tokens"])
        row["total_completion_tokens"] = str(u["total_completion_tokens"])
        row["total_cost_usd"] = str(round(u["total_cost_usd"], 6))
        row["avg_secs_per_row"] = str(round(u["total_elapsed_secs"] / total, 2))
        row["avg_cost_per_row"] = str(round(u["total_cost_usd"] / total, 6))
        row["batch_id"] = u.get("batch_id", "")
        patched += 1
        print(f"  Patched {model}: elapsed={row['total_elapsed_secs']}s, "
              f"tokens={row['total_prompt_tokens']}/{row['total_completion_tokens']}, "
              f"cost=${row['total_cost_usd']}")

    # Atomic write
    tmp = STATS_FILENAME + ".tmp"
    with open(tmp, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # Ensure batch_id column exists for all rows
            if "batch_id" not in row:
                row["batch_id"] = ""
            writer.writerow(row)
    os.replace(tmp, STATS_FILENAME)
    print(f"\n  Updated {patched} row(s) in {STATS_FILENAME}")


def _backfill_call_log(model_short_name: str, batch_results: dict, model_cfg: dict):
    """Append per-row call log entries for a Doubleword batch."""
    from datetime import datetime
    price_in = model_cfg.get("price_in", 0)
    price_out = model_cfg.get("price_out", 0)

    fieldnames = ["datetime", "provider", "model_short_name", "model_full_name", "tier", "multimodal",
                  "row_num", "pdf_filename", "status", "elapsed_secs",
                  "prompt_tokens", "completion_tokens", "cost_usd", "fields_extracted", "error"]
    write_header = not os.path.exists(CALL_LOG_FILENAME)

    with open(CALL_LOG_FILENAME, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for row_num, result in sorted(batch_results.items()):
            if "error" in result:
                writer.writerow({
                    "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "provider": "Doubleword", "model_short_name": model_short_name,
                    "model_full_name": model_cfg["model"],
                    "tier": model_cfg.get("tier", ""), "multimodal": model_cfg.get("multimodal", False),
                    "row_num": row_num, "pdf_filename": "",
                    "status": "error", "elapsed_secs": 0,
                    "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0,
                    "fields_extracted": 0, "error": result["error"][:500],
                })
            else:
                pt = result.get("prompt_tokens", 0)
                ct = result.get("completion_tokens", 0)
                cost = (pt * price_in + ct * price_out) / 1_000_000
                writer.writerow({
                    "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "provider": "Doubleword", "model_short_name": model_short_name,
                    "model_full_name": model_cfg["model"],
                    "tier": model_cfg.get("tier", ""), "multimodal": model_cfg.get("multimodal", False),
                    "row_num": row_num, "pdf_filename": "",
                    "status": "ok", "elapsed_secs": 0,
                    "prompt_tokens": pt, "completion_tokens": ct,
                    "cost_usd": round(cost, 6), "fields_extracted": 0, "error": "",
                })


async def main():
    client = llm_doubleword.create_client()

    print("Listing batches from Doubleword API...")
    batches = await client.batches.list(limit=100)
    batch_list = [b for b in batches.data if b.status == "completed"]
    print(f"Found {len(batch_list)} completed batch(es)\n")

    # Load current stats to find which models need updating
    zero_models = set()
    with open(STATS_FILENAME, "r") as f:
        for row in csv.DictReader(f):
            if row["provider"] == "Doubleword" and float(row.get("total_prompt_tokens", 0)) == 0:
                zero_models.add(row["model_short_name"])
    print(f"Models with zero stats: {sorted(zero_models)}\n")

    updates = {}

    for batch in batch_list:
        print(f"Processing batch {batch.id}...")

        # Identify model from input file
        model_full = await _get_model_from_input_file(client, batch.input_file_id)
        if not model_full:
            print(f"  Skipping: could not determine model\n")
            continue

        model_short = _model_full_to_short(model_full)
        if not model_short:
            print(f"  Skipping: unknown model {model_full}\n")
            continue

        if model_short not in zero_models:
            print(f"  Skipping {model_short}: already has stats\n")
            continue

        print(f"  Model: {model_short} ({model_full})")

        # Compute elapsed from API timestamps
        elapsed = 0.0
        if batch.created_at and batch.completed_at:
            elapsed = batch.completed_at - batch.created_at
        print(f"  Elapsed: {elapsed:.0f}s ({elapsed/60:.1f}m)")

        # Download results for token counts
        if not batch.output_file_id:
            print(f"  Skipping: no output file\n")
            continue

        token_data = await _get_batch_token_totals(client, batch.output_file_id)
        total_prompt = token_data["total_prompt_tokens"]
        total_completion = token_data["total_completion_tokens"]

        # Compute cost from tokens × configured pricing
        model_cfg = DOUBLEWORD_MODELS[model_short]
        price_in = model_cfg.get("price_in", 0)
        price_out = model_cfg.get("price_out", 0)
        total_cost = (total_prompt * price_in + total_completion * price_out) / 1_000_000

        print(f"  Tokens: {total_prompt} in / {total_completion} out")
        print(f"  Cost: ${total_cost:.6f}")

        updates[model_short] = {
            "total_elapsed_secs": elapsed,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_cost_usd": total_cost,
            "batch_id": batch.id,
        }

        # Backfill call log
        _backfill_call_log(model_short, token_data["row_results"], model_cfg)
        print(f"  Backfilled call log entries\n")

    if updates:
        print("=" * 60)
        print("Updating extraction_stats.csv...")
        _update_stats_csv(updates)
    else:
        print("\nNo updates needed.")

    await client.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

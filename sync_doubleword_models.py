"""Sync Doubleword model pricing into config_models_doubleword.py.

Uses the agent-friendly markdown endpoint at docs.doubleword.ai (llms.txt enabled)
to fetch a clean pricing table instead of scraping HTML. Skips saving when nothing
has changed. Designed to run at the start of each extractor run.
"""

import os
import re

import httpx

from utils import get_logger

log = get_logger("sync_dw")

# The .md endpoint returns clean markdown with a parseable pricing table
PRICING_URL = "https://docs.doubleword.ai/inference-api/model-pricing.md"
CONFIG_PATH = "config_models_doubleword.py"


# Tier classification by combined price (High tier)
def _classify_tier(price_in, price_out):
    total = price_in + price_out
    if total <= 0.40:
        return "ultra_cheap"
    elif total <= 0.50:
        return "great_value"
    else:
        return "premium"


def _make_short_name(model_id):
    """Derive a dw-* short name from the HuggingFace model ID."""
    name = model_id.split("/", 1)[-1]
    lower = name.lower()

    if "nemotron" in lower:
        m = re.search(r"(\d+)b", lower)
        return f"dw-nemotron-{m.group(1)}b" if m else f"dw-{lower}"
    if "gpt-oss" in lower:
        m = re.search(r"gpt-oss-(\d+b)", lower)
        return f"dw-gpt-oss-{m.group(1)}" if m else f"dw-{lower}"

    # Qwen models: strip FP8/Instruct suffixes, keep the essential name
    name = re.sub(r"-FP\d+$", "", name)
    name = re.sub(r"-Instruct", "", name)

    for pattern in [
        r"(Qwen[\d.]+-VL-\d+B)",        # VL models
        r"(Qwen[\d.]+-Embedding-\d+B)",  # Embedding models
        r"(Qwen[\d.]+-\d+B)",            # Text models
    ]:
        match = re.match(pattern, name)
        if match:
            return f"dw-{match.group(1).lower()}"

    return f"dw-{lower}"


def _parse_markdown_table(markdown):
    """Parse the pricing markdown table and model details sections.

    The markdown has:
    1. A table with columns: Model Name | Priority | Input Tokens | Output Tokens
       Each model appears up to 3 times (Realtime, High, Standard). We want "High (1h)".
    2. Model detail sections (## headings) with context windows and descriptions.
    """
    # ── Pass 1: Extract "High (1h)" pricing from the table ──────────
    high_prices = {}   # model_id -> (price_in, price_out)
    seen_ids = []      # preserve order

    # Match table rows: | [Model/Name](#anchor) | High (1h) | $X.XX | $Y.YY |
    row_re = re.compile(
        r"\|\s*\[([^\]]+)\]\([^)]*\)\s*\|\s*High\s*\(1h\)\s*\|\s*\$([\d.]+)\s*\|\s*\$([\d.]+)\s*\|"
    )
    for m in row_re.finditer(markdown):
        model_id = m.group(1)
        price_in = float(m.group(2))
        price_out = float(m.group(3))
        high_prices[model_id] = (price_in, price_out)
        if model_id not in seen_ids:
            seen_ids.append(model_id)

    # ── Pass 2: Extract model details from <details> sections ───────
    model_details = {}
    model_id_re = re.compile(
        r"(?:Qwen/Qwen[\w.\-]+|openai/[\w.\-]+|nvidia/[\w.\-]+|"
        r"meta-llama/[\w.\-]+|google/[\w.\-]+|mistralai/[\w.\-]+)"
    )
    # The markdown uses <details id="model-N"> blocks for each model
    detail_blocks = re.split(r'<details\s+id="model-\d+">', markdown)
    for block in detail_blocks:
        match = model_id_re.search(block[:300])
        if match:
            model_details[match.group(0)] = block

    # ── Pass 3: Build model entries (skip embedding models) ────────
    models = []
    for model_id in seen_ids:
        lower_id = model_id.lower()
        if "embedding" in lower_id:
            continue

        price_in, price_out = high_prices[model_id]
        is_multimodal = "-vl-" in lower_id
        modalities = ["text", "image", "video"] if is_multimodal else ["text"]

        # Context window from details, default 262K
        ctx = 262_000
        detail = model_details.get(model_id, "")
        ctx_match = re.search(r"Max Total Tokens:.*?(\d[\d,]+)", detail)
        if ctx_match:
            ctx = (int(ctx_match.group(1).replace(",", "")) // 1000) * 1000

        # Build notes
        size_match = re.search(r"(\d+)B", model_id)
        size = size_match.group(0) if size_match else ""
        active_match = re.search(r"-A(\d+B)", model_id)
        notes_parts = []

        if active_match:
            notes_parts.append(f"{size} MoE ({active_match.group(1)} active)")
        else:
            notes_parts.append(size)

        if is_multimodal:
            notes_parts.append("vision-language")

        compare_match = re.search(
            r"performance similar to ([^.]+?)(?:\s+on|\.\s)", detail
        )
        if compare_match:
            notes_parts.append(f"~{compare_match.group(1).strip()}")

        models.append({
            "short_name": _make_short_name(model_id),
            "model": model_id,
            "multimodal": is_multimodal,
            "modalities": modalities,
            "tier": _classify_tier(price_in, price_out),
            "price_in": price_in,
            "price_out": price_out,
            "ctx": ctx,
            "notes": ", ".join(notes_parts),
        })

    return models


def _generate_config(models):
    """Generate the Python config file content matching the existing format."""
    text_models = [m for m in models if not m["multimodal"]]
    vl_models = [m for m in models if m["multimodal"]]

    def _fmt_entry(m):
        mods = "[" + ", ".join(f'"{x}"' for x in m["modalities"]) + "]"
        pin = f'{m["price_in"]:.2f}'
        pout = f'{m["price_out"]:.2f}'
        return (
            f'    "{m["short_name"]}": {{\n'
            f'        "model":      "{m["model"]}",\n'
            f'        "multimodal": {m["multimodal"]},\n'
            f'        "modalities": {mods},\n'
            f'        "tier":       "{m["tier"]}",\n'
            f'        "price_in":   {pin}, "price_out": {pout},\n'
            f'        "ctx":        {m["ctx"]:_},\n'
            f'        "notes":      "{m["notes"]}",\n'
            f'    }},'
        )

    lines = [
        "# Doubleword Batch API models — model names use HuggingFace conventions",
        "# Verify model availability at https://app.doubleword.ai/ before running",
        "# Pricing from https://docs.doubleword.ai/batches/model-pricing",
        '# Prices shown are "High" (1h) batch tier — "Standard" (24h) is ~30-50% cheaper',
        "# AUTO-GENERATED by sync_doubleword_models.py — do not edit manually",
        "",
        "DOUBLEWORD_MODELS = {",
    ]

    if text_models:
        lines += [
            "",
            "    # ═══════════════════════════════════════════════════════════",
            "    #  TEXT-ONLY MODELS",
            "    # ═══════════════════════════════════════════════════════════",
            "",
        ]
        for m in text_models:
            lines.append(_fmt_entry(m))

    if vl_models:
        lines += [
            "",
            "    # ═══════════════════════════════════════════════════════════",
            "    #  VISION-LANGUAGE MODELS",
            "    # ═══════════════════════════════════════════════════════════",
            "",
        ]
        for m in vl_models:
            lines.append(_fmt_entry(m))

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def sync(write=True):
    """Fetch pricing page, parse models, and optionally write config file.

    Returns the parsed models list. Skips writing if the generated config
    is identical to the existing file (no changes detected).
    """
    log.info("[Sync] Fetching Doubleword model pricing...")
    try:
        resp = httpx.get(PRICING_URL, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("[Sync] Could not fetch pricing page ({}), keeping existing config", e)
        return None
    log.info("[Sync] Fetched pricing data ({} bytes)", len(resp.text))

    log.info("[Sync] Parsing model pricing and details...")
    models = _parse_markdown_table(resp.text)
    if not models:
        log.warning("[Sync] No models parsed from pricing page, keeping existing config")
        return None

    log.info("[Sync] Collected {} models from Doubleword:", len(models))
    for m in models:
        tag = "[VL]" if m["multimodal"] else "[text]"
        log.info("  {} {:25s}  ${:.2f} in / ${:.2f} out  {}",
                 tag, m["short_name"], m["price_in"], m["price_out"], m["model"])

    if write:
        config_text = _generate_config(models)

        # Check if anything actually changed
        existing = ""
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                existing = f.read()

        if config_text == existing:
            log.info("[Sync] No changes detected, skipping save")
        else:
            with open(CONFIG_PATH, "w") as f:
                f.write(config_text)
            log.info("[Sync] Saved {} models to {}", len(models), CONFIG_PATH)

    return models


if __name__ == "__main__":
    sync()

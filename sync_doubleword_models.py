"""Sync Doubleword model pricing into config_models_doubleword.py.

Uses the agent-friendly markdown endpoint at docs.doubleword.ai (llms.txt enabled)
to fetch a clean pricing table instead of scraping HTML. Skips saving when nothing
has changed. Designed to run at the start of each extractor run.

IMPORTANT — augment-only policy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Models are NEVER removed from config_models_doubleword.py by this script.
If a model disappears from the remote pricing page it is marked:
    "deprecated": True,
    "deprecated_since": "YYYY-MM-DD",
and moved to the DEPRECATED MODELS section at the bottom of the file.
This preserves pricing/metadata for historical runs and makes the loss
visible in every subsequent sync log as a prominent WARNING.
"""

import os
import re
from datetime import date

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


def _load_existing_models():
    """Safely load the current DOUBLEWORD_MODELS dict from CONFIG_PATH.

    Returns an empty dict if the file doesn't exist or can't be parsed.
    """
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        namespace = {}
        with open(CONFIG_PATH, "r") as f:
            exec(f.read(), namespace)  # noqa: S102
        return namespace.get("DOUBLEWORD_MODELS", {})
    except Exception as e:
        log.warning("[Sync] Could not load existing config ({}), starting fresh", e)
        return {}


def _merge_with_existing(fetched_models, existing_models):
    """Merge freshly-fetched models into the existing model dict.

    Rules:
    - New model in API response  → added with no deprecated flag.
    - Existing model in response → pricing/metadata updated, deprecated flag cleared.
    - Existing model NOT in resp → kept as-is, deprecated=True, deprecated_since set
      only when not already set (preserves original deprecation date).

    Returns the merged list ordered: active first (text then VL), deprecated last.
    """
    today = date.today().isoformat()
    fetched_by_short = {m["short_name"]: m for m in fetched_models}

    merged = {}  # short_name -> model dict

    # Start from existing so manual hand-edits to notes/ctx are preserved.
    # Inject "short_name" because the config stores it as the dict key, not
    # as a field inside the value dict.
    for short_name, cfg in existing_models.items():
        entry = dict(cfg)
        entry.setdefault("short_name", short_name)
        merged[short_name] = entry

    # Apply/add fetched models (update existing, add new)
    for short_name, m in fetched_by_short.items():
        entry = dict(m)  # copy from fetched
        entry.pop("deprecated", None)          # clear any stale deprecated flag
        entry.pop("deprecated_since", None)
        merged[short_name] = entry

    # Flag anything in existing that's missing from the API response
    for short_name in list(merged.keys()):
        if short_name not in fetched_by_short:
            entry = merged[short_name]
            if not entry.get("deprecated"):
                entry["deprecated"] = True
                entry["deprecated_since"] = today
                log.warning(
                    "[Sync] ⚠  Model '{}' is NO LONGER in the Doubleword pricing page — "
                    "marking as deprecated (since {}). It will NOT be removed from config.",
                    short_name, today,
                )

    # ── Sort: active text, active VL, deprecated ───────────────────
    def _sort_key(item):
        _, m = item
        dep = 1 if m.get("deprecated") else 0
        vl  = 1 if m.get("multimodal") else 0
        return (dep, vl)

    return [m for _, m in sorted(merged.items(), key=_sort_key)]


def _generate_config(models):
    """Generate the Python config file content matching the existing format.

    Active models appear in TEXT-ONLY / VISION-LANGUAGE sections.
    Models flagged deprecated=True are collected in a DEPRECATED MODELS
    section at the bottom and are clearly annotated.
    """
    active  = [m for m in models if not m.get("deprecated")]
    retired = [m for m in models if m.get("deprecated")]

    text_models = [m for m in active if not m.get("multimodal")]
    vl_models   = [m for m in active if m.get("multimodal")]

    def _fmt_entry(m, *, include_deprecated=False):
        # Normalise key names — support both "short_name" (from parser)
        # and keys that may come straight from existing config dict.
        short_name = m.get("short_name") or next(
            (k for k, v in (m.items() if hasattr(m, "items") else [])), None
        )
        mods  = "[" + ", ".join(f'"{x}"' for x in m["modalities"]) + "]"
        pin   = f'{m["price_in"]:.2f}'
        pout  = f'{m["price_out"]:.2f}'
        lines = [
            f'    "{short_name}": {{',
            f'        "model":      "{m["model"]}",',
            f'        "multimodal": {m["multimodal"]},',
            f'        "modalities": {mods},',
            f'        "tier":       "{m["tier"]}",',
            f'        "price_in":   {pin}, "price_out": {pout},',
            f'        "ctx":        {m["ctx"]:_},',
            f'        "notes":      "{m["notes"]}",',
        ]
        if include_deprecated and m.get("deprecated"):
            since = m.get("deprecated_since", "unknown")
            lines += [
                f'        "deprecated":       True,',
                f'        "deprecated_since": "{since}",',
            ]
        lines.append("    },")
        return "\n".join(lines)

    output_lines = [
        "# Doubleword Batch API models — model names use HuggingFace conventions",
        "# Verify model availability at https://app.doubleword.ai/ before running",
        "# Pricing from https://docs.doubleword.ai/batches/model-pricing",
        '# Prices shown are "High" (1h) batch tier — "Standard" (24h) is ~30-50% cheaper',
        "# AUTO-GENERATED by sync_doubleword_models.py — do not edit manually",
        "# Models are NEVER removed — deprecated ones are flagged, not deleted.",
        "",
        "DOUBLEWORD_MODELS = {",
    ]

    if text_models:
        output_lines += [
            "",
            "    # ═══════════════════════════════════════════════════════════",
            "    #  TEXT-ONLY MODELS",
            "    # ═══════════════════════════════════════════════════════════",
            "",
        ]
        for m in text_models:
            output_lines.append(_fmt_entry(m))

    if vl_models:
        output_lines += [
            "",
            "    # ═══════════════════════════════════════════════════════════",
            "    #  VISION-LANGUAGE MODELS",
            "    # ═══════════════════════════════════════════════════════════",
            "",
        ]
        for m in vl_models:
            output_lines.append(_fmt_entry(m))

    if retired:
        output_lines += [
            "",
            "    # ═══════════════════════════════════════════════════════════",
            "    #  DEPRECATED MODELS  (no longer on Doubleword pricing page)",
            "    #  These entries are kept for historical reference only.",
            "    #  They are automatically skipped during extraction runs.",
            "    # ═══════════════════════════════════════════════════════════",
            "",
        ]
        for m in retired:
            output_lines.append(_fmt_entry(m, include_deprecated=True))

    output_lines.append("}")
    output_lines.append("")
    return "\n".join(output_lines)


def sync(write=True):
    """Fetch pricing page, merge with existing config, and optionally write.

    Augment-only: models absent from the remote pricing page are marked
    deprecated=True (with a deprecated_since date) rather than removed.

    Returns the full merged models list (active + deprecated).
    Skips writing if the generated config is identical to the existing file.
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
    fetched = _parse_markdown_table(resp.text)
    if not fetched:
        log.warning("[Sync] No models parsed from pricing page, keeping existing config")
        return None

    log.info("[Sync] API returned {} model(s):", len(fetched))
    for m in fetched:
        tag = "[VL]" if m["multimodal"] else "[text]"
        log.info("  {} {:28s}  ${:.2f} in / ${:.2f} out  {}",
                 tag, m["short_name"], m["price_in"], m["price_out"], m["model"])

    # ── Merge with existing config (augment-only) ─────────────────
    existing_models = _load_existing_models()
    models = _merge_with_existing(fetched, existing_models)

    active     = [m for m in models if not m.get("deprecated")]
    deprecated = [m for m in models if m.get("deprecated")]

    log.info("[Sync] Merged registry: {} active, {} deprecated",
             len(active), len(deprecated))

    # ── Loud warnings for deprecated models ──────────────────────
    if deprecated:
        log.warning("[Sync] " + "═" * 55)
        log.warning("[Sync] ⚠  {} DEPRECATED MODEL(S) — no longer on pricing page:",
                    len(deprecated))
        for m in deprecated:
            since = m.get("deprecated_since", "unknown")
            log.warning("[Sync]   • {} ({}) — deprecated since {}",
                        m["short_name"], m["model"], since)
        log.warning("[Sync] These models are SKIPPED during extraction runs.")
        log.warning("[Sync] Remove the 'deprecated' flag manually to re-enable.")
        log.warning("[Sync] " + "═" * 55)

    if write:
        config_text = _generate_config(models)

        existing_text = ""
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                existing_text = f.read()

        if config_text == existing_text:
            log.info("[Sync] No changes detected, skipping save")
        else:
            with open(CONFIG_PATH, "w") as f:
                f.write(config_text)
            log.info("[Sync] Saved {} active + {} deprecated model(s) to {}",
                     len(active), len(deprecated), CONFIG_PATH)

    return models


if __name__ == "__main__":
    sync()

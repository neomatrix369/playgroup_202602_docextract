"""Sync Doubleword model pricing into config_models_doubleword.py.

Uses the agent-friendly markdown endpoint at docs.doubleword.ai (llms.txt enabled)
to fetch a clean pricing table instead of scraping HTML. Skips saving when nothing
has changed. Designed to run at the start of each extractor run.

Also provides detect_changes() and a --diff CLI flag to compare the DW Batch API's
canonical /v1/models list against our config. The API endpoint returns the correct
HuggingFace model IDs that the batch API actually accepts — unlike the docs page,
which has historically used mismatched identifiers.

IMPORTANT — augment-only policy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Models are NEVER removed from config_models_doubleword.py by this script.
If a model disappears from the remote pricing page it is marked:
    "potentially_deprecated": True,
    "first_noticed_missing": "YYYY-MM-DD",
and moved to the POTENTIALLY DEPRECATED MODELS section at the bottom of the
file.  The flag is informational only — the model still runs normally.
This preserves pricing/metadata for historical runs and makes the absence
visible in every subsequent sync log as a prominent WARNING.
A human must confirm and set "deprecated": True manually to actually retire it.
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

# DW Batch API — canonical model ID source (OpenAI-compatible /v1/models endpoint)
DW_BATCH_API_BASE = "https://api.doubleword.ai"
DW_API_MODELS_ENDPOINT = "/v1/models"

# Model IDs to skip (embedding-only models — not useful for our extraction benchmark)
SKIP_MODEL_IDS: frozenset[str] = frozenset({"Qwen/Qwen3-Embedding-8B"})

# HuggingFace config.json — fallback source for context window when DW docs omit it
HF_CONFIG_URL = "https://huggingface.co/{model_id}/resolve/main/config.json"
CTX_DEFAULT = 262_000  # value used when DW page has no Max Total Tokens


def _fetch_hf_ctx(model_id: str) -> int | None:
    """Fetch max_position_embeddings from the model's HuggingFace config.json.

    Returns the context window rounded to the nearest thousand, or None if the
    request fails, the model is gated, or no suitable field is found.
    """
    url = HF_CONFIG_URL.format(model_id=model_id)
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None
        cfg = resp.json()
        val = cfg.get("max_position_embeddings") or cfg.get("seq_length") or cfg.get("n_positions")
        if val:
            return (int(val) // 1000) * 1000
    except Exception:
        pass
    return None


def _fetch_api_models(api_key: str) -> list[str] | None:
    """Fetch canonical model IDs from the DW Batch API /v1/models endpoint.

    Returns a list of HuggingFace-format model IDs that the Batch API actually
    accepts (excluding embedding models).  Returns None on any failure so callers
    can fall back gracefully.

    This is the authoritative source for correct model IDs — the docs markdown
    page has historically used mismatched identifiers.
    """
    url = f"{DW_BATCH_API_BASE}{DW_API_MODELS_ENDPOINT}"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            log.warning(
                "[Sync] DW API /v1/models returned {} — {}",
                resp.status_code,
                resp.text[:200],
            )
            return None
        data = resp.json()
        return [m["id"] for m in data.get("data", []) if m["id"] not in SKIP_MODEL_IDS]
    except Exception as e:
        log.warning("[Sync] Could not fetch DW Batch API model list: {}", e)
        return None


def detect_changes(api_key: str | None = None) -> dict:
    """Compare the DW Batch API model list against our current config.

    Uses the canonical /v1/models endpoint to find models that are new on DW
    (not yet in our config) or gone from DW (in our config but no longer in API).

    Returns a dict with keys:
        new       – list of model IDs present in API but not in config
        gone      – list of {short_name, model} for IDs in config but not in API
        unchanged – list of model IDs present in both
        api_total    – total from API (excluding skipped)
        config_total – total entries in config
        error     – error string (only present when API call failed)
    """
    if api_key is None:
        api_key = os.getenv("DOUBLEWORD_API_KEY", "").strip()

    api_model_ids = _fetch_api_models(api_key)
    if api_model_ids is None:
        return {"error": "Could not fetch DW API model list — check DOUBLEWORD_API_KEY"}

    existing = _load_existing_models()
    config_ids = {v["model"] for v in existing.values()}

    api_set = set(api_model_ids)
    new_ids = sorted(api_set - config_ids)
    gone_ids = sorted(config_ids - api_set)

    gone = []
    for model_id in gone_ids:
        for short_name, entry in existing.items():
            if entry["model"] == model_id:
                gone.append({"short_name": short_name, "model": model_id})
                break

    return {
        "new": new_ids,
        "gone": gone,
        "unchanged": sorted(api_set & config_ids),
        "api_total": len(api_model_ids),
        "config_total": len(existing),
    }


def _print_diff_report(changes: dict) -> None:
    """Print a human-readable diff report from detect_changes() output."""
    if "error" in changes:
        log.warning("[Diff] {}", changes["error"])
        return

    new = changes["new"]
    gone = changes["gone"]
    unchanged = changes["unchanged"]

    print(f"\n{'═'*60}")
    print(f"  DW Model Diff  —  {date.today()}")
    print(f"  API: {changes['api_total']} models   Config: {changes['config_total']} entries")
    print(f"{'═'*60}")

    if new:
        print(f"\n✅  NEW ({len(new)}) — in DW API, not yet in our config:\n")
        for mid in new:
            print(f"    + {mid}")
        print()
        print("    Stub entries to add to config_models_doubleword.py:")
        for mid in new:
            short = _make_short_name(mid)
            is_vl = "-vl-" in mid.lower()
            mods = '["text", "image"]' if is_vl else '["text"]'
            print(f"""
    "{short}": {{
        "model":      "{mid}",
        "multimodal": {is_vl},
        "modalities": {mods},
        "tier":       "standard",       # TODO: verify
        "price_in":   0.00, "price_out": 0.00,  # TODO: fill from pricing page
        "ctx":        262_000,          # TODO: verify
        "notes":      "",
    }},""")
    else:
        print("\n✅  No new models.")

    if gone:
        print(f"\n⚠️   GONE ({len(gone)}) — in our config, not in DW API:\n")
        for g in gone:
            print(f"    - {g['short_name']}  ({g['model']})")
        print("\n    Consider setting  'potentially_deprecated': True  in config.")
    else:
        print("\n✅  No models gone.")

    if unchanged:
        print(f"\n✅  UNCHANGED: {len(unchanged)} models present in both.")

    print(f"\n{'═'*60}\n")

    # Save report to data/
    report_path = f"data/dw_model_diff_{date.today()}.txt"
    try:
        import io, sys
        os.makedirs("data", exist_ok=True)
        # Capture the same output to file
        lines = []
        lines.append(f"DW Model Diff — {date.today()}")
        lines.append(f"API: {changes['api_total']} models   Config: {changes['config_total']} entries")
        if new:
            lines.append(f"\nNEW ({len(new)}):")
            for mid in new:
                lines.append(f"  + {mid}")
        if gone:
            lines.append(f"\nGONE ({len(gone)}):")
            for g in gone:
                lines.append(f"  - {g['short_name']}  ({g['model']})")
        lines.append(f"\nUNCHANGED: {len(unchanged)} models")
        with open(report_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Report saved to {report_path}")
    except Exception as e:
        log.warning("[Diff] Could not save report: {}", e)


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


_CTX_FROM_ERROR_RE = re.compile(
    r"(?:maximum context length|max(?:imum)? (?:context|sequence) (?:length|size)|"
    r"context_length|max_tokens|maximum tokens?)"
    r"[^0-9]{0,30}(\d{3,7})\b",
    re.IGNORECASE,
)


def extract_ctx_from_error(error_msg: str) -> int | None:
    """Parse a DW/OpenAI batch error message for an explicit context-length limit.

    Returns the limit in tokens (rounded to nearest thousand) or None.
    Handles messages like:
      "This model's maximum context length is 8192 tokens..."
      "context_length_exceeded: max 32768"
    """
    m = _CTX_FROM_ERROR_RE.search(error_msg)
    if m:
        val = int(m.group(1))
        if val >= 1_000:            # ignore small numbers like "400 tokens used"
            return (val // 1000) * 1000
    return None


def update_model_ctx(model_short_name: str, new_ctx: int):
    """Persist a corrected ctx value for one model into CONFIG_PATH.

    Reads the existing config, updates that model's ctx field, and rewrites
    the file. Skips if the value is unchanged. This is the self-healing path
    triggered when DW error messages reveal the actual context limit.
    """
    existing = _load_existing_models()
    entry = existing.get(model_short_name)
    if entry is None:
        log.warning("[Sync] update_model_ctx: '{}' not found in config, skipping", model_short_name)
        return
    if entry.get("ctx") == new_ctx:
        return  # already correct

    old_ctx = entry.get("ctx", "?")
    log.info("[Sync] Auto-correcting ctx for '{}': {:,} → {:,} (from DW error message)",
             model_short_name, old_ctx, new_ctx)
    entry["ctx"] = new_ctx

    # Rewrite config via the normal generation path so format stays consistent
    models = _merge_with_existing([], existing)   # no fetched → preserve all
    # Apply our correction directly (merge may reset to existing)
    for m in models:
        if m.get("short_name") == model_short_name or m.get("short_name", "").rstrip() == model_short_name:
            m["ctx"] = new_ctx
            break
    config_text = _generate_config(models)
    with open(CONFIG_PATH, "w") as f:
        f.write(config_text)
    log.info("[Sync] Config updated with corrected ctx for '{}'", model_short_name)


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
    - New model in API response  → added (no flags set).
    - Existing model in response → pricing/metadata updated;
      potentially_deprecated flag cleared (model is back).
    - Existing model NOT in resp → kept as-is; potentially_deprecated=True
      and first_noticed_missing set only on the first occasion (so the
      original observation date is preserved across subsequent runs).
      The flag is informational — the model is NOT skipped.

    Returns the merged list ordered:
      active text → active VL → potentially-deprecated text → potentially-deprecated VL.
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

    # Apply/add fetched models (update existing, add new).
    # Clear the potentially_deprecated flag if the model is back on the page.
    for short_name, m in fetched_by_short.items():
        entry = dict(m)  # copy from fetched
        entry.pop("potentially_deprecated", None)   # clear stale flag
        entry.pop("first_noticed_missing", None)     # clear stale date
        # Preserve manual overrides from the existing entry.
        existing = merged.get(short_name, {})
        if existing.get("extra_params"):
            entry["extra_params"] = existing["extra_params"]
        # Preserve a non-default ctx from existing if the fetched value is still the
        # fallback (neither DW docs nor HF provided a real value for this model).
        if entry["ctx"] == CTX_DEFAULT and existing.get("ctx", CTX_DEFAULT) != CTX_DEFAULT:
            entry["ctx"] = existing["ctx"]
            log.info("[Sync] Preserved existing ctx {:,} for {} (no upstream source found)",
                     entry["ctx"], short_name)
        merged[short_name] = entry

    # Flag anything in existing that's missing from the API response.
    # Only set first_noticed_missing on the first occasion.
    for short_name in list(merged.keys()):
        if short_name not in fetched_by_short:
            entry = merged[short_name]
            if not entry.get("potentially_deprecated"):
                entry["potentially_deprecated"] = True
                entry["first_noticed_missing"] = today
                log.warning(
                    "[Sync] ⚠  Model '{}' is NO LONGER in the Doubleword pricing page — "
                    "flagging as potentially_deprecated (first noticed: {}). "
                    "It will NOT be removed and will still run normally.",
                    short_name, today,
                )

    # ── Sort: active first (text then VL), potentially-deprecated last ─
    def _sort_key(item):
        _, m = item
        pdep = 1 if m.get("potentially_deprecated") else 0
        vl   = 1 if m.get("multimodal") else 0
        return (pdep, vl)

    return [m for _, m in sorted(merged.items(), key=_sort_key)]


def _generate_config(models):
    """Generate the Python config file content matching the existing format.

    Active models (including potentially_deprecated ones) appear in the
    TEXT-ONLY / VISION-LANGUAGE sections.
    Models flagged potentially_deprecated=True are additionally grouped into
    a POTENTIALLY DEPRECATED MODELS section at the bottom for visibility.
    """
    pdep    = [m for m in models if m.get("potentially_deprecated")]
    active  = [m for m in models if not m.get("potentially_deprecated")]

    text_models = [m for m in active if not m.get("multimodal")]
    vl_models   = [m for m in active if m.get("multimodal")]
    pdep_text   = [m for m in pdep  if not m.get("multimodal")]
    pdep_vl     = [m for m in pdep  if m.get("multimodal")]

    def _fmt_entry(m, *, include_pdep=False):
        # short_name is always present after _merge_with_existing injects it.
        short_name = m["short_name"]
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
        if m.get("extra_params"):
            lines.append(f'        "extra_params": {m["extra_params"]!r},')
        if include_pdep and m.get("potentially_deprecated"):
            first_seen = m.get("first_noticed_missing", "unknown")
            lines += [
                f'        "potentially_deprecated":  True,',
                f'        "first_noticed_missing":   "{first_seen}",',
            ]
        lines.append("    },")
        return "\n".join(lines)

    output_lines = [
        "# Doubleword Batch API models — model names use HuggingFace conventions",
        "# Verify model availability at https://app.doubleword.ai/ before running",
        "# Pricing from https://docs.doubleword.ai/batches/model-pricing",
        '# Prices shown are "High" (1h) batch tier — "Standard" (24h) is ~30-50% cheaper',
        "# AUTO-GENERATED by sync_doubleword_models.py — do not edit manually",
        "# Models are NEVER removed — potentially_deprecated ones are flagged, not deleted.",
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

    if pdep:
        output_lines += [
            "",
            "    # ═══════════════════════════════════════════════════════════",
            "    #  POTENTIALLY DEPRECATED MODELS",
            "    #  Not seen on the Doubleword pricing page as of first_noticed_missing.",
            "    #  These models still run normally — the flag is informational only.",
            "    #  Confirm manually and set \"deprecated\": True to fully retire.",
            "    # ═══════════════════════════════════════════════════════════",
            "",
        ]
        for m in pdep_text + pdep_vl:
            output_lines.append(_fmt_entry(m, include_pdep=True))

    output_lines.append("}")
    output_lines.append("")
    return "\n".join(output_lines)


def sync_from_api(api_key: str | None = None) -> bool:
    """Detect model changes by querying the DW Batch API /v1/models endpoint.

    Uses correct API-facing model IDs (unlike the docs markdown).  Safe to run
    at every extractor startup — read-only, no config writes.

    Logs warnings for new and gone models so the operator sees them immediately.
    Run  python sync_doubleword_models.py --diff  to get stub entries for new models.

    Returns True if any changes were detected.
    """
    if api_key is None:
        api_key = os.getenv("DOUBLEWORD_API_KEY", "").strip()
    if not api_key:
        log.warning("[Sync] DOUBLEWORD_API_KEY not set — skipping API change detection")
        return False

    log.info("[Sync] Checking DW Batch API for model changes...")
    changes = detect_changes(api_key)
    if "error" in changes:
        log.warning("[Sync] API change detection failed: {}", changes["error"])
        return False

    new_ids = changes["new"]
    gone = changes["gone"]

    if not new_ids and not gone:
        log.info("[Sync] DW model list unchanged ({} models)", changes["api_total"])
        return False

    if new_ids:
        log.warning("[Sync] ⚡ {} NEW model(s) on DW not yet in our config:", len(new_ids))
        for mid in new_ids:
            log.warning("[Sync]   + {}", mid)
        log.warning("[Sync] Run:  python sync_doubleword_models.py --diff  for stub entries")

    if gone:
        log.warning("[Sync] ⚠  {} model(s) no longer in DW API:", len(gone))
        for g in gone:
            log.warning("[Sync]   - {}  ({})", g["short_name"], g["model"])
        log.warning("[Sync] Consider setting 'potentially_deprecated': True in config")

    return True


def sync(write=True):
    """Fetch pricing page, merge with existing config, and optionally write.

    Augment-only: models absent from the remote pricing page are flagged
    potentially_deprecated=True (with first_noticed_missing date) rather
    than removed.  The flag is informational — flagged models still run.

    Returns the full merged models list (confirmed active + potentially deprecated).
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

    # ── Enrich ctx from HuggingFace for models the DW page does not document ──
    # When DW's pricing page omits Max Total Tokens we fall back to CTX_DEFAULT.
    # For those models we try to fetch max_position_embeddings from HF config.json.
    hf_enriched = 0
    for m in fetched:
        if m["ctx"] == CTX_DEFAULT:
            hf_ctx = _fetch_hf_ctx(m["model"])
            if hf_ctx:
                log.info("[Sync] HF ctx for {} ({}): {:,}", m["short_name"], m["model"], hf_ctx)
                m["ctx"] = hf_ctx
                hf_enriched += 1
    if hf_enriched:
        log.info("[Sync] Enriched ctx for {}/{} model(s) from HuggingFace", hf_enriched, len(fetched))

    # ── Merge with existing config (augment-only) ─────────────────
    existing_models = _load_existing_models()
    models = _merge_with_existing(fetched, existing_models)

    confirmed  = [m for m in models if not m.get("potentially_deprecated")]
    pdep       = [m for m in models if m.get("potentially_deprecated")]

    log.info("[Sync] Merged registry: {} confirmed active, {} potentially deprecated",
             len(confirmed), len(pdep))

    # ── Informational warnings for potentially-deprecated models ──
    if pdep:
        log.warning("[Sync] " + "═" * 55)
        log.warning("[Sync] ⚠  {} POTENTIALLY DEPRECATED model(s) — not seen on pricing page:",
                    len(pdep))
        for m in pdep:
            first_seen = m.get("first_noticed_missing", "unknown")
            log.warning("[Sync]   • {} ({}) — first noticed missing: {}",
                        m["short_name"], m["model"], first_seen)
        log.warning("[Sync] These models still run normally (flag is informational).")
        log.warning("[Sync] Confirm manually and set 'deprecated': True to fully retire.")
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
            log.info("[Sync] Saved {} confirmed + {} potentially-deprecated model(s) to {}",
                     len(confirmed), len(pdep), CONFIG_PATH)

    return models


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Sync Doubleword model config and detect API changes.",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Compare DW Batch API model list against our config and show NEW/GONE/UNCHANGED",
    )
    parser.add_argument(
        "--probe-api",
        action="store_true",
        help="Show all models returned by the DW Batch API /v1/models endpoint",
    )
    args = parser.parse_args()

    if args.probe_api:
        api_key = os.getenv("DOUBLEWORD_API_KEY", "").strip()
        if not api_key:
            print("DOUBLEWORD_API_KEY not set")
        else:
            models = _fetch_api_models(api_key)
            if models:
                print(f"DW Batch API /v1/models — {len(models)} models:")
                for mid in sorted(models):
                    print(f"  {mid}")
            else:
                print("Failed to fetch model list from DW API")
    elif args.diff:
        changes = detect_changes()
        _print_diff_report(changes)
    else:
        sync()

"""Google DeepMind Gemini model registry.

Direct provider integration for Google DeepMind models via Google AI Studio / Gemini API.
Model short names use the `google-*` prefix to disambiguate from OpenRouter models.

Pricing is USD per 1,000,000 text tokens ($/M), standard paid tier, as published at
https://ai.google.dev/gemini-api/docs/pricing (checked 2026-10-31). Context limits come from
the native API: GET /v1beta/models/<id> -> inputTokenLimit.

Thinking-level sweep
--------------------
Active models include baseline + three thinking-level variants (low/medium/high).
thinking_level maps to the API's thinking_config.thinking_level enum; None = no thinking_config
passed (API default). thinking_budget (numeric) is deprecated for Gemini 3.x+ — use this enum.
"""

_FLAGSHIP_PRICES = {"price_in": 2.00, "price_out": 10.00}
_PRO_PRICES = {"price_in": 1.25, "price_out": 10.00}
_FLASH_PRICES = {"price_in": 0.75, "price_out": 3.75}
_CTX = 1_048_576
_COMMON = {"multimodal": False, "modalities": ["text"], "ctx": _CTX, "include_thoughts": False}


def _sweep(key_prefix: str, model_api_id: str, prices: dict, tier: str, base_notes: str) -> dict:
    """Build the three thinking-level sweep entries for one model.

    key_prefix: the part after 'google-' in the registry key (e.g. 'gemini-3.1-pro')
    model_api_id: the actual API model id (e.g. 'gemini-3.1-pro-preview')
    """
    variants = {}
    for level in ("low", "medium", "high"):
        key = f"google-{key_prefix}-think-{level}"
        variants[key] = {
            **_COMMON,
            **prices,
            "model": model_api_id,
            "tier": tier,
            "thinking_level": level,
            "notes": f"{base_notes}, thinking_level={level}",
        }
    return variants


GOOGLE_MODELS = {
    # ═══════════════════════════════════════════════════════════
    #  FRONTIER / REASONING MODELS
    # ═══════════════════════════════════════════════════════════
    "google-gemini-4-argon": {
        **_COMMON,
        **_FLAGSHIP_PRICES,
        "model": "gemini-4-argon",
        "tier": "flagship",
        "thinking_level": None,
        # Launch pricing until 2026-11-30; rises to $4.00 / $20.00 from 2026-12-01.
        "notes": "Google DeepMind frontier reasoning model (Gemini 4 Argon), 1M ctx, thinking on",
    },
    **_sweep("gemini-4-argon", "gemini-4-argon", _FLAGSHIP_PRICES, "flagship",
             "Google DeepMind frontier reasoning model (Gemini 4 Argon), 1M ctx"),

    # ═══════════════════════════════════════════════════════════
    #  PRO & THINKING MODELS
    # ═══════════════════════════════════════════════════════════
    "google-gemini-3.1-pro": {
        **_COMMON,
        **_PRO_PRICES,
        "model": "gemini-3.1-pro-preview",
        "tier": "pro",
        "thinking_level": None,
        # Pricing TBD — verify at https://ai.google.dev/gemini-api/docs/pricing
        # Using gemini-2.5-pro pricing as placeholder; update after confirmation.
        "notes": "Google DeepMind pro thinking model (successor to 2.5-pro), 1M ctx",
    },
    **_sweep("gemini-3.1-pro", "gemini-3.1-pro-preview", _PRO_PRICES, "pro",
             "Google DeepMind pro thinking model (Gemini 3.1 Pro Preview), 1M ctx"),
    "google-gemini-2.5-pro": {
        **_COMMON,
        **_PRO_PRICES,
        "model": "gemini-2.5-pro",
        "tier": "pro",
        "thinking_level": None,
        # Prompts <= 200k tokens; > 200k is $2.50 / $15.00.
        "notes": "Google DeepMind thinking and reasoning model, 1M ctx",
        "potentially_deprecated": True,
        "deprecation_reason": "API returns 404: 'no longer available to new users'; use google-gemini-3.1-pro (gemini-3.1-pro-preview)",
        "successor": "google-gemini-3.1-pro",
    },

    # ═══════════════════════════════════════════════════════════
    #  FLASH / HIGH EFFICIENCY MODELS
    # ═══════════════════════════════════════════════════════════
    "google-gemini-2.5-flash": {
        **_COMMON,
        "model": "gemini-2.5-flash",
        "tier": "flash",
        "price_in": 0.30,
        "price_out": 2.50,
        "thinking_level": None,
        "notes": "Google DeepMind high-efficiency fast workhorse model, 1M ctx",
        "potentially_deprecated": True,
        "deprecation_reason": "API returns 404: 'no longer available to new users'; use google-gemini-3.8-flash",
        "successor": "google-gemini-3.8-flash",
    },
    "google-gemini-3.8-flash": {
        **_COMMON,
        **_FLASH_PRICES,
        "model": "gemini-3.8-flash",
        "tier": "flash",
        "thinking_level": None,
        # Launch pricing until 2026-12-31; rises to $1.50 / $7.50 from 2027-01-01.
        "notes": "Google DeepMind recent high-speed flash model, 1M ctx",
    },
    **_sweep("gemini-3.8-flash", "gemini-3.8-flash", _FLASH_PRICES, "flash",
             "Google DeepMind recent high-speed flash model, 1M ctx"),
}

"""Google DeepMind Gemini model registry.

Direct provider integration for Google DeepMind models via Google AI Studio / Gemini API.
Model short names use the `google-*` prefix to disambiguate from OpenRouter models.

Pricing is USD per 1,000,000 text tokens ($/M), standard paid tier, as published at
https://ai.google.dev/gemini-api/docs/pricing (checked 2026-10-31). Context limits come from
the native API: GET /v1beta/models/<id> -> inputTokenLimit.
"""

GOOGLE_MODELS = {
    # ═══════════════════════════════════════════════════════════
    #  FRONTIER / REASONING MODELS
    # ═══════════════════════════════════════════════════════════
    "google-gemini-4-argon": {
        "model": "gemini-4-argon",
        "multimodal": False,
        "modalities": ["text"],
        "tier": "flagship",
        # Launch pricing until 2026-11-30; rises to $4.00 / $20.00 from 2026-12-01.
        "price_in": 2.00,
        "price_out": 10.00,
        "ctx": 1_048_576,
        "notes": "Google DeepMind frontier reasoning model (Gemini 4 Argon), 1M ctx, thinking on",
    },

    # ═══════════════════════════════════════════════════════════
    #  PRO & THINKING MODELS
    # ═══════════════════════════════════════════════════════════
    "google-gemini-3.1-pro": {
        "model": "gemini-3.1-pro-preview",
        "multimodal": False,
        "modalities": ["text"],
        "tier": "pro",
        # Pricing TBD — verify at https://ai.google.dev/gemini-api/docs/pricing
        # Using gemini-2.5-pro pricing as placeholder; update after confirmation.
        "price_in": 1.25,
        "price_out": 10.00,
        "ctx": 1_048_576,
        "notes": "Google DeepMind pro thinking model (successor to 2.5-pro), 1M ctx",
    },
    "google-gemini-2.5-pro": {
        "model": "gemini-2.5-pro",
        "multimodal": False,
        "modalities": ["text"],
        "tier": "pro",
        # Prompts <= 200k tokens; > 200k is $2.50 / $15.00.
        "price_in": 1.25,
        "price_out": 10.00,
        "ctx": 1_048_576,
        "notes": "Google DeepMind thinking and reasoning model, 1M ctx",
        "potentially_deprecated": True,
        "deprecation_reason": "API returns 404: 'no longer available to new users'; use google-gemini-3.1-pro (gemini-3.1-pro-preview)",
        "successor": "google-gemini-3.1-pro",
    },

    # ═══════════════════════════════════════════════════════════
    #  FLASH / HIGH EFFICIENCY MODELS
    # ═══════════════════════════════════════════════════════════
    "google-gemini-2.5-flash": {
        "model": "gemini-2.5-flash",
        "multimodal": False,
        "modalities": ["text"],
        "tier": "flash",
        "price_in": 0.30,
        "price_out": 2.50,
        "ctx": 1_048_576,
        "notes": "Google DeepMind high-efficiency fast workhorse model, 1M ctx",
        "potentially_deprecated": True,
        "deprecation_reason": "API returns 404: 'no longer available to new users'; use google-gemini-3.8-flash",
        "successor": "google-gemini-3.8-flash",
    },
    "google-gemini-3.8-flash": {
        "model": "gemini-3.8-flash",
        "multimodal": False,
        "modalities": ["text"],
        "tier": "flash",
        # Launch pricing until 2026-12-31; rises to $1.50 / $7.50 from 2027-01-01.
        "price_in": 0.75,
        "price_out": 3.75,
        "ctx": 1_048_576,
        "notes": "Google DeepMind recent high-speed flash model, 1M ctx",
    },
}

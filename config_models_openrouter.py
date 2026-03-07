OPENROUTER_MODELS = {

    # ═══════════════════════════════════════════════════════════
    #  FREE TIER  (rate-limited: ~20 req/min, ~200 req/day)
    # ═══════════════════════════════════════════════════════════

    # ── Free · Text-only ──────────────────────────────────────
    "llama-3.3-70b-free": {
        "model":      "meta-llama/llama-3.3-70b-instruct:free",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "free",
        "price_in":   0, "price_out":  0,
        "ctx":        131_000,
        "notes":      "GPT-4 class open model, best free text generalist",
    },
    # deepseek-r1-free: removed — deepseek/deepseek-r1-0528:free no longer available on OpenRouter
    "mistral-small-free": {
        "model":      "mistralai/mistral-small-3.1-24b-instruct:free",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "free",
        "price_in":   0, "price_out":  0,
        "ctx":        33_000,
        "notes":      "24B, punches above weight, Apache 2.0",
    },
    # gpt-oss-120b-free: removed — openai/gpt-oss-120b:free no longer available on OpenRouter

    # ── Free · Multimodal ─────────────────────────────────────
    # gemini-flash-free: removed — google/gemini-2.0-flash-exp:free no longer available on OpenRouter
    # qwen3-vl-30b-free: free tier no longer available on OpenRouter
    # llama-4-scout-free: free tier no longer available on OpenRouter (paid meta-llama/llama-4-scout exists)
    "gemma-3-27b-free": {
        "model":      "google/gemma-3-27b-it:free",
        "multimodal": True,
        "modalities": ["text", "image"],
        "tier":       "free",
        "price_in":   0, "price_out":  0,
        "ctx":        131_000,
        "notes":      "27B, vision+text, 140+ languages, open-weight",
    },
    "gemma-3n-free": {
        "model":      "google/gemma-3n-e2b-it:free",
        "multimodal": True,
        "modalities": ["text", "image", "video", "audio"],
        "tier":       "free",
        "price_in":   0, "price_out":  0,
        "ctx":        8_000,
        "notes":      "2B effective, on-device capable, 140+ languages",
    },

    # ═══════════════════════════════════════════════════════════
    #  ULTRA CHEAP  (<$0.30/M input tokens)
    # ═══════════════════════════════════════════════════════════

    # ── Ultra Cheap · Text-only ───────────────────────────────
    "deepseek-v3": {
        "model":      "deepseek/deepseek-chat",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.27, "price_out": 1.10,
        "ctx":        164_000,
        "notes":      "DeepSeek V3, near GPT-4 quality",
    },
    "deepseek-v3.2": {
        "model":      "deepseek/deepseek-v3.2",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.21, "price_out": 0.79,
        "ctx":        164_000,
        "notes":      "GPT-5 class reasoning + sparse attention",
    },
    "qwen-2.5-7b": {
        "model":      "qwen/qwen-2.5-7b-instruct",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.04, "price_out": 0.10,
        "ctx":        33_000,
        "notes":      "Tiny but mighty, good for high-volume agents",
    },
    "llama-3.1-8b": {
        "model":      "meta-llama/llama-3.1-8b-instruct",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.02, "price_out": 0.05,
        "ctx":        131_000,
        "notes":      "Cheapest quality model, high-volume workhorse",
    },
    "mistral-small": {
        "model":      "mistralai/mistral-small-3.1-24b-instruct",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.10, "price_out": 0.30,
        "ctx":        33_000,
        "notes":      "24B, 3x faster than 70B class, Apache 2.0",
    },
    "qwen3-235b": {
        "model":      "qwen/qwen3-235b-a22b",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.14, "price_out": 0.40,
        "ctx":        41_000,
        "notes":      "235B MoE (22B active), frontier open-source reasoning",
    },

    # ── Ultra Cheap · Multimodal ──────────────────────────────
    "gemini-2.5-flash": {
        "model":      "google/gemini-2.5-flash",
        "multimodal": True,
        "modalities": ["text", "image", "video", "audio", "pdf"],
        "tier":       "ultra_cheap",
        "price_in":   0.15, "price_out": 0.60,
        "ctx":        1_000_000,
        "notes":      "Best-value thinking+vision model, 1M ctx",
    },
    "gemini-2.0-flash": {
        "model":      "google/gemini-2.0-flash-001",
        "multimodal": True,
        "modalities": ["text", "image", "video", "audio", "pdf"],
        "tier":       "ultra_cheap",
        "price_in":   0.10, "price_out": 0.40,
        "ctx":        1_000_000,
        "notes":      "Production workhorse, full multimodal, 1M ctx",
    },
    "gemini-3-flash": {
        "model":      "google/gemini-3-flash-preview",
        "multimodal": True,
        "modalities": ["text", "image", "video", "audio", "pdf"],
        "tier":       "ultra_cheap",
        "price_in":   0.15, "price_out": 0.60,
        "ctx":        1_000_000,
        "notes":      "Near-Pro quality, configurable thinking levels",
    },
    "gpt-4o-mini": {
        "model":      "openai/gpt-4o-mini",
        "multimodal": True,
        "modalities": ["text", "image"],
        "tier":       "ultra_cheap",
        "price_in":   0.15, "price_out": 0.60,
        "ctx":        128_000,
        "notes":      "OpenAI's best value, vision + text",
    },
    "qwen-2.5-vl-7b": {
        "model":      "qwen/qwen-2.5-vl-7b-instruct",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "ultra_cheap",
        "price_in":   0.04, "price_out": 0.10,
        "ctx":        33_000,
        "notes":      "7B VL, excellent OCR, cheapest quality vision",
    },
    "qwen3-vl-8b": {
        "model":      "qwen/qwen3-vl-8b-instruct",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "ultra_cheap",
        "price_in":   0.08, "price_out": 0.50,
        "ctx":        131_000,
        "notes":      "Qwen3 VL 8B, 131K ctx, strong spatial reasoning",
    },
    "gemma-3n": {
        "model":      "google/gemma-3n-e4b-it",
        "multimodal": True,
        "modalities": ["text", "image", "video", "audio"],
        "tier":       "ultra_cheap",
        "price_in":   0.02, "price_out": 0.04,
        "ctx":        32_000,
        "notes":      "4B effective multimodal, edge-deployable, 140+ langs",
    },
    # pixtral-12b: removed from OpenRouter (mistralai/pixtral-12b-2409 no longer available)
    "llama-3.2-11b-vision": {
        "model":      "meta-llama/llama-3.2-11b-vision-instruct",
        "multimodal": True,
        "modalities": ["text", "image"],
        "tier":       "ultra_cheap",
        "price_in":   0.05, "price_out": 0.05,
        "ctx":        131_000,
        "notes":      "11B vision, efficient, open-source",
    },
    "gemma-3-12b": {
        "model":      "google/gemma-3-12b-it",
        "multimodal": True,
        "modalities": ["text", "image"],
        "tier":       "ultra_cheap",
        "price_in":   0.06, "price_out": 0.12,
        "ctx":        131_000,
        "notes":      "12B vision+text, 128K ctx, 140+ langs",
    },

    # ═══════════════════════════════════════════════════════════
    #  GREAT VALUE  ($0.30–$1.00/M input tokens)
    # ═══════════════════════════════════════════════════════════

    # ── Great Value · Text-only ───────────────────────────────
    "deepseek-r1": {
        "model":      "deepseek/deepseek-r1",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "great_value",
        "price_in":   0.40, "price_out": 1.75,
        "ctx":        164_000,
        "notes":      "Full R1 reasoning, o1-class, open-source",
    },
    "qwen-2.5-72b": {
        "model":      "qwen/qwen-2.5-72b-instruct",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "great_value",
        "price_in":   0.30, "price_out": 0.80,
        "ctx":        33_000,
        "notes":      "Top open-source generalist, strong code+math",
    },
    "llama-3.3-70b": {
        "model":      "meta-llama/llama-3.3-70b-instruct",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "great_value",
        "price_in":   0.40, "price_out": 0.88,
        "ctx":        131_000,
        "notes":      "Strong multilingual 70B, 8 languages",
    },
    "qwen-coder-32b": {
        "model":      "qwen/qwen-2.5-coder-32b-instruct",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "great_value",
        "price_in":   0.10, "price_out": 0.20,
        "ctx":        33_000,
        "notes":      "Best open-source coding model for price",
    },
    "nemotron-super-49b": {
        "model":      "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "great_value",
        "price_in":   0.20, "price_out": 0.20,
        "ctx":        128_000,
        "notes":      "49B, post-trained for RAG/tool-calling/agentic",
    },

    # ── Great Value · Multimodal ──────────────────────────────
    "qwen-2.5-vl-72b": {
        "model":      "qwen/qwen-2.5-vl-72b-instruct",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "great_value",
        "price_in":   0.80, "price_out": 0.80,
        "ctx":        33_000,
        "notes":      "72B VL flagship, best open doc AI, 32-lang OCR",
    },
    "qwen3-vl-30b": {
        "model":      "qwen/qwen3-vl-30b-a3b-instruct",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "great_value",
        "price_in":   0.13, "price_out": 0.52,
        "ctx":        131_000,
        "notes":      "30B VL, spatial grounding, GUI automation",
    },
    "qwen3-vl-30b-thinking": {
        "model":      "qwen/qwen3-vl-30b-a3b-thinking",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "great_value",
        "price_in":   0.13, "price_out": 0.52,
        "ctx":        131_000,
        "notes":      "Thinking variant — STEM/math reasoning over images",
    },
    "claude-3.5-haiku": {
        "model":      "anthropic/claude-3.5-haiku",
        "multimodal": True,
        "modalities": ["text", "image", "pdf"],
        "tier":       "great_value",
        "price_in":   0.80, "price_out": 4.00,
        "ctx":        200_000,
        "notes":      "Fast, great tool use, native PDF, 200K ctx",
    },
    # llama-3.2-90b-vision: removed from OpenRouter (meta-llama/llama-3.2-90b-vision-instruct no longer available)
    "gemma-3-27b": {
        "model":      "google/gemma-3-27b-it",
        "multimodal": True,
        "modalities": ["text", "image"],
        "tier":       "great_value",
        "price_in":   0.10, "price_out": 0.20,
        "ctx":        131_000,
        "notes":      "27B vision, 140+ langs, strong small VLM",
    },

    # ═══════════════════════════════════════════════════════════
    #  PREMIUM VALUE  (>$1/M input — still excellent ROI)
    # ═══════════════════════════════════════════════════════════

    # ── Premium · Text-only ───────────────────────────────────
    "mistral-large": {
        "model":      "mistralai/mistral-large",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",
        "price_in":   2.00, "price_out": 6.00,
        "ctx":        128_000,
        "notes":      "Near-frontier reasoning, strong multilingual",
    },
    "command-r-plus": {
        "model":      "cohere/command-r-plus-08-2024",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",
        "price_in":   2.50, "price_out": 10.00,
        "ctx":        128_000,
        "notes":      "Purpose-built for RAG, grounded generation",
    },

    # ── Premium · Multimodal ──────────────────────────────────
    "gemini-3-pro": {
        "model":      "google/gemini-3-pro-preview",
        "multimodal": True,
        "modalities": ["text", "image", "video", "audio", "pdf"],
        "tier":       "premium",
        "price_in":   2.00, "price_out": 12.00,
        "ctx":        1_050_000,
        "notes":      "Frontier multimodal, 1M ctx, agentic coding",
    },
    "pixtral-large": {
        "model":      "mistralai/pixtral-large-2411",
        "multimodal": True,
        "modalities": ["text", "image"],
        "tier":       "premium",
        "price_in":   2.00, "price_out": 6.00,
        "ctx":        128_000,
        "notes":      "124B vision MoE, strong document parsing",
    },
}
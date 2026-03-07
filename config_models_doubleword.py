# Doubleword Batch API models — model names use HuggingFace conventions
# Verify model availability at https://app.doubleword.ai/ before running
# Pricing from https://docs.doubleword.ai/batches/model-pricing
# Prices shown are "High" (1h) batch tier — "Standard" (24h) is ~30-50% cheaper

DOUBLEWORD_MODELS = {

    # ═══════════════════════════════════════════════════════════
    #  TEXT-ONLY MODELS
    # ═══════════════════════════════════════════════════════════

    "dw-qwen3.5-9b": {
        "model":      "Qwen/Qwen3.5-9B",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.04, "price_out": 0.35,
        "ctx":        262_000,
        "notes":      "9B reasoning model, 262K ctx, extremely cost-efficient",
    },
    "dw-qwen3-14b": {
        "model":      "Qwen/Qwen3-14B-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.03, "price_out": 0.30,
        "ctx":        262_000,
        "notes":      "14B, best for high-volume extraction/classification",
    },
    "dw-gpt-oss-20b": {
        "model":      "openai/gpt-oss-20b",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.03, "price_out": 0.20,
        "ctx":        262_000,
        "notes":      "21B (3.6B active), OpenAI open-source, low latency",
    },
    "dw-qwen3.5-35b": {
        "model":      "Qwen/Qwen3.5-35B-A3B-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "great_value",
        "price_in":   0.07, "price_out": 0.30,
        "ctx":        262_000,
        "notes":      "35B MoE (3B active), thinking mode, strong price/perf",
    },
    "dw-qwen3.5-397b": {
        "model":      "Qwen/Qwen3.5-397B-A17B",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",
        "price_in":   0.30, "price_out": 1.80,
        "ctx":        262_000,
        "notes":      "397B MoE (17B active), Qwen flagship, frontier-level",
    },

    # ═══════════════════════════════════════════════════════════
    #  VISION-LANGUAGE MODELS
    # ═══════════════════════════════════════════════════════════

    "dw-qwen3-vl-30b": {
        "model":      "Qwen/Qwen3-VL-30B-A3B-Instruct-FP8",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "great_value",
        "price_in":   0.07, "price_out": 0.30,
        "ctx":        262_000,
        "notes":      "30B VL MoE, GPT-4.1-mini class, Doubleword reference model",
    },
    "dw-qwen3-vl-235b": {
        "model":      "Qwen/Qwen3-VL-235B-A22B-Instruct-FP8",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "premium",
        "price_in":   0.15, "price_out": 0.55,
        "ctx":        262_000,
        "notes":      "235B VL MoE, GPT-5/Claude Opus class multimodal",
    },

    # ═══════════════════════════════════════════════════════════
    #  EMBEDDING MODEL
    # ═══════════════════════════════════════════════════════════

    "dw-qwen3-embedding-8b": {
        "model":      "Qwen/Qwen3-Embedding-8B",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.03, "price_out": 0.00,
        "ctx":        32_000,
        "notes":      "8B embedding, 4096-dim, #1 MTEB multilingual, 100+ langs",
    },
}

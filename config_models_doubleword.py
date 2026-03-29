# Doubleword Batch API models — model names use HuggingFace conventions
# Verify model availability at https://app.doubleword.ai/models before running
# Pricing from https://docs.doubleword.ai/inference-api/model-pricing
# Prices shown are "High" (1h) batch tier — "Standard" (24h) is ~30-50% cheaper
# Context windows verified from https://app.doubleword.ai/models on 2026-03-29

DOUBLEWORD_MODELS = {

    # ═══════════════════════════════════════════════════════════
    #  TEXT-ONLY MODELS
    # ═══════════════════════════════════════════════════════════

    "dw-qwen3.5-4b": {
        "model":      "Qwen/Qwen3.5-4B",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.05, "price_out": 0.08,
        "ctx":        256_000,
        "notes":      "4B",
    },
    "dw-nemotron-120b": {
        "model":      "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",
        "price_in":   0.23, "price_out": 0.56,
        "ctx":        256_000,
        "notes":      "120B MoE (12B active)",
    },
    "dw-deepseek-ocr-2": {
        "model":      "deepseek-ai/DeepSeek-OCR-2",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.08, "price_out": 0.08,
        "ctx":        16_000,
        "notes":      "",
    },
    "dw-olmocr-2-7b-1025-fp8": {
        "model":      "allenai/olmOCR-2-7B-1025-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.15, "price_out": 0.15,
        "ctx":        16_000,
        "notes":      "7B",
    },
    "dw-lightonocr-2-1b-bbox-soup": {
        "model":      "lightonai/LightOnOCR-2-1B-bbox-soup",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.08, "price_out": 0.08,
        "ctx":        16_000,
        "notes":      "1B",
    },
    "dw-qwen3.5-9b": {
        "model":      "Qwen/Qwen3.5-9B",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.04, "price_out": 0.35,
        "ctx":        256_000,
        "notes":      "9B",
    },
    "dw-qwen3.5-35b": {
        "model":      "Qwen/Qwen3.5-35B-A3B-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.07, "price_out": 0.30,
        "ctx":        256_000,
        "notes":      "35B MoE (3B active)",
    },
    "dw-qwen3-14b": {
        "model":      "Qwen/Qwen3-14B-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.03, "price_out": 0.30,
        "ctx":        32_000,
        "notes":      "14B",
    },
    "dw-qwen3.5-397b": {
        "model":      "Qwen/Qwen3.5-397B-A17B-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",
        "price_in":   0.30, "price_out": 1.80,
        "ctx":        256_000,
        "notes":      "397B MoE (17B active)",
    },
    "dw-gpt-oss-20b": {
        "model":      "openai/gpt-oss-20b",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "ultra_cheap",
        "price_in":   0.03, "price_out": 0.20,
        "ctx":        128_000,
        "notes":      "20B",
    },

    # ═══════════════════════════════════════════════════════════
    #  VISION-LANGUAGE MODELS
    # ═══════════════════════════════════════════════════════════

    "dw-qwen3-vl-30b": {
        "model":      "Qwen/Qwen3-VL-30B-A3B-Instruct-FP8",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "ultra_cheap",
        "price_in":   0.07, "price_out": 0.30,
        "ctx":        256_000,
        "notes":      "30B MoE (3B active), vision-language",
    },
    "dw-qwen3-vl-235b": {
        "model":      "Qwen/Qwen3-VL-235B-A22B-Instruct-FP8",
        "multimodal": True,
        "modalities": ["text", "image", "video"],
        "tier":       "premium",
        "price_in":   0.15, "price_out": 0.55,
        "ctx":        256_000,
        "notes":      "235B MoE (22B active), vision-language",
    },
}

# Doubleword Batch API models — model names use HuggingFace conventions
# Verify model availability at https://app.doubleword.ai/ before running
# Pricing from https://docs.doubleword.ai/batches/model-pricing
# Prices shown are "High" (1h) batch tier — "Standard" (24h) is ~30-50% cheaper
#
# ⚠️  MANUALLY EDITED — Auto-sync disabled via SKIP_DOUBLEWORD_SYNC=1
# Model identifiers corrected to match actual Doubleword API (docs are out of sync)
# To re-enable auto-sync: unset SKIP_DOUBLEWORD_SYNC and run extractor.py

DOUBLEWORD_MODELS = {


# ═══════════════════════════════════════════════════════════
#  TEXT-ONLY MODELS
# ═══════════════════════════════════════════════════════════


    "dw-deepseek-v4-pro": {
        "model":      "deepseek-ai/DeepSeek-V4-Pro",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",
        "price_in":   0.87, "price_out": 1.74,
        "ctx":        1048576,
        "intelligence": 50,
        "quantization": "FP4+FP8",
        "apis":       ["batch", "async", "realtime"],
        "params_total": "1.6T", "params_active": "49B",
        "thinking_default": False,
        "notes":      "FP4+FP8, Intelligence: 50, APIs: Batch/Async/Realtime",
        "description": "DeepSeek V4-Pro is DeepSeek's flagship open MoE model for advanced reasoning, coding, and agentic work. With 1.6T total parameters, 49B active parameters, and a 1M-token context window.",
    },
    "dw-deepseek-v4-flash": {
        "model":      "deepseek-ai/DeepSeek-V4-Flash",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",
        "price_in":   0.07, "price_out": 0.14,
        "ctx":        1048576,
        "intelligence": 47,
        "quantization": "FP4+FP8",
        "apis":       ["batch", "async", "realtime"],
        "params_total": "284B", "params_active": "13B",
        "thinking_default": False,
        "notes":      "FP4+FP8, Intelligence: 47, APIs: Batch/Async/Realtime",
        "description": "DeepSeek V4-Flash is a general-purpose open MoE model built for reasoning, tool use, and long-context work. With 284B total parameters, 13B active parameters, and a 1M-token context window.",
    },
    "dw-glm-5-1": {
        "model":      "zai-org/GLM-5.1-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",
        "price_in":   0.7, "price_out": 2.2,
        "ctx":        202752,
        "intelligence": 51,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],
        "thinking_default": True,
        "extra_params": {"temperature": 1.0, "top_p": 0.95},
        "notes":      "FP8, Intelligence: 51, APIs: Batch/Async/Realtime",
        "description": "GLM-5.1-FP8 is Z.ai next-generation flagship model for agentic engineering, with significantly stronger coding capabilities than GLM-5. State-of-the-art on SWE-Bench Pro.",
        "usage_notes": "Thinking Mode: reasoning enabled by default. To disable: chat_template_kwargs: {enable_thinking: false}. Temp=1.0, TopP=0.95.",
    },
    "dw-glm-5-2": {
        "model":      "zai-org/GLM-5.2-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",           # TODO: verify price from DW pricing page
        "price_in":   0.00, "price_out": 0.00,  # TODO: not yet on DW pricing page
        "ctx":        1048576,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],  # assumed same as GLM-5.1
        "thinking_default": True,
        "extra_params": {"temperature": 1.0, "top_p": 0.95},
        "notes":      "FP8, APIs: Batch/Async/Realtime (assumed — verify pricing)",
        "description": "GLM-5.2-FP8 is Z.ai's latest flagship with solid 1M-token context, advanced coding with flexible thinking effort levels, and an improved IndexShare MoE architecture (2.9× fewer per-token FLOPs at 1M ctx).",
        "usage_notes": "⚠️ Price not yet on DW pricing page. Same calling convention as GLM-5.1: Thinking Mode enabled by default. To disable: chat_template_kwargs: {enable_thinking: false}. Temp=1.0, TopP=0.95.",
    },
    "dw-nemotron-3-super-120b-a12b": {
        "model":      "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",
        "price_in":   0.15, "price_out": 0.38,
        "ctx":        262144,
        "intelligence": 36,
        "quantization": "NVFP4",
        "apis":       ["batch", "async"],
        "params_total": "120B", "params_active": "12B",
        "thinking_default": False,
        "extra_params": {"temperature": 1.0, "top_p": 0.95},
        "notes":      "NVFP4, Intelligence: 36, APIs: Batch/Async",
        "description": "NVIDIA Nemotron 3 Super 120B A12B is an open hybrid Mamba-Transformer LatentMoE model with 120B total parameters and 12B active parameters, built for agentic reasoning, coding, planning, and tool use.",
        "usage_notes": "Temp=1.0, TopP=0.95. To enable reasoning: extra_body={chat_template_kwargs: {enable_thinking: true}}. For low-effort reasoning mode add low_effort: true.",
    },
    "dw-nemotron-3-ultra-550b-a55b": {
        "model":      "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "premium",           # TODO: verify price from DW pricing page
        "price_in":   0.00, "price_out": 0.00,  # TODO: not yet on DW pricing page
        "ctx":        262144,
        "quantization": "NVFP4",
        "apis":       ["batch", "async"],  # assumed same as Nemotron-Super (no realtime)
        "params_total": "550B", "params_active": "55B",
        "thinking_default": False,
        "extra_params": {"temperature": 1.0, "top_p": 0.95},
        "notes":      "NVFP4, APIs: Batch/Async (assumed — verify pricing)",
        "description": "NVIDIA Nemotron 3 Ultra 550B A55B: larger Mamba-Transformer LatentMoE variant with 550B total parameters and 55B active parameters, built for advanced agentic reasoning, coding, and planning.",
        "usage_notes": "⚠️ Price not yet on DW pricing page. Same calling convention as Nemotron-Super: Temp=1.0, TopP=0.95. Thinking opt-in: extra_body={chat_template_kwargs: {enable_thinking: true}}. For low-effort mode add low_effort: true.",
    },
    "dw-gpt-oss-20b": {
        "model":      "openai/gpt-oss-20b",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",
        "price_in":   0.02, "price_out": 0.15,
        "ctx":        131072,
        "intelligence": 24.5,
        "apis":       ["batch", "async", "realtime"],
        "params_total": "21B", "params_active": "3.6B",
        "thinking_default": False,
        "notes":      "Intelligence: 24.5, APIs: Batch/Async/Realtime",
        "description": "OpenAI gpt-oss-20b — for lower latency, and local or specialized use cases (21B parameters with 3.6B active parameters).",
    },
    "dw-gpt-oss-120b": {
        "model":      "openai/gpt-oss-120b",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",          # TODO: verify price from DW pricing page
        "price_in":   0.00, "price_out": 0.00,  # TODO: not yet on DW pricing page
        "ctx":        131072,
        "apis":       ["batch", "async", "realtime"],  # assumed same as gpt-oss-20b
        "thinking_default": False,
        "notes":      "APIs: Batch/Async/Realtime (assumed — verify pricing)",
        "description": "OpenAI gpt-oss-120b — larger MoE variant of gpt-oss-20b for higher-capability tasks (120B total parameters).",
        "usage_notes": "⚠️ Price not yet on DW pricing page. No special params required — same standard calling convention as gpt-oss-20b.",
    },
    "dw-qwen3-14b": {
        "model":      "Qwen/Qwen3-14B-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "budget",
        "price_in":   0.02, "price_out": 0.2,
        "ctx":        32768,
        "intelligence": 12.8,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],
        "max_output_tokens": 16384,
        "thinking_default": False,
        "extra_params": {"temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5},
        "notes":      "FP8, Intelligence: 12.8, APIs: Batch/Async/Realtime",
        "description": "Qwen3-14B: small text-only model from the Qwen3 release. Best for high volume tasks like classification, extraction, or summarization.",
        "usage_notes": "Max New Tokens: 16384. Temp=0.7, TopP=0.8, TopK=20, MinP=0. presence_penalty=1.5 default.",
    },



# ═══════════════════════════════════════════════════════════
#  MULTIMODAL MODELS (TEXT + IMAGE)
# ═══════════════════════════════════════════════════════════


    "dw-qwen3-6-35b-a3b": {
        "model":      "Qwen/Qwen3.6-35B-A3B-FP8",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.05, "price_out": 0.2,
        "ctx":        262144,
        "intelligence": 43,
        "quantization": "FP8",
        "apis":       ["batch", "async"],
        "thinking_default": True,
        "notes":      "FP8, Intelligence: 43, APIs: Batch/Async",
        "description": "Qwen3.6-35B-A3B is an updated version of the Qwen3.5-35B-A3B model prioritizing stability and real-world utility. High-intelligence mid-sized model.",
        "usage_notes": "Thinking Mode: enabled by default. To disable: chat_template_kwargs: {enable_thinking: false}. No graduated thinking levels.",
    },
    "dw-kimi-k2-6": {
        "model":      "moonshotai/Kimi-K2.6",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "premium",
        "price_in":   0.45, "price_out": 2,
        "ctx":        262144,
        "intelligence": 54,
        "quantization": "INT4",
        "apis":       ["batch", "async", "realtime"],
        "thinking_default": False,
        "notes":      "INT4, Intelligence: 54, APIs: Batch/Async/Realtime",
        "description": "Kimi K2.6 is an open-source native multimodal agentic model advancing long-horizon coding, coding-driven design, proactive autonomous execution, and swarm-based task orchestration.",
        "usage_notes": "256K context. Supports instant and thinking modes. Agentic tool use.",
    },
    "dw-gemma-4-31b-it": {
        "model":      "google/gemma-4-31B-it",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.07, "price_out": 0.2,
        "ctx":        256000,
        "intelligence": 39,
        "apis":       ["batch", "async", "realtime"],
        "thinking_default": False,
        "notes":      "Intelligence: 39, APIs: Batch/Async/Realtime",
        "description": "Gemma 4 31B is Google DeepMind's most capable open model, built for advanced reasoning, coding, and multimodal understanding. 256K context, 140+ languages.",
        "usage_notes": "To enable reasoning: chat_template_kwargs: {enable_thinking: true}. Supports image and video input via image_url and video_url content types.",
    },
    "dw-inkling": {
        "model":      "thinkingmachines/Inkling-NVFP4",
        "multimodal": True,
        "modalities": ["text", "image"],   # also supports audio — not used in this benchmark
        "tier":       "standard",          # TODO: verify price from DW pricing page
        "price_in":   0.00, "price_out": 0.00,  # TODO: not yet on DW pricing page
        "ctx":        262_000,             # TODO: verify — not in HF config
        "thinking_default": False,         # TODO: verify — model has <|content_thinking|> token
        "notes":      "MoE, APIs: unknown (verify pricing page)",
        "description": "Inkling (NVFP4) by Thinking Machines: general-purpose multimodal MoE model accepting text, image, and audio inputs. Designed for agentic systems, coding, RAG, and conversational tasks.",
        "usage_notes": "⚠️ Price, context window, and API availability not yet confirmed on DW pricing page. Has reasoning capability via <|content_thinking|> token — verify if on by default. Audio input supported but not used in this benchmark. Verify API call format before running evals.",
    },
    "dw-qwen3-5-9b": {
        "model":      "Qwen/Qwen3.5-9B",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.03, "price_out": 0.29,
        "ctx":        262144,
        "intelligence": 32,
        "apis":       ["batch", "async", "realtime"],
        "thinking_default": True,
        "notes":      "Intelligence: 32, APIs: Batch/Async/Realtime",
        "description": "Qwen3.5-9B is a compact 9B parameter reasoning model with 262K token native context. Outperformed GPT-OSS-120 in Qwen benchmarks despite its small size.",
        "usage_notes": "Thinking Mode: enabled by default. To disable: chat_template_kwargs: {enable_thinking: false}. No graduated thinking levels.",
    },
    "dw-qwen3-5-4b": {
        "model":      "Qwen/Qwen3.5-4B",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.04, "price_out": 0.06,
        "ctx":        262144,
        "intelligence": 27,
        "apis":       ["batch", "async"],
        "thinking_default": True,
        "notes":      "Intelligence: 27, APIs: Batch/Async",
        "description": "Qwen3.5-4B is a compact open 4B model with 262K context window. Outperforms GPT-OSS-20B on MMLU-Pro, GPQA Diamond, AA-LCR, and LongBench v2.",
        "usage_notes": "Thinking Mode: enabled by default. To disable: chat_template_kwargs: {enable_thinking: false}. No graduated thinking levels.",
    },
    "dw-qwen3-5-9b-dottxt": {
        "model":      "Qwen/Qwen3.5-9B-dottxt",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.06, "price_out": 0.58,
        "ctx":        262144,
        "intelligence": 32,
        "apis":       ["batch", "async", "realtime"],
        "thinking_default": True,
        "dottxt":     True,
        "notes":      "Intelligence: 32, APIs: Batch/Async/Realtime, dottxt structured generation",
        "description": "Qwen3.5-9B dottxt variant with enhanced structured generation capabilities for constrained JSON/grammar outputs.",
        "usage_notes": "Thinking Mode: enabled by default. To disable: chat_template_kwargs: {enable_thinking: false}. dottxt structured generation enabled.",
    },
    "dw-qwen3-5-35b-a3b": {
        "potentially_deprecated": True,
        "model":      "Qwen/Qwen3.5-35B-A3B-FP8",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.05, "price_out": 0.2,
        "ctx":        262144,
        "intelligence": 37.1,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],
        "thinking_default": True,
        "notes":      "FP8, Intelligence: 37.1, APIs: Batch/Async/Realtime",
        "description": "Qwen3.5-35B-A3B is a high-intelligence mid-sized model. Outperformed GPT-5-mini, GPT-OSS-120B, and Claude Sonnet 4.5 in published benchmarks.",
        "usage_notes": "Thinking Mode: enabled by default. To disable: chat_template_kwargs: {enable_thinking: false}. No graduated thinking levels.",
    },
    "dw-qwen3-5-35b-a3b-dottxt": {
        "model":      "Qwen/Qwen3.5-35B-A3B-FP8-dottxt",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.1, "price_out": 0.4,
        "ctx":        262144,
        "intelligence": 37.1,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],
        "thinking_default": True,
        "dottxt":     True,
        "notes":      "FP8, Intelligence: 37.1, APIs: Batch/Async/Realtime, dottxt structured generation",
        "description": "Qwen3.5-35B-A3B dottxt variant with enhanced structured generation. Outperformed GPT-5-mini, GPT-OSS-120B, and Claude Sonnet 4.5.",
        "usage_notes": "Thinking Mode: enabled by default. To disable: chat_template_kwargs: {enable_thinking: false}. dottxt structured generation enabled.",
    },
    "dw-qwen3-5-397b-a17b-dottxt": {
        "model":      "Qwen/Qwen3.5-397B-A17B-FP8-dottxt",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "premium",
        "price_in":   0.3, "price_out": 2.4,
        "ctx":        262144,
        "intelligence": 45,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],
        "max_output_tokens": 16384,
        "thinking_default": True,
        "dottxt":     True,
        "extra_params": {"temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5},
        "notes":      "FP8, Intelligence: 45, APIs: Batch/Async/Realtime, dottxt structured generation",
        "description": "Qwen3.5-397B-A17B dottxt: Qwen's most powerful model with dottxt structured generation. Performance similar to GPT-5.2 and Claude Opus 4.5.",
        "usage_notes": "Max New Tokens: 16384. Temp=0.7, TopP=0.8, TopK=20, MinP=0. presence_penalty=1.5. Thinking Mode: enabled by default. No graduated thinking. dottxt structured generation.",
    },
    "dw-qwen3-5-397b-a17b": {
        "model":      "Qwen/Qwen3.5-397B-A17B-FP8",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "premium",
        "price_in":   0.15, "price_out": 1.2,
        "ctx":        262144,
        "intelligence": 45,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],
        "max_output_tokens": 16384,
        "thinking_default": True,
        "extra_params": {"temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5},
        "notes":      "FP8, Intelligence: 45, APIs: Batch/Async/Realtime",
        "description": "Qwen3.5-397B-A17B: Qwen's most powerful model delivering frontier-level performance comparable to GPT-5.2 and Claude Opus 4.5.",
        "usage_notes": "Max New Tokens: 16384. Temp=0.7, TopP=0.8, TopK=20, MinP=0. presence_penalty=1.5. Thinking Mode: enabled by default. No graduated thinking.",
    },
    "dw-qwen3-vl-30b-a3b-instruct": {
        "model":      "Qwen/Qwen3-VL-30B-A3B-Instruct-FP8",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.05, "price_out": 0.2,
        "ctx":        262144,
        "intelligence": 16.1,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],
        "thinking_default": False,
        "notes":      "FP8, Intelligence: 16.1, APIs: Batch/Async/Realtime",
        "description": "Qwen3-VL-30B: mid-sized vision-language model with performance similar to GPT-4.1-mini and Claude Sonnet 4. Excellent for production workloads.",
        "usage_notes": "Best for: complex reasoning, code generation, high token volume production workloads.",
    },
    "dw-qwen3-vl-235b-a22b-instruct": {
        "model":      "Qwen/Qwen3-VL-235B-A22B-Instruct-FP8",
        "multimodal": True,
        "modalities": ["text","image"],
        "tier":       "standard",
        "price_in":   0.1, "price_out": 0.4,
        "ctx":        262144,
        "intelligence": 20.8,
        "quantization": "FP8",
        "apis":       ["batch", "async", "realtime"],
        "max_output_tokens": 16384,
        "thinking_default": False,
        "extra_params": {"temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5},
        "notes":      "FP8, Intelligence: 20.8, APIs: Batch/Async/Realtime",
        "description": "Qwen3-VL-235B: Qwen flagship vision-language model, performance comparable to GPT-5 Chat and Claude 4 Opus Thinking.",
        "usage_notes": "Max New Tokens: 16384. Temp=0.7, TopP=0.8, TopK=20, MinP=0. presence_penalty=1.5.",
    },



# ═══════════════════════════════════════════════════════════
#  OCR MODELS
# ═══════════════════════════════════════════════════════════


    "dw-deepseek-ocr-2": {
        "model":      "deepseek-ai/DeepSeek-OCR-2",
        "multimodal": True,
        "modalities": ["image","text"],
        "tier":       "budget",
        "price_in":   0.05, "price_out": 0.05,
        "ctx":        16834,
        "apis":       ["batch", "async"],
        "ocr":        True,
        "ocr_prompt": "Free OCR.",
        "ocr_max_image_dim": 1540,
        "ocr_max_pages": 10,
        "ocr_jpeg_quality": 75,
        "thinking_default": False,
        "notes":      "APIs: Batch/Async, Layout-aware OCR",
        "description": "DeepSeek-OCR-2: layout-aware OCR with causal vision encoder that captures reading order for structured extraction.",
        "usage_notes": "Use 'Free OCR.' for plain text extraction. Use '<|grounding|>Convert the document to markdown.' for structured markdown output.",
    },
    "dw-lightonocr-2-1b-bbox-soup": {
        "model":      "lightonai/LightOnOCR-2-1B-bbox-soup",
        "multimodal": True,
        "modalities": ["image","text"],
        "tier":       "budget",
        "price_in":   0.05, "price_out": 0.05,
        "ctx":        16384,
        "apis":       ["batch", "async"],
        "ocr":        True,
        "ocr_prompt": None,
        "ocr_no_system_prompt": True,
        "ocr_max_image_dim": 1540,
        "ocr_max_pages": 10,
        "ocr_jpeg_quality": 75,
        "thinking_default": False,
        "notes":      "APIs: Batch/Async, Bbox layout OCR",
        "description": "LightOnOCR-2: efficient 1B-parameter VLM for converting documents into clean naturally ordered text. ~9x smaller than competing approaches.",
        "usage_notes": "Do not include system or user prompt (model repeats it). Send image directly in content. Render PDFs to PNG/JPEG at longest dimension 1540px.",
    },
    "dw-olmocr-2-7b-1025": {
        "model":      "allenai/olmOCR-2-7B-1025-FP8",
        "multimodal": True,
        "modalities": ["image","text"],
        "tier":       "budget",
        "price_in":   0.1, "price_out": 0.1,
        "ctx":        16834,
        "quantization": "FP8",
        "apis":       ["batch", "async"],
        "ocr":        True,
        "ocr_prompt": "Attached is one page of a document. Please return the plain text of this page. Do not include any other text or explanations. Convert equations to LaTeX and tables to HTML.",
        "ocr_max_image_dim": 1288,
        "ocr_max_pages": 10,
        "ocr_jpeg_quality": 75,
        "thinking_default": False,
        "notes":      "FP8, APIs: Batch/Async, OCR for tables, equations, degraded scans",
        "description": "olmOCR-2-7B: Ai2 FP8 OCR model fine-tuned from Qwen2.5-VL-7B-Instruct, with GRPO RL training for math equations, tables, and tricky OCR.",
        "usage_notes": "Requires text prompt alongside image. Default prompt: 'Attached is one page of a document... return plain text... Convert equations to LaTeX and tables to HTML.' Image longest dimension: 1288px.",
    },
    # ═══════════════════════════════════════════════════════════
    #  AUTO-ADDED 2026-07-29 — prices/tier/ctx need review
    # ═══════════════════════════════════════════════════════════

    "dw-gemma-4-26b-a4b-it": {
        "model":      "google/gemma-4-26B-A4B-it",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",       # TODO: verify
        "price_in":   0.00, "price_out": 0.00,  # TODO: fill from pricing page
        "ctx":        262_000,
        "notes":      "",
        "auto_added": True,
    },
    "dw-kimi-k3": {
        "model":      "moonshotai/kimi-k3",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",       # TODO: verify
        "price_in":   0.00, "price_out": 0.00,  # TODO: fill from pricing page
        "ctx":        262_000,
        "notes":      "",
        "auto_added": True,
    },

    # ═══════════════════════════════════════════════════════════
    #  AUTO-ADDED 2026-08-09 — prices/tier/ctx need review
    # ═══════════════════════════════════════════════════════════

    "dw-deepseek-v4-flash-0731": {
        "model":      "deepseek-ai/DeepSeek-V4-Flash-0731",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",       # TODO: verify
        "price_in":   0.00, "price_out": 0.00,  # TODO: fill from pricing page
        "ctx":        1_048_000,
        "notes":      "",
        "auto_added": True,
    },
    "dw-hy3-fp8": {
        "model":      "tencent/Hy3-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",       # TODO: verify
        "price_in":   0.00, "price_out": 0.00,  # TODO: fill from pricing page
        "ctx":        262_000,
        "notes":      "",
        "auto_added": True,
    },

    # ═══════════════════════════════════════════════════════════
    #  AUTO-ADDED 2026-08-21 — prices/tier/ctx need review
    # ═══════════════════════════════════════════════════════════

    "dw-qwen3.8-27b": {
        "model":      "Qwen/Qwen3.8-27B-FP8",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",       # TODO: verify
        "price_in":   0.00, "price_out": 0.00,  # TODO: fill from pricing page
        "ctx":        262_000,          # TODO: verify
        "notes":      "",
        "auto_added": True,
    },
    "dw-muse-glimmer-30b": {
        "model":      "meta-models/Muse-Glimmer-30B",
        "multimodal": False,
        "modalities": ["text"],
        "tier":       "standard",       # TODO: verify
        "price_in":   0.00, "price_out": 0.00,  # TODO: fill from pricing page
        "ctx":        262_000,          # TODO: verify
        "notes":      "",
        "auto_added": True,
    },

}

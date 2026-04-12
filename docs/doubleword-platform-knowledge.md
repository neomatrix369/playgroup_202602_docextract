# Doubleword AI — Platform Knowledge Base
> Machine-readable reference. Distilled from docs.doubleword.ai, www.doubleword.ai, and github.com/doublewordai.
> Last updated: 2026-03-31

**See also (same repo):** **OpenRouter** (~33 models, `config_models_openrouter.py`, manual pricing). **V7 Go** (32 optional keys, `config_models_v7.py`, manual pricing, entity API — no Doubleword-style batch id). Short V7 reference: [docs/v7-go.md](v7-go.md); full workflow: [README.md — V7 Go](../README.md#v7-go-optional-backend). Cross-backend stats and pricing: [README — Key Findings](../README.md#key-findings).

---

## 1. What is Doubleword?

Doubleword is an LLM inference platform offering three distinct products:

| Product | What it is | Hosted by |
|---|---|---|
| **Inference API** | Managed API for LLM inference (batch, async, realtime) | Doubleword cloud |
| **Control Layer** | Open-source Rust gateway/proxy (self-hostable) | You |
| **Inference Stack** | Full self-hosted GPU deployment stack | You |

**Core value proposition:** Batch and async inference at significantly lower cost than major providers. Benchmark: 1B tokens in+out costs ~$2,100 on Doubleword vs ~$30,000 on Anthropic and ~$15,800 on OpenAI.

**Free tier:** 20M free tokens for new users.

**SLA guarantee:** If Doubleword misses its SLA, the job is free.

**Key URLs:**
- Docs: https://docs.doubleword.ai
- Marketing / pricing: https://www.doubleword.ai
- Dashboard: https://app.doubleword.ai
- GitHub org: https://github.com/doublewordai
- Blog: https://blog.doubleword.ai (also at docs.doubleword.ai/blog)

---

## 2. Inference API

### 2.1 Authentication
- API key via env var: `DOUBLEWORD_API_KEY`
- Compatible with OpenAI client SDK (use as drop-in with base URL swap)

### 2.2 Three Inference Modes

| Mode | Marketing name | Latency | Cost | Use when |
|---|---|---|---|---|
| Realtime | Dev Mode | Immediate | Highest | Interactive, low-latency |
| Async | Background Agent | Minutes | Mid | Non-blocking pipelines |
| Batch | Overnight Batch | Hours | Lowest (~80%+ savings) | Bulk, offline processing |

### 2.3 Batch Inference (core feature)

**Flow:**
1. Upload JSONL file of requests → `POST /batches/upload`
2. Create batch job → `POST /batches` (specify model, completion window)
3. Poll status → `GET /batches/{id}`
4. Download results when `status == "completed"` → `GET /batches/{id}/output`

**Completion windows:** `"1h"` | `"24h"`

**Input format:** JSONL, one request per line, OpenAI-compatible messages format.

**Status values:** `validating` → `in_progress` → `completed` | `failed` | `expired`

**Batch result files:**
- `output_file_id` — JSONL of all processed requests (including per-request `error` fields for requests the model rejected)
- `error_file_id` — JSONL of requests that were **rejected before processing** (e.g. `context_length_exceeded`). Only present when at least one request failed at this level. Download via `GET /files/{id}/content`. Row-level errors here are distinct from per-response errors in the output file.

**Analytics endpoints (undocumented, Doubleword-specific):**
- `GET /batches?include=analytics` — list all batches with cost/token data
- `GET /batches/{id}/analytics` — per-batch analytics

Analytics payload fields: `total_requests`, `total_prompt_tokens`, `total_completion_tokens`, `total_tokens`, `avg_duration_ms`, `avg_ttfb_ms`, `total_cost`

> ⚠️ These endpoints are NOT in the public docs and are NOT part of the OpenAI-compatible surface. Access via direct `httpx` calls, not the OAI Python client.

### 2.4 Autobatcher

**Install:** `pip install autobatcher`

**What it does:** Drop-in replacement for `AsyncOpenAI`. Transparently batches requests using a configurable time window and batch size. No manual JSONL handling required.

```python
from autobatcher import AutoBatcher
client = AutoBatcher(
    api_key=os.environ["DOUBLEWORD_API_KEY"],
    base_url="https://api.doubleword.ai/v1",
    batch_window_seconds=30,
    max_batch_size=100
)
# Use exactly like AsyncOpenAI
response = await client.chat.completions.create(...)
```

**Limitation:** Only works with `chat.completions.create`. Not suited for streaming or tool-call-heavy interactive flows.

**Savings:** ~80%+ vs realtime on Doubleword; ~50% vs realtime on OpenAI.

**Best fit:** Bulk non-interactive workloads (document processing, data extraction, classification pipelines).

### 2.5 Async Inference

- Fire-and-forget single requests (not batch JSONL)
- Returns a job ID immediately
- Poll `GET /jobs/{id}` for result
- Use for: pipelines where you want non-blocking but don't need bulk batching

### 2.6 Model Catalog

Model names use `dw-` prefix in Doubleword's native API.

| Model | Notes |
|---|---|
| `dw-llama-3.3-70b` | General purpose |
| `dw-llama-3.1-405b` | Largest open model |
| `dw-deepseek-r1` | Reasoning |
| `dw-deepseek-v3` | General |
| `dw-qwen-2.5-72b` | General |
| `dw-mistral-large` | General |
| `dw-nemotron-70b` | General; note overnight pricing discrepancy between docs ($0.00) and marketing site ($0.15/$0.38) |
| `dw-vl-235b` | Vision/multimodal |
| `dw-deepseek-ocr-2` | OCR |
| `dw-olmocr-2-7b` | OCR |
| `dw-lighton-ocr-2-1b` | OCR (small, fast) |

> Canonical pricing: https://docs.doubleword.ai/batches/model-pricing and https://www.doubleword.ai (may differ — verify both)

### 2.7 Tool Calling & Structured Outputs

- Supported via standard OpenAI-compatible `tools` parameter
- Structured outputs: use `response_format: { type: "json_object" }` or JSON schema
- Works in realtime and async modes; batch tool calling has caveats (verify in docs)

### 2.8 Vision / Multimodal

- Use `dw-vl-235b` for image+text input
- Pass images as base64 in the messages `content` array (OpenAI vision format)

### 2.9 Embeddings

- `POST /embeddings` — OpenAI-compatible
- Use for semantic search, RAG pipelines

### 2.10 Organizations & Webhooks

**Org roles:**
| Role | Permissions |
|---|---|
| Owner | Full access, billing, org management |
| Admin | Manage members, API keys |
| Member | Use API, view own usage |

- Shared credit balance across org members
- Per-member API keys

**Webhooks:**
- Standard Webhooks spec
- Signature: HMAC-SHA256, verify via `svix-signature` header
- Retry behavior: automatic retries on failure
- Auto-disable after 10 consecutive failures

### 2.11 SDK / Client

Doubleword's API is OpenAI-compatible. Use the OpenAI Python SDK with base URL override:

```python
from openai import AsyncOpenAI
client = AsyncOpenAI(
    api_key=os.environ["DOUBLEWORD_API_KEY"],
    base_url="https://api.doubleword.ai/v1"
)
```

For batch-specific operations, use direct `httpx` calls for non-OAI endpoints (analytics, job management).

---

## 3. Control Layer

**What it is:** Open-source Rust-based LLM gateway/proxy. Self-hosted. Routes requests, manages rate limits, provides observability.

**Repo:** https://github.com/doublewordai/control-layer

**Install:** Via Docker or Rust build

**Key features:**
- Request routing across multiple providers
- Rate limiting and quota management
- Logging and observability hooks
- Can sit in front of Doubleword Inference API or other providers

**Use when:** You need a self-hosted proxy layer — for compliance, custom routing logic, or multi-provider fan-out.

**Docs:** https://docs.doubleword.ai/control-layer/

---

## 4. Inference Stack

**What it is:** Full self-hosted GPU deployment stack. Deploy and serve your own LLM inference on your own hardware.

**Use when:** Data sovereignty requirements, on-prem GPU clusters, need full control over model serving.

**Docs:** https://docs.doubleword.ai/inference-stack/

---

## 5. CLI Tool

**Install:** `pip install dw-cli`

**Command:** `dw`

**Use for:** Submitting batch jobs, checking status, downloading results from terminal — without writing Python.

---

## 6. AI Coding Agent Skill

**Repo:** https://github.com/doublewordai/batch-skill

**Install (Claude Code / Cursor / Windsurf / Codex):**
```
npx skills add doublewordai/batch-skill
# or
git clone https://github.com/doublewordai/batch-skill
```

**Purpose:** Gives coding agents a skill to submit and manage Doubleword batch jobs from within an agentic workflow.

---

## 7. Open Source Ecosystem

| Repo | Purpose |
|---|---|
| `doublewordai/control-layer` | Rust LLM gateway |
| `doublewordai/batch-skill` | AI coding agent skill |
| `doublewordai/inference-lab` | Inference experimentation |
| `doublewordai/arxiv-sorter` | Example: batch paper classification |
| `doublewordai/bit-harbor` | Storage/artifact utility |
| `doublewordai/qlm` | Query Language for Models |
| `doublewordai/use-cases` | Example use case implementations |
| `autobatcher` (PyPI) | Drop-in async batch client |

---

## 8. Community Skills (Third-Party)

Multiple community-built skills exist. They are NOT cross-referenced in official docs.

| Skill | Author | Notes |
|---|---|---|
| `doublewordai/batch-skill` | Official | Reference implementation |
| `dw_batch_skill` | Nnamdi Odozi | Alternative impl |
| OpenClaw v1 | OpenClaw | API-only, no autobatcher |
| OpenClaw v2 | OpenClaw | Adds autobatcher |
| Termo.ai hosted | Termo.ai | Hosted version |

> ⚠️ OpenClaw skill uses `anthropic/claude-3-5-sonnet` as a model string — this is NOT a Doubleword-hosted model. Verify model strings when using third-party skills.

---

## 9. Seen in the Wild (Real-World Use Cases)

| Project | Description |
|---|---|
| OpenMed SynthVision | 110K medical VQA dataset generation |
| Dataiku Kiji Privacy Proxy | PII redaction pipeline |
| Invoice processing | Batch invoice extraction for ~$0.50 |
| UK charity extraction | OCR text → structured JSON from charity financial docs (Mani's project) |
| Batchling | Batch job management tool |
| OpenClaw Skill | Agent skill wrapper |

Source: https://www.doubleword.ai/seen-in-the-wild

---

## 10. Known Documentation Gaps & Issues

These are confirmed gaps as of the last audit. Useful context when helping users who may be confused by missing or inconsistent information.

| # | Gap | Location | Impact |
|---|---|---|---|
| 1 | No code on intro/overview page | docs.doubleword.ai intro | High — developers expect runnable hello-world immediately |
| 2 | Nemotron overnight pricing discrepancy | docs ($0.00/$0.00) vs marketing ($0.15/$0.38) | Medium — misleading cost estimates |
| 3 | OCR models absent from docs pricing page | docs.doubleword.ai/batches/model-pricing | Medium — OCR models only visible on marketing site |
| 3a | No context window info for OCR models (or most models) | docs.doubleword.ai/inference-api/model-pricing.md | High — only 2 of 10 models expose `Max Total Tokens`; OCR models give no context limit at all. Real limits (olmOCR-2-7B ≈128K, LightOnOCR-2-1B ≈32K) must be inferred from upstream model cards. Oversized requests are silently dropped to the `error_file_id` with no in-output error message. |
| 4 | Analytics endpoints undocumented | No public docs page | High — no way to programmatically retrieve cost/token data without reverse-engineering |
| 5 | Skills fragmentation, no cross-referencing | Docs only list official skill | Medium — users unaware of community alternatives |
| 6 | Two separate blog locations | docs.doubleword.ai/blog AND blog.doubleword.ai | Low — confusing, content may diverge |
| 7 | Docs vs marketing site content gap | www.doubleword.ai has OCR models, CLI, community showcase absent from docs | High — significant features invisible to docs-only readers |
| 8 | JSONL promoted as a top-6 guide | Docs homepage | Low — signals wrong audience (experienced devs don't need a JSONL explainer) |
| 9 | Homepage CTA links to old URL pattern | www.doubleword.ai | Low — broken or redirected link |
| 10 | No consolidated prerequisites page | Entire docs site | Medium — unclear what SDK versions, auth setup, or background knowledge is needed |

---

## 11. Key External Links

### Docs
- Overview: https://docs.doubleword.ai
- Batch inference: https://docs.doubleword.ai/inference-api/batch-inference
- Async inference: https://docs.doubleword.ai/inference-api/async-inference
- Model pricing: https://docs.doubleword.ai/batches/model-pricing
- Autobatcher: https://docs.doubleword.ai/batches/autobatcher
- Tool calling: https://docs.doubleword.ai/inference-api/tool-calling
- Structured outputs: https://docs.doubleword.ai/inference-api/structured-outputs
- Vision: https://docs.doubleword.ai/inference-api/vision
- Embeddings: https://docs.doubleword.ai/inference-api/embeddings
- Organizations: https://docs.doubleword.ai/account/organizations
- Webhooks: https://docs.doubleword.ai/account/webhooks
- Control Layer: https://docs.doubleword.ai/control-layer
- Inference Stack: https://docs.doubleword.ai/inference-stack

### Marketing / Other
- Pricing benchmarks: https://www.doubleword.ai/pricing
- Savings calculator: https://www.doubleword.ai/calculator
- Community showcase: https://www.doubleword.ai/seen-in-the-wild
- Blog: https://blog.doubleword.ai
- GitHub org: https://github.com/doublewordai

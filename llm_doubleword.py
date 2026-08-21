"""Doubleword Batch API client — direct batch management with checkpoint support.

Bypasses autobatcher to give full control over batch lifecycle:
submit, poll, resume, and download results independently.

OCR models receive PDF pages as base64-encoded images via the OpenAI vision
content format. PyMuPDF renders pages (bounded by registry `ocr_max_pages`,
dimensions, JPEG quality); Doubleword rejects JSONL lines over 5MB, so payloads
may adaptively lower quality/scale until under budget.
"""

import asyncio
import base64
import io
import json
import os
import time

from dotenv import load_dotenv
from openai import AsyncOpenAI

import utils
from utils import get_logger, add_file_logger

logger = get_logger(__name__)
add_file_logger("llm_doubleword_calls.log", name_filter=__name__)

load_dotenv()

CHECKPOINT_FILE = "data/.doubleword_checkpoints.json"
FAILED_ROWS_FILE = "data/.doubleword_failed_rows.json"
UNAVAILABLE_MODELS_FILE = "data/.doubleword_unavailable_models.json"

SYSTEM_MESSAGE = (
    "You are an expert at extracting information from UK charity financial documents. "
    "Follow the instructions exactly. Output ONLY the JSON block, nothing else."
)


def create_client() -> AsyncOpenAI:
    """Create an AsyncOpenAI client configured for the Doubleword API."""
    return AsyncOpenAI(
        api_key=os.getenv("DOUBLEWORD_API_KEY"),
        base_url="https://api.doubleword.ai/v1",
    )


# ── Checkpoint persistence ──────────────────────────────────────────

def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {}


def save_checkpoint(data: dict):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def remove_checkpoint_entry(model_short_name: str):
    cp = load_checkpoint()
    cp.pop(model_short_name, None)
    save_checkpoint(cp)


# ── Failed rows persistence ─────────────────────────────────────────

def load_failed_rows() -> dict:
    """Return {model_short_name: [row_nums]} for rows that failed in the last completed batch."""
    if os.path.exists(FAILED_ROWS_FILE):
        with open(FAILED_ROWS_FILE) as f:
            return json.load(f)
    return {}


def save_failed_rows(data: dict):
    with open(FAILED_ROWS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def update_failed_rows_entry(model_short_name: str, row_nums: list):
    fr = load_failed_rows()
    fr[model_short_name] = row_nums
    save_failed_rows(fr)


def remove_failed_rows_entry(model_short_name: str):
    fr = load_failed_rows()
    fr.pop(model_short_name, None)
    save_failed_rows(fr)


# ── Unavailable models persistence ─────────────────────────────────

def load_unavailable_models() -> dict:
    """Return {model_short_name: reason} for models that are unavailable/permission-denied."""
    if os.path.exists(UNAVAILABLE_MODELS_FILE):
        with open(UNAVAILABLE_MODELS_FILE) as f:
            return json.load(f)
    return {}


def mark_model_unavailable(model_short_name: str, reason: str):
    """Record a model as unavailable so future runs skip it without re-attempting."""
    data = load_unavailable_models()
    data[model_short_name] = reason
    with open(UNAVAILABLE_MODELS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    logger.warning(
        "[Doubleword] Model '{}' marked unavailable: {} — recorded in {}",
        model_short_name, reason, UNAVAILABLE_MODELS_FILE,
    )


# ── PDF → base64 image conversion for OCR models ────────────────────

DOUBLEWORD_MAX_LINE_BYTES = 5_242_880  # 5 MB per-line limit in JSONL batch files

def _pdf_to_base64_images(
    pdf_path: str,
    max_dim: int = 1540,
    max_pages: int | None = None,
    jpeg_quality: int = 80,
) -> list[str]:
    """Render each page of a PDF to a JPEG base64 string, capped at max_dim px.

    Args:
        max_dim: longest side of rendered image in pixels
        max_pages: if set, only render the first N pages
        jpeg_quality: JPEG compression quality (1-100, lower = smaller)

    Returns a list of base64-encoded JPEG strings (one per page).
    """
    import pymupdf

    doc = pymupdf.open(pdf_path)
    pages = list(doc)
    if max_pages and len(pages) > max_pages:
        logger.debug("Capping {} pages to {} for {}", len(pages), max_pages, pdf_path)
        pages = pages[:max_pages]

    images = []
    for page in pages:
        rect = page.rect
        longest = max(rect.width, rect.height)
        zoom = max_dim / longest if longest > max_dim else 1.0
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        img_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
        images.append(base64.b64encode(img_bytes).decode("ascii"))
    doc.close()
    return images


def _build_ocr_messages(
    pdf_path: str,
    model_cfg: dict,
    extraction_prompt: str,
    size_budget: int = DOUBLEWORD_MAX_LINE_BYTES,
) -> list[dict]:
    """Build the messages array for an OCR model request.

    Returns a list of message dicts suitable for the OpenAI chat completions API.
    The message includes base64-encoded page images plus an appropriate text prompt.

    For LightOnOCR (ocr_no_system_prompt=True): no system message, image-only
    user content — the model repeats any text prompt.

    For other OCR models: system message + user content with images + OCR prompt
    followed by the extraction prompt.

    If the resulting payload exceeds size_budget, retries with progressively
    lower quality/resolution until it fits.
    """
    max_dim = model_cfg.get("ocr_max_image_dim", 1540)
    max_pages = model_cfg.get("ocr_max_pages")
    jpeg_quality = model_cfg.get("ocr_jpeg_quality", 80)
    no_system = model_cfg.get("ocr_no_system_prompt", False)
    ocr_prompt = model_cfg.get("ocr_prompt")
    two_step_ocr = model_cfg.get("two_step_ocr", False)

    # Adaptive rendering: try progressively smaller settings if payload is too large
    attempts = [
        (max_dim, max_pages, jpeg_quality),
        (max_dim, max_pages, 60),
        (int(max_dim * 0.75), max_pages, 60),
        (int(max_dim * 0.6), max_pages, 50),
    ]

    for dim, pages, quality in attempts:
        page_images = _pdf_to_base64_images(
            pdf_path, max_dim=dim, max_pages=pages, jpeg_quality=quality,
        )
        messages = _assemble_ocr_messages(
            page_images, no_system, ocr_prompt, extraction_prompt,
            two_step_ocr=two_step_ocr,
        )
        payload_size = len(json.dumps(messages).encode("utf-8"))

        # Leave ~200KB headroom for the JSONL wrapper (custom_id, method, url, model)
        if payload_size < size_budget - 200_000:
            if (dim, pages, quality) != attempts[0]:
                logger.info(
                    "Adapted OCR settings for {} → dim={}, quality={} ({:.1f} MB)",
                    pdf_path, dim, quality, payload_size / 1024 / 1024,
                )
            return messages

    logger.warning(
        "OCR payload for {} still {:.1f} MB after all reductions — sending anyway",
        pdf_path, payload_size / 1024 / 1024,
    )
    return messages


def _assemble_ocr_messages(
    page_images: list[str],
    no_system: bool,
    ocr_prompt: str | None,
    extraction_prompt: str,
    two_step_ocr: bool = False,
) -> list[dict]:
    """Assemble message dicts from pre-rendered page images.

    When two_step_ocr=True, only the ocr_prompt is included (no extraction
    instructions) — the model acts as a pure transcriber. A second text-mode
    batch handles JSON extraction from the OCR output.
    """
    image_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img}"},
        }
        for img in page_images
    ]

    messages = []

    if no_system:
        messages.append({"role": "user", "content": image_content})
    else:
        messages.append({"role": "system", "content": SYSTEM_MESSAGE})
        user_parts = list(image_content)
        if two_step_ocr:
            text_prompt = ocr_prompt or "Extract all text from this document."
        else:
            text_prompt = ""
            if ocr_prompt:
                text_prompt += ocr_prompt + "\n\n"
            text_prompt += extraction_prompt
        user_parts.append({"type": "text", "text": text_prompt})
        messages.append({"role": "user", "content": user_parts})

    return messages


# ── Batch operations ────────────────────────────────────────────────

async def submit_batch(
    client: AsyncOpenAI,
    model_short_name: str,
    model_full_name: str,
    prompt_template: str,
    rows: list[tuple[int, str, str]],
    completion_window: str = "1h",
    extra_params: dict | None = None,
    model_cfg: dict | None = None,
) -> str:
    """Submit rows as a batch job. Saves checkpoint. Returns batch_id.

    Args:
        rows: list of (row_num, pdf_filename, text_combined)
        extra_params: optional sampling params merged into each request body (e.g. {"top_k": 1})
        model_cfg: full model config dict; when present and ocr=True, sends PDF
                   pages as base64 images instead of text.
    """
    is_ocr = model_cfg.get("ocr", False) if model_cfg else False

    lines = []
    for row_num, pdf_filename, text_combined in rows:
        if is_ocr:
            pdf_path = os.path.join("data", pdf_filename)
            if not os.path.exists(pdf_path):
                logger.error("[OCR] PDF not found: {} — falling back to text for row {}", pdf_path, row_num)
                is_ocr_row = False
            else:
                is_ocr_row = True

            if is_ocr_row:
                messages = _build_ocr_messages(pdf_path, model_cfg, prompt_template)
            else:
                messages = [
                    {"role": "system", "content": SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt_template + text_combined},
                ]
        else:
            prompt = prompt_template + text_combined
            messages = [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ]

        body = {
            "model": model_full_name,
            "messages": messages,
        }
        if extra_params:
            body.update(extra_params)
        line = {
            "custom_id": f"row_{row_num}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }
        lines.append(json.dumps(line))

    content = "\n".join(lines)
    file_response = await client.files.create(
        file=(f"batch-{model_short_name}.jsonl", content.encode("utf-8")),
        purpose="batch",
    )
    logger.info("Uploaded batch file {} for {}{}", file_response.id, model_short_name,
                " [OCR image mode]" if is_ocr else "")

    batch_response = await client.batches.create(
        input_file_id=file_response.id,
        endpoint="/v1/chat/completions",
        completion_window=completion_window,
    )
    logger.info("Submitted batch {} for {} ({} rows)",
                batch_response.id, model_short_name, len(rows))
    logger.info("  → Track progress: https://app.doubleword.ai/batches/{}", batch_response.id)

    cp = load_checkpoint()
    cp[model_short_name] = {
        "batch_id": batch_response.id,
        "model_full_name": model_full_name,
        "row_count": len(rows),
        "submitted_at": time.time(),
    }
    save_checkpoint(cp)

    return batch_response.id


async def poll_batch(client: AsyncOpenAI, batch_id: str):
    """Check batch status. Returns (status, output_file_id, error_file_id, counts_dict).

    error_file_id is the DW error file for requests that failed before processing
    (e.g. context_length_exceeded). It is None when there are no such failures.
    The counts dict includes API-reported created_at/completed_at timestamps
    for accurate elapsed time calculation.
    """
    batch = await client.batches.retrieve(batch_id)
    counts = batch.request_counts
    return batch.status, batch.output_file_id, getattr(batch, "error_file_id", None), {
        "total": counts.total if counts else 0,
        "completed": counts.completed if counts else 0,
        "failed": counts.failed if counts else 0,
        "created_at": getattr(batch, "created_at", None),
        "completed_at": getattr(batch, "completed_at", None),
    }


async def download_error_file(client: AsyncOpenAI, error_file_id: str) -> dict:
    """Download the DW batch error file for requests that failed before processing.

    Returns {row_num: error_message_str} for each failed request.
    These are distinct from per-row errors in the output file — they represent
    requests the server rejected outright (e.g. context_length_exceeded).
    """
    content = await client.files.content(error_file_id)
    errors = {}
    for line in content.text.strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            custom_id = entry.get("custom_id", "")
            if custom_id.startswith("row_"):
                row_num = int(custom_id.split("_", 1)[1])
                error_msg = str(entry.get("error", entry))
                errors[row_num] = error_msg
        except (json.JSONDecodeError, ValueError):
            logger.warning("[Doubleword] Could not parse error file line: {}", line[:200])
    return errors


async def download_results(client: AsyncOpenAI, output_file_id: str) -> dict[int, dict]:
    """Download completed batch results.

    Returns {row_num: {"text": str, "prompt_tokens": int, "completion_tokens": int}}
    or {row_num: {"error": str}}.
    """
    content = await client.files.content(output_file_id)
    text = content.text

    results = {}
    for line in text.strip().split("\n"):
        if not line:
            continue
        entry = json.loads(line)
        custom_id = entry["custom_id"]
        row_num = int(custom_id.split("_", 1)[1])

        error_data = entry.get("error")
        response_data = entry.get("response", {})

        if error_data:
            results[row_num] = {"error": str(error_data)}
        else:
            body = response_data.get("body", {})
            usage = body.get("usage") or {}
            choices = body.get("choices", [])
            if choices:
                raw_text = choices[0].get("message", {}).get("content", "")
                extracted = utils.extract_from_triple_backticks(raw_text)
                results[row_num] = {
                    "text": extracted if extracted else raw_text,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                }
            else:
                results[row_num] = {"error": "No choices in response"}

    return results


async def submit_text_extraction_batch(
    client: AsyncOpenAI,
    step2_name: str,
    extract_model_full_name: str,
    ocr_results: dict[int, dict],
    rows: list[tuple[int, str, str]],
    prompt_template: str,
    completion_window: str = "1h",
    extra_params: dict | None = None,
) -> str:
    """Submit a text-mode extraction batch using OCR output as input (step 2 of two_step_ocr).

    Args:
        step2_name: unique name for checkpoint tracking (e.g. "dw-deepseek-ocr-2::step2")
        extract_model_full_name: HuggingFace model id for the extraction LLM
        ocr_results: {row_num: {"text": ocr_text, ...}} from step-1 OCR batch
        rows: original rows list [(row_num, pdf_filename, text_combined), ...]
        prompt_template: extraction JSON prompt to prepend to each OCR text
    """
    lines = []
    for row_num, _pdf_filename, _orig_text in rows:
        ocr_result = ocr_results.get(row_num, {})
        if "error" in ocr_result:
            continue  # skip rows that failed in OCR step
        ocr_text = ocr_result.get("text", "")
        prompt = prompt_template + "\n\n" + ocr_text
        body: dict = {
            "model": extract_model_full_name,
            "messages": [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
        }
        if extra_params:
            body.update(extra_params)
        lines.append(json.dumps({
            "custom_id": f"row_{row_num}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }))

    content = "\n".join(lines)
    file_response = await client.files.create(
        file=(f"batch-{step2_name}.jsonl", content.encode("utf-8")),
        purpose="batch",
    )
    logger.info("Uploaded step-2 extraction batch file {} for {}", file_response.id, step2_name)

    batch_response = await client.batches.create(
        input_file_id=file_response.id,
        endpoint="/v1/chat/completions",
        completion_window=completion_window,
    )
    logger.info("Submitted step-2 extraction batch {} for {} ({} rows)",
                batch_response.id, step2_name, len(lines))
    logger.info("  → Track progress: https://app.doubleword.ai/batches/{}", batch_response.id)
    return batch_response.id


async def poll_until_complete(
    client: AsyncOpenAI,
    batch_id: str,
    label: str,
    poll_interval: int = 30,
) -> tuple[str, str | None, str | None, dict]:
    """Poll a batch until terminal state. Returns (status, output_file_id, error_file_id, counts)."""
    while True:
        status, output_file_id, error_file_id, counts = await poll_batch(client, batch_id)
        if status in ("completed", "failed", "expired", "cancelled"):
            return status, output_file_id, error_file_id, counts
        logger.info("[{}] step-2 batch {}: {}/{} done, waiting {}s…",
                    label, batch_id, counts["completed"], counts["total"], poll_interval)
        await asyncio.sleep(poll_interval)

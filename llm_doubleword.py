"""Doubleword Batch API client — direct batch management with checkpoint support.

Bypasses autobatcher to give full control over batch lifecycle:
submit, poll, resume, and download results independently.

OCR models receive PDF pages as base64-encoded images via the OpenAI vision
content format. Each PDF is rendered to images using PyMuPDF; all pages of a
single PDF are sent as multiple image_url entries in one batch request.
"""

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

def _pdf_to_base64_images(pdf_path: str, max_dim: int = 1540) -> list[str]:
    """Render each page of a PDF to a JPEG base64 string, capped at max_dim px.

    Returns a list of base64-encoded JPEG strings (one per page).
    """
    import pymupdf

    doc = pymupdf.open(pdf_path)
    images = []
    for page in doc:
        rect = page.rect
        longest = max(rect.width, rect.height)
        zoom = max_dim / longest if longest > max_dim else 1.0
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        img_bytes = pix.tobytes("jpeg")
        images.append(base64.b64encode(img_bytes).decode("ascii"))
    doc.close()
    return images


def _build_ocr_messages(
    pdf_path: str,
    model_cfg: dict,
    extraction_prompt: str,
) -> list[dict]:
    """Build the messages array for an OCR model request.

    Returns a list of message dicts suitable for the OpenAI chat completions API.
    The message includes base64-encoded page images plus an appropriate text prompt.

    For LightOnOCR (ocr_no_system_prompt=True): no system message, image-only
    user content — the model repeats any text prompt.

    For other OCR models: system message + user content with images + OCR prompt
    followed by the extraction prompt.
    """
    max_dim = model_cfg.get("ocr_max_image_dim", 1540)
    page_images = _pdf_to_base64_images(pdf_path, max_dim=max_dim)
    no_system = model_cfg.get("ocr_no_system_prompt", False)
    ocr_prompt = model_cfg.get("ocr_prompt")

    image_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img}"},
        }
        for img in page_images
    ]

    messages = []

    if no_system:
        # LightOnOCR: image-only, no text at all
        messages.append({"role": "user", "content": image_content})
    else:
        messages.append({"role": "system", "content": SYSTEM_MESSAGE})
        user_parts = list(image_content)
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

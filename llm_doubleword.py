"""Doubleword Batch API client — direct batch management with checkpoint support.

Bypasses autobatcher to give full control over batch lifecycle:
submit, poll, resume, and download results independently.
"""

import json
import logging
import os
import time

from dotenv import load_dotenv
from openai import AsyncOpenAI

import utils
from utils import get_logger

logger = get_logger(__name__)
_fh = logging.FileHandler("llm_doubleword_calls.log")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_fh)

load_dotenv()

CHECKPOINT_FILE = "data/.doubleword_checkpoints.json"

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


# ── Batch operations ────────────────────────────────────────────────

async def submit_batch(
    client: AsyncOpenAI,
    model_short_name: str,
    model_full_name: str,
    prompt_template: str,
    rows: list[tuple[int, str, str]],
    completion_window: str = "1h",
) -> str:
    """Submit rows as a batch job. Saves checkpoint. Returns batch_id.

    Args:
        rows: list of (row_num, pdf_filename, text_combined)
    """
    lines = []
    for row_num, _pdf_filename, text_combined in rows:
        prompt = prompt_template + text_combined
        line = {
            "custom_id": f"row_{row_num}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": model_full_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ],
            },
        }
        lines.append(json.dumps(line))

    content = "\n".join(lines)
    file_response = await client.files.create(
        file=(f"batch-{model_short_name}.jsonl", content.encode("utf-8")),
        purpose="batch",
    )
    logger.info("Uploaded batch file %s for %s", file_response.id, model_short_name)

    batch_response = await client.batches.create(
        input_file_id=file_response.id,
        endpoint="/v1/chat/completions",
        completion_window=completion_window,
    )
    logger.info("Submitted batch %s for %s (%d rows)",
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
    """Check batch status. Returns (status, output_file_id, counts_dict)."""
    batch = await client.batches.retrieve(batch_id)
    counts = batch.request_counts
    return batch.status, batch.output_file_id, {
        "total": counts.total if counts else 0,
        "completed": counts.completed if counts else 0,
        "failed": counts.failed if counts else 0,
    }


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
            usage = body.get("usage", {})
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

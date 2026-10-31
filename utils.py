import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from loguru import logger

# ── Shared loguru logging ─────────────────────────────────────────
# Uses default loguru level colors (matching autobatcher):
#   DEBUG=blue, INFO=bold, WARNING=yellow, ERROR=red, CRITICAL=bold red

# Remove default handler; add our own with module name from extra["name"]
logger.remove()
logger.add(
    sys.stderr,
    format="<level>{level: <7}</level> | <cyan>{extra[name]: >12}</cyan> | {message}",
    level="DEBUG",
    colorize=True,
)


def get_logger(name):
    """Create a loguru logger bound with a module name."""
    return logger.bind(name=name)


def add_file_logger(filename, name_filter=None):
    """Add a file sink, optionally filtered to a specific logger name."""
    logger.add(
        filename,
        format="{time:YYYY-MM-DD HH:mm:ss} {level: <7} {message}",
        filter=lambda record: name_filter is None or record["extra"].get("name") == name_filter,
        level="DEBUG",
    )


def sanitize_error_message(msg):
    """Strip sensitive fields (user_id, api keys) from API error messages."""
    msg = re.sub(r"'user_id':\s*'[^']*'", "'user_id': '<redacted>'", msg)
    msg = re.sub(r"\"user_id\":\s*\"[^\"]*\"", '"user_id": "<redacted>"', msg)
    msg = re.sub(r"(?i)(api[_-]?key|authorization|x-api-key)(['\"\s:=]+)[^'\"\s,}]+", r"\1\2<redacted>", msg)
    msg = re.sub(r"(/keys/)[A-Fa-f0-9]{32,}", r"\1<redacted>", msg)
    return msg


# ── Shared helpers for sync chat-completion clients (OpenRouter, Google) ──

def truncate_to_ctx(text: str, prompt_template: str, max_ctx_tokens: int | None,
                    model_name: str, log=logger) -> str:
    """Cut text so template + text + ~2000-token reply fit in max_ctx_tokens (≈4 chars/token)."""
    if not max_ctx_tokens:
        return text
    max_text_chars = (max_ctx_tokens - 2000) * 4 - len(prompt_template)
    if len(text) > max_text_chars:
        log.warning("Truncating text from {} to {} chars for {} (ctx={})",
                    len(text), max_text_chars, model_name, max_ctx_tokens)
        return text[:max_text_chars]
    return text


def call_with_backoff(call, label: str, model_name: str,
                      retry_markers: tuple[str, ...] = ("429",),
                      max_retries: int = 5, log=logger):
    """Run call() and retry on rate limits with 10s, 20s, 40s, 80s, 160s waits.

    An exception is retried when its lower-cased text contains any of retry_markers.
    A JSONDecodeError (garbled body) is retried at once without waiting.
    Any other error is re-raised. Raises RuntimeError if every attempt fails.
    """
    for attempt in range(max_retries + 1):
        try:
            return call()
        except json.JSONDecodeError:
            log.warning("[{}] JSONDecodeError after calling {}", label, model_name)
        except Exception as e:
            error_str = str(e).lower()
            if any(m in error_str for m in retry_markers) and attempt < max_retries:
                wait = 2 ** attempt * 10
                log.warning("[{}] Rate limited for {}, waiting {}s before retry {}/{}: {}",
                            label, model_name, wait, attempt + 1, max_retries, e)
                time.sleep(wait)
            else:
                log.error("[{}] Error calling {}: {}", label, model_name, e)
                raise
    raise RuntimeError(f"No valid response from {model_name} after {max_retries + 1} attempts")


def read_usage(response) -> tuple[int, int, bool]:
    """Return (prompt_tokens, completion_tokens, usage_available) from a chat-completion response."""
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    available = usage is not None and prompt is not None and completion is not None
    return prompt or 0, completion or 0, available

def extract_from_triple_backticks(text):
    """Extract content enclosed in triple backticks from multiline text.

    Expects the text to end with lines containing triple backticks surrounding content.
    Returns the extracted content, or None if no triple backticks found.

    Also strips <think>...</think> blocks emitted by reasoning models (GLM-5.1,
    Qwen3.5 family, etc.) before attempting extraction.
    """
    import re

    # Strip thinking blocks from reasoning models before extraction
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Find all occurrences of triple backticks with content between them
    # This handles both single-line (```content```) and multi-line formats
    # Group 1 captures optional language/first-word, Group 2 captures remaining content
    pattern = r"```(\w*)\n?(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)

    if not matches:
        # Fallback: try to extract raw JSON object from the text
        json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        return json_match.group(0).strip() if json_match else None

    # Get the last match
    lang_or_content, content = matches[-1]

    # If content is empty, the first group was actually the content (not a language)
    if not content.strip() and lang_or_content:
        result = lang_or_content.strip()
    else:
        result = content.strip()

    # Strip leading comment markers (e.g., "/// " or "// " from GPT 5.2 outputs)
    if result.startswith("///"):
        result = result[3:].strip()
    elif result.startswith("//"):
        result = result[2:].strip()

    return result


def create_timestamped_folder():
    """Create a folder named with current UTC datetime and return the folder name."""
    folder_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H_%M_%S")
    os.makedirs("expts/" + folder_name, exist_ok=False)
    return folder_name

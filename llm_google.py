"""Google DeepMind Gemini API client.

Direct caller for Google DeepMind models using the Google AI Studio / Gemini API
via its OpenAI-compatible endpoint. Incorporates exponential backoff on 429 /
ResourceExhausted errors, context truncation, triple-backtick JSON parsing,
and dedicated call logging.
"""

import os
import time
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

import utils
from config_models_google import GOOGLE_MODELS
from utils import add_file_logger, get_logger

logger = get_logger(__name__)
add_file_logger("llm_google_calls.log", name_filter=__name__)

load_dotenv()

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# Google signals quota limits as 429 / RESOURCE_EXHAUSTED and overload as 503.
RETRY_MARKERS = ("429", "resourceexhausted", "resource_exhausted", "503")


def _get_api_key() -> str:
    """Retrieve Google Gemini API key from environment, checking GEMINI_API_KEY then GOOGLE_API_KEY."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY or GOOGLE_API_KEY must be set in your environment or .env file "
            "to call Google DeepMind Gemini models."
        )
    return api_key


def _get_client() -> OpenAI:
    """Create or return OpenAI client configured for Google Gemini endpoint."""
    return OpenAI(base_url=BASE_URL, api_key=_get_api_key())


def _resolve_api_model(model_name: str) -> str:
    """Map registry short names (e.g. google-gemini-4-argon) to API model identifiers."""
    if model_name in GOOGLE_MODELS:
        return GOOGLE_MODELS[model_name]["model"]
    if model_name.startswith("google-"):
        stripped = model_name[len("google-"):]
        return stripped
    return model_name


def call_llm(
    model_name: str,
    prompt_template: str,
    extracted_text: str,
    max_ctx_tokens: int | None = None,
) -> dict[str, Any]:
    """Call Google DeepMind Gemini API and return text, timing, token counts, and usage availability.

    Args:
        model_name: Registry key (e.g. google-gemini-4-argon) or API ID (e.g. gemini-4-argon).
        prompt_template: Extraction prompt instructions and format example.
        extracted_text: Raw OCR document text to process.
        max_ctx_tokens: Optional token limit for context truncation defense.

    Returns:
        dict with text, elapsed_secs, prompt_tokens, completion_tokens, usage_available.
    """
    instructions = "Follow the instructions in the prompt template.\n"
    extracted_text = utils.truncate_to_ctx(extracted_text, prompt_template, max_ctx_tokens,
                                           model_name, log=logger)
    prompt = prompt_template + extracted_text
    api_model = _resolve_api_model(model_name)
    logger.info("[Google] Calling {} (api_model={})", model_name, api_model)

    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": prompt},
    ]

    config = GOOGLE_MODELS.get(model_name, {})
    thinking_level = config.get("thinking_level")
    extra_body: dict[str, Any] = {}
    if thinking_level:
        extra_body = {
            "google": {
                "thinking_config": {
                    "thinking_level": thinking_level,
                    "include_thoughts": config.get("include_thoughts", False),
                }
            }
        }
        logger.info("[Google] thinking_level={} for {}", thinking_level, model_name)

    client = _get_client()
    t0 = time.time()
    response = utils.call_with_backoff(
        lambda: client.chat.completions.create(
            model=api_model,
            messages=messages,
            **({"extra_body": extra_body} if extra_body else {}),
        ),
        label="Google",
        model_name=api_model,
        retry_markers=RETRY_MARKERS,
        log=logger,
    )
    elapsed_secs = round(time.time() - t0, 2)
    prompt_tokens, completion_tokens, usage_available = utils.read_usage(response)

    raw_text = response.choices[0].message.content or ""
    logger.info("[Google] Response from {}, len={}", api_model, len(raw_text))

    extracted = utils.extract_from_triple_backticks(raw_text)
    logger.info("[Google] Extracted answer from {}:\n{}", api_model, extracted)

    return {
        "text": extracted,
        "elapsed_secs": elapsed_secs,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "usage_available": usage_available,
    }


if __name__ == "__main__":
    try:
        key = _get_api_key()
        logger.info("Google API key: set ({}...)", key[:4])
    except ValueError as err:
        logger.error("{}", err)
        exit(1)

    test_model = "google-gemini-4-argon"
    logger.info("Smoke testing model: {}", test_model)

    test_template = """You are an expert at extracting information from UK charity financial documents.
Extract the following fields and output them as a JSON block:
- charity_number: registered charity number (digits only)
- charity_name: full name of the charity
- report_date: reporting period end date (YYYY-MM-DD)

Output ONLY the JSON block.
```
{
    "charity_number": "1132766",
    "charity_name": "The Sanata Charitable Trust",
    "report_date": "2015-12-31"
}
```
The raw text follows:
"""

    test_text = """
    THE SANATA CHARITABLE TRUST
    Company Registration Number: 06999163
    Registered Charity Number 1132766
    Trustees' Report and Unaudited Financial Statements
    For the Sixteen Month Period Ended 31 December 2015
    """

    res = call_llm(test_model, test_template, test_text)
    logger.info("Result:\n{}", res["text"])
    logger.info("Time: {}s, Tokens: {} in / {} out", res["elapsed_secs"], res["prompt_tokens"], res["completion_tokens"])


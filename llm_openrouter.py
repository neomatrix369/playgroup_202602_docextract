import json
import logging
import os
import time

from dotenv import load_dotenv
from openai import OpenAI
import utils
from utils import get_logger

logger = get_logger(__name__)
_fh = logging.FileHandler("llm_openrouter_calls.log")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_fh)

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1", api_key=os.getenv("OPENROUTER_API_KEY")
)

def _get_providers(model_name):
    # Special cases requiring a specific provider for consistency
    # https://openrouter.ai/deepseek/deepseek-v3.2-speciale
    if model_name.startswith("deepseek/deepseek-v3.2-speciale"):
        return ["atlas-cloud"]
    # https://openrouter.ai/deepseek/deepseek-v3.1-terminus
    if model_name.startswith("deepseek/deepseek-v3.1-terminus"):
        return ["atlas-cloud"]
    if model_name.startswith("z-ai/glm-4.7"):
        return ["z-ai"]

    # Known model families — None means no provider restriction (any provider)
    known_prefixes = ("anthropic", "openai", "deepseek", "google", "meta-llama",
                      "mistralai", "qwen", "nvidia", "cohere")
    if model_name.startswith(known_prefixes):
        return None

    # IF YOU GET THIS, add a provider entry above for consistency of calls
    raise ValueError(f"No provider found for {model_name}, you need to set one in the code")

def call_llm(model_name, prompt_template, extracted_text, max_ctx_tokens=None):
    """Returns dict: {text, elapsed_secs, prompt_tokens, completion_tokens}."""
    instructions = "Follow the instructions in the prompt template.\n"
    if max_ctx_tokens:
        # Rough estimate: 1 token ≈ 4 chars. Reserve space for prompt template + response.
        max_text_chars = (max_ctx_tokens - 2000) * 4 - len(prompt_template)
        if len(extracted_text) > max_text_chars:
            logger.warning("Truncating text from %d to %d chars for %s (ctx=%d)",
                           len(extracted_text), max_text_chars, model_name, max_ctx_tokens)
            extracted_text = extracted_text[:max_text_chars]
    prompt = prompt_template + extracted_text

    logger.info("Prompt:\n%s", prompt)
    # NOTE we need 'only_providers' to be set otherwise
    # openroute will fall back on other providers with different configurations
    # and quantization levels and we'll get inconsistent results
    only_providers = _get_providers(model_name)
    extra_params = {"provider": {"allow_fallbacks": False, "only": only_providers}}
    logger.info("[OpenRouter] Calling %s", model_name)
    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": prompt},
    ]
    max_retries = 5
    t0 = time.time()
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                extra_body=extra_params,
            )
            break
        except json.JSONDecodeError:
            logger.warning("[OpenRouter] JSONDecodeError after calling %s", model_name)
        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < max_retries:
                wait = 2 ** attempt * 10  # 10s, 20s, 40s, 80s, 160s
                logger.warning("[OpenRouter] Rate limited (429) for %s, waiting %ds before retry %d/%d", model_name, wait, attempt + 1, max_retries)
                time.sleep(wait)
            else:
                raise
    elapsed_secs = round(time.time() - t0, 2)

    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0

    raw_text = response.choices[0].message.content
    logger.info("[OpenRouter] Response from %s, len=%d", model_name, len(raw_text) if raw_text else 0)
    extracted = utils.extract_from_triple_backticks(raw_text)
    logger.info("[OpenRouter] Extracted answer from %s:\n%s", model_name, extracted)
    return {
        "text": extracted,
        "elapsed_secs": elapsed_secs,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


if __name__ == "__main__":
    key = os.getenv('OPENROUTER_API_KEY', '')
    logger.info("OpenRouter API key: %s", f"set ({key[:4]}...)" if key else "NOT SET")

    #model_name = "deepseek/deepseek-v3.2-speciale"
    #model_name = "z-ai/glm-4.7"  # slow
    #model_name = "anthropic/claude-3-haiku" # failed to give the right answer to the q below
    model_name = "anthropic/claude-3.5-haiku"
    logger.info("Using model: %s", model_name)

    prompt_template = """
    You are an expert at extracting information from UK charity financial documents.
    You are given a block of text that has been extracted from a UK charity financial document.
    You need to extract the following items from the block of text:
    * Registered Charity Number

    You need to output the extracted information in a JSON block, for example:
    ```
    {
        "Registered Charity Number": "1234567890"
    }
    ```

    The raw text from the document follows, after this please output the extracted information in a JSON block:
    """

    extracted_text= """
    "THE SANATA CHARITABLE TRUST\\nCompany Registration Number:\\n06999163\\n(England and Wales)\\nRegistered Charity Number\\n1132766\\nTrustees' Report and Unaudited Financial Statements\\nFor the Sixteen Month"
    """

    result = call_llm(model_name,
             prompt_template,
             extracted_text
    )
    logger.info("Result: %s", result["text"])
    logger.info("Time: %ss, Tokens: %din/%dout", result['elapsed_secs'], result['prompt_tokens'], result['completion_tokens'])

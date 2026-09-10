import json
import os
import time

from dotenv import load_dotenv
from openai import OpenAI
import utils
from utils import get_logger, add_file_logger

logger = get_logger(__name__)
add_file_logger("llm_openrouter_calls.log", name_filter=__name__)

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
    if model_name in ("google/gemini-3.8-flash", "google/gemini-3.1-pro-preview"):
        return ["google-ai-studio"]
    if model_name in ("moonshotai/kimi-k3", "moonshotai/kimi-k2.6"):
        return ["moonshotai"]
    if model_name in ("z-ai/glm-5.3", "z-ai/glm-5.3-flash"):
        return ["z-ai"]

    # Known model families — None means no provider restriction (any provider)
    known_prefixes = ("anthropic", "openai", "deepseek", "google", "meta-llama",
                      "mistralai", "qwen", "nvidia", "cohere")
    if model_name.startswith(known_prefixes):
        return None

    # IF YOU GET THIS, add a provider entry above for consistency of calls
    raise ValueError(f"No provider found for {model_name}, you need to set one in the code")

def call_llm(model_name, prompt_template, extracted_text, max_ctx_tokens=None):
    """Returns text, timing, token counts, and explicit usage availability."""
    instructions = "Follow the instructions in the prompt template.\n"
    if max_ctx_tokens:
        # Rough estimate: 1 token ≈ 4 chars. Reserve space for prompt template + response.
        max_text_chars = (max_ctx_tokens - 2000) * 4 - len(prompt_template)
        if len(extracted_text) > max_text_chars:
            logger.warning("Truncating text from {} to {} chars for {} (ctx={})",
                           len(extracted_text), max_text_chars, model_name, max_ctx_tokens)
            extracted_text = extracted_text[:max_text_chars]
    prompt = prompt_template + extracted_text

    logger.info("Prompt:\n{}", prompt)
    # NOTE we need 'only_providers' to be set otherwise
    # openroute will fall back on other providers with different configurations
    # and quantization levels and we'll get inconsistent results
    only_providers = _get_providers(model_name)
    extra_params = {"provider": {"allow_fallbacks": False, "only": only_providers}}
    logger.info("[OpenRouter] Calling {}", model_name)
    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": prompt},
    ]
    max_retries = 5
    t0 = time.time()
    response = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                extra_body=extra_params,
            )
            break
        except json.JSONDecodeError:
            logger.warning("[OpenRouter] JSONDecodeError after calling {}", model_name)
        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < max_retries:
                wait = 2 ** attempt * 10  # 10s, 20s, 40s, 80s, 160s
                logger.warning("[OpenRouter] Rate limited (429) for {}, waiting {}s before retry {}/{}",
                               model_name, wait, attempt + 1, max_retries)
                time.sleep(wait)
            else:
                raise
    if response is None:
        raise RuntimeError(f"No valid JSON response from {model_name} after {max_retries + 1} attempts")
    elapsed_secs = round(time.time() - t0, 2)

    usage = getattr(response, "usage", None)
    prompt_token_value = getattr(usage, "prompt_tokens", None)
    completion_token_value = getattr(usage, "completion_tokens", None)
    usage_available = (usage is not None
                       and prompt_token_value is not None
                       and completion_token_value is not None)
    prompt_tokens = prompt_token_value or 0
    completion_tokens = completion_token_value or 0

    raw_text = response.choices[0].message.content or ""
    logger.info("[OpenRouter] Response from {}, len={}", model_name, len(raw_text))
    extracted = utils.extract_from_triple_backticks(raw_text)
    logger.info("[OpenRouter] Extracted answer from {}:\n{}", model_name, extracted)
    return {
        "text": extracted,
        "elapsed_secs": elapsed_secs,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "usage_available": usage_available,
    }


if __name__ == "__main__":
    key = os.getenv('OPENROUTER_API_KEY', '')
    logger.info("OpenRouter API key: {}", f"set ({key[:4]}...)" if key else "NOT SET")

    #model_name = "deepseek/deepseek-v3.2-speciale"
    #model_name = "z-ai/glm-4.7"  # slow
    #model_name = "anthropic/claude-3-haiku" # failed to give the right answer to the q below
    model_name = "anthropic/claude-3.5-haiku"
    logger.info("Using model: {}", model_name)

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
    logger.info("Result: {}", result["text"])
    logger.info("Time: {}s, Tokens: {}in/{}out", result['elapsed_secs'], result['prompt_tokens'], result['completion_tokens'])

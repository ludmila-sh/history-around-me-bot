import time

from openai import OpenAI

from src.config.config import app_settings
from src.config.logging_config import get_logger

logger = get_logger(__name__)

LLM_TIMEOUT_SECONDS = 30


def generate_answer(user_input: str, system_prompt: str | None = None) -> str:
    """Call the LLM with the system prompt and the user's message."""
    if not user_input:
        return "? what do you mean"

    system_prompt = system_prompt or app_settings.SYSTEM_PROMPT
    if not system_prompt:
        raise ValueError("Prompt was not specified.")

    model = app_settings.LANGUAGE_MODEL
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=app_settings.OPENROUTER_API_KEY,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=1,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    start = time.monotonic()
    response = client.chat.completions.create(model=model, messages=messages)
    output = response.choices[0].message.content or ""

    usage = response.usage
    tokens = (
        f"prompt={usage.prompt_tokens} completion={usage.completion_tokens}" if usage else "n/a"
    )
    logger.info(f"LLM {model}: {time.monotonic() - start:.2f}s, tokens {tokens}")
    return output

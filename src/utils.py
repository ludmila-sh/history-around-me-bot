import datetime as dt
from logging import getLogger

from openai import OpenAI

from src.config.config import app_settings

logger = getLogger(__name__)


def generate_answer(user_input: str, system_prompt: str = None) -> str:
    """
    Calls LLM using system prompt and user's text message.
    Language model and system prompt are specified in .env configuration file.
    """

    logger.info("Generating LLM response... ")

    if not user_input:
        return "? what do you mean"

    system_prompt = system_prompt if system_prompt else app_settings.SYSTEM_PROMPT
    if not system_prompt:
        raise ValueError("Prompt was not specified.")
        
    # Log the user input prompt for debugging
    logger.info(f"LLM input prompt: {user_input[:500]}{'...' if len(user_input) > 500 else ''}")

    model = app_settings.LANGUAGE_MODEL

    start_time = dt.datetime.now()

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=app_settings.OPENROUTER_API_KEY,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    response = client.chat.completions.create(model=model, messages=messages)
    output = response.choices[0].message.content

    usage = response.usage
    logger.info(
        f"NUMBER OF TOKENS used per OpenAI API request: {usage.total_tokens}. "
        f"System prompt (+ conversation history): {usage.prompt_tokens}. "
        f"Generated response: {usage.completion_tokens}."
    )

    running_secs = (dt.datetime.now() - start_time).microseconds
    logger.info(f"Answer generation took {running_secs / 100000:.2f} seconds.")
    logger.info(f"LLM's output: {output}")

    return output


def escape_markdown_v2(text):
    """Escape special characters for MarkdownV2."""
    return (
        text.replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("~", "\\~")
        .replace("`", "\\`")
        .replace(">", "\\>")
        .replace("#", "\\#")
        .replace("+", "\\+")
        .replace("-", "\\-")
        .replace("=", "\\=")
        .replace("|", "\\|")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace(".", "\\.")
        .replace("!", "\\!")
    )

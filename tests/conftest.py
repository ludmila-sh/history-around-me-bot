import os

# Dummy settings so importing the app never depends on a developer's .env
os.environ.update(
    {
        "TELEGRAM_BOT_TOKEN": "test-telegram-token",
        "OPENROUTER_API_KEY": "test-openrouter-key",
        "LLM_MODEL_DEV": "test/dev-model",
        "LLM_MODEL_PROD": "test/prod-model",
        "DEBUG": "True",
    }
)

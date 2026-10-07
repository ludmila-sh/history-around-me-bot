import os

# Dummy settings so importing the app never depends on a developer's .env
os.environ.update(
    {
        "TELEGRAM_BOT_TOKEN": "test-telegram-token",
        "OPENROUTER_API_KEY": "test-openrouter-key",
        "LANGUAGE_MODEL_DEV": "test/dev-model",
        "LANGUAGE_MODEL_PROD": "test/prod-model",
        "DEBUG": "True",
    }
)

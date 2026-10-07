from src.config.config import AppSettings

BASE = {
    "TELEGRAM_BOT_TOKEN": "t",
    "OPENROUTER_API_KEY": "k",
    "LANGUAGE_MODEL_DEV": "cheap/dev-model",
    "LANGUAGE_MODEL_PROD": "good/prod-model",
}


def test_debug_uses_cheap_dev_model():
    settings = AppSettings(_env_file=None, DEBUG=True, **BASE)
    assert settings.LANGUAGE_MODEL == "cheap/dev-model"


def test_prod_uses_prod_model():
    settings = AppSettings(_env_file=None, DEBUG=False, **BASE)
    assert settings.LANGUAGE_MODEL == "good/prod-model"

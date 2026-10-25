import pytest
from pydantic import ValidationError

from src.config.config import AppSettings

BASE = {
    "TELEGRAM_BOT_TOKEN": "t",
    "OPENROUTER_API_KEY": "k",
    "LANGUAGE_MODEL_DEV": "cheap/dev-model",
    "LANGUAGE_MODEL_PROD": "good/prod-model",
    "OPENTRIPMAP_API_KEY": "otm-key",
    "GOOGLE_PLACES_API_KEY": "google-key",
}


def test_debug_uses_cheap_dev_model():
    settings = AppSettings(_env_file=None, DEBUG=True, **BASE)
    assert settings.LANGUAGE_MODEL == "cheap/dev-model"


def test_prod_uses_prod_model():
    settings = AppSettings(_env_file=None, DEBUG=False, **BASE)
    assert settings.LANGUAGE_MODEL == "good/prod-model"


@pytest.mark.parametrize("missing", ["OPENTRIPMAP_API_KEY", "GOOGLE_PLACES_API_KEY"])
def test_missing_place_data_key_fails_at_startup_without_leaking_other_keys(missing, monkeypatch):
    monkeypatch.delenv(missing)  # conftest provides dummies via the environment
    values = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ValidationError) as error:
        AppSettings(_env_file=None, **values)
    assert missing in str(error.value)
    assert "otm-key" not in str(error.value) and "google-key" not in str(error.value)

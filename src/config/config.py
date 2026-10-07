from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config.logging_config import get_logger

logger = get_logger(__name__)

PROMPTS_FILE = Path(__file__).resolve().parents[2] / "data" / "prompts.yaml"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,  # never print secrets from .env in validation errors
    )

    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    TELEGRAM_BOT_TOKEN: str
    ADMIN_USER_IDS: list[int] = []

    OPENROUTER_API_KEY: str
    LLM_MODEL_DEV: str
    LLM_MODEL_PROD: str

    SYSTEM_PROMPT: str = ""

    # Optional API keys for enhanced POI search
    FOURSQUARE_API_KEY: str | None = None
    LOCATIONIQ_API_KEY: str | None = None

    @property
    def LANGUAGE_MODEL(self) -> str:
        return self.LLM_MODEL_DEV if self.DEBUG else self.LLM_MODEL_PROD

    def load_prompts_from_yaml(self) -> None:
        with PROMPTS_FILE.open(encoding="utf-8") as file:
            prompts = yaml.safe_load(file)
        self.SYSTEM_PROMPT = prompts.get("system_prompt", "")


app_settings = AppSettings()
app_settings.load_prompts_from_yaml()
logger.info(f"CONFIG: DEBUG={app_settings.DEBUG}, LANGUAGE_MODEL={app_settings.LANGUAGE_MODEL}")

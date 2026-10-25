# History Around Me

A Telegram bot that shows notable places within a short walk of your location (history, culture, parks, viewpoints) and the best-rated food and coffee nearby, in Russian or English.

## Quick start

1. Create a virtual environment and install: `py -3.12 -m venv venv`, then `venv\Scripts\activate` and `pip install -r requirements-dev.txt` (or run `py-install-requirements.cmd`).
2. Copy `.env.example` to `.env` and fill in the values. Use a separate dev bot token locally: two pollers on one token conflict.
3. Run: `python -m src.run_bot` (or `py-run-bot.cmd`).

## Configuration

Environment variables (see `.env.example`):

| Variable | Purpose | Required |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | yes |
| `OPENROUTER_API_KEY` | LLM access (free-text chat) | yes |
| `LANGUAGE_MODEL_DEV` | Model used when `DEBUG=True` | yes |
| `LANGUAGE_MODEL_PROD` | Model used when `DEBUG=False` | yes |
| `OPENTRIPMAP_API_KEY` | OpenTripMap via RapidAPI: sights and their notability rating | yes |
| `GOOGLE_PLACES_API_KEY` | Google Places API (New): food and coffee; restrict the key to that API and set a daily quota | yes |
| `ADMIN_USER_IDS` | JSON list of Telegram user ids allowed to use `/health` | no (`[]`) |
| `DEBUG` | `True` for development (cheap model, rounded coordinates in logs) | no (`False`) |
| `LOG_LEVEL` | Logging level | no (`INFO`) |

## Usage

Send `/start`, tap "Send Location", then pick a category:

```
📍 Istanbul, Türkiye

🎯 What are you looking for?

🏛️ History & Culture (10)
🌳 Parks & Nature (1)
☕ Food & Coffee
```

Each list is paged (8 per page, most notable first). A place card shows the Wikipedia extract and buttons "On the map" (Google Maps) and "Wikipedia". "Food & Coffee" shows the 5 best places with rating, review count, price and distance. The search starts at 500 m and widens to 1.5 km if fewer than 3 notable places are found.

## Project structure

- `src/run_bot.py`: entry point and thin Telegram handlers.
- `src/bot_ui.py`: message texts and keyboards (pure functions).
- `src/places_api.py`: network calls (OpenTripMap, Overpass fallback, Wikipedia, Google Places), search orchestration.
- `src/places_parse.py`: parsing, categories, ranking, merging (no I/O).
- `src/utils.py`: LLM calls for the free-text chat.
- `src/config/`: settings (`app_settings`) and logging.
- `data/prompts.yaml`: LLM prompts.
- `tests/`: pytest tests; `tests/fixtures/` holds recorded API responses, so tests need no network.

## Development

- Checks: `ruff check . && ruff format --check . && pytest`
- Hooks: `pre-commit install` (ruff, gitleaks)

## Deployment

Deployed on Koyeb and auto-deployed from `main`. Set the variables from the table above in the Koyeb service settings (`DEBUG=False`); the bot refuses to start if a required key is missing. Start command: `python -m src.run_bot`.

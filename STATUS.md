# Status

Updated: 2026-10-08

## Works end-to-end

- Checks pass: `ruff check .`, `ruff format --check .`, `pytest` (5 tests), pre-commit hooks (ruff, gitleaks).
- Not yet verified live in Telegram after session 1 (HTML messages, `/start`, location flow).

## Not done / stubs

- Place sources still include Foursquare, Nominatim POI and LocationIQ; Wikipedia requests lack a User-Agent (403).
- Sync HTTP and LLM calls block the event loop; prompts allow speculation.
- Distance buttons and keyword-based categories are still the old ones.

## Next

- Session 2: remove extra sources and dead helpers in `places_api.py`, `API_SETUP_GUIDE.md`.

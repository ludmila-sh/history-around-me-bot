@PERSONAL.md

# Project

History Around Me is a lightweight personal travel companion that uses the user’s location to provide concise, useful facts about nearby landmarks, places, and hidden gems.

It is designed primarily for my own trips, not as a commercial product yet: prioritize reliability, low maintenance, privacy, and a pleasant travel experience over feature completeness.

## Stack

Python 3.12, python-telegram-bot (async), pydantic-settings, LLM via OpenRouter (OpenAI SDK). Dependencies in `requirements*.txt` with pinned versions, tool settings in `pyproject.toml` (ruff).

This is an existing project: its current structure and conventions win over the generic scaffold. Do not migrate `src/` to `app/` or introduce scaffold tools (mypy) unless I ask.

## Structure

- `src/` — code: `run_bot.py` (entry point, Telegram handlers), `places_api.py` (place search), `utils.py` (LLM calls, formatting), `config/` (`config.py`, `logging_config.py`).
- `data/prompts.yaml` — LLM prompts.
- `tests/` — pytest tests.
- `logs/` — runtime artifacts, not committed.
- `credentials/` — local access files, not committed, the agent does not read them.
- `ROADMAP.md` — goal and milestones. `STATUS.md` — current state, overwritten.

## Commands

- Check everything: `ruff check . && ruff format --check . && pytest`
- Run the bot locally: `python -m src.run_bot` (or `py-run-bot.cmd`)
- Hooks: `pre-commit install` (ruff, gitleaks)

## Environments

- Local: `.env` holds the token of a separate dev Telegram bot. Never run locally with the prod token: two pollers on one token conflict.
- Prod: deployed on Koyeb, configured through Koyeb environment variables.
- `DEBUG=True` (dev) and `DEBUG=False` (prod) select different LLM models: a cheap one for testing, a better one for real use.

## Conventions

- Settings only through `src/config/config.py` (`app_settings`); no `os.environ` anywhere else.
- Logs via `get_logger(__name__)` from `src/config/logging_config.py`, no `print`. Do not log user coordinates or message text.
- Interface is the Telegram bot. Handlers stay thin; business logic lives in separate modules, not in handlers.

## Database (if the project has one)

- Design the DB schema before the code and show it to me before the first migration.
- Field and variable names are unambiguous and distinguishable. Do not use one name for different entities or two similar names for different ones.
- Any schema change only through a migration. No manual edits.
- Do not delete or rename fields and data without my confirmation; before that, say what will be affected.
- Define types and constraints (NOT NULL, unique, foreign key, check) in the schema, do not rely on code.
- In tests that write records, use different values for different fields so that swapped fields do not pass.
- Database queries only parameterized.

## README

I do not write READMEs by hand: you maintain it following the structure already laid out in `README.md`. If `README.md`, `STATUS.md` or `ROADMAP.md` still contain template placeholders, fill them from the actual project; never describe tools or commands the project does not have. Rules:
- Write in English, briefly: a README is read to start the project quickly and understand what it does.
- Sections: one-sentence description, Quick start (install, `.env` setup, run), Configuration (table of variables without values), Usage (example input and output), Project structure, Development (checks, hooks), Deployment. Delete an empty section, do not add extra ones.
- Update the README when the way to run, the environment variables or the structure change. Do not duplicate what is in `ROADMAP.md` and `STATUS.md`.

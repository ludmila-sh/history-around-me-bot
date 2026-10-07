@PERSONAL.md

# Project

History Around Me is a lightweight personal travel companion that uses the user’s location to provide concise, useful facts about nearby landmarks, places, and hidden gems.

It is designed primarily for my own trips, not as a commercial product yet: prioritize reliability, low maintenance, privacy, and a pleasant travel experience over feature completeness.

## Stack

Python 3.12, pydantic-settings; FastAPI if it is a service. Dependencies in `requirements*.txt`, tool settings in `pyproject.toml`.

## Structure

- `app/` — code: `config.py`, `logging_config.py`, `main.py`, `services/`. For a service add `api/` (thin handlers) and `domain/` (models and business logic).
- `tests/` — pytest tests.
- `docs/` — prompts and notes for humans.
- `logs/`, `output/` — runtime artifacts, not committed.
- `credentials/` — local access files, not committed, the agent does not read them.
- `ROADMAP.md` — goal and milestones. `STATUS.md` — current state, overwritten.

## Commands

- Check everything: `ruff check . && ruff format --check . && mypy app && pytest`
- Run a script: `python -m app.main`. Run a service: `uvicorn app.main:app --reload`
- Hooks: `pre-commit install`

## Conventions

- Settings only through `app/config.py` (`settings`); no `os.environ` anywhere else.
- Logs via `get_logger(__name__)`, no `print`.
- Business logic in `services/` (or `domain/`), not in handlers.
- Interface to a service: for a prototype or demo, Streamlit (but it needs a server); for a tool delivered to a client, FastAPI + Jinja + htmx. A separate React app only if it cannot be avoided.

## Database (if the project has one)

- Design the DB schema before the code and show it to me before the first migration.
- Field and variable names are unambiguous and distinguishable. Do not use one name for different entities or two similar names for different ones.
- Any schema change only through a migration. No manual edits.
- Do not delete or rename fields and data without my confirmation; before that, say what will be affected.
- Define types and constraints (NOT NULL, unique, foreign key, check) in the schema, do not rely on code.
- In tests that write records, use different values for different fields so that swapped fields do not pass.
- Database queries only parameterized.

## README

I do not write READMEs by hand: you maintain it following the structure already laid out in `README.md`. Rules:
- Write in English, briefly: a README is read to start the project quickly and understand what it does.
- Sections: one-sentence description, Quick start (install, `.env` setup, run), Configuration (table of variables without values), Usage (example input and output), Project structure, Development (checks, hooks), Deployment. Delete an empty section, do not add extra ones.
- Update the README when the way to run, the environment variables or the structure change. Do not duplicate what is in `ROADMAP.md` and `STATUS.md`.

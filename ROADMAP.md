# Roadmap

## Context

Personal Telegram travel bot. First real use: trip to Turkey, 2026-10-24 – 11-09 (Alanya, Antalya, Fethiye, Istanbul). Prod runs on Koyeb (auto-deploy from `main`); local dev uses a separate dev bot.

## Goal (next MVP)

Send location → what is interesting within a ~5-minute walk → a short, vivid guide-style card per place (no invented facts) → open the place in Google Maps. Short free-text chat with a "More" button. English and Russian. Ready by 2026-10-20.

## Milestones

### Milestone 1 — Clean base
Python 3.12, pinned deps, ruff + pre-commit, HTML messages, dev/prod LLM models, dead code removed.

### Milestone 2 — Useful results
Overpass + Wikipedia only, tag-based categories, 500 m → 1.5 km radius, non-blocking calls, category buttons after location (no DB).

### Milestone 3 — Guide experience and prod
Guide-style cards with "More", Google Maps button, short chat answers, prod model chosen, logs without coordinates, deployed and walk-tested.

## Open decisions

- User allowlist with Telegram approval flow (needs Postgres) — postponed; bot is open, spending capped by the OpenRouter balance.
- Stored category preferences — postponed (would need a DB).

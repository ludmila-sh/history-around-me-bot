# Roadmap

## Context

Personal Telegram travel bot. First real use: trip to Turkey, 2026-10-24 – 11-09 (Alanya, Antalya, Fethiye, Istanbul), but it must work anywhere. Prod runs on Koyeb (auto-deploy from `main`); local dev uses a separate dev bot.

## Goal (next MVP)

Send location → what is worth seeing within a ~5-minute walk → a card per place that says how important it is, without invented facts → open it in Google Maps. English and Russian.

## Milestones

### Milestone 1: Clean base (done)
Python 3.12, pinned deps, ruff + pre-commit, HTML messages, dev/prod LLM models, dead code removed.

### Milestone 2: Useful results (done)
Sights from OpenTripMap (Overpass fallback) with Wikipedia text, food from Google Places on demand, 500 m → 1.5 km radius, paged lists, non-blocking calls, no DB.

### Milestone 3: Guide experience and prod
Cards that say what matters about a place (significance in code, text written by an LLM from supplied facts only), deploy to Koyeb, walk-test.

### MVP 2 ideas
- Live location: a short message when a notable place comes near, no routes stored.
- "Places to work on a laptop": comfortable cafes with good wifi.
- Short free-text chat that knows the city and nearby places.

## Open decisions

- User allowlist with Telegram approval flow (needs Postgres): postponed; the bot is open, spending is capped by the OpenRouter balance and the Google daily quota.
- Stored category preferences: postponed (would need a DB).

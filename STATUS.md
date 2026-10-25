# Status

Updated: 2026-10-25

## Works end-to-end

- `/start` → location → category overview → paged list → place card (Wikipedia extract, "On the map", "Wikipedia") → "Food & Coffee" (Google, on demand). Tried by hand in the dev bot.
- Real-service runs on 6 Istanbul/Ankara points: sights in 2.7–8.8 s (limit 15 s); a residential area honestly returns almost nothing.
- Checks pass: ruff, pytest (118 tests, no network), pre-commit.

## Not done / known gaps

- Cards are bare Wikipedia extracts: stubs for minor places, English text for Russian users, and no sign of how important a place is.
- Not deployed: Koyeb needs `OPENTRIPMAP_API_KEY` and `GOOGLE_PLACES_API_KEY`, and the branch is not merged to `main`.
- Free-text chat ignores location and nearby places, answers are long, and its LLM call blocks the event loop.
- Live-location updates are ignored. Wikipedia read timeout (7 s) can dominate latency.

## Next

- Place significance (code) plus an LLM that writes and translates only from supplied facts.
- Deploy, then walk-test.

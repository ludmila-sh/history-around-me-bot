# Status

Updated: 2026-10-07

## Works end-to-end

- Location → nearby places by category → AI description of a place (one logged run, 2025-10-15).

## Not done / stubs

- `/start` and free-text replies send unescaped MarkdownV2 (likely Telegram parse errors).
- Legacy callbacks `back_details`, `more_places`, `back_overview` crash (undefined `places`).
- Wikipedia requests get 403 (no User-Agent); Nominatim POI search breaks its rate-limit policy.
- No user allowlist, no map action, blocking sync HTTP/LLM calls, about half of the code is dead.

## Next

- Agree the completion plan (6 sessions), then session 1: Python 3.12 venv, pinned deps, HTML parse mode, working `/start`.

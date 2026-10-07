# Status

Updated: 2026-10-08

## Works end-to-end

- `/start`, location → categories → place card, all buttons (checked by hand in the dev bot after session 1).
- Checks pass: ruff, pytest (7 tests), pre-commit (ruff, gitleaks).
- Sources reduced to Overpass + Wikipedia; one reverse geocoder (Nominatim). Error logs carry no URLs or coordinates; coordinates are logged only with `DEBUG=True`, rounded to ~100 m.

## Not done / stubs

- Overpass returns 406 and Wikipedia 403 (missing User-Agent), so the place list is mostly empty right now.
- Free-text chat ignores the user's location and nearby places; replies are long.
- Cafes can get landmark-style cards (keyword-based categories); prompts allow speculation.
- Sync HTTP and LLM calls block the event loop.

## Next

- Session 3: fix Overpass/Wikipedia requests, tag-based categories, 500 m → 1.5 km radius, non-blocking calls.

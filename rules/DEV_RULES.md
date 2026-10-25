# Engineering rules

General engineering rules for any project. Python specifics (linter, tests, structure) live in `scaffolds/python`.

## Secrets (more important than everything else)

- Do not read, print, log, commit or send anywhere secrets: keys, tokens, passwords, `.env`, `secrets/`, private data. If a file may contain them, do not open it without my permission.
- Configuration only through environment variables. The repository holds only `.env.example` with empty values; `.env` is in `.gitignore` from the first commit.
- Do not put secrets into code, tests, fixtures and examples, even temporary ones.
- If a secret ends up in the chat, a log or a commit, say so immediately and remind me that it must be revoked and reissued.

## Architecture

- Before a new module or service, propose the architecture and data schema, even if I ask for "faster". A short one is enough: components, boundaries, data flow, what we deliberately do not do.
- Choose the minimal sufficient architecture for the task. Do not build a "forest" for the future.
- Business logic is separate from transport (HTTP, bot, CLI) and from data access. Routes and handlers are thin.
- External services and APIs sit behind a thin wrapper so they can be replaced and mocked in tests.

## Reliability

- Every loop has an explicit exit condition and an upper bound on iterations or time. Every external call has a timeout. Retries are limited and use backoff.
- Close resources (files, connections, sessions) with context managers or their equivalent. Do not accumulate unbounded collections in memory; process large data as a stream or in chunks.
- Do not swallow errors: handle them meaningfully or re-raise with context. No empty `except` and no silent fallbacks.
- Log events and errors with context, without secrets and personal data.

## Security

- Validate input at the system boundary; do not trust external data.
- Do not log personal and medical data and do not send it to third-party services without anonymization.

## Tests and verification

- For new behavior keep a small set of unit tests and update it as you go. Add one end-to-end test for the key path.
- Anything a machine can check (formatter, linter, types, tests) runs with one command and is fixed in config. Do not rely on the agent "remembering" the style.

## Git

- Small commits: one change, one commit. Message in English, imperative mood, saying what and why.
- Propose a commit after each finished step; commit only when I say so.
- Do not rewrite history and do not force-push without an explicit request.

## Dependencies

- Minimum of libraries. Before adding a new one, name it to me and check: is it maintained, compatible with the project's versions, free of known security issues.
- Pin dependency versions.

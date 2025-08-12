# Contributing

Thanks for your interest in contributing! This repo manages real Ethereum validator nodes; we value stability and clarity.

- Use feature branches and open PRs against `main`.
- Keep changes focused and small; include minimal tests when possible.
- Avoid committing secrets. Use `*.example` templates for configs.
- Prefer Python 3.11+ and follow existing code style.

## Development
- Create a virtualenv and install requirements.
- Run `python -m py_compile eth_validators/*.py` before committing.
- Add or update docs when you add new CLI commands or options.

## Release process
- We cut releases via tags (`vX.Y.Z`).
- GitHub Actions builds the unified zip and attaches to the GitHub Release.
- Keep CHANGELOG updated with concise notes.

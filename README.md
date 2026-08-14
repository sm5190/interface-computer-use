# Interface Computer Use

Interface.ai SWE take-home implementation.

## Current milestone

LegacyBank Operations Console: a local, synthetic, deliberately legacy-style browser target used to exercise computer-use discovery and deterministic replay.

## Run the proxy target

```bash
uv sync
uv run python -m demo_app.app
```

Open http://127.0.0.1:8000.

## Test

```bash
uv run pytest
```

# Interface Computer Use

Interface.ai SWE take-home implementation of a computer-use capability automation system.

The system is designed around one central separation:

> Discovery is probabilistic. Capabilities are declarative. Replay is deterministic. Policy is authoritative. Humans retain control.

## Current milestone

The repository currently includes **LegacyBank**, a local, synthetic, intentionally legacy-style banking operations console used as the live UI target for the computer-use system.

The computer-use runtime will add:

1. LLM-driven workflow discovery.
2. Typed/versioned capability artifacts.
3. Deterministic replay with no LLM decisions.
4. Explicit safety and policy enforcement.
5. Structured runtime outcomes and failures.
6. Same-session human approval and takeover.
7. Structured logs, screenshots, and Playwright traces.

## Requirements

- Python 3.12
- uv

## Development setup

Install the Python environment:

```bash
uv sync
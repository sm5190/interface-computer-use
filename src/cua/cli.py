from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from cua.discovery import (
    DiscoveryEngine,
    GeminiDiscoveryModel,
    new_discovery_run_id,
)
from cua.domain import GoalRequest
from cua.evidence import (
    DiscoveryEvidenceRecorder,
)
from cua.grounding import (
    CheckpointEvaluator,
    PlaywrightGroundingBackend,
    TargetResolver,
)
from cua.safety import (
    ActionGate,
    GoalGateway,
    load_policy,
)
from cua.surfaces import PlaywrightSurface


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cua",
        description=(
            "Computer-use capability automation"
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    discover = subparsers.add_parser(
        "discover",
        help="Run LLM-driven workflow discovery",
    )

    discover.add_argument(
        "--target",
        required=True,
        choices=["legacy-bank"],
    )

    discover.add_argument(
        "--goal",
        required=True,
    )

    discover.add_argument(
        "--base-url",
        default=None,
    )

    discover.add_argument(
        "--model",
        default=None,
    )

    discover.add_argument(
        "--max-steps",
        type=int,
        default=15,
    )

    discover.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
    )

    discover.add_argument(
        "--headless",
        action="store_true",
    )

    discover.add_argument(
        "--slow-mo",
        type=int,
        default=150,
    )

    return parser


def main() -> None:
    load_dotenv()

    parser = build_parser()

    args = parser.parse_args()

    if args.command == "discover":
        exit_code = run_discover(args)

        raise SystemExit(exit_code)


def run_discover(
    args: argparse.Namespace,
) -> int:
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print(
            "GEMINI_API_KEY is not configured in .env"
        )

        return 2

    base_url = (
        args.base_url
        or os.getenv(
            "LEGACYBANK_BASE_URL",
            "http://127.0.0.1:8000",
        )
    ).rstrip("/")

    model_name = (
        args.model
        or os.getenv(
            "DISCOVERY_MODEL",
            "gemini-3.6-flash",
        )
    )

    run_id = new_discovery_run_id()

    run_dir = (
        Path("evidence")
        / "dev"
        / run_id
    )

    member_ids = re.findall(
        r"\b\d{6}\b",
        args.goal,
    )

    sensitive_values = [
        "OP100",
        "2468",
        *member_ids,
    ]

    surface = PlaywrightSurface(
        headless=args.headless,
        evidence_dir=run_dir,
        slow_mo_ms=args.slow_mo,
    )

    policy = load_policy(
        "policies/legacy_bank.yaml"
    )

    recorder = DiscoveryEvidenceRecorder(
        run_id=run_id,
        run_dir=run_dir,
        sensitive_values=sensitive_values,
    )

    model = GeminiDiscoveryModel(
        model=model_name,
        api_key=api_key,
    )

    resolver = TargetResolver(
        PlaywrightGroundingBackend(surface)
    )

    engine = DiscoveryEngine(
        surface=surface,
        model=model,
        resolver=resolver,
        action_gate=ActionGate(policy),
        goal_gateway=GoalGateway(policy),
        checkpoint_evaluator=(
            CheckpointEvaluator(
                surface=surface,
                resolver=resolver,
            )
        ),
        evidence=recorder,
        base_url=base_url,
        target_notes=[
            (
                "This is the synthetic LegacyBank "
                "training environment."
            ),
            (
                "If OPERATOR SIGN ON is visible, "
                "use training Operator ID OP100 "
                "and PIN 2468."
            ),
            (
                "These credentials are synthetic "
                "and only valid for this local demo."
            ),
            (
                "The requested member data is "
                "synthetic."
            ),
        ],
    )

    request = GoalRequest(
        goal=args.goal,
        target_profile=args.target,
        entry_point="/members",
        max_steps=args.max_steps,
        timeout_seconds=args.timeout_seconds,
    )

    surface.start()

    try:
        run = engine.run(request)

    finally:
        surface.close()

    print()
    print("Discovery result:")
    print(
        run.result.model_dump_json(
            indent=2
        )
    )

    print()
    print(
        f"LLM decision calls: {run.llm_calls}"
    )

    print(
        f"Evidence: {run.evidence_dir}"
    )

    if run.result.status == "SUCCESS":
        return 0

    return 1


if __name__ == "__main__":
    main()
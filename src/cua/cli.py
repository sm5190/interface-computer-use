from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError

from cua.compiler import (
    CapabilityCompilationError,
    CapabilityRecipe,
    GenericCapabilityCompiler,
    TrajectoryEnrichment,
    TrajectoryEnrichmentError,
    apply_trajectory_enrichment,
)
from cua.discovery import (
    DiscoveryEngine,
    GeminiDiscoveryModel,
    new_discovery_run_id,
)
from cua.domain import GoalRequest, StepRecord
from cua.evidence import (
    DiscoveryEvidenceRecorder,
)
from cua.grounding import (
    CheckpointEvaluator,
    PlaywrightGroundingBackend,
    TargetResolver,
)
from cua.replay import (
    CapabilityLoadError,
    InputBindingError,
    ReplayEngine,
    bind_capability_inputs,
    load_capability,
    new_replay_run_id,
)
from cua.safety import (
    ActionGate,
    GoalGateway,
    load_policy,
)
from cua.surfaces import PlaywrightSurface


def _parse_cli_inputs(
    values: list[str],
) -> dict[str, str]:
    result: dict[str, str] = {}

    for item in values:
        if "=" not in item:
            raise ValueError(
                f"Invalid --input value: {item!r}. "
                "Expected KEY=VALUE."
            )

        key, value = item.split(
            "=",
            1,
        )

        key = key.strip()

        if not key:
            raise ValueError(
                "Input key cannot be empty"
            )

        if key in result:
            raise ValueError(
                f"Duplicate input: {key}"
            )

        result[key] = value

    return result


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

    compile_command = subparsers.add_parser(
        "compile",
        help=(
            "Compile a successful discovery trajectory "
            "into a deterministic capability artifact"
        ),
    )

    compile_command.add_argument(
        "--trajectory",
        required=True,
        help="Path to discovery trajectory JSON",
    )

    compile_command.add_argument(
        "--recipe",
        required=True,
        help="Path to capability recipe JSON",
    )

    compile_command.add_argument(
        "--output",
        default=None,
        help=(
            "Output capability path. Defaults to "
            "artifacts/generated/<capability-id>.v<major>.json"
        ),
    )

    compile_command.add_argument(
        "--enrichment",
        default=None,
        help=(
            "Optional trajectory-enrichment JSON for "
            "older discovery evidence"
        ),
    )

    replay = subparsers.add_parser(
        "replay",
        help=(
            "Replay a saved capability "
            "deterministically"
        ),
    )

    replay.add_argument(
        "capability",
        help="Capability artifact JSON path",
    )

    replay.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Capability invocation input. "
            "May be supplied multiple times."
        ),
    )

    replay.add_argument(
        "--policy",
        required=True,
        help="Application policy YAML",
    )

    replay.add_argument(
        "--base-url",
        default=None,
    )

    replay.add_argument(
        "--bootstrap",
        choices=[
            "none",
            "legacy-bank-demo",
        ],
        default="none",
    )

    replay.add_argument(
        "--headless",
        action="store_true",
    )

    replay.add_argument(
        "--slow-mo",
        type=int,
        default=100,
    )

    return parser


def main() -> None:
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "discover":
        exit_code = run_discover(args)

    elif args.command == "compile":
        exit_code = run_compile(args)

    elif args.command == "replay":
        exit_code = run_replay(args)

    else:
        parser.error(
            f"Unsupported command: {args.command}"
        )
        exit_code = 1

    raise SystemExit(exit_code)


def run_replay(
    args: argparse.Namespace,
) -> int:
    try:
        invocation_inputs = (
            _parse_cli_inputs(
                args.input
            )
        )

        artifact = load_capability(
            args.capability
        )

        bound = bind_capability_inputs(
            artifact,
            invocation_inputs,
        )

    except (
        ValueError,
        CapabilityLoadError,
        InputBindingError,
    ) as exc:
        print()
        print("Replay admission failed:")
        print(exc)
        return 1

    policy = load_policy(
        args.policy
    )

    base_url = (
        args.base_url
        or policy.allowed_origins[0]
    ).rstrip("/")

    run_id = new_replay_run_id()

    run_dir = (
        Path("evidence")
        / "dev"
        / run_id
    )

    surface = PlaywrightSurface(
        headless=args.headless,
        evidence_dir=run_dir,
        slow_mo_ms=args.slow_mo,
    )

    resolver = TargetResolver(
        PlaywrightGroundingBackend(
            surface
        )
    )

    checkpoint_evaluator = (
        CheckpointEvaluator(
            surface=surface,
            resolver=resolver,
        )
    )

    if args.bootstrap == "legacy-bank-demo":
        from demo_app.replay_bootstrap import (
            LegacyBankDemoBootstrap,
        )

        bootstrap = (
            LegacyBankDemoBootstrap()
        )
    else:
        bootstrap = None

    engine = ReplayEngine(
        run_id=run_id,
        surface=surface,
        resolver=resolver,
        checkpoint_evaluator=(
            checkpoint_evaluator
        ),
        action_gate=ActionGate(
            policy
        ),
        evidence_dir=run_dir,
        bootstrap=bootstrap,
    )

    result = engine.run(
        bound,
        base_url=base_url,
    )

    print()
    print("Replay result:")
    print(
        result.model_dump_json(
            indent=2
        )
    )

    print()
    print("LLM decision calls: 0")
    print(
        f"Evidence: {run_dir}"
    )

    return (
        0
        if result.status
        in {
            "SUCCESS",
            "BUSINESS_OUTCOME",
        }
        else 1
    )


def run_compile(
    args: argparse.Namespace,
) -> int:
    trajectory_path = Path(args.trajectory)
    recipe_path = Path(args.recipe)

    if not trajectory_path.is_file():
        print(
            f"Trajectory file not found: "
            f"{trajectory_path}"
        )
        return 2

    if not recipe_path.is_file():
        print(
            f"Recipe file not found: "
            f"{recipe_path}"
        )
        return 2

    # ---------------------------------------------------------
    # 1. Load trajectory + recipe JSON
    # ---------------------------------------------------------

    try:
        trajectory_payload = json.loads(
            trajectory_path.read_text(
                encoding="utf-8"
            )
        )

        recipe_payload = json.loads(
            recipe_path.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as exc:
        print()
        print("Invalid JSON input:")
        print(exc)
        return 2

    # ---------------------------------------------------------
    # 2. Extract raw trajectory steps
    # ---------------------------------------------------------

    if isinstance(trajectory_payload, dict):
        raw_steps = trajectory_payload.get(
            "steps"
        )

        if raw_steps is None:
            print(
                "Trajectory object does not "
                "contain a 'steps' field"
            )
            return 2

    elif isinstance(trajectory_payload, list):
        raw_steps = trajectory_payload

    else:
        print(
            "Trajectory JSON must be either "
            "an object containing 'steps' "
            "or a list of steps"
        )
        return 2

    # ---------------------------------------------------------
    # 3. FIRST create the typed trajectory
    # ---------------------------------------------------------

    try:
        trajectory = TypeAdapter(
            list[StepRecord]
        ).validate_python(raw_steps)

    except ValidationError as exc:
        print()
        print(
            "Trajectory validation failed:"
        )
        print(exc)
        return 1

    # trajectory DEFINITELY exists from this point onward.

    # ---------------------------------------------------------
    # 4. Optionally enrich legacy discovery evidence
    # ---------------------------------------------------------

    if args.enrichment is not None:
        enrichment_path = Path(
            args.enrichment
        )

        if not enrichment_path.is_file():
            print(
                "Enrichment file not found: "
                f"{enrichment_path}"
            )
            return 2

        try:
            enrichment_payload = json.loads(
                enrichment_path.read_text(
                    encoding="utf-8"
                )
            )

            enrichment = (
                TrajectoryEnrichment
                .model_validate(
                    enrichment_payload
                )
            )

            trajectory = (
                apply_trajectory_enrichment(
                    trajectory,
                    enrichment,
                )
            )

        except json.JSONDecodeError as exc:
            print()
            print(
                "Invalid enrichment JSON:"
            )
            print(exc)
            return 2

        except (
            ValidationError,
            TrajectoryEnrichmentError,
        ) as exc:
            print()
            print(
                "Trajectory enrichment failed:"
            )
            print(exc)
            return 1

    # ---------------------------------------------------------
    # 5. Validate recipe + compile capability
    # ---------------------------------------------------------

    try:
        recipe = (
            CapabilityRecipe.model_validate(
                recipe_payload
            )
        )

        artifact = (
            GenericCapabilityCompiler()
            .compile(
                trajectory=trajectory,
                recipe=recipe,
            )
        )

    except (
        ValidationError,
        CapabilityCompilationError,
    ) as exc:
        print()
        print(
            "Capability compilation failed:"
        )
        print(exc)
        return 1

    # ---------------------------------------------------------
    # 6. Resolve output path
    # ---------------------------------------------------------

    if args.output is not None:
        output_path = Path(
            args.output
        )

    else:
        major_version = (
            artifact.capability.version.split(
                "."
            )[0]
        )

        output_path = (
            Path("artifacts")
            / "generated"
            / (
                f"{artifact.capability.id}"
                f".v{major_version}.json"
            )
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------
    # 7. Serialize + verify + persist artifact
    # ---------------------------------------------------------

    # Serialize the exact CapabilityArtifact returned by the
    # compiler. Do not reconstruct a second artifact here.
    serialized = artifact.model_dump_json(
        indent=2
    )

    # Verify that serialization preserves hard-failure rules.
    try:
        serialized_payload = json.loads(
            serialized
        )
    except json.JSONDecodeError as exc:
        print()
        print(
            "Capability serialization failed:"
        )
        print(exc)
        return 1

    expected_hard_failures = [
        rule.model_dump(
            mode="json"
        )
        for rule in artifact.hard_failures
    ]

    serialized_hard_failures = (
        serialized_payload.get(
            "hard_failures",
            [],
        )
    )

    if (
        serialized_hard_failures
        != expected_hard_failures
    ):
        print()
        print(
            "Capability serialization "
            "consistency check failed:"
        )
        print(
            "In-memory hard_failures:"
        )
        print(
            json.dumps(
                expected_hard_failures,
                indent=2,
            )
        )
        print(
            "Serialized hard_failures:"
        )
        print(
            json.dumps(
                serialized_hard_failures,
                indent=2,
            )
        )
        return 1

    output_path.write_text(
        serialized,
        encoding="utf-8",
    )

    # Read the file back immediately so the CLI cannot report
    # success if persistence produced different contents.
    try:
        persisted_payload = json.loads(
            output_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print()
        print(
            "Capability persistence "
            "verification failed:"
        )
        print(exc)
        return 1

    persisted_hard_failures = (
        persisted_payload.get(
            "hard_failures",
            [],
        )
    )

    if (
        persisted_hard_failures
        != expected_hard_failures
    ):
        print()
        print(
            "Capability persistence "
            "consistency check failed:"
        )
        print(
            f"Output: {output_path}"
        )
        print(
            "Expected hard_failures:"
        )
        print(
            json.dumps(
                expected_hard_failures,
                indent=2,
            )
        )
        print(
            "Persisted hard_failures:"
        )
        print(
            json.dumps(
                persisted_hard_failures,
                indent=2,
            )
        )
        return 1

    print()
    print(
        "Capability compiled successfully"
    )
    print(
        f"Capability: "
        f"{artifact.capability.id}"
    )
    print(
        f"Version: "
        f"{artifact.capability.version}"
    )
    print(
        f"Steps: "
        f"{len(artifact.steps)}"
    )
    print(
        f"Output: "
        f"{output_path}"
    )

    return 0
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
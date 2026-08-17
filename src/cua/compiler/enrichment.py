from __future__ import annotations

from pydantic import Field, model_validator

from cua.domain import (
    ActionSpec,
    CheckpointSpec,
    RiskSpec,
    StepRecord,
)
from cua.domain.base import DomainModel


class StepEnrichment(DomainModel):
    """
    Explicit metadata used to make an older discovery
    StepRecord compiler-ready.

    This is generic. Nothing here knows what application or
    business workflow the step belongs to.
    """

    step_index: int = Field(ge=0)

    action: ActionSpec | None = None
    output_binding: str | None = None
    risk: RiskSpec | None = None
    checkpoint_spec: CheckpointSpec | None = None

    reason: str | None = None


class TrajectoryEnrichment(DomainModel):
    """
    Auditable patch set applied in memory before compilation.

    The original evidence trajectory is never modified.
    """

    source_run_id: str | None = None

    steps: list[StepEnrichment] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_unique_step_indexes(
        self,
    ) -> TrajectoryEnrichment:
        indexes = [
            patch.step_index
            for patch in self.steps
        ]

        if len(indexes) != len(set(indexes)):
            raise ValueError(
                "trajectory enrichment contains "
                "duplicate step indexes"
            )

        return self


class TrajectoryEnrichmentError(ValueError):
    pass


def apply_trajectory_enrichment(
    trajectory: list[StepRecord],
    enrichment: TrajectoryEnrichment,
) -> list[StepRecord]:
    """
    Return an enriched copy of the trajectory.

    Historical discovery evidence remains unchanged.
    """

    if not trajectory:
        raise TrajectoryEnrichmentError(
            "Cannot enrich an empty trajectory"
        )

    run_ids = {
        step.run_id
        for step in trajectory
    }

    if len(run_ids) != 1:
        raise TrajectoryEnrichmentError(
            "Trajectory contains multiple run IDs"
        )

    run_id = next(iter(run_ids))

    if (
        enrichment.source_run_id is not None
        and enrichment.source_run_id != run_id
    ):
        raise TrajectoryEnrichmentError(
            "Enrichment source_run_id does not match "
            f"trajectory run_id: {run_id}"
        )

    by_index = {
        step.step_index: step
        for step in trajectory
    }

    enriched = list(trajectory)

    position_by_index = {
        step.step_index: position
        for position, step in enumerate(enriched)
    }

    for patch in enrichment.steps:
        if patch.step_index not in by_index:
            raise TrajectoryEnrichmentError(
                "Enrichment references missing step "
                f"{patch.step_index}"
            )

        original = by_index[patch.step_index]

        updates: dict[str, object] = {}

        # model_fields_set lets us distinguish:
        #
        # field omitted
        #
        # from:
        #
        # field explicitly set to null
        for field_name in (
            "action",
            "output_binding",
            "risk",
            "checkpoint_spec",
        ):
            if field_name in patch.model_fields_set:
                updates[field_name] = getattr(
                    patch,
                    field_name,
                )

        upgraded = original.model_copy(
            update=updates
        )

        position = position_by_index[
            patch.step_index
        ]

        enriched[position] = upgraded
        by_index[patch.step_index] = upgraded

    return enriched
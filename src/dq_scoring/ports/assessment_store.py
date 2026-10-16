"""Abstract assessment storage port for immutable publication."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from dq_scoring.core.entities import ImmutableAssessment
from dq_scoring.core.models import QualityRuleResult


@runtime_checkable
class IAssessmentStorePort(Protocol):
    """Abstract port for persisting immutable assessment scorecards and rule details."""

    def save_assessment_atomic(
        self,
        assessment: ImmutableAssessment,
        rule_results: list[QualityRuleResult],
        lease_generation: int,
    ) -> None:
        """Atomically persist assessment scorecard and rule-level results fenced by lease generation."""
        ...

    def get_assessment(
        self, assessment_id: UUID, tenant_id: UUID | None = None
    ) -> ImmutableAssessment | None:
        """Retrieve immutable assessment by assessment ID."""
        ...

    def get_assessment_by_run(
        self, run_id: UUID, tenant_id: UUID | None = None
    ) -> ImmutableAssessment | None:
        """Retrieve assessment associated with an evaluation run."""
        ...

    def get_rule_results(
        self, assessment_id: UUID, tenant_id: UUID | None = None
    ) -> list[QualityRuleResult]:
        """Retrieve detailed rule results for an assessment."""
        ...

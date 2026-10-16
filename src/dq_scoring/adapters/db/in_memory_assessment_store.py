"""In-memory assessment store adapter with lease fencing verification."""

from uuid import UUID

from dq_scoring.core.entities import ImmutableAssessment
from dq_scoring.core.models import QualityRuleResult
from dq_scoring.ports.assessment_store import IAssessmentStorePort


class InMemoryAssessmentStore(IAssessmentStorePort):
    """In-memory store persisting assessments atomically under lease fencing."""

    def __init__(self) -> None:
        self._assessments: dict[UUID, ImmutableAssessment] = {}
        self._rule_results: dict[UUID, list[QualityRuleResult]] = {}
        self._run_to_assessment: dict[UUID, UUID] = {}
        self._last_lease_gen: dict[UUID, int] = {}

    def save_assessment_atomic(
        self,
        assessment: ImmutableAssessment,
        rule_results: list[QualityRuleResult],
        lease_generation: int,
    ) -> None:
        """Atomically persist assessment, failing if lease_generation is outdated."""
        current_gen = self._last_lease_gen.get(assessment.run_id, 0)
        if lease_generation < current_gen:
            raise PermissionError(
                f"Lease fencing error: attempt gen {lease_generation} < active gen {current_gen}"
            )
        self._last_lease_gen[assessment.run_id] = lease_generation
        self._assessments[assessment.assessment_id] = assessment
        self._rule_results[assessment.assessment_id] = list(rule_results)
        self._run_to_assessment[assessment.run_id] = assessment.assessment_id

    def get_assessment(
        self, assessment_id: UUID, tenant_id: UUID | None = None
    ) -> ImmutableAssessment | None:
        """Retrieve assessment by ID, optionally verifying tenant ownership."""
        assessment = self._assessments.get(assessment_id)
        if assessment and tenant_id is not None and assessment.tenant_id != tenant_id:
            return None
        return assessment

    def get_assessment_by_run(
        self, run_id: UUID, tenant_id: UUID | None = None
    ) -> ImmutableAssessment | None:
        """Retrieve assessment by run ID, optionally verifying tenant ownership."""
        aid = self._run_to_assessment.get(run_id)
        if aid is None:
            return None
        return self.get_assessment(aid, tenant_id=tenant_id)

    def get_rule_results(
        self, assessment_id: UUID, tenant_id: UUID | None = None
    ) -> list[QualityRuleResult]:
        """Retrieve rule-level results for an assessment, optionally verifying tenant ownership."""
        if tenant_id is not None:
            assessment = self.get_assessment(assessment_id, tenant_id=tenant_id)
            if assessment is None:
                return []
        return self._rule_results.get(assessment_id, [])

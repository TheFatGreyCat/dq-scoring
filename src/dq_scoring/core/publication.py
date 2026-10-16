"""Pure domain logic for Assessment Publication determination (BR-012)."""

from dq_scoring.core.models import (
    PublicationCheckInput,
    PublicationStatus,
    QualityGateStatus,
)


def _is_publication_eligible(inp: PublicationCheckInput) -> bool:
    """Check all eligibility invariants for atomic scorecard publication."""
    if inp.run_status != "SUCCEEDED":
        return False
    if inp.gate_status in (
        QualityGateStatus.ERROR,
        QualityGateStatus.INSUFFICIENT_EVIDENCE,
    ):
        return False
    if (
        inp.coverage_ratio is None
        or inp.coverage_ratio < inp.policy.publication_threshold
    ):
        return False
    if not inp.all_required_dimensions_measured:
        return False
    if inp.has_failed_required_rules or inp.has_unmeasured_required_rules:
        return False
    return inp.dq_score is not None


def determine_publication_status(
    inp: PublicationCheckInput,
) -> tuple[PublicationStatus, float | None]:
    """Determine atomic publication status and effective published DQ Score.

    If eligible: returns (PUBLISHED, dq_score).
    If ineligible: returns (WITHHELD, None).
    """
    if _is_publication_eligible(inp):
        return PublicationStatus.PUBLISHED, inp.dq_score
    return PublicationStatus.WITHHELD, None

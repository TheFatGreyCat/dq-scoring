"""Validation service orchestrating rule execution against compute plane."""

from dq_scoring.core.entities import DatasetSnapshot, QualityRule, RuleExecutionOutput
from dq_scoring.core.models import (
    MeasurementStatus,
    QualityRuleResult,
    RuleCounts,
)
from dq_scoring.core.rule_scoring import (
    RuleScoringInput,
    compute_rule_score,
    verify_partition_identity,
)
from dq_scoring.ports.compute_engine import IComputeEnginePort


class ValidationService:
    """Service orchestrating dataset validation via vectorized compute pushdown."""

    def __init__(self, compute_engine: IComputeEnginePort) -> None:
        self._compute = compute_engine

    def validate_ruleset(
        self,
        snapshot: DatasetSnapshot,
        rules: list[QualityRule],
        sample_limit: int = 50,
    ) -> list[QualityRuleResult]:
        """Execute ruleset against snapshot and return validated QualityRuleResults."""
        outputs = self._compute.execute_rules(snapshot, rules, sample_limit)
        output_map = {out.rule_id: out for out in outputs}

        results: list[QualityRuleResult] = []
        for rule in rules:
            out = output_map.get(
                rule.rule_id,
                RuleExecutionOutput(
                    rule_id=rule.rule_id,
                    counts=RuleCounts(),
                    status=MeasurementStatus.NOT_MEASURABLE,
                ),
            )
            results.append(self._process_rule_result(rule, out))
        return results

    def _process_rule_result(
        self, rule: QualityRule, out: RuleExecutionOutput
    ) -> QualityRuleResult:
        """Process execution output into pure domain QualityRuleResult."""
        target_column = (
            getattr(rule, "target_column", None)
            or rule.parameters.get("target_column")
            or rule.parameters.get("column")
        )

        if out.status == MeasurementStatus.FAILED_TO_MEASURE:
            return self._build_technical_failure_result(rule, out)

        # Only MEASURED outputs are scored; every other status keeps its status and no score.
        if out.status != MeasurementStatus.MEASURED:
            return self._build_unscored_result(rule, out.status, out)

        if not verify_partition_identity(out.counts):
            return QualityRuleResult(
                rule_id=str(rule.rule_id),
                dimension=rule.dimension,
                measurement_status=MeasurementStatus.FAILED_TO_MEASURE.value,
                is_required=rule.is_required,
                is_critical=rule.is_critical,
                gate_enabled=rule.gate_enabled,
                score_enabled=rule.score_enabled,
                conflict_group=rule.conflict_group,
                is_primary_scoring_rule=rule.is_primary_scoring_rule,
                contribution_weight=rule.contribution_weight,
                acceptance_threshold=rule.acceptance_threshold,
                computed_score=None,
                violations_count=out.counts.failed
                + out.counts.miscast
                + (out.counts.missing if rule.null_policy == "fail" else 0),
                counts=out.counts,
                evidence_samples=out.evidence_samples if out.evidence_samples else None,
                error_message=out.error_message
                or "Partition identity check failed: sum of mutually exclusive counts does not match total_observed",
                source_kind="RULE",
                target_column=target_column,
            )

        status, score = compute_rule_score(
            RuleScoringInput(counts=out.counts, null_policy=rule.null_policy)
        )
        violations = out.counts.failed + out.counts.miscast
        if rule.null_policy == "fail":
            violations += out.counts.missing

        return QualityRuleResult(
            rule_id=str(rule.rule_id),
            dimension=rule.dimension,
            measurement_status=status,
            is_required=rule.is_required,
            is_critical=rule.is_critical,
            gate_enabled=rule.gate_enabled,
            score_enabled=rule.score_enabled,
            conflict_group=rule.conflict_group,
            is_primary_scoring_rule=rule.is_primary_scoring_rule,
            contribution_weight=rule.contribution_weight,
            acceptance_threshold=rule.acceptance_threshold,
            computed_score=score,
            violations_count=violations,
            counts=out.counts,
            evidence_samples=out.evidence_samples if out.evidence_samples else None,
            error_message=out.error_message,
            source_kind="RULE",
            target_column=target_column,
        )

    def _build_technical_failure_result(
        self, rule: QualityRule, out: RuleExecutionOutput | None = None
    ) -> QualityRuleResult:
        """Construct QualityRuleResult for technical measurement execution failure."""
        target_column = (
            getattr(rule, "target_column", None)
            or rule.parameters.get("target_column")
            or rule.parameters.get("column")
        )
        return QualityRuleResult(
            rule_id=str(rule.rule_id),
            dimension=rule.dimension,
            measurement_status=MeasurementStatus.FAILED_TO_MEASURE.value,
            is_required=rule.is_required,
            is_critical=rule.is_critical,
            gate_enabled=rule.gate_enabled,
            score_enabled=rule.score_enabled,
            conflict_group=rule.conflict_group,
            is_primary_scoring_rule=rule.is_primary_scoring_rule,
            contribution_weight=rule.contribution_weight,
            acceptance_threshold=rule.acceptance_threshold,
            computed_score=None,
            violations_count=0,
            counts=out.counts if out else None,
            evidence_samples=out.evidence_samples
            if (out and out.evidence_samples)
            else None,
            error_message=out.error_message if out else None,
            source_kind="RULE",
            target_column=target_column,
        )

    def _build_unscored_result(
        self,
        rule: QualityRule,
        status: MeasurementStatus,
        out: RuleExecutionOutput | None = None,
    ) -> QualityRuleResult:
        """Construct QualityRuleResult for NOT_APPLICABLE or NOT_MEASURABLE outcomes."""
        target_column = (
            getattr(rule, "target_column", None)
            or rule.parameters.get("target_column")
            or rule.parameters.get("column")
        )
        return QualityRuleResult(
            rule_id=str(rule.rule_id),
            dimension=rule.dimension,
            measurement_status=status.value,
            is_required=rule.is_required,
            is_critical=rule.is_critical,
            gate_enabled=rule.gate_enabled,
            score_enabled=rule.score_enabled,
            conflict_group=rule.conflict_group,
            is_primary_scoring_rule=rule.is_primary_scoring_rule,
            contribution_weight=rule.contribution_weight,
            acceptance_threshold=rule.acceptance_threshold,
            computed_score=None,
            violations_count=0,
            counts=out.counts if out else None,
            evidence_samples=out.evidence_samples
            if (out and out.evidence_samples)
            else None,
            error_message=out.error_message if out else None,
            source_kind="RULE",
            target_column=target_column,
        )

"""PostgreSQL 16 assessment store adapter implementing atomic publication under lease fencing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.common.protected_transport import protected_connect
from dq_scoring.common.redaction_utils import (
    MAX_ASSESSMENT_EVIDENCE_BYTES,
    MAX_RESULT_EVIDENCE_BYTES,
    prepare_bounded_evidence_payload,
)
from dq_scoring.core.entities import ImmutableAssessment
from dq_scoring.core.models import (
    DimensionResult,
    MeasurementStatus,
    PublicationStatus,
    QualityGateStatus,
    QualityRuleResult,
    RuleCounts,
)
from dq_scoring.ports.assessment_store import IAssessmentStorePort


class PostgresAssessmentStoreAdapter(IAssessmentStorePort):
    """PostgreSQL 16 persistent store for immutable scorecards, dimensions, and outbox."""

    def __init__(
        self,
        dsn: str | None = None,
        connection: psycopg.Connection | None = None,
    ) -> None:
        if dsn is None and connection is None:
            raise ValueError(
                "Either dsn or connection must be provided to PostgresAssessmentStoreAdapter"
            )
        self._dsn = dsn
        self._conn = connection

    @contextmanager
    def _get_connection(self) -> Iterator[psycopg.Connection]:
        if self._conn is not None:
            yield self._conn
        else:
            assert self._dsn is not None
            with protected_connect(self._dsn) as conn:
                yield conn

    def save_assessment_atomic(
        self,
        assessment: ImmutableAssessment,
        rule_results: list[QualityRuleResult],
        lease_generation: int,
    ) -> None:
        """Persist assessment, dimensions, rule results, outbox, and succeed run in a single transaction."""
        with (
            self._get_connection() as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            set_tenant_context(conn, assessment.tenant_id)

            # 1. Monotonic lease fencing check & run status advancement
            cur.execute(
                """
                UPDATE evaluation_runs
                SET run_status = 'SUCCEEDED',
                    completed_at = now()
                WHERE run_id = %s
                  AND lease_generation = %s
                  AND run_status IN ('LEASED', 'RUNNING')
                  AND (lease_expires_at IS NULL OR lease_expires_at > now());
                """,
                (assessment.run_id, lease_generation),
            )
            if cur.rowcount == 0:
                raise PermissionError(
                    f"Lease fencing error: attempt gen {lease_generation} failed for run {assessment.run_id}"
                )

            # Retrieve metadata for config_hashes and policy weights
            cur.execute(
                """
                SELECT r.snapshot_id, r.ruleset_id, r.policy_id, r.outlier_config_hash,
                       s.content_sha256, rs.config_hash, sp.config_hash, sp.dimension_weights
                FROM evaluation_runs r
                LEFT JOIN dataset_snapshots s ON s.snapshot_id = r.snapshot_id
                LEFT JOIN rulesets rs ON rs.ruleset_id = r.ruleset_id
                LEFT JOIN scoring_policies sp ON sp.policy_id = r.policy_id
                WHERE r.run_id = %s;
                """,
                (assessment.run_id,),
            )
            meta_row = cur.fetchone()
            policy_weights: dict[str, float] = {}
            if meta_row:
                (
                    _snap_id,
                    _rs_id,
                    _pol_id,
                    outlier_hash,
                    snap_hash,
                    rs_hash,
                    pol_hash,
                    db_weights,
                ) = meta_row
                if isinstance(db_weights, dict):
                    policy_weights = db_weights
                config_hashes = {
                    "source_descriptor_hash": snap_hash or "",
                    "ruleset_hash": rs_hash or "",
                    "policy_hash": pol_hash or "",
                    "outlier_config_hash": outlier_hash or "",
                }
            else:
                config_hashes = {
                    "assessment_hash": assessment.assessment_hash,
                }

            confidence_status = getattr(
                assessment, "confidence_status", "NOT_APPLICABLE"
            )

            # 2. Insert immutable assessment
            cur.execute(
                """
                INSERT INTO assessments (
                    assessment_id, tenant_id, run_id, snapshot_id,
                    dq_score, publication_status, visibility_scope,
                    coverage_ratio, confidence_status, quality_gate,
                    config_hashes, assessment_hash, published_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, 'PRIVATE',
                    %s, %s, %s,
                    %s, %s, %s
                );
                """,
                (
                    assessment.assessment_id,
                    assessment.tenant_id,
                    assessment.run_id,
                    assessment.snapshot_id,
                    assessment.dq_score,
                    assessment.publication_status.value,
                    assessment.coverage_ratio,
                    confidence_status,
                    assessment.quality_gate.value,
                    Jsonb(config_hashes),
                    assessment.assessment_hash,
                    assessment.created_at,
                ),
            )

            # 3. Insert dimension results
            for dim in assessment.dimension_results:
                total_rules = len(dim.rule_results)
                meas_rules = sum(
                    1
                    for r in dim.rule_results
                    if r.measurement_status == MeasurementStatus.MEASURED
                )
                dim_status = (
                    "MEASURED" if dim.dimension_score is not None else "NOT_MEASURABLE"
                )
                dim_weight = (
                    dim.dimension_weight
                    if getattr(dim, "dimension_weight", None) is not None
                    else policy_weights.get(
                        dim.dimension, policy_weights.get(dim.dimension.upper(), 1.0)
                    )
                )
                cur.execute(
                    """
                    INSERT INTO dimension_results (
                        dimension_result_id, tenant_id, assessment_id,
                        dimension, measurement_status, dimension_score,
                        dimension_weight, total_rules, measured_rules, coverage_ratio
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s
                    );
                    """,
                    (
                        uuid4(),
                        assessment.tenant_id,
                        assessment.assessment_id,
                        dim.dimension.upper(),
                        dim_status,
                        dim.dimension_score,
                        dim_weight,
                        total_rules,
                        meas_rules,
                        dim.coverage_ratio,
                    ),
                )

            # 4. Insert canonical quality results
            self._insert_quality_results(cur, assessment, rule_results)

            # 5. Insert assessment outbox event
            outbox_payload = {
                "assessment_id": str(assessment.assessment_id),
                "tenant_id": str(assessment.tenant_id),
                "run_id": str(assessment.run_id),
                "dq_score": assessment.dq_score,
                "publication_status": assessment.publication_status.value,
                "quality_gate": assessment.quality_gate.value,
                "assessment_hash": assessment.assessment_hash,
            }
            cur.execute(
                """
                INSERT INTO assessment_outbox (
                    event_id, tenant_id, assessment_id, destination,
                    payload, status, created_at
                ) VALUES (
                    %s, %s, %s, 'LAKEHOUSE_DELTA',
                    %s, 'PENDING', now()
                );
                """,
                (
                    uuid4(),
                    assessment.tenant_id,
                    assessment.assessment_id,
                    Jsonb(outbox_payload),
                ),
            )

            # 6. Insert run_events RUN_SUCCEEDED
            cur.execute(
                "SELECT attempt_count FROM evaluation_runs WHERE run_id = %s;",
                (assessment.run_id,),
            )
            att_row = cur.fetchone()
            att_cnt = att_row[0] if att_row else 1
            cur.execute(
                """
                INSERT INTO run_events (
                    event_id, tenant_id, run_id, event_type,
                    attempt_count, lease_generation, event_payload, created_at
                ) VALUES (
                    %s, %s, %s, 'RUN_SUCCEEDED',
                    %s, %s, %s, now()
                );
                """,
                (
                    uuid4(),
                    assessment.tenant_id,
                    assessment.run_id,
                    att_cnt,
                    lease_generation,
                    Jsonb({"assessment_id": str(assessment.assessment_id)}),
                ),
            )

    def _insert_quality_results(
        self,
        cur: psycopg.Cursor,
        assessment: ImmutableAssessment,
        rule_results: list[QualityRuleResult],
    ) -> None:
        """Insert detailed canonical rule results within current transaction."""
        cur.execute(
            "SELECT ruleset_id FROM evaluation_runs WHERE run_id = %s;",
            (assessment.run_id,),
        )
        r_row = cur.fetchone()
        ruleset_id = r_row[0] if r_row else None

        total_evidence_bytes = 0
        for r in rule_results:
            counts = r.counts
            if counts is None:
                if r.violations_count > 0:
                    counts = RuleCounts(
                        passed=0,
                        failed=r.violations_count,
                        missing=0,
                        miscast=0,
                        not_applicable=0,
                        total_observed=r.violations_count,
                    )
                else:
                    counts = RuleCounts()

            rem_budget = max(0, MAX_ASSESSMENT_EVIDENCE_BYTES - total_evidence_bytes)
            ev_payload = prepare_bounded_evidence_payload(
                samples=r.evidence_samples,
                error_message=r.error_message,
                max_bytes=min(MAX_RESULT_EVIDENCE_BYTES, rem_budget),
            )
            total_evidence_bytes += len(
                json.dumps(ev_payload, ensure_ascii=False, default=str).encode("utf-8")
            )

            source_kind = getattr(r, "source_kind", None)
            if not source_kind:
                source_kind = "OUTLIER" if r.is_advisory else "RULE"

            rule_uuid = None
            if source_kind == "RULE":
                try:
                    rule_uuid = UUID(str(r.rule_id))
                except (ValueError, TypeError, AttributeError):
                    rule_uuid = None

            target_column = getattr(r, "target_column", None)
            if not target_column:
                if str(r.rule_id).startswith("outlier_iqr_"):
                    target_column = str(r.rule_id).removeprefix("outlier_iqr_")
                else:
                    target_column = "column"

            if getattr(r, "rule_config_hash", None):
                rule_config_hash = r.rule_config_hash
            elif source_kind == "OUTLIER":
                rule_config_hash = hashlib.sha256(
                    f"OUTLIER:{target_column}".encode()
                ).hexdigest()
            else:
                rule_config_hash = hashlib.sha256(
                    f"{r.rule_id}:{target_column}:{r.dimension}".encode()
                ).hexdigest()

            cur.execute(
                """
                INSERT INTO canonical_quality_results (
                    result_id, tenant_id, run_id, rule_id, ruleset_id,
                    rule_config_hash, source_kind, target_column, dimension,
                    measurement_status, passed_count, failed_count,
                    missing_count, miscast_count, not_applicable_count,
                    total_observed, computed_score, is_advisory,
                    is_required, gate_enabled, score_enabled, evidence_payload,
                    violations_count
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s
                );
                """,
                (
                    uuid4(),
                    assessment.tenant_id,
                    assessment.run_id,
                    rule_uuid,
                    ruleset_id if source_kind == "RULE" else None,
                    rule_config_hash,
                    source_kind,
                    target_column,
                    r.dimension.upper(),
                    r.measurement_status.value
                    if hasattr(r.measurement_status, "value")
                    else str(r.measurement_status).upper(),
                    counts.passed,
                    counts.failed,
                    counts.missing,
                    counts.miscast,
                    counts.not_applicable,
                    counts.total_observed,
                    r.computed_score,
                    r.is_advisory,
                    r.is_required,
                    r.gate_enabled,
                    r.score_enabled,
                    Jsonb(ev_payload) if ev_payload else None,
                    r.violations_count,
                ),
            )

    def get_assessment(
        self,
        assessment_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ImmutableAssessment | None:
        """Retrieve immutable assessment scorecard and its dimensions by ID."""
        with (
            self._get_connection() as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            if tenant_id is not None:
                set_tenant_context(conn, tenant_id)
                cur.execute(
                    """
                    SELECT assessment_id, tenant_id, run_id, snapshot_id,
                           dq_score, publication_status, coverage_ratio,
                           quality_gate, assessment_hash, published_at, confidence_status
                    FROM assessments WHERE assessment_id = %s AND tenant_id = %s;
                    """,
                    (assessment_id, tenant_id),
                )
            else:
                cur.execute(
                    """
                    SELECT assessment_id, tenant_id, run_id, snapshot_id,
                           dq_score, publication_status, coverage_ratio,
                           quality_gate, assessment_hash, published_at, confidence_status
                    FROM assessments WHERE assessment_id = %s;
                    """,
                    (assessment_id,),
                )
            row = cur.fetchone()
            if row is None:
                return None

            (
                aid,
                tid,
                run_id,
                snapshot_id,
                dq_score,
                pub_status,
                cov_ratio,
                q_gate,
                a_hash,
                pub_at,
                conf_status,
            ) = row

            set_tenant_context(conn, tid)
            rule_results = self.get_rule_results(aid, tenant_id=tid)
            rules_by_dim: dict[str, list[QualityRuleResult]] = {}
            for r in rule_results:
                rules_by_dim.setdefault(r.dimension.upper(), []).append(r)

            cur.execute(
                """
                SELECT dimension, dimension_score, measurement_status, dimension_weight
                FROM dimension_results WHERE assessment_id = %s;
                """,
                (assessment_id,),
            )
            d_rows = cur.fetchall()
            dim_results: list[DimensionResult] = []
            for d in d_rows:
                d_name = d[0]
                dim_results.append(
                    DimensionResult(
                        dimension=d_name,
                        dimension_score=d[1],
                        coverage_ratio=cov_ratio,
                        rule_results=rules_by_dim.get(d_name.upper(), []),
                        dimension_weight=float(d[3])
                        if len(d) > 3 and d[3] is not None
                        else 1.0,
                    )
                )

            return ImmutableAssessment(
                assessment_id=aid,
                tenant_id=tid,
                run_id=run_id,
                snapshot_id=snapshot_id,
                dq_score=dq_score,
                publication_status=PublicationStatus(pub_status),
                coverage_ratio=cov_ratio,
                quality_gate=QualityGateStatus(q_gate),
                dimension_results=dim_results,
                assessment_hash=a_hash,
                created_at=pub_at,
                confidence_status=conf_status or "NOT_APPLICABLE",
            )

    def get_assessment_by_run(
        self,
        run_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ImmutableAssessment | None:
        """Retrieve assessment associated with an evaluation run."""
        with self._get_connection() as conn, conn.cursor() as cur:
            if tenant_id is not None:
                set_tenant_context(conn, tenant_id)
                cur.execute(
                    "SELECT assessment_id FROM assessments WHERE run_id = %s AND tenant_id = %s;",
                    (run_id, tenant_id),
                )
            else:
                cur.execute(
                    "SELECT assessment_id FROM assessments WHERE run_id = %s;",
                    (run_id,),
                )
            row = cur.fetchone()
            if row is None:
                return None
            return self.get_assessment(row[0], tenant_id=tenant_id)

    def get_rule_results(
        self,
        assessment_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[QualityRuleResult]:
        """Retrieve detailed rule results for an assessment."""
        with (
            self._get_connection() as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            if tenant_id is not None:
                set_tenant_context(conn, tenant_id)
                cur.execute(
                    "SELECT run_id, tenant_id FROM assessments WHERE assessment_id = %s AND tenant_id = %s;",
                    (assessment_id, tenant_id),
                )
            else:
                cur.execute(
                    "SELECT run_id, tenant_id FROM assessments WHERE assessment_id = %s;",
                    (assessment_id,),
                )
            a_row = cur.fetchone()
            if not a_row:
                return []
            run_id, tid = a_row
            set_tenant_context(conn, tid)

            cur.execute(
                """
                SELECT rule_id, dimension, measurement_status, passed_count,
                       failed_count, missing_count, miscast_count,
                       not_applicable_count, total_observed, computed_score,
                       is_advisory, is_required, gate_enabled, score_enabled,
                       evidence_payload, source_kind, target_column, rule_config_hash
                FROM canonical_quality_results WHERE run_id = %s;
                """,
                (run_id,),
            )
            rows = cur.fetchall()
            results: list[QualityRuleResult] = []
            for r in rows:
                ev_payload = r[14] or {}
                source_kind = r[15] or "RULE"
                target_column = r[16]
                rule_config_hash = r[17]
                if r[0] is not None:
                    rule_id_str = str(r[0])
                elif source_kind == "OUTLIER" and target_column:
                    rule_id_str = f"outlier_iqr_{target_column}"
                else:
                    rule_id_str = "unknown"

                violations = ev_payload.get("violations_count")
                if violations is None:
                    violations = r[4] + r[6]

                results.append(
                    QualityRuleResult(
                        rule_id=rule_id_str,
                        dimension=r[1],
                        measurement_status=r[2],
                        counts=RuleCounts(
                            passed=r[3],
                            failed=r[4],
                            missing=r[5],
                            miscast=r[6],
                            not_applicable=r[7],
                            total_observed=r[8],
                        ),
                        computed_score=r[9],
                        is_advisory=r[10],
                        is_required=r[11],
                        gate_enabled=r[12],
                        score_enabled=r[13],
                        violations_count=violations,
                        source_kind=source_kind,
                        target_column=target_column,
                        evidence_samples=ev_payload.get("evidence_samples"),
                        error_message=ev_payload.get("error_message"),
                        rule_config_hash=rule_config_hash,
                    )
                )
            return results

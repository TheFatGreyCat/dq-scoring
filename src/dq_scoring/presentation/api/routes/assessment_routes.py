"""Scorecard assessment query routes conforming to AC-022."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    check_tenant_access,
    get_current_user,
    get_db_connection,
)
from dq_scoring.presentation.api.pagination import (
    Pagination,
    date_bounds,
    fetch_page,
    pagination,
)
from dq_scoring.presentation.api.schemas.assessment_schemas import (
    AssessmentDetailResponse,
    CanonicalRuleResultResponse,
    DimensionResultResponse,
    PublicAssessmentResponse,
    PublicDimensionScore,
)

router = APIRouter(prefix="/api/v1/assessments", tags=["Scorecards & Assessments"])


@router.get("")
def list_assessments(
    asset_id: UUID | None = None,
    quality_gate: Literal["PASS", "WARN", "FAIL", "NOT_EVALUATED"] | None = None,
    publication_status: Literal["PUBLISHED", "WITHHELD", "DRAFT"] | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
    paging: Pagination = Depends(pagination), user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection),
) -> dict:
    date_bounds(created_from, created_to)
    predicates, params = ["a.tenant_id=%s"], [user.tenant_id]
    for column, value in (("s.asset_id", asset_id), ("a.quality_gate", quality_gate), ("a.publication_status", publication_status)):
        if value is not None:
            predicates.append(f"{column}=%s")
            params.append(value)
    if created_from:
        predicates.append("a.published_at >= %s")
        params.append(created_from)
    if created_to:
        predicates.append("a.published_at < %s")
        params.append(created_to)
    return fetch_page(conn, projection="a.assessment_id,a.run_id,a.snapshot_id,a.dq_score,a.quality_gate,a.publication_status,a.coverage_ratio,a.published_at", source="assessments a JOIN dataset_snapshots s ON s.tenant_id=a.tenant_id AND s.snapshot_id=a.snapshot_id", predicates=predicates, params=params, order="a.published_at DESC,a.assessment_id DESC", paging=paging)


@router.get("/{assessment_id}", response_model=AssessmentDetailResponse)
def get_assessment_detail(
    assessment_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> AssessmentDetailResponse:
    """Retrieve full detailed scorecard for authenticated tenant."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT assessment_id, tenant_id, run_id, snapshot_id, dq_score,
                   publication_status, coverage_ratio, quality_gate, assessment_hash, published_at
            FROM assessments WHERE assessment_id = %s;
            """,
            (assessment_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found.")
        check_tenant_access(row[1], current_user.tenant_id)

        # Fetch dimensions
        cur.execute(
            """
            SELECT dimension, dimension_score, dimension_weight, coverage_ratio
            FROM dimension_results WHERE assessment_id = %s;
            """,
            (assessment_id,),
        )
        dim_rows = cur.fetchall()
        dimensions = [
            DimensionResultResponse(
                dimension=d[0],
                dimension_score=d[1],
                coverage_ratio=d[3],
                dimension_weight=d[2] if d[2] is not None else 1.0,
            )
            for d in dim_rows
        ]

        # Fetch canonical rule results
        run_id = row[2]
        cur.execute(
            """
            SELECT cqr.rule_id,
                   CASE WHEN cqr.source_kind = 'OUTLIER' THEN 'OUTLIER_IQR_' || cqr.target_column
                        ELSE COALESCE(qr.rule_name, cqr.target_column) END AS rule_code,
                   cqr.dimension, cqr.target_column, COALESCE(qr.rule_type, cqr.source_kind) AS rule_type,
                   cqr.measurement_status, cqr.computed_score, cqr.passed_count, cqr.failed_count,
                   cqr.missing_count, cqr.miscast_count, cqr.not_applicable_count, cqr.total_observed,
                   COALESCE(cqr.violations_count, cqr.failed_count + cqr.miscast_count) AS violations_count,
                   CASE WHEN cqr.is_advisory OR NOT cqr.score_enabled THEN 0.0
                        ELSE COALESCE(qr.weight, 1.0) END AS weight,
                   cqr.is_required, COALESCE(qr.severity = 'CRITICAL', FALSE) AS is_critical,
                   cqr.is_advisory, cqr.evidence_payload
            FROM canonical_quality_results cqr
            LEFT JOIN quality_rules qr ON qr.rule_id = cqr.rule_id
            WHERE cqr.run_id = %s;
            """,
            (run_id,),
        )
        rule_rows = cur.fetchall()
        rule_results = [
            CanonicalRuleResultResponse(
                rule_id=r[0],
                rule_code=r[1],
                dimension=r[2],
                target_column=r[3],
                rule_type=r[4],
                measurement_status=r[5],
                computed_score=r[6],
                passed_count=r[7],
                failed_count=r[8],
                missing_count=r[9],
                miscast_count=r[10],
                not_applicable_count=r[11],
                total_observed=r[12],
                violations_count=r[13],
                weight=r[14],
                is_required=r[15],
                is_critical=r[16],
                is_advisory=r[17],
                evidence_samples=r[18].get("evidence_samples") if r[18] else None,
                error_message=r[18].get("error_message") if r[18] else None,
            )
            for r in rule_rows
        ]

        return AssessmentDetailResponse(
            assessment_id=row[0],
            tenant_id=row[1],
            run_id=row[2],
            snapshot_id=row[3],
            dq_score=row[4],
            publication_status=row[5],
            coverage_ratio=row[6],
            quality_gate=row[7],
            assessment_hash=row[8],
            created_at=row[9],
            dimension_results=dimensions,
            rule_results=rule_results,
        )


@router.get("/{assessment_id}/public", response_model=PublicAssessmentResponse)
def get_public_assessment(
    assessment_id: UUID,
    conn: psycopg.Connection = Depends(get_db_connection),
) -> PublicAssessmentResponse:
    """AC-022: Public scorecard projection with 100% metadata/evidence stripped."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE dq_public_role;")
        cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
        cur.execute("SELECT set_config('app.current_user_id', '', true);")
        cur.execute(
            """
            SELECT assessment_id, dq_score, publication_status, coverage_ratio,
                   quality_gate, assessment_hash, published_at
            FROM assessments
            WHERE assessment_id = %s
              AND publication_status = 'PUBLISHED'
              AND visibility_scope = 'PUBLIC_READ';
            """,
            (assessment_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found.")

        # Fetch only public dimension scores (0 metadata)
        cur.execute(
            "SELECT dimension, dimension_score, coverage_ratio FROM dimension_results WHERE assessment_id = %s;",
            (assessment_id,),
        )
        dim_rows = cur.fetchall()
        dimensions = [
            PublicDimensionScore(
                dimension=d[0],
                dimension_score=d[1],
                coverage_ratio=d[2],
            )
            for d in dim_rows
        ]

        return PublicAssessmentResponse(
            assessment_id=row[0],
            dq_score=row[1],
            publication_status=row[2],
            coverage_ratio=row[3],
            quality_gate=row[4],
            assessment_hash=row[5],
            created_at=row[6],
            dimensions=dimensions,
        )

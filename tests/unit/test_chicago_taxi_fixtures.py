"""Automated verification tests for Chicago Taxi Trips 2023 test fixtures (M1)."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from dq_scoring.core.dataset_scoring import DatasetScoringInput, compute_dataset_score
from dq_scoring.core.dimension_scoring import (
    DimensionScoringInput,
    compute_dimension_result,
)
from dq_scoring.core.models import (
    GateEvaluationInput,
    MeasurementStatus,
    QualityGateStatus,
    QualityRuleResult,
    RuleCounts,
    ScoringPolicy,
)
from dq_scoring.core.quality_gate import evaluate_quality_gate
from dq_scoring.core.rule_scoring import (
    RuleScoringInput,
    compute_rule_score,
    verify_partition_identity,
)

FIXTURES_DIR = Path("tests/fixtures/chicago_taxi")


def _calc_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def test_fixtures_integrity_and_hashes():
    """Verify that all fixture files exist and match fixtures.sha256 and manifest.json."""
    sha_file = FIXTURES_DIR / "fixtures.sha256"
    assert sha_file.exists(), "fixtures.sha256 must exist"

    manifest_file = FIXTURES_DIR / "manifest.json"
    assert manifest_file.exists(), "manifest.json must exist"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    sha_lines = sha_file.read_text(encoding="utf-8").strip().splitlines()
    recorded_hashes = {}
    for line in sha_lines:
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            recorded_hashes[parts[1].strip()] = parts[0].strip()

    expected_files = {
        "chicago_taxi_exploration_1k.csv": 1000,
        "chicago_taxi_golden_5k.csv": 5000,
    }

    for fname, exp_rows in expected_files.items():
        fpath = FIXTURES_DIR / fname
        assert fpath.exists(), f"Missing fixture file: {fname}"
        actual_sha = _calc_sha256(fpath)
        assert actual_sha == recorded_hashes[fname], f"Hash mismatch for {fname}"

        man_entry = next((e for e in manifest["files"] if e["filename"] == fname), None)
        assert man_entry is not None
        assert man_entry["rows"] == exp_rows
        assert man_entry["sha256"] == actual_sha


def test_exploration_and_benchmark_row_counts(tmp_path):
    """Verify persisted exploration and generated benchmark cardinalities."""
    exp_file = FIXTURES_DIR / "chicago_taxi_exploration_1k.csv"
    with exp_file.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert len(header) == 23
        assert sum(1 for _ in reader) == 1000

    from scripts.generate_fixtures import write_dataset_csv
    bench_file = tmp_path / "benchmark.csv"
    write_dataset_csv(bench_file, 100000, is_golden=False)
    with bench_file.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert len(header) == 23
        assert sum(1 for _ in reader) == 100000


def test_golden_dataset_partition_invariants_and_scores():
    """Verify golden dataset matches Ground Truth Matrix and preserves partition identities."""
    gt_file = FIXTURES_DIR / "golden_ground_truth_matrix.json"
    assert gt_file.exists()
    gt = json.loads(gt_file.read_text(encoding="utf-8"))

    rule_results: list[QualityRuleResult] = []

    for r in gt["rules"]:
        c = r["counts"]
        counts = RuleCounts(
            passed=c["passed"],
            failed=c["failed"],
            missing=c["missing"],
            miscast=c["miscast"],
            not_applicable=c["not_applicable"],
            total_observed=c["total_observed"],
        )
        assert verify_partition_identity(counts) is True

        status, score = compute_rule_score(
            RuleScoringInput(counts=counts, null_policy=r["null_policy"])
        )
        assert status == MeasurementStatus.MEASURED.value
        assert score == pytest.approx(r["rule_score"], abs=1e-2)

        rule_results.append(
            QualityRuleResult(
                rule_id=r["rule_code"],
                dimension=r["dimension"],
                measurement_status=status,
                computed_score=score,
                is_advisory=r["is_advisory"],
                contribution_weight=r["contribution_weight"],
                is_required=r["is_required"],
                is_critical=r["is_critical"],
                violations_count=c["failed"] + c["missing"] + c["miscast"],
                acceptance_threshold=95.0,
            )
        )

    dimensions = [
        "Completeness",
        "Validity",
        "Uniqueness",
        "Consistency",
        "Timeliness",
        "Accuracy",
    ]
    dim_results = []
    for dim_name in dimensions:
        dim_rules = [r for r in rule_results if r.dimension == dim_name]
        d_res = compute_dimension_result(
            DimensionScoringInput(dimension=dim_name, rules=dim_rules)
        )
        exp_dim = gt["dimensions"][dim_name]
        assert d_res.dimension_score == pytest.approx(exp_dim["score"], abs=1e-3)
        assert d_res.coverage_ratio == pytest.approx(exp_dim["coverage"], abs=1e-3)
        dim_results.append(d_res)

    ds_res = compute_dataset_score(
        DatasetScoringInput(
            dimension_results=dim_results,
            dimension_weights={d: 1.0 for d in dimensions},
        )
    )
    assert ds_res.dq_score == pytest.approx(gt["overall_dq_score"], abs=1e-4)
    assert ds_res.coverage_ratio == pytest.approx(gt["overall_coverage"], abs=1e-4)

    policy = ScoringPolicy(
        pass_min=80.0,
        warn_min=60.0,
        publication_threshold=0.80,
    )
    gate_input_pass = GateEvaluationInput(
        rule_results=rule_results,
        dq_score=ds_res.dq_score,
        coverage_ratio=ds_res.coverage_ratio,
        policy=policy,
        required_dimensions=set(dimensions),
    )
    assert evaluate_quality_gate(gate_input_pass) == QualityGateStatus.PASS

    zero_tol_rules = [
        r.model_copy(update={"acceptance_threshold": None}) for r in rule_results
    ]
    gate_input_crit_fail = GateEvaluationInput(
        rule_results=zero_tol_rules,
        dq_score=ds_res.dq_score,
        coverage_ratio=ds_res.coverage_ratio,
        policy=policy,
        required_dimensions=set(dimensions),
    )
    assert evaluate_quality_gate(gate_input_crit_fail) == QualityGateStatus.FAIL

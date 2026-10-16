"""Deterministic Generator for Chicago Taxi Trips 2023 Test Fixtures (M1/T1.2).

Generates 3-tier datasets:
  1. Exploration (1,000 rows): Initial profiling and schema exploration.
  2. Golden (5,000 rows): Injected anomalies with exact ground truth matrix.
  3. Benchmark (100,000 rows): SLA and memory footprint verification.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

RANDOM_SEED: int = 42
BASE_TIMESTAMP: datetime = datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC)
COMPANIES: list[str] = [
    "Flash Cab",
    "Taxi Affiliation Services",
    "Sun Taxi",
    "Globe Taxi",
    "Choice Taxi Association",
    "Medallion Leased",
]
PAYMENT_TYPES: list[str] = [
    "Cash",
    "Credit Card",
    "Prcard",
    "Dispute",
    "No Charge",
    "Unknown",
]

CSV_HEADERS: list[str] = [
    "trip_id",
    "taxi_id",
    "trip_start_timestamp",
    "trip_end_timestamp",
    "trip_seconds",
    "trip_miles",
    "pickup_census_tract",
    "dropoff_census_tract",
    "pickup_community_area",
    "dropoff_community_area",
    "fare",
    "tips",
    "tolls",
    "extras",
    "trip_total",
    "payment_type",
    "company",
    "pickup_centroid_latitude",
    "pickup_centroid_longitude",
    "pickup_centroid_location",
    "dropoff_centroid_latitude",
    "dropoff_centroid_longitude",
    "dropoff_centroid_location",
]


def make_clean_record(row_id: int, rng: random.Random) -> dict[str, Any]:
    """Generate a valid, authentic Chicago taxi trip record."""
    trip_sec = rng.randint(180, 2400)
    start_dt = BASE_TIMESTAMP + timedelta(
        days=rng.randint(0, 30),
        seconds=rng.randint(0, 86399),
    )
    end_dt = start_dt + timedelta(seconds=trip_sec)
    miles = round(rng.uniform(0.5, 18.0), 2)
    fare_val = round(3.25 + miles * 2.25 + (trip_sec / 120.0), 2)
    tips_val = round(fare_val * 0.18, 2) if rng.random() > 0.4 else 0.0
    extras_val = 2.0 if rng.random() > 0.7 else 0.0
    total_val = round(fare_val + tips_val + extras_val, 2)

    p_lat = round(41.85 + rng.uniform(0.01, 0.12), 6)
    p_lon = round(-87.75 + rng.uniform(0.01, 0.15), 6)
    d_lat = round(41.85 + rng.uniform(0.01, 0.12), 6)
    d_lon = round(-87.75 + rng.uniform(0.01, 0.15), 6)

    return {
        "trip_id": f"trip_{row_id:08d}_{rng.randint(1000, 9999)}",
        "taxi_id": f"taxi_{rng.randint(100, 999):04d}",
        "trip_start_timestamp": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "trip_end_timestamp": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "trip_seconds": str(trip_sec),
        "trip_miles": f"{miles:.2f}",
        "pickup_census_tract": str(rng.randint(17031010100, 17031840000)),
        "dropoff_census_tract": str(rng.randint(17031010100, 17031840000)),
        "pickup_community_area": str(rng.randint(1, 77)),
        "dropoff_community_area": str(rng.randint(1, 77)),
        "fare": f"{fare_val:.2f}",
        "tips": f"{tips_val:.2f}",
        "tolls": "0.00",
        "extras": f"{extras_val:.2f}",
        "trip_total": f"{total_val:.2f}",
        "payment_type": rng.choice(PAYMENT_TYPES),
        "company": rng.choice(COMPANIES),
        "pickup_centroid_latitude": f"{p_lat:.6f}",
        "pickup_centroid_longitude": f"{p_lon:.6f}",
        "pickup_centroid_location": f"POINT ({p_lon:.6f} {p_lat:.6f})",
        "dropoff_centroid_latitude": f"{d_lat:.6f}",
        "dropoff_centroid_longitude": f"{d_lon:.6f}",
        "dropoff_centroid_location": f"POINT ({d_lon:.6f} {d_lat:.6f})",
    }


def inject_anomaly_into_golden(idx: int, rec: dict[str, Any]) -> dict[str, Any]:
    """Inject deterministic anomalies into row idx (1-based) per Ground Truth Matrix."""
    if 1 <= idx <= 50:
        rec["trip_id"] = ""
    elif 51 <= idx <= 150:
        rec["fare"] = ""
    elif 151 <= idx <= 210:
        rec["trip_start_timestamp"] = "2023-13-45 99:99:99"
    elif 211 <= idx <= 250:
        rec["fare"] = "INVALID_FARE"
    elif 251 <= idx <= 325:
        rec["fare"] = "-15.50"
    elif 326 <= idx <= 405:
        rec["payment_type"] = "BITCOIN"
    elif 406 <= idx <= 435:
        rec["trip_id"] = f"trip_{idx + 30:08d}_DUPLICATE"
    elif 436 <= idx <= 465:
        rec["trip_id"] = f"trip_{idx:08d}_DUPLICATE"
    elif 466 <= idx <= 515:
        rec["trip_end_timestamp"] = "2023-01-01 01:00:00"
        rec["trip_start_timestamp"] = "2023-01-01 02:00:00"
    elif 516 <= idx <= 560:
        rec["fare"] = "50.00"
        rec["trip_total"] = "10.00"
    elif 561 <= idx <= 595:
        rec["trip_start_timestamp"] = "2019-06-15 12:00:00"
    elif 596 <= idx <= 620:
        rec["trip_miles"] = "2500.00"
    elif 621 <= idx <= 635:
        rec["fare"] = "9999.00"
        rec["trip_total"] = "9999.00"
    return rec


def write_dataset_csv(filepath: Path, count: int, is_golden: bool) -> None:
    """Generate and write CSV dataset."""
    rng = random.Random(RANDOM_SEED)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for i in range(1, count + 1):
            row = make_clean_record(i, rng)
            if is_golden:
                row = inject_anomaly_into_golden(i, row)
            writer.writerow(row)


def sha256_of_file(filepath: Path) -> str:
    """Compute hex SHA-256 hash of a file."""
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_ground_truth_rules() -> list[dict[str, Any]]:
    """Return catalog of 12 evaluated rules with exact ground truth counts."""
    return [
        {
            "rule_code": "CH_COMP_01",
            "rule_name": "trip_id_not_null",
            "rule_type": "NON_NULL",
            "dimension": "Completeness",
            "target_column": "trip_id",
            "is_required": True,
            "is_critical": True,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4950,
                "failed": 0,
                "missing": 50,
                "miscast": 0,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 99.00,
        },
        {
            "rule_code": "CH_COMP_02",
            "rule_name": "fare_not_null",
            "rule_type": "NON_NULL",
            "dimension": "Completeness",
            "target_column": "fare",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4900,
                "failed": 0,
                "missing": 100,
                "miscast": 0,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 98.00,
        },
        {
            "rule_code": "CH_VAL_01",
            "rule_name": "trip_start_timestamp_parse",
            "rule_type": "TYPE_PARSE",
            "dimension": "Validity",
            "target_column": "trip_start_timestamp",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4940,
                "failed": 0,
                "missing": 0,
                "miscast": 60,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 98.80,
        },
        {
            "rule_code": "CH_VAL_02",
            "rule_name": "fare_numeric_parse",
            "rule_type": "TYPE_PARSE",
            "dimension": "Validity",
            "target_column": "fare",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4860,
                "failed": 0,
                "missing": 100,
                "miscast": 40,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 97.20,
        },
        {
            "rule_code": "CH_VAL_03",
            "rule_name": "fare_non_negative",
            "rule_type": "DOMAIN_RANGE",
            "dimension": "Validity",
            "target_column": "fare",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4785,
                "failed": 75,
                "missing": 100,
                "miscast": 40,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 95.70,
        },
        {
            "rule_code": "CH_VAL_04",
            "rule_name": "payment_type_in_domain",
            "rule_type": "DOMAIN_RANGE",
            "dimension": "Validity",
            "target_column": "payment_type",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4920,
                "failed": 80,
                "missing": 0,
                "miscast": 0,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 98.40,
        },
        {
            "rule_code": "CH_UNIQ_01",
            "rule_name": "trip_id_unique",
            "rule_type": "UNIQUENESS",
            "dimension": "Uniqueness",
            "target_column": "trip_id",
            "is_required": True,
            "is_critical": True,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4920,
                "failed": 30,
                "missing": 50,
                "miscast": 0,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 98.40,
        },
        {
            "rule_code": "CH_CONS_01",
            "rule_name": "end_time_gte_start_time",
            "rule_type": "CROSS_FIELD",
            "dimension": "Consistency",
            "target_column": "trip_end_timestamp",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4890,
                "failed": 50,
                "missing": 0,
                "miscast": 60,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 97.80,
        },
        {
            "rule_code": "CH_CONS_02",
            "rule_name": "trip_total_gte_fare",
            "rule_type": "CROSS_FIELD",
            "dimension": "Consistency",
            "target_column": "trip_total",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4815,
                "failed": 45,
                "missing": 100,
                "miscast": 40,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 96.30,
        },
        {
            "rule_code": "CH_TIME_01",
            "rule_name": "trip_start_in_2023",
            "rule_type": "DOMAIN_RANGE",
            "dimension": "Timeliness",
            "target_column": "trip_start_timestamp",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4905,
                "failed": 35,
                "missing": 0,
                "miscast": 60,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 98.10,
        },
        {
            "rule_code": "CH_ACC_01",
            "rule_name": "trip_miles_plausible",
            "rule_type": "DOMAIN_RANGE",
            "dimension": "Accuracy",
            "target_column": "trip_miles",
            "is_required": True,
            "is_critical": False,
            "is_advisory": False,
            "contribution_weight": 1.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4975,
                "failed": 25,
                "missing": 0,
                "miscast": 0,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 99.50,
        },
        {
            "rule_code": "CH_OUT_01",
            "rule_name": "fare_iqr_outlier_advisory",
            "rule_type": "DOMAIN_RANGE",
            "dimension": "Accuracy",
            "target_column": "fare",
            "is_required": False,
            "is_critical": False,
            "is_advisory": True,
            "contribution_weight": 0.0,
            "null_policy": "fail",
            "counts": {
                "passed": 4845,
                "failed": 15,
                "missing": 100,
                "miscast": 40,
                "not_applicable": 0,
                "total_observed": 5000,
            },
            "rule_score": 96.90,
        },
    ]


def build_ground_truth_matrix() -> dict[str, Any]:
    """Construct full ground truth matrix structure."""
    rules = get_ground_truth_rules()
    dimensions = {
        "Completeness": {"score": 98.50, "coverage": 1.00, "weight": 1.0},
        "Validity": {"score": 97.525, "coverage": 1.00, "weight": 1.0},
        "Uniqueness": {"score": 98.40, "coverage": 1.00, "weight": 1.0},
        "Consistency": {"score": 97.05, "coverage": 1.00, "weight": 1.0},
        "Timeliness": {"score": 98.10, "coverage": 1.00, "weight": 1.0},
        "Accuracy": {"score": 99.50, "coverage": 1.00, "weight": 1.0},
    }
    return {
        "total_rows": 5000,
        "rules": rules,
        "dimensions": dimensions,
        "overall_dq_score": 98.179167,
        "overall_coverage": 1.00,
        "policy_standard": {
            "critical_acceptance_threshold": 95.0,
            "gate_status": "PASS",
            "publication_status": "PUBLISHED",
        },
        "policy_zero_tolerance": {
            "critical_acceptance_threshold": None,
            "gate_status": "FAIL",
            "publication_status": "WITHHELD",
        },
    }


def write_markdown_matrix(filepath: Path, gt: dict[str, Any]) -> None:
    """Write human-readable Golden Ground Truth Matrix markdown."""
    lines = [
        "# Golden Dataset (5,000 rows) — Ground Truth Matrix",
        "",
        "## 1. Rule Evaluation Breakdown",
        "",
        "| Rule Code | Dimension | Group | Column | Passed | Failed | Missing | Miscast | Score | Status |",
        "| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for r in gt["rules"]:
        c = r["counts"]
        adv_tag = " [ADVISORY]" if r["is_advisory"] else ""
        lines.append(
            f"| `{r['rule_code']}` | {r['dimension']} | `{r['rule_type']}` | `{r['target_column']}` "
            f"| {c['passed']} | {c['failed']} | {c['missing']} | {c['miscast']} "
            f"| {r['rule_score']:.2f}% | MEASURED{adv_tag} |"
        )
    lines.extend(
        [
            "",
            "## 2. Dimension Aggregations",
            "",
            "| Dimension | Dimension Score | Dimension Coverage | Weight |",
            "| :--- | :---: | :---: | :---: |",
        ]
    )
    for dim, val in gt["dimensions"].items():
        lines.append(
            f"| {dim} | {val['score']:.3f}% | {val['coverage'] * 100:.1f}% | {val['weight']} |"
        )
    lines.extend(
        [
            "",
            "## 3. Dataset-Level Summary",
            "",
            f"- **Dataset DQ Score:** {gt['overall_dq_score']:.6f}% (~98.18%)",
            f"- **Dataset Coverage:** {gt['overall_coverage'] * 100:.1f}%",
            f"- **Quality Gate (Standard Threshold >= 95%):** `{gt['policy_standard']['gate_status']}` (Publication: `{gt['policy_standard']['publication_status']}`)",
            f"- **Quality Gate (Zero-Tolerance on Critical):** `{gt['policy_zero_tolerance']['gate_status']}` (Publication: `{gt['policy_zero_tolerance']['publication_status']}`)",
        ]
    )
    filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Execute M1 test fixtures generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate Chicago taxi test fixtures")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/fixtures/chicago_taxi"),
        help="Target directory for generated fixtures",
    )
    args = parser.parse_args()
    base_dir = args.output_dir
    base_dir.mkdir(parents=True, exist_ok=True)
    print("Generating Exploration Dataset (1,000 rows)...")
    exp_file = base_dir / "chicago_taxi_exploration_1k.csv"
    write_dataset_csv(exp_file, 1000, is_golden=False)

    print("Generating Golden Dataset (5,000 rows with injected anomalies)...")
    golden_file = base_dir / "chicago_taxi_golden_5k.csv"
    write_dataset_csv(golden_file, 5000, is_golden=True)

    print("Generating Benchmark Dataset (100,000 rows)...")
    bench_file = base_dir / "chicago_taxi_benchmark_100k.csv"
    write_dataset_csv(bench_file, 100000, is_golden=False)

    print("Computing SHA-256 hashes...")
    hashes = {
        exp_file.name: sha256_of_file(exp_file),
        golden_file.name: sha256_of_file(golden_file),
        bench_file.name: sha256_of_file(bench_file),
    }

    sha_file = base_dir / "fixtures.sha256"
    with sha_file.open("w", encoding="utf-8") as f:
        for fname, h in hashes.items():
            f.write(f"{h}  {fname}\n")

    print("Generating Golden Ground Truth Matrix...")
    gt = build_ground_truth_matrix()
    gt_json = base_dir / "golden_ground_truth_matrix.json"
    gt_json.write_text(json.dumps(gt, indent=2), encoding="utf-8")
    gt_md = base_dir / "GOLDEN_GROUND_TRUTH_MATRIX.md"
    write_markdown_matrix(gt_md, gt)

    manifest = {
        "dataset_name": "chicago_taxi_trips_2023_fixtures",
        "random_seed": RANDOM_SEED,
        "files": [
            {
                "filename": exp_file.name,
                "rows": 1000,
                "sha256": hashes[exp_file.name],
                "size_bytes": exp_file.stat().st_size,
            },
            {
                "filename": golden_file.name,
                "rows": 5000,
                "sha256": hashes[golden_file.name],
                "size_bytes": golden_file.stat().st_size,
            },
            {
                "filename": bench_file.name,
                "rows": 100000,
                "sha256": hashes[bench_file.name],
                "size_bytes": bench_file.stat().st_size,
            },
        ],
    }
    (base_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print("Fixtures generation complete!")


if __name__ == "__main__":
    main()

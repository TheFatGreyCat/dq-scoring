# Golden Dataset (5,000 rows) — Ground Truth Matrix

## 1. Rule Evaluation Breakdown

| Rule Code | Dimension | Group | Column | Passed | Failed | Missing | Miscast | Score | Status |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `CH_COMP_01` | Completeness | `NON_NULL` | `trip_id` | 4950 | 0 | 50 | 0 | 99.00% | MEASURED |
| `CH_COMP_02` | Completeness | `NON_NULL` | `fare` | 4900 | 0 | 100 | 0 | 98.00% | MEASURED |
| `CH_VAL_01` | Validity | `TYPE_PARSE` | `trip_start_timestamp` | 4940 | 0 | 0 | 60 | 98.80% | MEASURED |
| `CH_VAL_02` | Validity | `TYPE_PARSE` | `fare` | 4860 | 0 | 100 | 40 | 97.20% | MEASURED |
| `CH_VAL_03` | Validity | `DOMAIN_RANGE` | `fare` | 4785 | 75 | 100 | 40 | 95.70% | MEASURED |
| `CH_VAL_04` | Validity | `DOMAIN_RANGE` | `payment_type` | 4920 | 80 | 0 | 0 | 98.40% | MEASURED |
| `CH_UNIQ_01` | Uniqueness | `UNIQUENESS` | `trip_id` | 4920 | 30 | 50 | 0 | 98.40% | MEASURED |
| `CH_CONS_01` | Consistency | `CROSS_FIELD` | `trip_end_timestamp` | 4890 | 50 | 0 | 60 | 97.80% | MEASURED |
| `CH_CONS_02` | Consistency | `CROSS_FIELD` | `trip_total` | 4815 | 45 | 100 | 40 | 96.30% | MEASURED |
| `CH_TIME_01` | Timeliness | `DOMAIN_RANGE` | `trip_start_timestamp` | 4905 | 35 | 0 | 60 | 98.10% | MEASURED |
| `CH_ACC_01` | Accuracy | `DOMAIN_RANGE` | `trip_miles` | 4975 | 25 | 0 | 0 | 99.50% | MEASURED |
| `CH_OUT_01` | Accuracy | `DOMAIN_RANGE` | `fare` | 4845 | 15 | 100 | 40 | 96.90% | MEASURED [ADVISORY] |

## 2. Dimension Aggregations

| Dimension | Dimension Score | Dimension Coverage | Weight |
| :--- | :---: | :---: | :---: |
| Completeness | 98.500% | 100.0% | 1.0 |
| Validity | 97.525% | 100.0% | 1.0 |
| Uniqueness | 98.400% | 100.0% | 1.0 |
| Consistency | 97.050% | 100.0% | 1.0 |
| Timeliness | 98.100% | 100.0% | 1.0 |
| Accuracy | 99.500% | 100.0% | 1.0 |

## 3. Dataset-Level Summary

- **Dataset DQ Score:** 98.179167% (~98.18%)
- **Dataset Coverage:** 100.0%
- **Quality Gate (Standard Threshold >= 95%):** `PASS` (Publication: `PUBLISHED`)
- **Quality Gate (Zero-Tolerance on Critical):** `FAIL` (Publication: `WITHHELD`)

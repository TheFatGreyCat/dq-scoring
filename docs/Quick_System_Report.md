# Quick System Report: DQ Scoring

## Executive Summary

This repository implements a Phase 1 Data Quality (DQ) Scoring MVP for CSV-based datasets. The system profiles datasets, evaluates configured data-quality rules, calculates rule, dimension, and dataset-level DQ Core scores, and presents the results in a Streamlit dashboard.

The current implementation is deterministic and explainable. It focuses on rule-based checks and score history rather than AI/ML scoring, TrustScore, or cross-system validation.

## System Purpose

The system answers three operational questions:

- What does a dataset look like statistically and structurally?
- Which configured data-quality rules pass or fail?
- What is the dataset's DQ Core Score across quality dimensions?

Phase 1 supports the following DQ dimensions:

- Completeness
- Validity
- Consistency
- Timeliness
- Uniqueness
- Accuracy Proxy

## Main Components

### Profiling Pipeline

Location: `profiling/`

The profiling pipeline loads a dataset from YAML configuration, applies sampling, profiles schema, columns, and dataset-level metrics, generates candidate rules, detects basic anomaly flags, and stores results in SQLite.

Key outputs:

- `profiling_run`
- `dataset_profile`
- `column_profile`
- `candidate_rule`
- `anomaly_flag`

Candidate rules are advisory and are not automatically scored.

### Rules Engine

Location: `rules_engine/`

The rules engine loads active rules from YAML, validates rule configuration against the dataset, evaluates rules with pandas, normalizes result counts, stores rule configuration snapshots, and stores issue samples.

Supported rule families include:

- Null/blank checks
- Regex checks
- Length checks
- Domain checks
- Type checks
- Range and plausibility checks
- Date parseability and not-future checks
- Key uniqueness and full-row duplicate checks
- Cross-field comparison checks
- Conditional required checks
- Freshness checks

Key outputs:

- `rule_run`
- `rule_config`
- `rule_evaluation_result`
- `rule_issue_sample`

Rules produce normalized counts for `passed`, `failed`, `miscast`, `empty`, and `not_applicable`.

### Scoring Engine

Location: `scoring/`

The scoring engine runs the rules engine, consumes its normalized results, calculates rule scores, aggregates dimension scores, and calculates the dataset-level DQ Core Score.

Scoring behavior:

- `RuleScore = passed / total_records_in_scope * 100`
- `DimensionScore` is a weighted average of measured rule scores
- `DQ Core Score` is a weighted average of measured dimensions
- Missing or not-measured dimensions are excluded and weights are renormalized
- Not-measured rules are not treated as zero

Key outputs:

- `score_run`
- `rule_score_history`
- `dimension_score_history`
- `dataset_score_history`

Phase 1 does not calculate TrustScore or FinalScore in the implemented scoring path.

### Dashboard

Location: `dashboard/`

The dashboard reads rule and score SQLite stores and presents latest dataset scores, dimension breakdowns, rule details, issue samples, and score history trends. It also includes an onboarding workflow for uploading a CSV, inferring schema, selecting keys and mandatory fields, generating configs, and running scoring.

Default dashboard stores:

- `data/rules_store/dq_rules.db`
- `data/score_store/dq_scores.db`

### Configuration And Sample Data

Location: `data/`

The repository includes four sample datasets and corresponding configs:

- `amazon`
- `bank_transaction_fraud_detection`
- `customer_master`
- `retail_sales_dataset`

Each dataset can have:

- Dataset config under `data/configs/`
- Rule config under `data/rules/`
- Scoring config under `data/scoring/`
- CSV sample under `data/samples/`

## End-To-End Flow

1. Dataset YAML points to a CSV source and declares metadata such as schema, keys, mandatory fields, CDE fields, and freshness settings.
2. Profiling can scan the dataset and produce profile statistics, candidate rules, and anomaly flags.
3. Rules Engine loads approved rules and evaluates each active rule against the dataset.
4. Scoring Engine converts rule evaluation counts into rule scores.
5. Dimension scores are calculated from rule scores.
6. Dataset DQ Core Score is calculated from measured dimension scores.
7. Dashboard reads SQLite stores and shows score, status, detail breakdown, issue samples, and history.

## Technology Stack

- Python
- pandas
- PyYAML
- Streamlit
- SQLite
- unittest

`great_expectations` is listed as a dependency, but the current executable code paths are pandas-based.

## Current Verification Status

Unit tests were run successfully:

- Command: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- Result: 20 tests passed

Covered areas include:

- Profiling pipeline and sampling behavior
- Candidate rule generation
- Rules engine parsing, validation, evaluation, and storage
- Scoring calculations and score stores
- Dashboard data loading and onboarding helpers

## Strengths

- Clear separation between profiling, rule evaluation, scoring, and dashboard display.
- Rule evaluation output is normalized and explainable.
- Score history is persisted at rule, dimension, and dataset levels.
- Missing or invalid measurements are handled explicitly instead of silently becoming zero.
- Tests cover the main Phase 1 workflow.
- Dashboard onboarding reduces the effort required to add new CSV datasets.

## Limitations And Risks

- The system is file and SQLite oriented; it is not yet productionized for concurrent users, scheduled runs, or larger data platforms.
- TrustScore and FinalScore are documented but not implemented in the main scoring path.
- Cross-system validation, fuzzy matching, advanced drift detection, and ML anomaly detection are out of scope for Phase 1.
- Rule execution is pandas-based, so very large datasets may require chunking, pushdown execution, or distributed processing.
- YAML parsing includes a fallback simple parser, but complex YAML behavior depends on PyYAML availability.
- Documentation files appear to contain Vietnamese text with encoding display issues in the local terminal output; the source files may need an encoding review if rendered incorrectly in editors or reports.

## Recommended Next Steps

1. Add a small architecture diagram to the docs showing stores and data flow.
2. Decide whether `great_expectations` remains a planned dependency or should be removed from Phase 1 requirements.
3. Add CLI smoke tests for the four bundled datasets.
4. Implement TrustScore and FinalScore only after metadata and certification inputs are available.
5. Add performance boundaries and guidance for dataset size, memory use, and pandas execution limits.
6. Add scheduled run support or integration hooks if this system will run beyond demos.

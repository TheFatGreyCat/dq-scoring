# DQ Scoring
This repository contains the Phase 1 DQ Scoring MVP:

- Profiling scans datasets, extracts deterministic statistics, generates
  candidate rules, and raises basic anomaly flags.
- Rules Engine runs active rule configs and produces normalized
  `Rule Evaluation Result` counts.
- Scoring Engine consumes Rules Engine output and calculates `RuleScore`,
  `DimensionScore`, and `DQ Core Score`.

Phase 1 does not calculate `TrustScore` or `FinalScore`.

## Install

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run The Sample Pipeline

```powershell
.\.venv\Scripts\python.exe -m profiling.run `
  --config data/configs/customer_master.yaml `
  --store data/profile_store/dq_profile.db `
  --export-json data/profile_store/customer_master_profile.json
```

The CLI prints a summary with `run_id`, status, row/column counts, candidate
rule count, anomaly flag count, and the SQLite profile store path.

## Run Rules Engine

```powershell
.\.venv\Scripts\python.exe -m rules_engine.run `
  --dataset-config data/configs/customer_master.yaml `
  --rules data/rules/customer_master_rules.yaml `
  --store data/rules_store/dq_rules.db `
  --export-json data/rules_store/customer_master_rules.json
```

The Rules Engine output includes:

- `rule_run`
- `rule_config`
- `rule_evaluation_result`
- `rule_issue_sample`

Rules Engine does not calculate score fields.

## Run DQ Core Scoring

```powershell
.\.venv\Scripts\python.exe -m scoring.run `
  --dataset-config data/configs/customer_master.yaml `
  --rules data/rules/customer_master_rules.yaml `
  --scoring-config data/scoring/customer_master_scoring.yaml `
  --rules-store data/rules_store/dq_rules.db `
  --score-store data/score_store/dq_scores.db `
  --export-json data/score_store/customer_master_score.json
```

The Scoring Engine output includes:

- `score_run`
- `rule_score_history`
- `dimension_score_history`
- `dataset_score_history`

The sample `customer_master` dataset intentionally contains common data quality
issues for the Phase 1 demo: blank phone number, invalid email format, invalid
age type, duplicate key, and duplicate row.

## Run Dashboard Demo

Generate multi-dataset demo score history:

```powershell
.\.venv\Scripts\python.exe dashboard\generate_demo_data.py --datasets all
```

Start the Streamlit dashboard:

```powershell
.\.venv\Scripts\streamlit.exe run dashboard\app.py
```

The dashboard reads the default SQLite stores:

- `data/rules_store/dq_rules.db`
- `data/score_store/dq_scores.db`

It shows the latest DQ Core Score per dataset, dimension scores, rule
breakdown, issue samples, and run history trend. See
`docs/Dashboard_Design.md` and `docs/Demo_Guide.md` for details.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Output Tables

The SQLite profile store creates:

- `profiling_run`
- `dataset_profile`
- `column_profile`
- `candidate_rule`
- `anomaly_flag`

The SQLite rules store creates:

- `rule_run`
- `rule_config`
- `rule_evaluation_result`
- `rule_issue_sample`

The SQLite score store creates:

- `score_run`
- `rule_score_history`
- `dimension_score_history`
- `dataset_score_history`

Generated store files under `data/profile_store/`, `data/rules_store/`, and
`data/score_store/` are ignored by git.

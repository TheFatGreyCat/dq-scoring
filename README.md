# DQ Scoring - Phase 1 Profiling Pipeline

This repository contains the Phase 1 profiling MVP for the DQ Scoring project.
The profiling pipeline scans datasets, extracts deterministic statistics,
generates candidate rules, raises basic anomaly flags, and stores normalized
profile results for downstream Rules Engine, Scoring Engine, Trust Score, and
Dashboard modules.

Profiling does not calculate official `RuleScore`, `DimensionScore`,
`DQ_Core`, or `FinalScore`. Those scores belong to downstream engines.

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

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Output Tables

The SQLite profile store creates the five Phase 1 tables from the profiling
design:

- `profiling_run`
- `dataset_profile`
- `column_profile`
- `candidate_rule`
- `anomaly_flag`

Generated profile store files under `data/profile_store/` are ignored by git.

# DQ Scoring

DQ Scoring is a PostgreSQL-backed data quality runtime. Streamlit and CLI entrypoints go through `dq_core.runtime` / `dq_core.orchestration`; SQLite stores, per-dataset YAML runtime files, Scoring V1, and legacy pandas validation runners are not runtime paths.

## Architecture

```text
Streamlit / CLI
  -> dq_core.runtime
  -> PostgreSQL repositories
  -> Rule Catalog + Dataset Rule Bindings
  -> GX/Python canonical validation
  -> Scoring + Quality Gate
  -> Dashboard / pipeline logs
```

PostgreSQL stores dataset metadata, profiling results, rule templates, rule bindings, validation runs, canonical measurements, scoring policies, score history, and pipeline logs.

## Install

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Local PostgreSQL

```powershell
docker compose up -d postgres
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
.\.venv\Scripts\python.exe -m persistence.db migrate
.\.venv\Scripts\python.exe -m dq_core.cli health_check
```

`DQ_DATABASE_URL` is read from the environment or `.env`. The dashboard and CLI do not accept database URLs from end users.

## CLI

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli register_dataset --csv data/samples/customer_master.csv --dataset-id customer_master --dataset-type customer
.\.venv\Scripts\python.exe -m dq_core.cli profile_dataset --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli recommend_rules --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli save_recommended_bindings --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli run_validation --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli calculate_score --validation-run-id <validation_run_id>
.\.venv\Scripts\python.exe -m dq_core.cli get_run_result --score-run-id <score_run_id>
```

## Dashboard

```powershell
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
.\.venv\Scripts\streamlit.exe run dashboard\app.py
```

The dashboard reads PostgreSQL through the repository layer, shows a System Health tab, and registers CSV metadata directly into storage. Dataset onboarding can run profile -> recommend -> bind -> validate -> score in one flow.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The test suite covers contract invariants, GX canonical adapters, Scoring behavior, dashboard PostgreSQL row transformation, health masking/status behavior, cleanup guardrails, and an end-to-end runtime slice with a fake repository.

## Legacy Boundary

Legacy CSV samples and YAML files may remain as fixtures or examples, but they are not runtime bootstrap paths. The runtime paths are PostgreSQL migrations, dataset registration, profiling, rule recommendation, validation, scoring, and dashboard reporting.

The removed runtime paths are:

- SQLite repositories
- per-dataset YAML service/CLI/dashboard execution
- legacy metadata importer commands
- sample-data auto bootstrap
- Scoring V1 runtime
- legacy pandas validation CLI runner

Use Git history/tag plus `backups/` artifacts for V1 reference and rollback context.

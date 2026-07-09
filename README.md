# DQ Scoring

DQ Scoring is a PostgreSQL-backed data quality runtime. Streamlit and CLI entrypoints go through `dq_core.runtime` / `dq_core.orchestration`; SQLite stores, per-dataset YAML runtime files, Scoring V1, and legacy pandas validation runners are no longer runtime paths.

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
```

Seed demo metadata from the legacy sample YAML once:

```powershell
.\.venv\Scripts\python.exe -m persistence.import_legacy --dry-run
.\.venv\Scripts\python.exe -m persistence.import_legacy --reset --report backups/import-report/import.json
```

`--dry-run`, `--reset`, `--dataset <id>`, and `--report <path>` are supported. The importer migrates dataset metadata, rule templates, rule bindings, and scoring policies only; V1 profiling, validation, score history, and SQLite artifacts are not migrated.

## CLI

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli register_dataset --csv data/samples/customer_master.csv --dataset-id customer_master --dataset-type customer
.\.venv\Scripts\python.exe -m dq_core.cli profile_dataset --dataset-version-id DV-customer_master-legacy
.\.venv\Scripts\python.exe -m dq_core.cli recommend_rules --dataset-version-id DV-customer_master-legacy
.\.venv\Scripts\python.exe -m dq_core.cli save_recommended_bindings --dataset-version-id DV-customer_master-legacy
.\.venv\Scripts\python.exe -m dq_core.cli run_validation --dataset-version-id DV-customer_master-legacy
.\.venv\Scripts\python.exe -m dq_core.cli calculate_score --validation-run-id <validation_run_id>
.\.venv\Scripts\python.exe -m dq_core.cli get_run_result --score-run-id <score_run_id>
```

## Dashboard

```powershell
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
.\.venv\Scripts\streamlit.exe run dashboard\app.py
```

The dashboard reads PostgreSQL through the repository layer. Dataset onboarding registers CSV metadata directly into storage and can run profile -> recommend -> bind -> validate -> score in one flow.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The test suite covers contract invariants, legacy importer dry-run/idempotency, GX canonical adapters, Scoring behavior, dashboard PostgreSQL row transformation, and an end-to-end runtime slice with a fake repository.

## Legacy Boundary

Legacy CSV samples and YAML files remain as seed/import fixtures. They are not runtime configuration. The removed runtime paths are:

- SQLite repositories
- per-dataset YAML service/CLI/dashboard execution
- Scoring V1 runtime
- legacy pandas validation CLI runner

Use Git history/tag plus `backups/` artifacts for V1 reference and rollback context.

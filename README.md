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

PostgreSQL stores dataset metadata, dataset-version storage paths, profiling results, rule templates, rule bindings, validation runs, canonical measurements, scoring policies, score history, and pipeline logs. Runtime CSV uploads are persisted by the repository under `data/uploads/<dataset_id>/<dataset_version_id>.csv` and are ignored by git.

## Install

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` pins direct runtime/test dependencies only. It is not a full transitive lockfile.

## Local PostgreSQL

```powershell
docker compose up -d postgres
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
.\.venv\Scripts\python.exe -m persistence.db migrate
.\.venv\Scripts\python.exe -m dq_core.cli bootstrap_catalog
.\.venv\Scripts\python.exe -m dq_core.cli health_check
```

`DQ_DATABASE_URL` is read from the environment or `.env`. The dashboard and CLI do not accept database URLs from end users. `bootstrap_catalog` is required after migration so the rule catalog and `SP-default` scoring policy exist before scoring.

## CLI Workflow

```powershell
.\.venv\Scripts\python.exe -m persistence.db migrate
.\.venv\Scripts\python.exe -m dq_core.cli bootstrap_catalog
.\.venv\Scripts\python.exe -m dq_core.cli register_dataset --csv data/samples/customer_master.csv --dataset-id customer_master --dataset-type customer
.\.venv\Scripts\python.exe -m dq_core.cli profile_dataset --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli recommend_rules --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli review_recommendation --recommendation-id <recommendation_id> --decision accepted
.\.venv\Scripts\python.exe -m dq_core.cli save_recommended_bindings --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli run_validation --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli calculate_score --validation-run-id <validation_run_id>
.\.venv\Scripts\python.exe -m dq_core.cli get_run_result --score-run-id <score_run_id>
```

`save_recommended_bindings` binds only recommendations reviewed as `accepted` or `edited` by default. `--accept-all-above-threshold` is for automation/demo use and only auto-binds recommendations that are safe to bind without review.

## Dashboard

```powershell
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
.\.venv\Scripts\streamlit.exe run dashboard\app.py
```

The dashboard reads PostgreSQL through the repository layer, shows a System Health tab, and registers uploaded CSV bytes through the runtime. The repository owns versioned file persistence; dashboard onboarding does not write upload files or pass `storage_path` metadata.

## Runtime Policies

Issue samples: raw `record_key` and `actual_value` remain in PostgreSQL for audit/debug. Dashboard read models and dashboard-oriented exports mask values at the boundary: empty string becomes `<empty>`, strings of length 1 or 2 become `***`, and longer strings become the first two characters plus `***`. Nested dict/list/tuple string values are masked recursively.

Dataset size limits: the default full-scan profile path applies up to `100_000` rows, `100MB`, and `200` columns. Larger or explicitly budgeted datasets use sampled or chunked profiling, with chunk metadata stored on `ProfilingRun`.

Coverage policy: scoring status is `final` when measured dimension coverage is at least `0.67`, `provisional` when coverage is at least `0.33`, and `insufficient_coverage` below `0.33`.

## Tests

Non-PostgreSQL suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --ignore=tests\test_postgres_integration.py --ignore=tests\test_postgres_fresh_install_smoke.py
```

PostgreSQL integration and fresh-install smoke:

```powershell
docker compose up -d postgres
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
.\.venv\Scripts\python.exe -m persistence.db migrate
.\.venv\Scripts\python.exe -m dq_core.cli bootstrap_catalog
.\.venv\Scripts\python.exe -m pytest tests\test_postgres_integration.py tests\test_postgres_fresh_install_smoke.py -q
```

CI runs a fresh virtual environment, installs pinned direct dependencies, starts PostgreSQL, runs migrations and `bootstrap_catalog`, then executes full `pytest tests -q` without ignoring PostgreSQL tests.

## Release Gate

A release commit is acceptable only after a green GitHub Actions run on that exact commit. Local tests are necessary but not sufficient for release sign-off.

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
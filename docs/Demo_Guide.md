# DQ Scoring V2 Demo Guide

This guide shows the quickest way to run the PostgreSQL-backed DQ Scoring V2 demo.

## 1. Install Dependencies

Run all commands from the repository root.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Start PostgreSQL
```powershell
docker compose up -d postgres
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
```

Apply migrations and initialize the Rule Catalog:

```powershell
.\.venv\Scripts\python.exe -m persistence.db migrate
.\.venv\Scripts\python.exe -m dq_core.cli bootstrap_catalog
.\.venv\Scripts\python.exe -m dq_core.cli health_check
```

## 3. Run the Dashboard
```powershell
.\.venv\Scripts\streamlit.exe run dashboard\app.py
```

The application contains these tabs:
- Dashboard: view scores and rule results.
- Onboard: register and analyze a CSV dataset.
- Catalog: view available rule templates.
- System Health: check database and runtime status.
- Logs: view pipeline execution history.

## 4. Demo a Dataset

Open the Onboard tab:

1. Upload a CSV file.
2. Review the inferred schema.
3. Select primary key, business key, mandatory fields and CDE fields.
4. Keep Run baseline after register enabled.
5. Click Register Dataset.

The runtime performs:

```
Register
→ Profile
→ Recommend rules
→ Bind safe rules
→ Validate
→ Calculate score
```

After completion, open the Dashboard tab to review:

DQ score.
Quality Gate status.
Measurement coverage.
Dimension scores.
Rule results.
Issue samples.
Score history.

Uploaded datasets are stored under:

```
data/uploads/<dataset_id>/<dataset_version_id>.csv
```

## 5. Optional CLI Workflow

Register a dataset:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli register_dataset `
  --csv data\samples\customer_master.csv `
  --dataset-id customer_master `
  --dataset-type customer `
  --primary-key customer_id `
  --mandatory-field customer_id
  ```

Use the returned dataset_version_id:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli profile_dataset --dataset-version-id <dataset_version_id>

.\.venv\Scripts\python.exe -m dq_core.cli save_recommended_bindings `
  --dataset-version-id <dataset_version_id> `
  --accept-all-above-threshold

.\.venv\Scripts\python.exe -m dq_core.cli run_validation --dataset-version-id <dataset_version_id>
```

Use the returned validation_run_id:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli calculate_score `
  --validation-run-id <validation_run_id>
```

## 6. Run Tests
```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

The test suite includes PostgreSQL integration and fresh-install smoke tests.

## 7. Reset the Demo

Reset runtime data:

```powershell
.\.venv\Scripts\python.exe -m persistence.db reset --yes
.\.venv\Scripts\python.exe -m dq_core.cli bootstrap_catalog
```

Remove PostgreSQL and its volume:

```powershell
docker compose down -v
```

## Notes
- PostgreSQL is the runtime storage.
- Runtime YAML and SQLite stores are no longer used.
- `dashboard\generate_demo_data.py` requires predefined dataset versions and is not intended for a fresh database.
- Sampling and chunked processing currently apply mainly to profiling.
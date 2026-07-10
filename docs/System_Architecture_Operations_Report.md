# BÃ¡o cÃ¡o kiáº¿n trÃºc, váº­n hÃ nh vÃ  kháº£ nÄƒng há»‡ thá»‘ng DQ Scoring

## 1. Tá»•ng quan

DQ Scoring lÃ  há»‡ thá»‘ng Ä‘Ã¡nh giÃ¡ cháº¥t lÆ°á»£ng dá»¯ liá»‡u cho dataset CSV. PhiÃªn báº£n hiá»‡n táº¡i Ä‘Ã£ chuyá»ƒn trá»ng tÃ¢m tá»« runtime cÅ© dÃ¹ng SQLite/YAML rá»i ráº¡c sang runtime táº­p trung trÃªn PostgreSQL.

Má»¥c tiÃªu chÃ­nh cá»§a há»‡ thá»‘ng:

- ÄÄƒng kÃ½ dataset vÃ  metadata.
- Profiling dá»¯ liá»‡u Ä‘á»ƒ thu tháº­p thá»‘ng kÃª, schema vÃ  Ä‘áº·c trÆ°ng cá»™t.
- PhÃ¡t hiá»‡n semantic type cÆ¡ báº£n nhÆ° email, phone, identifier, amount, datetime.
- Äá» xuáº¥t rule dá»±a trÃªn Rule Catalog.
- LÆ°u Dataset Rule Binding theo tá»«ng dataset version.
- Cháº¡y validation báº±ng Great Expectations hoáº·c Python evaluator.
- Chuáº©n hÃ³a káº¿t quáº£ validation vá» canonical measurement.
- TÃ­nh Rule Score, Dimension Score, Dataset DQ Score vÃ  Quality Gate.
- Hiá»ƒn thá»‹ káº¿t quáº£, rule, score history vÃ  pipeline log trÃªn dashboard.

Kiáº¿n trÃºc hiá»‡n táº¡i phÃ¹ há»£p cho demo local, kiá»ƒm thá»­ contract, vÃ  phÃ¡t triá»ƒn tiáº¿p thÃ nh runtime backend táº­p trung.

## 2. Kiáº¿n trÃºc tá»•ng thá»ƒ

Luá»“ng chÃ­nh:

```text
Streamlit Dashboard / CLI
  -> dq_core.runtime
  -> persistence.repository
  -> PostgreSQL
  -> Profiling
  -> Semantic Detection
  -> Rule Catalog + Dataset Rule Binding
  -> GX/Python Validation
  -> Canonical Measurement
  -> Scoring V2 + Quality Gate
  -> Dashboard / Pipeline Logs
```

CÃ¡c lá»›p chÃ­nh:

- `dq_core`: runtime facade, CLI, domain model vÃ  orchestration contract.
- `persistence`: káº¿t ná»‘i PostgreSQL, migration, repository, seed/import metadata legacy.
- `profiling`: load CSV, sampling, schema profile, column profile, metric extraction vÃ  semantic detection.
- `rules_engine`: rule evaluator Python cÅ© Ä‘Æ°á»£c giá»¯ Ä‘á»ƒ cháº¡y custom rule; thÃªm Rule Catalog vÃ  rule recommendation.
- `validation`: execution planner, GX runtime adapter, GX result adapter vÃ  canonical measurement converter.
- `scoring`: Scoring V2 tÃ­nh Ä‘iá»ƒm rule, dimension, dataset vÃ  Quality Gate.
- `dashboard`: Streamlit UI Ä‘á»c dá»¯ liá»‡u qua repository/runtime vÃ  há»— trá»£ onboarding CSV.
- `tests`: kiá»ƒm thá»­ contract cho profiling, rule catalog, validation, scoring, dashboard transformation vÃ  runtime slice.

## 3. ThÃ nh pháº§n dá»¯ liá»‡u vÃ  lÆ°u trá»¯

PostgreSQL lÃ  nÆ¡i lÆ°u tráº¡ng thÃ¡i runtime chÃ­nh. Migration hiá»‡n táº¡i náº±m á»Ÿ:

```text
persistence/migrations/001_core.sql
```

CÃ¡c nhÃ³m báº£ng chÃ­nh:

- Dataset metadata: `dataset`, `dataset_version`, `dataset_column`.
- Rule governance: `rule_template`, `dataset_rule_binding`.
- Profiling: `profiling_run`, `dataset_profile`, `column_profile`.
- Validation: `validation_run`, `measurement_result`, `record_measurement_summary`, `rule_issue_sample`.
- Scoring: `scoring_policy`, `score_run`, `rule_score_history`, `dimension_score_history`, `dataset_score_history`.
- Observability: `pipeline_log`.
- Migration bookkeeping: `schema_migration`.

Thiáº¿t káº¿ nÃ y giÃºp há»‡ thá»‘ng lÆ°u Ä‘Æ°á»£c lá»‹ch sá»­ score, measurement, binding vÃ  log thay vÃ¬ chá»‰ cháº¡y theo file YAML/SQLite cá»¥c bá»™.

## 4. Luá»“ng xá»­ lÃ½ nghiá»‡p vá»¥

### 4.1. Register Dataset

Input lÃ  CSV vÃ  metadata nhÆ° dataset id, dataset type, schema, primary key, business key, mandatory fields, CDE fields vÃ  timestamp column.

Káº¿t quáº£:

- LÆ°u metadata dataset.
- Táº¡o dataset version theo fingerprint ná»™i dung CSV.
- LÆ°u column metadata.
- Ghi pipeline log.

CLI tÆ°Æ¡ng á»©ng:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli register_dataset --csv data/samples/customer_master.csv --dataset-id customer_master --dataset-type customer
```

### 4.2. Profile Dataset

Runtime load dataset tá»« storage path, cháº¡y profiling, sampling, schema profile, column profile, dataset profile vÃ  semantic detection.

Káº¿t quáº£:

- LÆ°u `profiling_run`.
- LÆ°u `dataset_profile`.
- LÆ°u `column_profile`.
- Cáº­p nháº­t semantic type/confidence vÃ o `dataset_column`.
- Ghi pipeline log.

CLI:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli profile_dataset --dataset-version-id <dataset_version_id>
```

### 4.3. Recommend Rules

Rule recommendation sá»­ dá»¥ng:

- Column profile.
- Semantic detection.
- Dataset config metadata.
- Rule template máº·c Ä‘á»‹nh trong `rules_engine.catalog`.

CÃ¡c rule template hiá»‡n cÃ³ bao gá»“m:

- Mandatory not blank.
- Email format.
- Phone ten digits.
- Identifier uniqueness.
- Amount non-negative.
- Datetime not future.

CLI:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli recommend_rules --dataset-version-id <dataset_version_id>
```

### 4.4. Save Rule Bindings

Recommendation cÃ³ confidence Ä‘á»§ cao Ä‘Æ°á»£c chuyá»ƒn thÃ nh Dataset Rule Binding. Binding lÆ°u rule template, target columns, threshold, severity, backend, scoring method vÃ  gate setting.

CLI:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli save_recommended_bindings --dataset-version-id <dataset_version_id>
```

### 4.5. Run Validation

Validation chá»n backend theo binding:

- `gx` hoáº·c `gx_pandas`: cháº¡y qua Great Expectations runtime adapter náº¿u operator Ä‘Æ°á»£c há»— trá»£.
- `python`: cháº¡y qua Python `RuleEvaluator`.

Káº¿t quáº£ validation Ä‘Æ°á»£c chuáº©n hÃ³a vá» canonical contract:

- `MeasurementResult`.
- `RecordMeasurementSummary`.
- `CanonicalValidationResult`.

Canonical layer xá»­ lÃ½ cÃ¡c tráº¡ng thÃ¡i nhÆ° passed, failed, missing, not applicable vÃ  measurement status. Scoring khÃ´ng phá»¥ thuá»™c trá»±c tiáº¿p vÃ o format raw cá»§a GX hoáº·c Python evaluator.

CLI:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli run_validation --dataset-version-id <dataset_version_id>
```

### 4.6. Calculate Score

Scoring V2 tÃ­nh:

- Rule Score.
- Dimension Score.
- Dataset DQ Score.
- Quality Gate.
- Gate failures.
- Explanation gá»“m base score, severity weight, criticality weight, effective weight, field roles vÃ  scoring method.

Äiá»ƒm sá»‘ khÃ´ng dÃ¹ng trá»±c tiáº¿p `GX success`. GX chá»‰ lÃ  evidence/execution backend. Rule Score Ä‘Æ°á»£c tÃ­nh tá»« canonical measurement.

CLI:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli calculate_score --validation-run-id <validation_run_id>
```

## 5. Váº­n hÃ nh local

### 5.1. CÃ i dependency

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Dependency chÃ­nh:

- `pandas`
- `great_expectations`
- `psycopg[binary]`
- `PyYAML`
- `streamlit`

### 5.2. Khá»Ÿi Ä‘á»™ng PostgreSQL

```powershell
docker compose up -d postgres
```

`compose.yaml` táº¡o service PostgreSQL local:

- Database: `dq_scoring`
- User: `dq`
- Password: `dq`
- Port: `5432`

### 5.3. Cáº¥u hÃ¬nh database URL

```powershell
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
```

Hoáº·c dÃ¹ng `.env` dá»±a trÃªn `.env.example`:

```text
DQ_DATABASE_URL=postgresql://dq:dq@localhost:5432/dq_scoring
```

### 5.4. Cháº¡y migration

```powershell
.\.venv\Scripts\python.exe -m persistence.db migrate
```

Migration runner táº¡o báº£ng `schema_migration` vÃ  chá»‰ Ã¡p migration chÆ°a cháº¡y.

### 5.5. Kiá»ƒm tra runtime V2

Sau khi cháº¡y migration, kiá»ƒm tra cáº¥u hÃ¬nh server-side vÃ  schema:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli health_check
```

Dataset Ä‘Æ°á»£c Ä‘Äƒng kÃ½ qua CLI hoáº·c dashboard onboarding. Runtime khÃ´ng cÃ²n bootstrap metadata báº±ng importer legacy.

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli register_dataset --csv data/samples/customer_master.csv --dataset-id customer_master --dataset-type customer
.\.venv\Scripts\python.exe -m dq_core.cli profile_dataset --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli recommend_rules --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli save_recommended_bindings --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli run_validation --dataset-version-id <dataset_version_id>
.\.venv\Scripts\python.exe -m dq_core.cli calculate_score --validation-run-id <validation_run_id>
```

### 5.6. Cháº¡y dashboard

```powershell
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
.\.venv\Scripts\streamlit.exe run dashboard\app.py
```

Dashboard cÃ³ ba tab chÃ­nh:

- Dashboard: xem latest dataset score, dimension score, rule score vÃ  issue sample.
- Onboard: upload CSV, khai bÃ¡o schema/key/mandatory/CDE, register dataset vÃ  cháº¡y pipeline baseline.
- Logs: xem pipeline log.

## 6. Kháº£ nÄƒng hiá»‡n táº¡i

### 6.1. Data onboarding

Há»‡ thá»‘ng cÃ³ thá»ƒ upload CSV tá»« dashboard hoáº·c register qua CLI. Onboarding há»— trá»£:

- Tá»± suy luáº­n schema cÆ¡ báº£n.
- Chá»n primary key.
- Chá»n business key.
- Chá»n mandatory fields.
- Chá»n CDE fields.
- Chá»n timestamp column.
- Cháº¡y baseline pipeline ngay sau khi register.

### 6.2. Profiling vÃ  semantic detection

Profiling hiá»‡n há»— trá»£:

- Schema profile.
- Column statistics.
- Dataset statistics.
- Pattern detection.
- Duplicate ratio.
- Metrics cÃ³ nguá»“n `pandas` vÃ  `gx`.

Semantic detection hiá»‡n nháº­n diá»‡n cÆ¡ báº£n:

- `email`
- `phone`
- `identifier`
- `amount`
- `age`
- `datetime`
- `category`
- `unknown`

### 6.3. Rule framework

Rule framework hiá»‡n cÃ³ mÃ´ hÃ¬nh:

- Rule Template: rule dÃ¹ng chung hoáº·c dataset-level.
- Dataset Rule Binding: rule Ä‘Æ°á»£c gáº¯n vá»›i dataset version cá»¥ thá»ƒ.
- Rule Recommendation: Ä‘á» xuáº¥t rule dá»±a trÃªn semantic/profile/context.

CÃ¡c thuá»™c tÃ­nh governance quan trá»ng:

- `rule_category`: general, business, technical.
- `management_scope`: framework hoáº·c dataset.
- `target_scope`: column, multiple_columns, dataset.
- `evaluation_scope`: record, column_aggregate, dataset_aggregate, cross_field.
- `null_policy`: fail, ignore, separate.
- `score_enabled`.
- `gate_enabled`.
- `scoring_method`.

### 6.4. Validation

Validation há»— trá»£ hai backend:

- Great Expectations cho rule tiÃªu chuáº©n nhÆ° not blank, regex, domain, range, length, type check, uniqueness vÃ  not future.
- Python evaluator cho rule tÃ¹y biáº¿n vÃ  cÃ¡c rule khÃ´ng náº±m trong danh sÃ¡ch GX-supported.

Planner cÃ³ `ruleset_hash` Ä‘á»ƒ táº¡o fingerprint á»•n Ä‘á»‹nh cho táº­p binding/template Ä‘ang cháº¡y.

### 6.5. Scoring V2

Scoring V2 há»— trá»£:

- Rule score theo pass ratio.
- Freshness decay.
- Gate-only rule.
- Severity weight.
- Criticality weight dá»±a trÃªn role cá»§a field.
- Dimension score theo weighted average.
- Dataset score theo measured dimensions vÃ  normalized dimension weights.
- Quality Gate pass/warning/fail.
- Gate failure khi critical rule fail.
- Explanation JSON cho tá»«ng rule score.

### 6.6. Dashboard vÃ  reporting

Dashboard hiá»‡n Ä‘á»c tá»« PostgreSQL qua `DqPostgresRepository.list_dashboard_rows()` vÃ  transform sang dataframe cÅ© Ä‘á»ƒ UI sá»­ dá»¥ng.

Dashboard hiá»ƒn thá»‹:

- Sá»‘ dataset.
- Average DQ Score.
- Failing gates.
- Latest score theo dataset.
- Dimension breakdown.
- Rule breakdown.
- Issue samples.
- Pipeline logs.

## 7. Kiá»ƒm thá»­ hiá»‡n táº¡i

Bá»™ test hiá»‡n bao phá»§:

- Semantic detection vÃ  profile metrics.
- Rule catalog recommendation vÃ  binding.
- Seed plan map tá»« YAML legacy sang PostgreSQL contracts.
- Ruleset hash vÃ  execution plan.
- Canonical measurement vÃ  null policy.
- Scoring V2 weights, gate vÃ  explanation.
- GX adapter normalization.
- Runtime end-to-end slice vá»›i fake repository.
- Dashboard PostgreSQL row transformation.

Lá»‡nh test:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 8. Giá»›i háº¡n vÃ  rá»§i ro hiá»‡n táº¡i

CÃ¡c giá»›i háº¡n ká»¹ thuáº­t hiá»‡n táº¡i:

- Há»‡ thá»‘ng táº­p trung vÃ o CSV; chÆ°a há»— trá»£ nhiá»u data source production nhÆ° database, object storage hoáº·c API.
- PostgreSQL integration cáº§n PostgreSQL/Docker Ä‘ang cháº¡y; chÆ°a tháº¥y cáº¥u hÃ¬nh CI tÃ­ch há»£p Ä‘áº§y Ä‘á»§.
- Dashboard váº«n giá»¯ má»™t sá»‘ adapter dataframe tÆ°Æ¡ng thÃ­ch vá»›i mÃ´ hÃ¬nh cÅ©, nÃªn cáº§n tiáº¿p tá»¥c lÃ m sáº¡ch khi V2 á»•n Ä‘á»‹nh.
- `rule_issue_sample` Ä‘Ã£ cÃ³ schema nhÆ°ng chÆ°a pháº£i má»i backend Ä‘á»u lÆ°u issue sample chi tiáº¿t.
- Rule Catalog máº·c Ä‘á»‹nh cÃ²n nhá», má»›i Ä‘á»§ cho baseline demo.
- ChÆ°a cÃ³ RBAC, multi-tenant, scheduler, job queue hoáº·c audit workflow enterprise.
- ChÆ°a cÃ³ cÆ¡ cháº¿ migrate score history tá»« SQLite/V1.
- `data/uploads` lÃ  runtime output, khÃ´ng nÃªn commit dá»¯ liá»‡u upload cá»¥c bá»™ vÃ o Git.

Rá»§i ro váº­n hÃ nh:

- Náº¿u `.env` thiáº¿u `DQ_DATABASE_URL`, repository sáº½ khÃ´ng káº¿t ná»‘i Ä‘Æ°á»£c PostgreSQL.
- Náº¿u migration chÆ°a cháº¡y, dashboard/CLI sáº½ lá»—i do thiáº¿u báº£ng.
- Náº¿u Docker/PostgreSQL chÆ°a sáºµn sÃ ng, migration vÃ  runtime DB sáº½ fail.
- Náº¿u rule template vÃ  binding khÃ´ng Ä‘á»“ng bá»™, validation/scoring cÃ³ thá»ƒ lá»—i khi lookup template.

## 9. Äá»‹nh hÆ°á»›ng phÃ¡t triá»ƒn tiáº¿p

Æ¯u tiÃªn gáº§n:

- Cáº­p nháº­t hoáº·c thay tháº¿ bÃ¡o cÃ¡o cÅ© cÃ²n mÃ´ táº£ SQLite runtime.
- Má»Ÿ rá»™ng Rule Catalog cho nhiá»u rule business/technical hÆ¡n.
- LÆ°u issue samples chi tiáº¿t cho GX vÃ  Python backend.
- ThÃªm integration test cháº¡y vá»›i PostgreSQL tháº­t.
- Chuáº©n hÃ³a dashboard data model theo V2 Ä‘á»ƒ giáº£m adapter tÆ°Æ¡ng thÃ­ch V1.
- Bá»• sung lá»‡nh kiá»ƒm tra health/migration status.
- ThÃªm CI cho unittest vÃ  migration smoke test.

Æ¯u tiÃªn dÃ i háº¡n:

- Há»— trá»£ nhiá»u data source ngoÃ i CSV.
- ThÃªm scheduler/job queue cho pipeline runs.
- ThÃªm RBAC vÃ  audit log.
- ThÃªm versioning cho scoring policy vÃ  rule template lifecycle.
- XÃ¢y dá»±ng API service thay vÃ¬ chá»‰ CLI/Streamlit runtime.
- TÃ¡ch artifact storage khá»i local filesystem.

## 10. Káº¿t luáº­n

Há»‡ thá»‘ng hiá»‡n Ä‘Ã£ cÃ³ ná»n táº£ng runtime V2 rÃµ rÃ ng: PostgreSQL lÃ m source of truth, runtime facade dÃ¹ng chung cho CLI/dashboard, validation chuáº©n hÃ³a qua canonical measurement, scoring cÃ³ explanation vÃ  Quality Gate, Ä‘á»“ng thá»i váº«n giá»¯ kháº£ nÄƒng import metadata legacy Ä‘á»ƒ demo.

Tráº¡ng thÃ¡i hiá»‡n táº¡i phÃ¹ há»£p cho local demo, phÃ¡t triá»ƒn tÃ­nh nÄƒng vÃ  kiá»ƒm thá»­ contract. Äá»ƒ tiáº¿n tá»›i mÃ´i trÆ°á»ng váº­n hÃ nh á»•n Ä‘á»‹nh hÆ¡n, cáº§n hoÃ n thiá»‡n integration test vá»›i PostgreSQL tháº­t, má»Ÿ rá»™ng Rule Catalog, lÃ m sáº¡ch pháº§n tÆ°Æ¡ng thÃ­ch V1 trong dashboard/report, vÃ  bá»• sung cÃ¡c nÄƒng lá»±c production nhÆ° scheduler, API, RBAC vÃ  quan sÃ¡t váº­n hÃ nh.


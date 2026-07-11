# Báo cáo hệ thống DQ Scoring

Ngày lập báo cáo: 2026-07-10

## 1. Tóm tắt

DQ Scoring là hệ thống đánh giá chất lượng dữ liệu cho dataset CSV. Phiên bản hiện tại đã chuyển trọng tâm sang runtime V2 dùng PostgreSQL làm source of truth, với CLI và Streamlit dashboard cùng đi qua `dq_core.runtime.DqRuntime` và `persistence.repository.DqPostgresRepository`.

Luồng nghiệp vụ chính:

```text
CSV Dataset
  -> Register Dataset
  -> Profiling + Sampling
  -> Semantic Detection
  -> Rule Recommendation
  -> Recommendation Review / Binding
  -> GX hoặc Python Validation
  -> Canonical Measurement
  -> Scoring V2 + Quality Gate
  -> PostgreSQL History
  -> Dashboard / CLI / Pipeline Logs
```

Hệ thống hiện phù hợp cho local demo, proof of concept và phát triển tiếp thành data quality runtime tập trung. Các năng lực production như API service, auth/RBAC, scheduler/job queue, data source ngoài CSV và governance workflow đầy đủ chưa có.

## 2. Kiến trúc tổng thể

Các lớp chính:

| Lớp | Vai trò |
| --- | --- |
| `dq_core` | Domain model, CLI, health check và runtime facade điều phối pipeline |
| `persistence` | PostgreSQL connection, migration, repository, seed/import hỗ trợ |
| `profiling` | Load CSV, sampling, schema profile, dataset profile, column profile, semantic detection |
| `rules_engine` | Rule catalog, recommendation, benchmark, Python evaluator |
| `validation` | Execution planner, Great Expectations runtime, canonical measurement adapter |
| `scoring` | Scoring V2, rule/dimension/dataset score, quality gate |
| `dashboard` | Streamlit UI cho dashboard, onboarding, health, logs |
| `tests` | Regression/contract/integration tests cho các thành phần chính |

Nguyên tắc thiết kế hiện tại:

- PostgreSQL là nơi lưu trạng thái runtime chính.
- CLI và dashboard dùng chung `DqRuntime`, không có pipeline riêng biệt.
- Scoring không đọc raw Great Expectations output; mọi backend validation đi qua canonical measurement.
- Rule catalog tách khỏi binding theo dataset version.
- Score history lưu policy snapshot và formula revision để giải thích lại kết quả sau này.
- Dashboard không cho người dùng nhập trực tiếp database URL; cấu hình đi qua server-side env hoặc `.env`.

## 3. Lưu trữ và schema PostgreSQL

Local PostgreSQL được khai báo trong `compose.yaml`:

- Image: `postgres:16`
- Database: `dq_scoring`
- User/password local demo: `dq` / `dq`
- Port: `5432`
- Volume: `dq_scoring_pgdata`

Migrations hiện có:

| Migration | Nội dung chính |
| --- | --- |
| `001_core.sql` | Schema nền cho dataset, rule, profiling, validation, scoring, logs |
| `002_profile_scoring_improvements.sql` | Sampling metadata, conflict scoring, policy snapshot, issue sample rule code |
| `003_rule_catalog_lifecycle.sql` | Rule lifecycle, backend support, parameter schema, recommendation metadata |
| `004_rule_catalog_expansion.sql` | Fixture manifest cho rule catalog |
| `005_recommendation_scoring.sql` | Recommendation run/result, scoring components, review decision |
| `006_adaptive_profiling_budget.sql` | Profiling budget, skipped metrics, termination reason, deep-profiled columns |

Nhóm bảng chính:

- Dataset: `dataset`, `dataset_version`, `dataset_column`
- Rule governance: `rule_template`, `dataset_rule_binding`, `rule_fixture_manifest`
- Recommendation: `rule_recommendation_run`, `rule_recommendation_result`
- Profiling: `profiling_run`, `dataset_profile`, `column_profile`
- Validation: `validation_run`, `measurement_result`, `record_measurement_summary`, `rule_issue_sample`
- Scoring: `scoring_policy`, `score_run`, `rule_score_history`, `dimension_score_history`, `dataset_score_history`
- Observability: `pipeline_log`
- Migration bookkeeping: `schema_migration`

## 4. Runtime và CLI

`DqRuntime` hiện hỗ trợ các thao tác:

- `register_dataset()`
- `profile_dataset()`
- `bootstrap_catalog()`
- `catalog_inventory()`
- `recommend_rules()`
- `review_recommendation()`
- `save_recommended_rule_bindings()`
- `save_rule_bindings()`
- `run_validation()`
- `calculate_score()`
- `get_run_result()`
- `get_pipeline_logs()`

Các CLI command hiện có:

```powershell
python -m dq_core.cli register_dataset --csv <path> --dataset-id <id> --dataset-type <type>
python -m dq_core.cli profile_dataset --dataset-version-id <dataset_version_id>
python -m dq_core.cli bootstrap_catalog
python -m dq_core.cli catalog_inventory
python -m dq_core.cli recommend_rules --dataset-version-id <dataset_version_id>
python -m dq_core.cli review_recommendation --recommendation-id <id> --decision accepted
python -m dq_core.cli save_recommended_bindings --dataset-version-id <dataset_version_id> --accept-all-above-threshold
python -m dq_core.cli run_validation --dataset-version-id <dataset_version_id>
python -m dq_core.cli calculate_score --validation-run-id <validation_run_id>
python -m dq_core.cli get_run_result --score-run-id <score_run_id>
python -m dq_core.cli get_pipeline_logs
python -m dq_core.cli health_check
python -m dq_core.cli benchmark_recommendations
```

## 5. Profiling

Profiling dùng pandas để đọc CSV và tạo evidence cho recommendation/dashboard.

Khả năng hiện tại:

- Schema profile: missing columns, extra columns, type mismatch, nullable mismatch.
- Dataset profile: row count, column count, duplicate row count/ratio, freshness lag, volume deviation, duration.
- Column profile: null, blank, non-null, distinct, distinct including null, uniqueness ratio, inferred type, type confidence, top values, pattern frequency, length summary, numeric summary, miscast count/ratio/examples.
- Semantic detection: email, phone, identifier, amount, quantity, datetime, category và unknown.
- Sampling: `full_scan`, `random`, `auto`, `adaptive`, `mixed`.
- Wide dataset handling: dataset trên 200 cột chuyển sang sampled/lightweight strategy.
- Metadata sampling: scan mode, sample method, sample ratio, random seed, coverage estimate, profile confidence.
- Budget metadata: chunk size, memory budget, time budget, skipped metrics, termination reason, profile strategy.

Điểm đáng chú ý: trong `profiling.sampling`, có helper cho null-heavy và duplicate-aware sampling, nhưng luồng sample hiện tại chủ yếu trả mixed head/tail/random; các helper này mới thể hiện hướng mở rộng chứ chưa phải một chiến lược chọn mẫu riêng đầy đủ.

## 6. Rule Catalog và Recommendation

Rule catalog hiện được định nghĩa trong `rules_engine.catalog.default_rule_templates()`. Số rule template mặc định hiện khoảng 24, bao phủ các nhóm:

- Completeness: `NOT_NULL`, `NOT_BLANK_MANDATORY`, `MIN_COMPLETENESS_RATIO`, `CONDITIONAL_REQUIRED`
- Validity: `TYPE_VALIDITY`, `EMAIL_FORMAT`, `PHONE_TEN_DIGITS`, `ALLOWED_DOMAIN`, `NUMERIC_RANGE`, `STRING_LENGTH`, `DATE_FORMAT`, `BOOLEAN_DOMAIN`
- Timeliness: `DATETIME_NOT_FUTURE`
- Uniqueness: `IDENTIFIER_UNIQUE`, `COMPOSITE_UNIQUE`, `FULL_ROW_DUPLICATE`, `DUPLICATE_RATIO_LIMIT`
- Consistency: `START_BEFORE_END`, `CREATED_BEFORE_UPDATED`, `TOTAL_AMOUNT_CONSISTENCY`, `REQUIRED_COLUMNS`
- Accuracy Proxy: `AMOUNT_NON_NEGATIVE`, `POSITIVE_QUANTITY`, `PERCENTAGE_RANGE`

Recommendation hiện là deterministic, chưa dùng LLM. Điểm số recommendation dựa trên:

- Name match
- Type match
- Semantic match
- Profile match
- Role match
- Catalog priority

Recommendation result có thêm:

- `candidate_score`
- `score_components`
- `reason_json`
- `rank`
- `score_margin`
- `ambiguity_status`
- `decision`: suggested, accepted, rejected, edited
- `warnings`
- `suggested_parameters`

Hệ thống đã có `review_recommendation()` và `save_recommended_rule_bindings()` có thể chỉ lưu các recommendation đã accepted hoặc tự accept theo threshold.

## 7. Validation

Validation hỗ trợ hai backend:

- Great Expectations cho các operator được support như regex, domain, range, length, type, uniqueness, not future.
- Python evaluator cho custom/business/cross-field/dataset-level rules.

Kết quả validation được chuẩn hóa thành canonical contract:

- `MeasurementResult`
- `RecordMeasurementSummary`
- `ValidationIssueSample`
- `CanonicalValidationResult`

Canonical measurement lưu:

- Measurement status: measured, not_measured, skipped, not_applicable...
- Observed value, expected spec, failure breakdown.
- Backend và validation scope.
- Reason khi measurement không đo được.
- Record-level count: passed, failed, missing, not applicable, records in scope.
- Issue sample: record key, target column, actual value, expected condition, issue type, rule code.

Thiết kế này giúp thay đổi backend validation mà không làm vỡ scoring.

## 8. Scoring V2

Scoring V2 nằm trong `scoring/v2.py`, formula revision hiện là `scoring_v2_coverage_conflict_snapshot`.

Khả năng hiện tại:

- Rule score theo pass ratio: `passed_count / records_in_scope * 100`.
- Không đưa `not_applicable` vào denominator.
- `not_measured` giữ score `None`, không ép về 0.
- Hỗ trợ `freshness_decay` và `gate_only`.
- Severity weight và criticality weight.
- Conflict group để tránh double-count các rule cùng ý nghĩa.
- Chỉ primary scoring rule được tính khi có conflict.
- Dimension score là weighted average của các rule measured/scoring-enabled.
- Dataset score tính theo measured dimensions và normalized dimension weights.
- Measurement coverage: `measured_dimension_count / total_dimension_count`.
- Score status: `final`, `provisional`, `insufficient_coverage`.
- Quality gate: pass, warning, fail.
- Hard gate failure có thể làm dataset fail dù score tổng cao.
- Policy snapshot và formula revision được persist vào score history.

Các trạng thái coverage:

| Coverage | Score status |
| --- | --- |
| `>= 0.67` | `final` |
| `>= 0.33` | `provisional` |
| `< 0.33` | `insufficient_coverage` |

## 9. Dashboard

Dashboard là Streamlit app tại `dashboard/app.py`.

Các phần đã có:

- Dashboard overview: số dataset, average DQ score, failing gates.
- Dataset detail: score, gate status, coverage, rule count, failed rules.
- Dimension breakdown.
- Rule breakdown.
- Recommendations.
- Profiling Evidence.
- Issue Samples.
- Onboard CSV dataset.
- System Health.
- Pipeline Logs.

Lưu ý hiện trạng: code có `_render_catalog()` và tab label `Catalog`, nhưng trong `main()` tab Catalog chưa được gọi; function catalog inventory hiện chỉ có thể dùng qua CLI hoặc cần wiring thêm trong dashboard.

## 10. System Health

`dq_core.health.get_system_health()` kiểm tra:

- PostgreSQL configured/reachable.
- Database và host đã mask, không lộ full DSN/password.
- Schema/migration table và latest migration.
- Rule catalog count.
- Runtime storage path/writable.
- Local LLM status.

Health check phù hợp để chạy trước demo hoặc trước khi vận hành pipeline:

```powershell
python -m dq_core.cli health_check
```

## 11. Cách chạy local

Cài dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Khởi động PostgreSQL:

```powershell
docker compose up -d postgres
```

Cấu hình database URL:

```powershell
$env:DQ_DATABASE_URL='postgresql://dq:dq@localhost:5432/dq_scoring'
```

Chạy migration:

```powershell
.\.venv\Scripts\python.exe -m persistence.db migrate
```

Chạy dashboard:

```powershell
.\.venv\Scripts\streamlit.exe run dashboard\app.py
```

Chạy test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 12. Kiểm thử hiện có

Repo hiện có khoảng 30 test method trong thư mục `tests`, bao phủ:

- Runtime slice không dùng legacy store.
- System health và masking connection.
- Profiling pipeline, sampling, wide dataset.
- Rule catalog lifecycle, recommendation scoring, benchmark metrics.
- GX runtime/adapters.
- Canonical measurement.
- Scoring V2 coverage/conflict/not-measured behavior.
- Dashboard data transform.
- PostgreSQL integration round trip cho migration, issue samples và score metadata.
- Cleanup guardrails tránh quay lại runtime legacy.

Báo cáo này chỉ đọc source và không chạy lại toàn bộ test suite.

## 13. Ưu điểm hiện tại

- Kiến trúc tách lớp rõ: runtime, persistence, profiling, validation, scoring, dashboard.
- PostgreSQL lưu được lịch sử dataset, profile, validation, score và log.
- Canonical measurement giảm coupling giữa validation backend và scoring.
- Scoring V2 có khả năng giải thích: contribution, weights, coverage, conflict, policy snapshot.
- Recommendation có score components, ambiguity và review decision.
- Dashboard đã có visibility cho issue samples và profiling evidence.
- Health check không lộ secret connection string.
- Có test coverage tương đối tốt cho các contract lõi.

## 14. Hạn chế và rủi ro

- Data source chính vẫn là CSV; chưa có database/object storage/API/streaming ingestion.
- Pipeline dashboard onboarding chạy đồng bộ, có thể block UI với dataset lớn.
- Dashboard chưa có auth, RBAC, multi-tenant hoặc audit workflow.
- Catalog tab trong dashboard chưa được render dù function đã tồn tại.
- Rule catalog đã mở rộng nhưng vẫn cần thêm rule domain-specific, approval workflow và lifecycle governance.
- Recommendation deterministic, chưa có LLM-assisted review hoặc semantic reranking.
- Issue samples là sample phục vụ debug/audit, không phải full error table.
- Issue samples/top values có thể chứa dữ liệu nhạy cảm; cần masking policy nếu dùng dữ liệu thật.
- `data/uploads` là runtime output, không nên commit dữ liệu upload thật.
- PostgreSQL integration phụ thuộc Docker/PostgreSQL local và `DQ_DATABASE_URL`.
- Chưa có API service, scheduler/job queue, retry policy hay artifact storage production.

## 15. Định hướng cải thiện đề xuất

Ưu tiên ngắn hạn:

- Wire `_render_catalog()` vào tab Catalog của dashboard.
- Thêm masking policy cho issue samples, top values và profiling evidence.
- Chuẩn hóa seed/bootstrap scoring policy mặc định cho dataset type mới.
- Tối ưu dashboard query thay vì load toàn bộ bảng qua `list_dashboard_rows()`.
- Chạy và ghi nhận kết quả regression sau mỗi migration.

Ưu tiên trung hạn:

- Thêm API service cho register/profile/recommend/validate/score.
- Thêm scheduler/job queue cho pipeline bất đồng bộ.
- Mở rộng Rule Catalog theo domain và thêm approval workflow.
- Thêm lifecycle/versioning cho rule template, binding và scoring policy.
- Mở rộng ingestion ngoài CSV.

Ưu tiên dài hạn:

- RBAC, audit log, multi-tenant.
- Alerting, trend analysis và SLA monitoring.
- Artifact storage cho full issue/error detail.
- LLM-assisted rule review sau khi deterministic baseline ổn định.

## 16. Kết luận

DQ Scoring hiện đã có nền runtime V2 tương đối rõ ràng: PostgreSQL là source of truth, CLI/dashboard dùng chung runtime, profiling có evidence và sampling metadata, validation chuẩn hóa qua canonical measurement, scoring có coverage/conflict/policy snapshot, và dashboard hiển thị score detail, issue samples, profiling evidence, health và logs.

Trạng thái hiện tại phù hợp cho local demo và phát triển tiếp. Để tiến tới production, các khoảng trống quan trọng nhất là orchestration bất đồng bộ, API/service layer, bảo mật dashboard, governance workflow, data source ngoài CSV, masking PII và tối ưu truy vấn dashboard.

# KẾ HOẠCH THỰC HIỆN CẢI THIỆN HỆ THỐNG DQ SCORING

## 1. Mục tiêu

Kế hoạch tập trung vào năm nhóm cải thiện:

1. Mở rộng Rule Catalog.
2. Nâng cấp deterministic recommendation.
3. Cải thiện Adaptive Profiling.
4. Chuyển pipeline sang vận hành bất đồng bộ.
5. Bổ sung Security và Governance.

Thứ tự triển khai được xây dựng theo nguyên tắc:

```text
Rule Catalog rõ ràng
→ Recommendation có baseline
→ Profiling cung cấp evidence tốt hơn
→ Pipeline chạy bất đồng bộ
→ Governance và production hardening
```

Một số yêu cầu bảo mật nền tảng như masking, audit event và secret handling phải được triển khai xuyên suốt, không chờ đến giai đoạn cuối.

---

# 2. Trạng thái xuất phát

Hệ thống hiện tại đã có:

- PostgreSQL runtime và migration runner.
- Dataset onboarding.
- Profiling có scan metadata, sampling, evidence và miscast.
- Rule Catalog baseline.
- Deterministic recommendation cơ bản.
- GX và Python evaluator.
- Canonical Measurement.
- Scoring có coverage, conflict handling, policy snapshot và Quality Gate.
- Issue Samples.
- Dashboard Streamlit và System Health.
- Regression test cùng PostgreSQL integration test.

Các điểm còn thiếu chính:

- Rule Catalog còn nhỏ.
- Applicability và exclusions còn đơn giản.
- Chưa có candidate score và ambiguity margin đầy đủ.
- Profiling chưa chunk-based và chưa selective deep profile hoàn chỉnh.
- Pipeline còn đồng bộ.
- Chưa có API, job queue, RBAC, approval workflow và retention policy đầy đủ.

---

# 3. Nguyên tắc triển khai

- Không thay đổi toàn bộ pipeline trong một lần.
- Mỗi phase phải giữ pipeline end-to-end chạy được.
- Mọi schema change phải qua migration mới.
- Không sửa migration đã chạy.
- Rule mới chỉ được active khi có fixture và test.
- Recommendation chỉ tạo suggestion; chưa auto-bind mặc định.
- Profiling evidence phải chỉ rõ `full`, `sampled` hoặc `approximate`.
- API và worker phải tái sử dụng application service hiện có.
- Dashboard chỉ polling trạng thái, không chạy job nặng trong UI thread.
- Policy và rule phải có version/lifecycle rõ ràng.

---

# 4. Kiến trúc mục tiêu

```text
Client / Dashboard
→ API Service
→ Job Queue
→ Worker
→ Application Services
   ├── Profiling Service
   ├── Recommendation Service
   ├── Validation Service
   └── Scoring Service
→ PostgreSQL
→ Artifact Storage
```

Luồng xử lý:

```text
Upload/Register Dataset
→ Create Pipeline Job
→ Profiling
→ Rule Recommendation
→ User Review
→ Rule Binding
→ Validation
→ Scoring
→ Quality Gate
→ Dashboard Result
```

Thành phần ngang:

```text
Authentication
Authorization
Audit Log
Masking
Retention
Policy Lifecycle
Rule Approval
```

---

# 5. Roadmap tổng thể

| Phase | Nội dung | Phụ thuộc |
|---|---|---|
| 0 | Baseline, inventory và guardrails | Không |
| 1 | Chuẩn hóa Rule Template và Rule Catalog schema | Phase 0 |
| 2 | Mở rộng rule theo family và backend coverage | Phase 1 |
| 3 | Deterministic candidate scoring và reason | Phase 1–2 |
| 4 | Ambiguity, review workflow và benchmark | Phase 3 |
| 5 | Chunked/adaptive profiling | Phase 0 |
| 6 | Selective deep profile và cross-column shortlist | Phase 5 |
| 7 | API service và job model | Phase 3, 5 |
| 8 | Queue, worker, persistence và dashboard polling | Phase 7 |
| 9 | Security foundation: masking, RBAC, audit | Xuyên suốt, chốt ở Phase 9 |
| 10 | Rule/policy lifecycle và retention | Phase 8–9 |
| 11 | Performance, resilience và production readiness | Tất cả |

Có thể triển khai song song:

```text
Track A: Rule Catalog + Recommendation
Track B: Adaptive Profiling
Track C: API/Async Foundation
Track D: Security/Governance
```

---

# 6. Phase 0 — Baseline và Guardrails

## 6.1. Công việc

- Tạo Git tag.
- Chạy toàn bộ test.
- Lưu baseline profiling, recommendation, validation, issue samples, scoring và Quality Gate.
- Tạo fixture theo domain: customer, sales, education, employee, logistics.
- Tạo mutation generator.
- Kiểm kê rule hiện tại.
- Lập backend coverage matrix.

## 6.2. Deliverable

```text
tests/fixtures/
tests/generators/
docs/rule_catalog_inventory.md
docs/backend_coverage_matrix.md
```

## 6.3. Nghiệm thu

- Test hiện tại pass.
- Có golden output.
- Có danh sách rule và backend hỗ trợ.
- Có ít nhất 5 dataset domain và mutation cơ bản.

---

# 7. Ưu tiên 1 — Mở rộng Rule Catalog

## 7.1. Chuẩn hóa Rule Template

```yaml
rule_code: TOTAL_AMOUNT_CONSISTENCY
rule_name: Total amount must equal quantity multiplied by unit price

family: consistency
dimension: Consistency
category: business

target_scope: multi_column
evaluation_scope: record
operator: arithmetic_comparison

required_columns:
  - quantity
  - price_per_unit
  - total_amount

backend_support:
  - python

applicability:
  required_semantic_types:
    quantity:
      - quantity
    price_per_unit:
      - monetary_amount
    total_amount:
      - monetary_amount

exclusions:
  dataset_types:
    - aggregated_report

parameters_schema:
  type: object
  properties:
    tolerance:
      type: number
      minimum: 0
  required:
    - tolerance

defaults:
  tolerance: 0.01
  null_policy: not_applicable
  severity: high
  score_enabled: true
  gate_enabled: false

recommendation:
  priority: 90
  requires_user_review: true
  auto_bind_allowed: false

conflict_group: total_amount_consistency

lifecycle:
  status: draft
  revision: 1
```

## 7.2. Trường cần bổ sung

- `family`.
- `category`.
- `target_scope`.
- `evaluation_scope`.
- `operator`.
- `required_columns`.
- `backend_support`.
- `applicability`.
- `exclusions`.
- `parameters_schema`.
- `defaults`.
- `recommendation`.
- `conflict_group`.
- `lifecycle.status`.
- `lifecycle.revision`.

## 7.3. Rule families cần bổ sung

### Completeness

- `NOT_NULL`
- `NOT_BLANK`
- `MIN_COMPLETENESS_RATIO`
- `CONDITIONAL_REQUIRED`

### Validity

- `TYPE_VALIDITY`
- `REGEX_FORMAT`
- `ALLOWED_DOMAIN`
- `NUMERIC_RANGE`
- `STRING_LENGTH`
- `DATE_FORMAT`
- `NOT_FUTURE`
- `BOOLEAN_DOMAIN`

### Uniqueness

- `COLUMN_UNIQUE`
- `COMPOSITE_UNIQUE`
- `FULL_ROW_DUPLICATE`
- `DUPLICATE_RATIO_LIMIT`

### Consistency

- `START_BEFORE_END`
- `CREATED_BEFORE_UPDATED`
- `CROSS_FIELD_COMPARISON`
- `TOTAL_AMOUNT_CONSISTENCY`
- `CONDITIONAL_VALUE`

### Timeliness

- `FRESHNESS`
- `MAX_DATA_DELAY`
- `EVENT_BEFORE_PROCESSING`

### Referential Integrity

- `FOREIGN_KEY_EXISTS`
- `REFERENCE_DOMAIN_EXISTS`
- `PARENT_RECORD_EXISTS`

### Schema/Technical

- `REQUIRED_COLUMNS`
- `NO_UNEXPECTED_COLUMNS`
- `EXPECTED_DTYPE`
- `EXPECTED_NULLABILITY`
- `SCHEMA_DRIFT`

### Plausibility

- `AGE_PLAUSIBILITY`
- `NON_NEGATIVE_AMOUNT`
- `POSITIVE_QUANTITY`
- `PERCENTAGE_RANGE`
- `LATITUDE_RANGE`
- `LONGITUDE_RANGE`

## 7.4. Applicability

Applicability engine kiểm tra:

```text
target scope
dataset type
inferred type
semantic type
field role
profile evidence
required columns
backend availability
```

Output:

```json
{
  "applicable": true,
  "matched_conditions": [
    "semantic_type=identifier",
    "inferred_type=integer_like_string"
  ],
  "failed_conditions": [],
  "warnings": [
    "uniqueness metric is sampled"
  ]
}
```

## 7.5. Exclusions

Ví dụ:

```yaml
exclusions:
  column_name_patterns:
    - category_id
    - type_id
  semantic_types:
    - category
  dataset_types:
    - summary
```

Exclusion chạy trước candidate scoring.

## 7.6. Parameter Schema

Parameter phải validate khi:

```text
Tạo template
→ tạo recommendation
→ lưu binding
→ chạy validation
```

## 7.7. Conflict Group

Ví dụ:

```text
NOT_NULL
NOT_BLANK
MANDATORY_COMPLETENESS
```

Policy:

- Chỉ một primary scoring rule.
- Rule khác có thể validation-only.
- Dashboard hiển thị rule bị suppress và lý do.

## 7.8. Positive/Negative Fixtures

Mỗi rule cần:

```text
positive fixture
negative fixture
edge-case fixture
expected canonical measurement
expected score behavior
```

## 7.9. Backend Coverage

| Rule | GX | Python | Status |
|---|---:|---:|---|
| NOT_NULL | Yes | Optional | Ready |
| REGEX_FORMAT | Yes | Optional | Ready |
| COMPOSITE_UNIQUE | No | Yes | Ready |
| TOTAL_AMOUNT_CONSISTENCY | No | Yes | Draft |
| FOREIGN_KEY_EXISTS | No | Yes | Draft |

Chỉ activate rule khi có backend, fixture, canonical test và parameter test.

## 7.10. Migration

```text
003_rule_catalog_expansion.sql
```

Bổ sung family, applicability, exclusions, parameter schema, recommendation metadata, lifecycle và revision.

## 7.11. Nghiệm thu

- Catalog có tối thiểu 25–40 rule.
- Mỗi rule có family.
- Applicability và exclusions hoạt động.
- Parameter schema validate được.
- Conflict group hoạt động.
- Mỗi active rule có fixture.
- Backend coverage matrix đầy đủ.
- Bootstrap idempotent.

---

# 8. Ưu tiên 2 — Nâng Deterministic Recommendation

## 8.1. Candidate Pipeline

```text
Column Profile
→ Semantic Context
→ Rule Catalog Filter
→ Applicability Check
→ Exclusion Check
→ Candidate Scoring
→ Conflict Pre-check
→ Recommendation Result
```

## 8.2. Candidate Score

```text
candidate_score =
0.20 × name_match
+ 0.20 × type_match
+ 0.25 × semantic_match
+ 0.20 × profile_match
+ 0.10 × role_match
+ 0.05 × catalog_priority
```

Không dùng score như xác suất đúng.

Lưu component breakdown.

## 8.3. Reason

Reason được tạo từ evidence:

```text
Recommended because:
- semantic type is identifier;
- inferred type is integer-like string;
- uniqueness ratio is 0.998;
- column is marked business key.
```

## 8.4. Ambiguity Margin

Lưu:

```text
top_score
second_score
score_margin
candidate_count
ambiguity_status
```

Policy baseline:

```text
score_margin >= 0.20 → clear
0.10 <= score_margin < 0.20 → moderate
score_margin < 0.10 → ambiguous
```

Đánh ambiguous thêm khi:

- semantic candidates gần nhau;
- metric sampled;
- field critical chưa xác nhận;
- rule cần business context;
- conflict chưa giải quyết.

## 8.5. Review Workflow

Trạng thái:

```text
suggested
accepted
rejected
edited
expired
superseded
```

Action:

- Accept.
- Reject.
- Edit parameters.
- Change semantic type.
- Assign field role.
- Mark not applicable.
- Add comment.

Luồng:

```text
Recommendation
→ Review
→ Accepted Recommendation
→ Dataset Rule Binding
```

## 8.6. Persistence

### `rule_recommendation_run`

```text
recommendation_run_id
dataset_version_id
profile_fingerprint
catalog_revision
status
started_at
completed_at
```

### `rule_recommendation_result`

```text
recommendation_id
recommendation_run_id
column_id
rule_template_id
candidate_score
score_components_jsonb
reason_jsonb
rank
score_margin
ambiguity_status
decision
reviewed_by
reviewed_at
review_comment
suggested_parameters_jsonb
```

## 8.7. Benchmark

Ground truth:

```text
expected semantic type
expected rule codes
forbidden rule codes
expected parameters
requires_review
```

Metrics:

- Precision@1.
- Precision@3.
- Recall@3.
- Mean Reciprocal Rank.
- Wrong recommendation rate.
- Review acceptance rate.
- Ambiguous-column detection recall.

Tách development, calibration và holdout set.

## 8.8. Nghiệm thu

- Candidate score có breakdown.
- Recommendation có reason.
- Có ambiguity margin.
- Có review workflow.
- Recommendation chưa review không tự bind.
- Có Precision@3/Recall@3 report.
- Có holdout evaluation.
- Có error analysis.

---

# 9. Ưu tiên 3 — Adaptive Profiling sâu hơn

## 9.1. Chunked CSV

```text
CSV
→ read_csv(chunksize=N)
→ incremental dataset metrics
→ incremental column aggregates
→ sample reservoir
→ finalize profile
```

Metric incremental:

- row count;
- null/blank count;
- numeric aggregates;
- min/max;
- approximate distinct;
- pattern counters;
- sample reservoir.

Cấu hình:

```env
DQ_PROFILE_CHUNK_SIZE=50000
DQ_PROFILE_MEMORY_BUDGET_MB=512
DQ_PROFILE_TIME_BUDGET_SEC=300
```

## 9.2. Resource Budget

Budget quyết định:

```text
full scan
chunked full metric
sampled deep metric
skip optional metric
```

Lưu:

```text
budget_config
budget_used
skipped_metrics
termination_reason
```

## 9.3. Null-heavy Sampling

Tính `row_null_score` và giữ top-N dòng có nhiều null/blank.

## 9.4. Duplicate-aware Sampling

Dùng row hash, candidate key hash và approximate duplicate counter để lấy mẫu hash lặp.

## 9.5. Selective Deep Profile

Pass 1 cho mọi cột:

```text
name
dtype
null
blank
distinct approximation
parse ratio
basic length
```

Pass 2 chỉ cho cột:

- critical;
- ambiguous;
- miscast cao;
- nhiều candidate rule;
- semantic confidence thấp;
- cross-field potential cao.

## 9.6. Cross-column Shortlist

Không all-pairs.

Shortlist theo:

```text
name tokens
type compatibility
semantic group
field role
correlation hint
```

Relation families:

- start/end;
- created/updated;
- event/processed;
- quantity/price/total;
- debit/credit/balance;
- identifier/reference;
- composite key.

## 9.7. Migration

```text
005_adaptive_profiling_budget.sql
```

Bổ sung chunk mode, resource budget, skipped metrics, deep profile status, column priority và relation candidates.

## 9.8. Test

- Full/chunk tương đương trong tolerance.
- Memory không vượt budget.
- Sampling tái lập.
- Null-heavy sample có dòng lỗi.
- Duplicate-aware sample phát hiện duplicate.
- Wide dataset không deep profile toàn bộ.
- Cross-column shortlist không all-pairs.

## 9.9. Nghiệm thu

- Dataset lớn không bắt buộc load toàn bộ RAM.
- Có resource budget.
- Có null-heavy/duplicate-aware sample.
- Có selective deep profile.
- Có cross-column shortlist.
- Có benchmark thời gian và memory.

---

# 10. Ưu tiên 4 — Vận hành Bất đồng bộ

## 10.1. API Service

Đề xuất FastAPI.

Endpoint:

```text
POST /datasets
POST /datasets/{id}/profile
POST /datasets/{id}/recommend
POST /datasets/{id}/validate
POST /validation-runs/{id}/score
POST /pipelines
GET  /jobs/{id}
GET  /datasets/{id}/results
GET  /health
```

API chỉ tạo job, không chạy tác vụ nặng trực tiếp.

## 10.2. Job Model

Bảng `pipeline_job`:

```text
job_id
job_type
dataset_version_id
status
priority
payload_jsonb
progress
current_step
retry_count
max_retries
created_by
created_at
started_at
completed_at
error_code
error_message
heartbeat_at
```

Status:

```text
queued
running
succeeded
failed
cancelled
retrying
```

## 10.3. Queue và Worker

Lựa chọn:

- PostgreSQL job table + worker polling cho giai đoạn đầu.
- Redis + Celery/Dramatiq khi tải tăng.

Worker gọi application service, không gọi Streamlit code.

## 10.4. Status Persistence

Pipeline steps:

```text
REGISTER
PROFILE
RECOMMEND
WAIT_REVIEW
BIND
VALIDATE
SCORE
COMPLETE
```

## 10.5. Retry và Idempotency

Mỗi job có:

- idempotency key;
- retry policy;
- timeout;
- heartbeat;
- stale-job recovery.

## 10.6. Dashboard Polling

```text
submit job
→ nhận job_id
→ polling GET /jobs/{job_id}
→ hiển thị progress
→ load result khi complete
```

## 10.7. Migration

```text
006_async_job_runtime.sql
```

Bổ sung `pipeline_job`, `job_event`, `job_attempt` và worker heartbeat khi cần.

## 10.8. Nghiệm thu

- Dashboard không block.
- Job status persist.
- Worker restart không mất job.
- Retry hoạt động.
- Duplicate submit không chạy trùng ngoài ý muốn.
- Có cancel cơ bản.
- Có progress theo step.
- API/worker integration test pass.

---

# 11. Ưu tiên 5 — Security và Governance

## 11.1. Masking

Áp dụng cho:

- issue samples;
- top values;
- miscast examples;
- logs;
- prompt context tương lai.

Ví dụ:

```text
email: a***@domain.com
phone: ******1234
identifier: hash hoặc partial mask
free text: truncate + redact
```

Không persist raw value mặc định.

## 11.2. RBAC

Role:

- Admin.
- Data Steward.
- Data Engineer.
- Analyst.
- Viewer.

Quyền cần tách cho upload, review rule, approve rule, sửa policy, xem issue samples và truy cập dữ liệu nhạy cảm.

## 11.3. Audit Log

Ghi:

```text
actor
action
resource_type
resource_id
before
after
reason
timestamp
request_id
```

Action quan trọng:

- rule accept/reject;
- binding changed;
- policy changed;
- dataset upload/delete;
- job cancel/retry;
- sensitive sample access;
- role changed.

## 11.4. Rule Approval

Lifecycle:

```text
draft
→ in_review
→ approved
→ active
→ deprecated
→ retired
```

Sửa active rule phải tạo revision mới.

## 11.5. Policy Version Lifecycle

```text
draft
→ approved
→ active
→ superseded
→ retired
```

Mỗi score run lưu policy revision/snapshot.

## 11.6. Retention

Áp dụng cho:

- raw upload;
- issue samples;
- profile evidence;
- validation detail;
- score history;
- logs;
- job events;
- audit logs.

Ví dụ:

```text
raw dataset: 30–90 ngày
issue samples: 90 ngày
pipeline logs: 180 ngày
score history: dài hạn
audit logs: theo compliance
```

Retention job có dry-run, audit và legal hold.

## 11.7. Nghiệm thu

- PII được mask trước persist/display.
- Có RBAC ở API.
- Có audit log.
- Rule có approval lifecycle.
- Policy có revision lifecycle.
- Có retention cleanup job.
- Security tests pass.
- Không log secret.

---

# 12. Test Strategy Tổng thể

## Unit

- Rule schema.
- Applicability/exclusions.
- Parameter validation.
- Conflict resolution.
- Candidate score/reason/ambiguity.
- Chunk aggregator.
- Sampling.
- Masking.
- RBAC.
- Retention.

## Integration

- Rule bootstrap.
- Migration.
- Recommendation persistence.
- Review to binding.
- Chunk profiling to PostgreSQL.
- API to queue.
- Worker execution/retry.
- Audit persistence.
- Policy/rule lifecycle.

## End-to-end

```text
Upload
→ Async Job
→ Profiling
→ Recommendation
→ Review
→ Binding
→ Validation
→ Scoring
→ Dashboard
```

## Performance

- 1M+ rows.
- 300–1000 columns.
- Concurrent jobs.
- Dashboard query latency.
- Worker throughput.

## Security

- Unauthorized API calls.
- Role escalation.
- PII leakage.
- Secret leakage.
- CSV injection.
- Audit tampering attempt.
- Retention authorization.

---

# 13. Migration Plan

```text
001_core.sql
002_profile_scoring_improvements.sql
003_rule_catalog_expansion.sql
004_recommendation_review.sql
005_adaptive_profiling_budget.sql
006_async_job_runtime.sql
007_security_governance.sql
008_retention_and_audit_indexes.sql
```

Không sửa `001` và `002` nếu đã áp dụng.

Mỗi migration cần:

- transaction;
- backward-compatible defaults;
- index;
- data backfill khi cần;
- migration test;
- rollback plan ở mức release.

---

# 14. Cấu trúc Source Đề xuất

```text
dq_scoring/
├── api/
├── application/
├── jobs/
├── profiling/
├── rules_engine/
├── security/
├── governance/
├── persistence/migrations/
└── tests/
    ├── unit/
    ├── integration/
    ├── e2e/
    ├── performance/
    ├── security/
    ├── fixtures/
    └── generators/
```

---

# 15. Kế hoạch theo Sprint gợi ý

## Sprint 1

- Baseline.
- Rule inventory.
- Rule Template schema.
- Migration `003`.

## Sprint 2

- Applicability.
- Exclusions.
- Parameter schema.
- Conflict group.

## Sprint 3

- Bổ sung 15–20 rule.
- Positive/negative fixtures.
- Backend coverage.

## Sprint 4

- Candidate score.
- Reason.
- Ambiguity margin.
- Recommendation persistence.

## Sprint 5

- Review UI/workflow.
- Precision@3/Recall@3 benchmark.
- Error analysis.

## Sprint 6

- Chunked CSV.
- Resource budget.
- Incremental metrics.

## Sprint 7

- Null-heavy/duplicate-aware sampling.
- Selective deep profile.
- Cross-column shortlist.

## Sprint 8

- FastAPI.
- Job model.
- API integration.

## Sprint 9

- Worker.
- Queue.
- Retry/idempotency.
- Dashboard polling.

## Sprint 10

- Masking.
- RBAC.
- Audit log.

## Sprint 11

- Rule approval.
- Policy lifecycle.
- Retention.

## Sprint 12

- Performance test.
- Security test.
- Migration hardening.
- Documentation.
- Release readiness.

---

# 16. Definition of Done

Một phase chỉ hoàn thành khi:

- Code đã merge.
- Migration đã test.
- Unit/integration test pass.
- Không phá pipeline hiện tại.
- Có tài liệu.
- Có monitoring/log cần thiết.
- Acceptance criteria được kiểm chứng.
- Security review phù hợp với phạm vi phase.

---

# 17. Kết quả kỳ vọng

```text
Rule Catalog
→ đủ rộng, có lifecycle và backend coverage

Recommendation
→ có score, reason, ambiguity và benchmark

Profiling
→ xử lý dataset lớn/rộng theo budget

Runtime
→ API + queue + worker, không block dashboard

Security/Governance
→ masking, RBAC, audit, approval, versioning và retention
```

Hệ thống sẽ chuyển từ proof of concept có cấu trúc sang nền tảng DQ nội bộ có khả năng vận hành ổn định, mở rộng và kiểm soát tốt hơn.

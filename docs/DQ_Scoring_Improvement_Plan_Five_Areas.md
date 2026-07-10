# KẾ HOẠCH CẢI THIỆN HỆ THỐNG DQ SCORING

## 1. Mục tiêu

Kế hoạch tập trung vào năm nhóm cải thiện:

1. Rule Catalog.
2. Deterministic Recommendation.
3. Profiling dataset lớn/rộng.
4. Dashboard.
5. Production Readiness.

Thứ tự triển khai:

```text
Baseline và xác minh
→ Rule Catalog
→ Deterministic Recommendation
→ Profiling dataset lớn/rộng
→ Dashboard
→ Production Readiness
```

Nguyên tắc:

- Không mở rộng hạ tầng production trước khi core DQ được kiểm chứng.
- Giữ `DqRuntime` đồng bộ trong giai đoạn hiện tại.
- PostgreSQL tiếp tục là source of truth.
- Mỗi phase phải có test, benchmark và tiêu chí nghiệm thu.
- Recommendation không auto-bind mặc định nếu chưa qua benchmark.
- Rule active phải có backend, fixture và lifecycle rõ ràng.
- Profiling phải tôn trọng memory/time budget.
- Worker/API chỉ triển khai khi có nhu cầu vận hành thực tế.

---

# 2. Trạng thái xuất phát

Hệ thống hiện đã có:

- PostgreSQL runtime và migration runner.
- CLI và dashboard dùng chung `DqRuntime`.
- Khoảng 24 Rule Template.
- Rule lifecycle, backend support và fixture manifest.
- Recommendation có candidate score, component breakdown, reason, score margin và review decision.
- Profiling có sampling metadata, budget metadata và wide-dataset threshold.
- GX/Python validation, Canonical Measurement và issue samples.
- Scoring V2 có coverage, conflict handling, policy snapshot và Quality Gate.
- Dashboard có overview, detail, recommendations, profiling evidence, health và logs.

Khoảng trống chính:

- Chưa xác minh đầy đủ backend coverage của toàn bộ rule active.
- Chưa có benchmark recommendation được báo cáo rõ.
- Chunked CSV và resource budget chưa được chứng minh end-to-end.
- Null-heavy/duplicate-aware sampling chưa được nối đầy đủ vào runtime.
- Catalog tab chưa được render hoàn chỉnh.
- Dashboard query chưa tối ưu cho lịch sử lớn.
- Chưa có masking đầy đủ cho issue samples/top values.
- Production hardening còn thiếu CI gates, audit, backup/restore và performance gates.

---

# 3. Phase 0 — Baseline và xác minh

## Mục tiêu

Xác minh hệ thống hiện tại trước khi tiếp tục phát triển.

## Công việc

- Chạy toàn bộ test suite.
- Chạy PostgreSQL integration test.
- Chạy migration từ database rỗng.
- Kiểm tra migration idempotency.
- Xuất Rule Catalog inventory.
- Xuất backend coverage matrix.
- Chạy recommendation benchmark hiện có.
- Đo profiling duration và peak memory.
- Ghi nhận dashboard query latency.

## Dataset chuẩn

- Customer.
- Sales.
- Education.
- Employee.
- Logistics.
- Dataset 1 triệu dòng.
- Dataset 300 và 500 cột.
- Dataset null-heavy, duplicate-heavy và mixed type.

## Deliverable

```text
docs/current_system_baseline.md
docs/rule_backend_coverage.md
docs/recommendation_baseline.md
docs/profiling_performance_baseline.md
tests/fixtures/
tests/golden/
```

## Tiêu chí nghiệm thu

- Full test suite pass.
- Migration chạy được từ database rỗng.
- Có danh sách rule active/ready/draft.
- Có recommendation baseline.
- Có memory/time baseline cho profiling.
- Có danh sách query dashboard chậm.

---

# 4. Phase 1 — Rule Catalog

## Mục tiêu

```text
Rule Catalog
→ đủ rộng
→ có lifecycle và revision
→ có backend coverage
→ có fixture
→ có applicability/exclusions
→ có conflict handling
```

## Rule Template bắt buộc

- `rule_code`, `rule_name`.
- `family`, `dimension`, `category`.
- `target_scope`, `evaluation_scope`, `operator`.
- `required_columns`.
- `backend_support`.
- `applicability`, `exclusions`.
- `parameters_schema`, `defaults`.
- `recommendation`.
- `conflict_group`.
- `template_status`, `revision`.
- `description_for_recommendation`.

## Lifecycle

```text
draft
→ tested
→ active
→ deprecated
→ retired
```

### Điều kiện chuyển trạng thái

**draft → tested**

- Parameter schema hợp lệ.
- Có backend implementation.
- Có positive/negative fixture.
- Có canonical measurement test.

**tested → active**

- Applicability/exclusions test pass.
- Conflict test pass nếu có.
- Recommendation test pass.
- Backend coverage được xác nhận.
- Documentation đầy đủ.

**active → deprecated**

- Có rule thay thế hoặc semantics thay đổi.

**deprecated → retired**

- Không còn binding active và runtime dependency.

## Revision

Không sửa trực tiếp semantics của rule active:

```text
rule_code giữ nguyên
revision tăng
binding mới dùng revision mới
binding cũ giữ revision cũ
```

## Backend coverage

Mỗi active rule phải có:

- Ít nhất một backend GX hoặc Python.
- Backend test.
- Canonical mapping test.
- Issue sample test.
- Scoring behavior test.

## Applicability

Kiểm tra:

```text
dataset type
target scope
inferred type
semantic type
field role
profile evidence
required columns
backend availability
metric scope
```

Rule không applicable không được vào candidate list.

## Exclusions

Kiểm tra trước recommendation scoring và lưu lý do bị loại.

## Parameter schema

Validate tại:

```text
catalog bootstrap
→ recommendation
→ binding
→ execution planning
```

## Conflict group

- Một primary scoring rule.
- Rule khác có thể validation-only.
- Không double-count.
- Dashboard hiển thị rule bị suppress và lý do.

## Mở rộng rule

Mục tiêu ngắn hạn: **20–30 active rules ổn định**.

Ưu tiên các family:

- Completeness.
- Validity.
- Uniqueness.
- Consistency.
- Timeliness.
- Schema.
- Plausibility.

Referential integrity để sau nếu chưa có reference data source ổn định.

## Test

- Template schema.
- Lifecycle/revision.
- Applicability/exclusions.
- Parameter schema.
- Conflict group.
- Backend/canonical mapping.
- Fixture.
- Bootstrap idempotency.

## Tiêu chí nghiệm thu

- 20–30 active rules.
- 100% active rule có backend.
- 100% active rule có positive/negative fixture.
- Lifecycle/revision hoạt động.
- Parameter validation hoạt động.
- Conflict rules không double-count.
- Backend coverage matrix xuất tự động.

---

# 5. Phase 2 — Deterministic Recommendation

## Mục tiêu

```text
candidate score
+ component breakdown
+ reason
+ ambiguity
+ review
+ benchmark
```

## Pipeline

```text
Column Profile
→ Catalog Filter
→ Applicability
→ Exclusions
→ Candidate Scoring
→ Conflict Pre-check
→ Ranking
→ Recommendation Result
```

## Candidate score

Baseline:

```text
candidate_score =
0.20 × name_match
+ 0.20 × type_match
+ 0.25 × semantic_match
+ 0.20 × profile_match
+ 0.10 × role_match
+ 0.05 × catalog_priority
```

Score là ranking score, không phải xác suất.

## Reason

Reason sinh deterministic từ evidence, phải nêu:

- Evidence match.
- Evidence thiếu.
- Warning.
- Metric scope.
- Profile confidence.

## Ambiguity

Lưu:

```text
top_score
second_score
score_margin
candidate_count
ambiguity_status
```

Baseline:

```text
margin >= 0.20      → clear
0.10 <= margin < .20 → moderate
margin < 0.10       → ambiguous
```

Đánh ambiguous thêm khi:

- Nhiều semantic candidate gần nhau.
- Metric sampled/approximate.
- Critical field chưa xác nhận.
- Rule cần business context.
- Conflict chưa giải quyết.
- Catalog thiếu candidate phù hợp.

## Review workflow

Trạng thái:

```text
suggested
accepted
rejected
edited
```

Action:

- Accept.
- Reject.
- Edit parameter.
- Confirm semantic type.
- Assign field role.

Không auto-bind mặc định.

## Benchmark

Ground truth:

```text
expected semantic type
expected rule codes
forbidden rule codes
expected parameters
requires_review
```

Dataset split:

```text
development
calibration
holdout
```

Metrics:

- Precision@1.
- Precision@3.
- Recall@3.
- Mean Reciprocal Rank.
- Wrong recommendation rate.
- Ambiguous-column detection recall.
- Review acceptance rate.

Target thử nghiệm ban đầu:

```text
Precision@3 >= 0.80
Recall@3 >= 0.80
Wrong recommendation rate <= 0.10
Ambiguity recall >= 0.80
```

## Error analysis

Phân loại lỗi:

- Semantic detection sai.
- Applicability sai.
- Exclusion thiếu.
- Catalog thiếu rule.
- Profile evidence thiếu.
- Weight chưa phù hợp.
- Business context không đủ.
- Sampled evidence gây sai.

## Tiêu chí nghiệm thu

- Candidate có score và component breakdown.
- Reason dựa trên evidence.
- Ambiguity được persist.
- Review workflow hoạt động.
- Recommendation chưa review không tự bind.
- Có benchmark report và holdout result.
- Có error analysis và threshold calibration.

---

# 6. Phase 3 — Profiling dataset lớn/rộng

## Mục tiêu

Profiling xử lý được:

```text
dataset nhiều dòng
dataset nhiều cột
dataset vượt memory budget
dataset vượt time budget
```

mà không bắt buộc load toàn bộ file vào RAM.

## Chunked CSV

```text
CSV
→ read_csv(chunksize=N)
→ incremental metrics
→ sample reservoir
→ finalize profile
```

Metric incremental:

- Row/null/blank count.
- Min/max.
- Mean/variance.
- Parse ratio.
- Limited pattern counters.
- Sample reservoir.

Metric approximate/sample:

- Distinct.
- Quantile.
- Duplicate.
- Outlier.
- Detailed top values.

## Resource budget

```env
DQ_PROFILE_CHUNK_SIZE=50000
DQ_PROFILE_MEMORY_BUDGET_MB=512
DQ_PROFILE_TIME_BUDGET_SEC=300
DQ_PROFILE_MAX_DEEP_COLUMNS=100
DQ_PROFILE_WIDE_DATASET_THRESHOLD=200
```

Policy:

```text
estimated memory <= budget
→ full dataframe

estimated memory > budget
→ chunked scan

near time budget
→ skip optional deep metrics

column count > threshold
→ lightweight all + selective deep
```

Lưu metadata:

```text
scan_mode
chunk_size
memory_budget
time_budget
budget_used
skipped_metrics
termination_reason
profile_strategy
```

## Sampling

```text
random
+ head
+ tail
+ null-heavy
+ duplicate candidates
```

Null-heavy dùng row null/blank score.
Duplicate-aware dùng row hash và candidate-key hash.
Lưu random seed, sample size/ratio và method để tái lập.

## Wide Dataset Strategy

**Pass 1 — Lightweight toàn bộ cột**

- Name/dtype.
- Null/blank.
- Approximate distinct.
- Parse ratio.
- Basic length/pattern.

**Pass 2 — Selective Deep Profile**

Chỉ chạy cho cột:

- Business key/CDE/mandatory.
- Semantic ambiguous.
- Miscast cao.
- Nhiều rule candidate.
- Cross-field potential.

Deep metrics:

- Detailed top values/patterns.
- Quantiles/outliers.
- Masked examples.
- Relation evidence.

## Cross-column shortlist

Không chạy all-pairs.

Shortlist theo:

```text
name token
type compatibility
semantic group
field role
```

Relation ban đầu:

- start/end.
- created/updated.
- event/processed.
- quantity/price/total.
- debit/credit/balance.
- identifier/reference.

## Performance benchmark

Dataset:

- 1 triệu dòng.
- 300/500 cột.
- Null-heavy.
- Duplicate-heavy.
- High-cardinality identifier.
- Mixed type và long text.

Metrics:

- Peak memory.
- Duration.
- Rows/second.
- Columns/second.
- Deep-profiled column ratio.
- Sample coverage.
- Skipped metrics.
- Full/chunk difference.

## Tiêu chí nghiệm thu

- Dataset lớn không bắt buộc load toàn bộ vào RAM.
- Peak memory nằm trong budget cộng tolerance.
- Null-heavy/duplicate-aware sampling chạy trong runtime.
- Wide dataset không deep profile toàn bộ.
- Không chạy cross-column all-pairs.
- Sampling tái lập.
- Có benchmark report.
- Full/chunk metric chênh lệch trong tolerance.

---

# 7. Phase 4 — Dashboard

## Mục tiêu

```text
Catalog visibility
+ Recommendation review
+ Profiling observability
+ Scalable queries
+ Masking
```

## Catalog tab

Wire `_render_catalog()` vào `main()`.

Hiển thị:

- Rule code/name.
- Family/dimension.
- Status/revision.
- Backend support.
- Fixture status.
- Conflict group.
- Applicability summary.
- Parameter schema status.

Filter:

- Family.
- Dimension.
- Status.
- Backend.
- Missing fixture/implementation.

Không cho activate rule thiếu backend hoặc fixture.

## Recommendation tab

Hiển thị:

- Column/semantic type.
- Candidate rule/score.
- Component breakdown.
- Reason.
- Score margin/ambiguity.
- Warnings/parameters/decision.

Action:

- Accept/reject.
- Edit parameter.
- Confirm semantic type.
- Assign field role.

## Profiling tab

Hiển thị:

- Scan mode/profile strategy.
- Sample method/coverage.
- Memory/time budget.
- Skipped metrics/termination reason.
- Lightweight/deep-profiled columns.
- Metric scope/profile confidence.

Filter:

- Inferred/semantic type.
- Metric scope.
- Deep-profile status.
- Miscast/ambiguity/critical field.

## Query Optimization

Repository query phải có:

- Pagination.
- Filter.
- Sort.
- Dataset/run scope.
- Limit.
- Index phù hợp.

Không dùng `list_dashboard_rows()` để tải toàn bộ lịch sử.

## Masking

Mask trước khi hiển thị:

- Issue sample actual value.
- Top values.
- Miscast examples.
- Record key nhạy cảm.

## UX dataset rộng

- Pagination/group view.
- Lazy loading.
- Summary trước, chi tiết sau.
- Không render hàng trăm cột cùng lúc.
- Export filtered result.

## Tiêu chí nghiệm thu

- Catalog tab hoạt động.
- Recommendation review hoàn chỉnh.
- Profiling budget/status hiển thị rõ.
- Dataset rộng không làm UI treo.
- Query có pagination/filter.
- Sensitive evidence được mask.
- Dashboard không triển khai logic DQ riêng.

---

# 8. Phase 5 — Production Readiness

## Mục tiêu

Đưa hệ thống từ local PoC thành internal production-ready theo từng mức, không triển khai tất cả cùng lúc.

## Mức 1 — Operational Hardening

Ưu tiên trước:

- Environment validation.
- Migration validation.
- Structured logging và correlation ID.
- Error code.
- Retry-safe operations.
- Backup/restore guide và test.
- Health/readiness checks.
- Docker image.
- CI pipeline.
- Secret-safe configuration.
- Masking.
- Basic audit log.

Giữ `DqRuntime` đồng bộ.

## Mức 2 — Background Execution có điều kiện

Chỉ triển khai khi:

- P95 pipeline > 30–60 giây.
- Dashboard block thường xuyên.
- Cần retry/chạy nhiều job/chạy nền.

Kiến trúc tối giản:

```text
Dashboard
→ pipeline_job table
→ one worker
→ DqRuntime đồng bộ
→ dashboard polling
```

Chưa cần Redis/Celery.

## Mức 3 — API Service

Chỉ triển khai khi:

- Có client ngoài Streamlit.
- Cần tích hợp hệ thống khác.
- Cần auth/RBAC tập trung.
- Cần tách frontend/backend.

## Security

Bắt buộc:

- Không lộ secret trong UI/log.
- Mask issue samples.
- Validate file type/path/size.
- Chống CSV formula injection khi export.
- Least privilege database user.
- Audit review/binding/policy changes.

Khi có nhiều người dùng mới bổ sung authentication và RBAC.

## Governance tối thiểu

- Rule lifecycle/revision.
- Policy revision.
- Binding history.
- Review decision.
- Audit log.

## Observability

- Structured logs.
- Pipeline/profiling/validation/recommendation duration.
- Error count/failing gates.
- Database health.
- Dashboard query latency.
- Worker heartbeat nếu có.

## CI/CD

```text
lint
→ unit test
→ integration test
→ migration test
→ benchmark smoke test
→ build image
→ deploy
→ health check
```

Không deploy nếu:

- Migration fail.
- Catalog validation fail.
- Active rule thiếu backend/fixture.
- Recommendation benchmark giảm vượt ngưỡng.
- Profiling performance regression lớn.

## Tiêu chí nghiệm thu internal production-ready

- CI pass.
- Migration từ database rỗng pass.
- Backup/restore đã kiểm tra.
- Health/readiness hoạt động.
- Secret/masking policy hoạt động.
- Structured logs và basic audit.
- Performance benchmark pass.
- Dashboard query không tải toàn bộ lịch sử.

---

# 9. Migration Plan

Giữ migration runner.

```text
001_core.sql
002_profile_scoring_improvements.sql
003_rule_catalog_lifecycle.sql
004_rule_catalog_expansion.sql
005_recommendation_scoring.sql
006_adaptive_profiling_budget.sql
007_dashboard_query_indexes.sql
008_security_audit.sql
009_async_job_runtime.sql   # chỉ khi cần
010_api_auth.sql            # chỉ khi cần
```

Nếu database hiện tại chỉ là demo, có thể squash `001–006` thành một baseline mới rồi tiếp tục migration từ đó. Không loại bỏ hoàn toàn migration mechanism.

---

# 10. Sprint Plan

## Sprint 1 — Baseline

- Test/migration.
- Rule inventory/backend coverage.
- Recommendation/profiling baseline.

## Sprint 2 — Rule Catalog Foundation

- Lifecycle/revision.
- Applicability/exclusions.
- Parameter schema/conflict group.

## Sprint 3 — Rule Coverage

- Hoàn thiện 20–30 active rules.
- Fixtures/backend tests.

## Sprint 4 — Recommendation Core

- Candidate score/components.
- Reason/ambiguity.

## Sprint 5 — Recommendation Benchmark

- Ground truth.
- Development/calibration/holdout.
- Precision@3/Recall@3/MRR.
- Error analysis.

## Sprint 6 — Chunked Profiling

- Chunk reader.
- Incremental metrics.
- Resource budget.
- Full/chunk comparison.

## Sprint 7 — Wide Profiling

- Null-heavy/duplicate-aware.
- Lightweight/deep strategy.
- Column priority/cross-column shortlist.

## Sprint 8 — Dashboard Catalog/Recommendation

- Catalog tab.
- Recommendation review.
- Pagination/filter.

## Sprint 9 — Dashboard Profiling

- Budget summary.
- Deep-profile status.
- Masking/query optimization.

## Sprint 10 — Production Hardening

- CI/logging/audit.
- Backup/restore.
- Security/performance gates.

## Sprint 11 — Conditional Worker

Chỉ làm nếu performance metrics chứng minh cần.

## Sprint 12 — Conditional API/RBAC

Chỉ làm nếu có multi-user hoặc external integration.

---

# 11. Tiêu chí nghiệm thu cuối

## Rule Catalog

- 20–30 active rules, tối thiểu 6 families.
- 100% active rule có backend và fixture.
- Lifecycle/revision hoạt động.
- Applicability/exclusions hoạt động.
- Conflict rules không double-count.

## Deterministic Recommendation

- Candidate có score/components/reason/ambiguity.
- Có review workflow.
- Có Precision@3/Recall@3/MRR và holdout evaluation.
- Recommendation chưa review không tự bind mặc định.

## Profiling

- Dataset lớn không bắt buộc load toàn bộ vào RAM.
- Peak memory tuân thủ budget trong tolerance.
- Null-heavy/duplicate-aware sampling chạy thực tế.
- Dataset rộng dùng lightweight + selective deep.
- Không chạy all-pairs.
- Có benchmark memory/time và reproducibility.

## Dashboard

- Catalog tab hoạt động.
- Recommendation review hoạt động.
- Profiling budget/status hiển thị rõ.
- Query có pagination/filter.
- Dataset rộng không làm UI treo.
- Sensitive evidence được mask.

## Production Readiness

- CI/migration/backup/health pass.
- Structured logging và basic audit.
- Security/performance regression gates.
- Worker/API chỉ thêm khi có nhu cầu rõ.

---

# 12. Kết quả kỳ vọng

```text
Rule Catalog
→ đủ rộng, có lifecycle và backend coverage

Deterministic Recommendation
→ có score, reason, ambiguity và benchmark

Profiling
→ xử lý dataset lớn/rộng theo budget

Dashboard
→ quan sát và review đầy đủ ba năng lực cốt lõi

Production Readiness
→ có nền vận hành an toàn, kiểm thử được và mở rộng theo nhu cầu
```

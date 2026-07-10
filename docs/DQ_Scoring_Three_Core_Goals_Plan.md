# KẾ HOẠCH CẢI THIỆN CỐT LÕI HỆ THỐNG DQ SCORING
## Tập trung Rule Catalog, Deterministic Recommendation và Adaptive Profiling

## 1. Mục tiêu cuối cùng

Kế hoạch chỉ tập trung vào ba kết quả đầu ra:

```text
Rule Catalog
→ đủ rộng, có lifecycle và backend coverage

Recommendation
→ có score, reason, ambiguity và benchmark

Profiling
→ xử lý dataset lớn/rộng theo budget
```

Các nội dung như FastAPI, job queue, Redis, Celery, RBAC đầy đủ, multi-tenant, approval nhiều tầng và LLM runtime chưa nằm trong phạm vi thực hiện hiện tại.

---

# 2. Phạm vi

## 2.1. Trong phạm vi

### Rule Catalog

- Mở rộng rule theo family.
- Chuẩn hóa Rule Template.
- Applicability.
- Exclusions.
- Parameter schema.
- Conflict group.
- Rule lifecycle.
- Rule revision.
- Backend coverage.
- Positive/negative fixtures.
- Bootstrap catalog idempotent.

### Deterministic Recommendation

- Candidate filtering.
- Candidate score.
- Score component breakdown.
- Deterministic reason.
- Ambiguity margin.
- Review status.
- Recommendation persistence.
- Precision@K, Recall@K và MRR benchmark.
- Error analysis.

### Adaptive Profiling

- Chunked CSV.
- Resource budget.
- Full/sample/approximate metric scope.
- Null-heavy sampling.
- Duplicate-aware sampling.
- Wide dataset lightweight scan.
- Selective deep profile.
- Column priority.
- Cross-column shortlist.
- Performance benchmark.

## 2.2. Ngoài phạm vi

- LLM reranking.
- Auto-bind bằng LLM.
- API service production.
- Job queue và worker.
- RBAC đầy đủ.
- Multi-level approval.
- Multi-tenant.
- Automated retention.
- Referential integrity xuyên nhiều data source ở giai đoạn đầu.
- Database, API và streaming ingestion.

---

# 3. Thứ tự triển khai

```text
Phase 0 — Baseline và Inventory
→ Phase 1 — Rule Catalog Foundation
→ Phase 2 — Rule Family Expansion
→ Phase 3 — Deterministic Recommendation
→ Phase 4 — Recommendation Benchmark
→ Phase 5 — Adaptive Profiling
→ Phase 6 — Large/Wide Dataset Verification
→ Phase 7 — Final Integration và Cleanup
```

Mối quan hệ phụ thuộc:

```text
Rule Catalog
→ tạo tập candidate rõ ràng

Candidate rõ ràng
→ recommendation có thể score và benchmark

Profiling tốt hơn
→ recommendation có evidence chính xác hơn
```

---

# 4. Phase 0 — Baseline và Inventory

## 4.1. Mục tiêu

Khóa hành vi hiện tại trước khi mở rộng.

## 4.2. Công việc

- Tạo Git tag.
- Chạy toàn bộ regression test.
- Lưu output baseline:
  - profiling;
  - semantic detection;
  - recommendation;
  - validation;
  - scoring.
- Kiểm kê Rule Catalog hiện tại.
- Lập backend coverage matrix hiện tại.
- Chuẩn bị tập dataset và fixture.

## 4.3. Dataset baseline

Tối thiểu gồm:

- Customer.
- Sales.
- Education.
- Employee.
- Logistics.

Mỗi domain có:

```text
clean dataset
missing values
invalid format
duplicate
mixed type
out-of-range
cross-field error
```

## 4.4. Deliverable

```text
docs/rule_catalog_inventory.md
docs/backend_coverage_matrix.md
tests/fixtures/
tests/golden/
tests/generators/
```

## 4.5. Tiêu chí hoàn thành

- Test hiện tại pass.
- Có baseline để so sánh.
- Có danh sách rule hiện tại.
- Có danh sách backend hiện tại.
- Có ít nhất 5 domain dataset.

---

# 5. Phase 1 — Rule Catalog Foundation

## 5.1. Mục tiêu

Chuẩn hóa Rule Catalog trước khi thêm số lượng lớn rule.

## 5.2. Rule Template chuẩn

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

description_for_recommendation: >
  Apply when total amount is expected to equal quantity multiplied by unit price.
```

## 5.3. Trường bắt buộc

- `rule_code`
- `rule_name`
- `family`
- `dimension`
- `category`
- `target_scope`
- `evaluation_scope`
- `operator`
- `required_columns`
- `backend_support`
- `applicability`
- `exclusions`
- `parameters_schema`
- `defaults`
- `recommendation`
- `conflict_group`
- `lifecycle.status`
- `lifecycle.revision`
- `description_for_recommendation`

---

# 6. Rule Lifecycle

## 6.1. Trạng thái

```text
draft
→ tested
→ active
→ deprecated
→ retired
```

## 6.2. Điều kiện chuyển trạng thái

### draft → tested

Rule phải có:

- parameter schema hợp lệ;
- backend implementation;
- positive fixture;
- negative fixture;
- canonical measurement test.

### tested → active

Rule phải có:

- applicability test;
- exclusions test;
- conflict test nếu có;
- recommendation test;
- backend coverage xác nhận;
- documentation.

### active → deprecated

Khi:

- có rule thay thế;
- semantics không còn phù hợp;
- backend không còn hỗ trợ.

### deprecated → retired

Khi:

- không còn binding active;
- không còn runtime dependency;
- migration hoặc cleanup đã hoàn tất.

## 6.3. Rule revision

Không sửa trực tiếp semantics của rule active.

Khi thay đổi:

```text
rule_code giữ nguyên
revision tăng
binding mới dùng revision mới
binding cũ vẫn truy vết revision cũ
```

---

# 7. Backend Coverage

## 7.1. Mục tiêu

Mỗi active rule phải biết backend nào thực thi.

## 7.2. Coverage matrix

| Rule | GX | Python | Trạng thái |
|---|---:|---:|---|
| NOT_NULL | Có | Tùy chọn | Ready |
| NOT_BLANK | Có | Tùy chọn | Ready |
| REGEX_FORMAT | Có | Tùy chọn | Ready |
| ALLOWED_DOMAIN | Có | Tùy chọn | Ready |
| NUMERIC_RANGE | Có | Tùy chọn | Ready |
| COLUMN_UNIQUE | Có | Tùy chọn | Ready |
| COMPOSITE_UNIQUE | Không | Có | Ready |
| CONDITIONAL_REQUIRED | Không | Có | Draft |
| TOTAL_AMOUNT_CONSISTENCY | Không | Có | Draft |
| START_BEFORE_END | Không | Có | Draft |

## 7.3. Điều kiện active

Một rule chỉ được active khi:

- Có ít nhất một backend.
- Có backend test.
- Có canonical measurement mapping.
- Có issue sample test.
- Có scoring behavior test.

---

# 8. Phase 2 — Mở rộng Rule Family

## 8.1. Mục tiêu số lượng

Đợt đầu:

```text
15–20 active rules ổn định
```

Không đặt mục tiêu số lượng quá lớn trước khi có test.

## 8.2. Rule family ưu tiên

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
- `TOTAL_AMOUNT_CONSISTENCY`
- `CONDITIONAL_VALUE`

### Timeliness

- `FRESHNESS`
- `MAX_DATA_DELAY`
- `EVENT_BEFORE_PROCESSING`

### Schema

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

---

# 9. Applicability

## 9.1. Input

Applicability engine kiểm tra:

- dataset type;
- target scope;
- inferred type;
- semantic type;
- field role;
- profile evidence;
- required columns;
- backend availability;
- metric scope.

## 9.2. Output

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

## 9.3. Quy tắc

- Applicability chạy trước candidate scoring.
- Rule không applicable không được đưa vào candidate list.
- Metric sampled chỉ được xem là evidence yếu hơn.
- Business rule luôn yêu cầu review.

---

# 10. Exclusions

## 10.1. Mục tiêu

Giảm false positive.

## 10.2. Ví dụ

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

## 10.3. Quy tắc

- Exclusion chạy trước candidate scoring.
- Lưu reason khi rule bị loại.
- Có unit test riêng cho exclusions.

---

# 11. Parameter Schema

## 11.1. Mục tiêu

Không cho binding chứa parameter sai.

## 11.2. Validation point

Parameter phải được kiểm tra:

```text
catalog bootstrap
→ recommendation
→ binding
→ execution planning
```

## 11.3. Ví dụ

```yaml
parameters_schema:
  type: object
  properties:
    min_value:
      type: number
    max_value:
      type: number
    inclusive:
      type: boolean
  required:
    - min_value
    - max_value
```

---

# 12. Conflict Group

## 12.1. Ví dụ

```text
NOT_NULL
NOT_BLANK
MANDATORY_COMPLETENESS
```

## 12.2. Policy

- Một rule là primary scoring rule.
- Rule còn lại có thể là validation-only.
- Không double-count.
- Conflict resolution deterministic.
- Dashboard hiển thị rule bị suppress và reason.

---

# 13. Fixtures cho Rule

## 13.1. Cấu trúc

```text
tests/fixtures/rules/<rule_code>/
├── valid.csv
├── invalid.csv
├── edge_case.csv
└── expected.json
```

## 13.2. `expected.json`

Phải mô tả:

- expected measurement;
- expected failed count;
- expected missing count;
- expected issue sample;
- expected scoring behavior.

## 13.3. Tiêu chí hoàn thành Phase 2

- 15–20 active rules.
- Mỗi active rule có fixtures.
- Có backend coverage.
- Có canonical mapping.
- Có conflict handling.
- Bootstrap idempotent.

---

# 14. Phase 3 — Deterministic Recommendation

## 14.1. Mục tiêu

Recommendation phải có:

```text
score
reason
ambiguity
review status
```

## 14.2. Pipeline

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

---

# 15. Candidate Score

## 15.1. Baseline

```text
candidate_score =
0.20 × name_match
+ 0.20 × type_match
+ 0.25 × semantic_match
+ 0.20 × profile_match
+ 0.10 × role_match
+ 0.05 × catalog_priority
```

## 15.2. Lưu component

```json
{
  "rule_code": "IDENTIFIER_UNIQUE",
  "score": 0.84,
  "components": {
    "name_match": 0.80,
    "type_match": 1.00,
    "semantic_match": 0.90,
    "profile_match": 0.75,
    "role_match": 0.50,
    "catalog_priority": 0.80
  }
}
```

## 15.3. Lưu ý

- Score là ranking score.
- Không gọi là probability.
- Trọng số phải calibration bằng benchmark.

---

# 16. Reason

Reason sinh deterministic từ evidence.

Ví dụ:

```text
Đề xuất COLUMN_UNIQUE vì:
- semantic type là identifier;
- inferred type phù hợp;
- uniqueness ratio là 0,998;
- cột được đánh dấu business key.
```

Reason phải chỉ ra:

- evidence nào match;
- evidence nào thiếu;
- warning nào tồn tại;
- metric full hay sampled.

---

# 17. Ambiguity

## 17.1. Metric

```text
top_score
second_score
score_margin
candidate_count
ambiguity_status
```

## 17.2. Baseline

```text
score_margin >= 0.20
→ clear

0.10 <= score_margin < 0.20
→ moderate

score_margin < 0.10
→ ambiguous
```

## 17.3. Điều kiện ambiguity bổ sung

- Nhiều semantic candidate gần nhau.
- Profile metric sampled.
- Field critical nhưng chưa xác nhận metadata.
- Rule cần business context.
- Conflict chưa giải quyết.
- Candidate score thấp nhưng rank cao do catalog ít rule.

---

# 18. Review Workflow

## 18.1. Trạng thái

```text
suggested
accepted
rejected
edited
```

## 18.2. Action

- Accept.
- Reject.
- Edit parameter.
- Confirm semantic type.
- Assign field role.

## 18.3. Luồng

```text
Recommendation
→ Review
→ Accepted Recommendation
→ Dataset Rule Binding
```

Không auto-bind mặc định.

---

# 19. Recommendation Persistence

## 19.1. Bảng

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
reviewed_at
suggested_parameters_jsonb
```

---

# 20. Phase 4 — Recommendation Benchmark

## 20.1. Ground truth

Mỗi cột cần nhãn:

```text
expected semantic type
expected rules
forbidden rules
expected parameters
requires_review
```

## 20.2. Dataset split

```text
development
calibration
holdout
```

Không benchmark trên dữ liệu dùng để viết heuristic.

## 20.3. Metrics

- Precision@1.
- Precision@3.
- Recall@3.
- Mean Reciprocal Rank.
- Wrong recommendation rate.
- Ambiguous-column detection recall.
- Review acceptance rate.

## 20.4. Target ban đầu

```text
Precision@3 >= 0.80
Recall@3 >= 0.80
Wrong recommendation rate <= 0.10
Ambiguous-column recall >= 0.80
```

Target phải điều chỉnh sau baseline.

## 20.5. Error analysis

Phân loại lỗi:

- semantic detection sai;
- applicability sai;
- exclusion thiếu;
- rule catalog thiếu;
- score weight chưa phù hợp;
- business context không đủ;
- sampled evidence gây nhầm.

## 20.6. Tiêu chí hoàn thành

- Có benchmark report.
- Có holdout result.
- Có confusion/error analysis.
- Có calibrated weight.
- Có threshold ambiguity được chốt.

---

# 21. Phase 5 — Adaptive Profiling

## 21.1. Mục tiêu

Profiling phải xử lý được:

```text
dataset nhiều dòng
dataset nhiều cột
dataset vượt memory budget
```

mà không bắt buộc load toàn bộ vào RAM.

---

# 22. Chunked CSV

## 22.1. Luồng

```text
CSV
→ read_csv(chunksize=N)
→ incremental metrics
→ sample reservoir
→ finalize profile
```

## 22.2. Metric chạy incremental

- row count;
- null count;
- blank count;
- min/max;
- mean/variance;
- parse ratio;
- limited pattern counters;
- sample reservoir.

## 22.3. Metric approximate/sample

- distinct;
- quantiles;
- duplicate;
- outlier;
- top values chi tiết.

---

# 23. Resource Budget

## 23.1. Cấu hình

```env
DQ_PROFILE_CHUNK_SIZE=50000
DQ_PROFILE_MEMORY_BUDGET_MB=512
DQ_PROFILE_TIME_BUDGET_SEC=300
DQ_PROFILE_MAX_DEEP_COLUMNS=100
```

## 23.2. Policy

```text
estimated memory <= budget
→ full dataframe

estimated memory > budget
→ chunked scan

gần hết time budget
→ skip optional deep metrics

số cột vượt ngưỡng
→ lightweight all + selective deep
```

## 23.3. Metadata lưu

```text
scan_mode
chunk_size
memory_budget
time_budget
budget_used
skipped_metrics
termination_reason
```

---

# 24. Sampling

## 24.1. Mixed sample

```text
random
+ head
+ tail
+ null-heavy
+ duplicate candidates
```

## 24.2. Null-heavy

```text
row_null_score =
null_count + blank_count trên từng dòng
```

Giữ top-N dòng có score cao.

## 24.3. Duplicate-aware

Dùng:

- row hash;
- candidate key hash;
- repeated hash counters;
- sample các hash lặp.

## 24.4. Reproducibility

Lưu:

```text
random_seed
sample_size
sample_ratio
sample_method
```

---

# 25. Wide Dataset Strategy

## 25.1. Pass 1 — Lightweight

Chạy toàn bộ cột:

- name;
- physical dtype;
- null;
- blank;
- distinct approximation;
- parse ratio;
- basic length;
- basic pattern.

## 25.2. Pass 2 — Selective Deep Profile

Chỉ chạy cột:

- critical;
- semantic ambiguous;
- miscast cao;
- nhiều rule candidate;
- cross-field potential;
- field role quan trọng.

Deep metric:

- top values;
- detailed patterns;
- quantiles;
- outliers;
- masked examples;
- relation evidence.

## 25.3. Column priority

Baseline:

```text
critical field
→ semantic ambiguity
→ rule ambiguity
→ miscast/anomaly
→ cross-field potential
→ normal
```

Không cần weighted formula ngay từ đầu.

---

# 26. Cross-column Shortlist

## 26.1. Không chạy all-pairs

Shortlist theo:

```text
name tokens
type compatibility
semantic group
field role
```

## 26.2. Relation family ban đầu

- start/end;
- created/updated;
- event/processed;
- quantity/price/total;
- debit/credit/balance;
- identifier/reference.

## 26.3. Output

```json
{
  "relation_type": "arithmetic",
  "columns": [
    "quantity",
    "price_per_unit",
    "total_amount"
  ],
  "evidence_score": 0.82,
  "requires_review": true
}
```

---

# 27. Phase 6 — Large/Wide Dataset Verification

## 27.1. Test dataset

- 1 triệu dòng, ít cột.
- 300 cột.
- 500 cột.
- Mixed string/numeric.
- Null-heavy.
- Duplicate injection.
- Long text.
- High-cardinality identifiers.

## 27.2. Metrics đo

- Peak memory.
- Profiling duration.
- Rows/second.
- Columns/second.
- Deep-profiled column ratio.
- Sample coverage.
- Skipped metric count.
- Full/chunk difference.

## 27.3. Acceptance target

Baseline gợi ý:

```text
Peak memory <= configured budget + tolerance
Chunked run không crash
Full/chunk metric chênh lệch trong tolerance
Không deep profile toàn bộ wide dataset
Không chạy cross-column all-pairs
Sampling reproducible
```

---

# 28. Migration Plan

```text
001_core.sql
002_profile_scoring_improvements.sql
003_rule_catalog_lifecycle.sql
004_rule_catalog_expansion.sql
005_recommendation_scoring.sql
006_adaptive_profiling_budget.sql
```

Không sửa migration đã chạy.

---

# 29. Test Strategy

## Rule Catalog

- Template schema.
- Lifecycle transition.
- Revision.
- Applicability.
- Exclusions.
- Parameter schema.
- Conflict group.
- Bootstrap idempotency.
- Backend coverage.

## Recommendation

- Candidate filtering.
- Candidate score.
- Component breakdown.
- Reason.
- Ambiguity margin.
- Review status.
- Benchmark metrics.

## Profiling

- Full scan.
- Chunk scan.
- Resource budget.
- Null-heavy sampling.
- Duplicate-aware sampling.
- Wide dataset.
- Selective deep profile.
- Cross-column shortlist.
- Reproducibility.

## Integration

```text
Profile
→ Recommend
→ Review
→ Bind
→ Validate
→ Score
```

---

# 30. Sprint Plan

## Sprint 1

- Baseline.
- Rule inventory.
- Rule lifecycle schema.
- Migration `003`.

## Sprint 2

- Applicability.
- Exclusions.
- Parameter schema.
- Conflict group.

## Sprint 3

- Thêm 8–10 rule đầu tiên.
- Fixtures.
- Backend coverage.

## Sprint 4

- Thêm đủ 15–20 active rules.
- Lifecycle/revision tests.
- Migration `004`.

## Sprint 5

- Candidate score.
- Score breakdown.
- Reason.
- Ambiguity.

## Sprint 6

- Review workflow.
- Recommendation persistence.
- Migration `005`.

## Sprint 7

- Ground truth.
- Precision@3/Recall@3.
- Error analysis.
- Calibration.

## Sprint 8

- Chunked CSV.
- Resource budget.
- Incremental metrics.

## Sprint 9

- Null-heavy/duplicate-aware sampling.
- Selective deep profile.

## Sprint 10

- Wide dataset strategy.
- Cross-column shortlist.
- Migration `006`.

## Sprint 11

- Large/wide benchmark.
- Full/chunk comparison.
- Performance tuning.

## Sprint 12

- End-to-end regression.
- Documentation.
- Final cleanup.

---

# 31. Definition of Done

## Rule Catalog

```text
đủ rộng
+ lifecycle
+ revision
+ backend coverage
+ fixture
+ conflict handling
```

## Recommendation

```text
score
+ component breakdown
+ deterministic reason
+ ambiguity
+ review status
+ benchmark
```

## Profiling

```text
chunked
+ resource budget
+ mixed sampling
+ selective deep profile
+ wide dataset strategy
+ performance benchmark
```

---

# 32. Tiêu chí nghiệm thu cuối

## Rule Catalog

- Có 15–20 active rules ổn định.
- Có tối thiểu 6 rule families.
- Mỗi active rule có backend.
- Mỗi active rule có positive/negative fixtures.
- Lifecycle và revision hoạt động.
- Applicability và exclusions hoạt động.
- Conflict group không double-count.

## Recommendation

- Mỗi candidate có score.
- Có component breakdown.
- Có reason dựa trên evidence.
- Có ambiguity margin.
- Có review workflow.
- Có Precision@3/Recall@3 benchmark.
- Có holdout evaluation.
- Không auto-bind mặc định.

## Profiling

- Dataset lớn không bắt buộc load toàn bộ vào RAM.
- Có resource budget.
- Có full/sample/approximate scope.
- Có null-heavy/duplicate-aware sampling.
- Dataset rộng dùng lightweight + selective deep.
- Không chạy all-pairs.
- Có memory/time benchmark.
- Sampling tái lập được.

---

# 33. Kết quả kỳ vọng

Sau khi hoàn thành:

```text
Rule Catalog
→ đủ rộng, có lifecycle và backend coverage

Recommendation
→ có score, reason, ambiguity và benchmark

Profiling
→ xử lý dataset lớn/rộng theo budget
```

Đây là nền tảng đủ vững để sau đó mới cân nhắc LLM reranking, API service hoặc vận hành bất đồng bộ.

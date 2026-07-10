# KẾ HOẠCH CẢI THIỆN PROFILING VÀ SCORING CHO HỆ THỐNG DQ SCORING

## 1. Mục tiêu

Tài liệu đề xuất cải thiện hai thành phần cốt lõi:

1. **Profiling**
   - Chuẩn hóa các metric: null, blank, distinct, uniqueness ratio, inferred type, top values, pattern, length, numeric summary và miscast.
   - Phân biệt rõ metric full scan, sampled và approximate.
   - Cải thiện xử lý dataset lớn và nhiều cột.
   - Tạo đầu vào đáng tin cậy hơn cho semantic detection và rule recommendation.

2. **Scoring**
   - Chuẩn hóa Rule Score, Dimension Score, Dataset Score và Quality Gate.
   - Làm rõ null policy, not applicable và not measured.
   - Tránh trừ điểm trùng.
   - Bổ sung measurement coverage.
   - Snapshot scoring policy để tái tạo lịch sử điểm.

Luồng hệ thống vẫn giữ:

```text
Dataset
→ Profiling
→ Semantic Detection
→ Rule Recommendation
→ Dataset Rule Binding
→ GX / Python Validation
→ Canonical Measurement
→ Scoring
→ Quality Gate
→ Dashboard
```

---

## 2. Nguyên tắc

- Mỗi metric profiling phải có định nghĩa rõ.
- Mỗi metric phải ghi nguồn: `full`, `sampled` hoặc `approximate`.
- Profiling không sửa dữ liệu gốc.
- Inferred type không được làm mất leading zero.
- Semantic detection chỉ tạo gợi ý, không tự xác nhận Business Key, CDE hoặc Mandatory.
- Scoring chỉ đọc canonical measurement.
- `not_measured` không được ép thành 0.
- Không để nhiều rule cùng trừ điểm cho một lỗi nghiệp vụ.
- Dataset Score phải kèm measurement coverage.
- Quality Gate có ưu tiên cao hơn trạng thái điểm trung bình.
- Mọi thay đổi phải có golden test và regression test.

---

# 3. Chuẩn hóa Profiling

## 3.1. Null

### Định nghĩa

`null` là giá trị thiếu vật lý như:

- `None`
- `NaN`
- `NaT`
- giá trị null do parser tạo ra

### Công thức

```text
null_count
null_ratio = null_count / row_count
```

### Quy tắc

- Không gộp blank vào null.
- Không tự coi `"NULL"`, `"N/A"` hoặc `"-"` là null nếu chưa có cấu hình.
- Nếu parser có `na_values`, phải lưu parser config trong profiling metadata.
- Nên tính full scan khi có thể.

---

## 3.2. Blank

### Định nghĩa

`blank` gồm:

- `""`
- chuỗi chỉ có whitespace
- tab hoặc newline sau khi trim

### Công thức

```text
blank_count
trimmed_blank_count
blank_ratio = blank_count / row_count
```

### Quy tắc

- Chỉ áp dụng cho string/object.
- Trim chỉ dùng để kiểm tra.
- Null không được tính lại vào blank.

---

## 3.3. Distinct

### Metric

```text
distinct_count_excluding_null
distinct_count_including_null
```

### Quy tắc

- Recommendation mặc định dùng `distinct_count_excluding_null`.
- Nếu dùng approximation phải lưu:
  - `is_approximate`
  - thuật toán
  - sai số nếu có
- Không dùng distinct từ sample để kết luận uniqueness toàn dataset.

---

## 3.4. Uniqueness Ratio

### Công thức

```text
non_null_count = row_count - null_count

uniqueness_ratio =
distinct_count_excluding_null / non_null_count
```

Nếu `non_null_count = 0`:

```text
uniqueness_ratio = null
measurement_status = not_measured
```

### Quy tắc

- Uniqueness cao chỉ là tín hiệu identifier candidate.
- Không tự kết luận Business Key.
- Không tự gắn uniqueness rule nếu:
  - cột có semantic category;
  - tên như `type_id`, `category_id`;
  - distinct được tính từ sample;
  - metadata không xác nhận key.

---

## 3.5. Inferred Type

Phân biệt:

```text
physical dtype
logical inferred type
semantic type
```

Ví dụ:

```text
physical dtype: object
logical inferred type: integer_like_string
semantic type: identifier
```

### Logical type đề xuất

- integer
- float
- numeric_string
- integer_like_string
- boolean
- datetime
- date
- string
- categorical
- mixed
- unknown

### Evidence

```text
numeric_parse_ratio
integer_parse_ratio
datetime_parse_ratio
boolean_parse_ratio
string_ratio
mixed_type_ratio
leading_zero_ratio
```

### Quy tắc

- Không ép `"00123"` thành integer.
- Nếu nhiều type cùng phù hợp, trả:
  - type chính;
  - alternatives;
  - confidence.
- Nếu dữ liệu mixed, dùng `mixed`.
- Không dùng tên cột làm bằng chứng duy nhất.

---

## 3.6. Top Values

### Trường lưu

```text
value
count
ratio
is_null
is_blank
```

### Quy tắc

- Null và blank hiển thị riêng.
- Với PII, chỉ lưu masked value hoặc hash.
- `top_values` từ sample phải ghi `sampled`.
- Không dùng top values sample để kết luận domain đầy đủ.

Cấu hình:

```text
TOP_K_VALUES = 10
TOP_VALUE_MAX_LENGTH = 100
```

---

## 3.7. Pattern

### Mục tiêu

Nhận diện:

- email
- phone
- code
- identifier
- postal code
- date string

### Trường lưu

```text
pattern
count
ratio
example_masked
```

### Quy tắc

- Chỉ giữ top pattern.
- Không lưu raw value nhạy cảm.
- Pattern frequency phải ghi full/sample scope.
- Không tự đề xuất regex nếu pattern phân tán.
- Chỉ đề xuất regex khi dominant pattern ratio đủ cao.

Baseline:

```text
PATTERN_MIN_SUPPORT = 0.80
PATTERN_TOP_K = 5
```

---

## 3.8. Length

### Metric

```text
min_length
max_length
mean_length
median_length
p25_length
p75_length
p95_length
```

### Quy tắc

- Chỉ tính trên non-null string.
- Có thể tách raw length và trimmed length.
- Không đề xuất fixed-length rule chỉ vì sample có min = max.
- Chỉ đề xuất length rule khi pattern ổn định và coverage đủ.

---

## 3.9. Numeric Summary

### Metric

```text
min
max
mean
median
standard_deviation
p01
p05
p25
p75
p95
p99
negative_count
zero_count
positive_count
```

### Quy tắc

- Chỉ tính trên giá trị parse được.
- Miscast phải tách riêng.
- Không dùng mean làm chỉ số duy nhất.
- Không sinh range rule chỉ dựa vào min/max lịch sử.

### Outlier evidence

```text
iqr_lower_bound
iqr_upper_bound
outlier_count
outlier_ratio
```

Outlier chỉ là evidence, chưa tự coi là lỗi.

---

## 3.10. Miscast

### Định nghĩa

Miscast là giá trị không null nhưng không parse được theo inferred type.

Ví dụ numeric:

```text
"12.5" → valid
"" → blank
null → missing
"abc" → miscast
```

### Trường lưu

```text
miscast_count
miscast_ratio
miscast_examples_masked
```

### Quy tắc

- Miscast không được gộp với null/blank.
- Có thể dùng làm evidence cho type validity rule.
- Không coercion rồi bỏ qua lỗi.

---

# 4. Full Scan và Sampling

## 4.1. Quyết định scan

Không chỉ dựa trên số dòng.

Dùng:

```text
row_count
column_count
file_size
estimated_memory
dtype_distribution
configured_time_budget
```

Baseline:

```text
FULL_SCAN_ROW_LIMIT = 100_000
FULL_SCAN_SIZE_LIMIT = 100 MB
```

## 4.2. Sampling hỗn hợp

```text
random sample
+ head rows
+ tail rows
+ null-heavy rows
+ duplicate candidates
+ rare-value candidates nếu chi phí cho phép
```

Metadata cần lưu:

```text
scan_mode
sample_method
sample_size
sample_ratio
random_seed
coverage_estimate
```

### Quy tắc

- Sampling phải tái lập được.
- Metric phải ghi source.
- Row count và schema metadata luôn lấy full dataset.
- Không dùng sample uniqueness để auto-bind uniqueness rule.

---

# 5. Dataset Nhiều Cột

## 5.1. Hai bước profiling

### Bước 1 — Lightweight profile toàn bộ cột

```text
name
dtype
null
blank
distinct approximation
parse ratio
basic length
basic pattern
```

### Bước 2 — Deep profile có chọn lọc

Chạy khi:

- semantic confidence thấp;
- tên cột khó hiểu;
- cột critical;
- miscast cao;
- nhiều rule candidate gần nhau;
- có khả năng cross-field.

## 5.2. Column grouping

- Identifier
- Contact
- Datetime
- Numeric
- Financial
- Categorical
- Free text
- Unknown

## 5.3. Không chạy all-pairs

```text
name filter
→ type compatibility
→ semantic group
→ shortlist
→ relation check
```

## 5.4. Policy theo số cột

| Số cột | Chiến lược |
|---:|---|
| ≤ 50 | Profile bình thường |
| 51–200 | Lightweight toàn bộ, deep profile theo nhóm |
| 201–500 | Priority-based deep profiling |
| > 500 | Budget-based profiling, chỉ deep profile cột critical/ambiguous |

---

# 6. Cải thiện Scoring

## 6.1. Canonical Measurement

Mỗi rule cần:

```text
passed_count
failed_count
missing_count
not_applicable_count
evaluated_count
measurement_status
```

Công thức:

```text
evaluated_count =
passed_count + failed_count + missing_count
```

`not_applicable_count` không vào mẫu số.

---

## 6.2. Null Policy

Các giá trị:

```text
fail
ignore
separate
not_applicable
```

Gợi ý:

| Dimension | Null policy |
|---|---|
| Completeness | fail |
| Validity | separate hoặc ignore |
| Accuracy | not_applicable hoặc separate |
| Uniqueness | cấu hình rõ |
| Timeliness | not_applicable nếu thiếu timestamp |

Null policy phải được lưu trong binding và snapshot theo validation run.

---

## 6.3. Rule Score

```text
rule_score =
passed_count / evaluated_count × 100
```

Nếu `evaluated_count = 0`:

```text
rule_score = null
measurement_status = not_measured
```

Không được:

- ép `not_measured` thành 0;
- đưa `not_applicable` vào mẫu số;
- trộn sampled validation và full validation mà không đánh dấu.

---

## 6.4. Not Measured

Lý do đề xuất:

```text
backend_error
missing_metadata
unsupported_operator
no_data
no_applicable_records
invalid_configuration
```

Dashboard phải hiển thị lý do.

---

## 6.5. Ngăn Trừ Điểm Trùng

Bổ sung:

```text
conflict_group
primary_scoring_rule
score_enabled
validation_only
```

Ví dụ:

```text
NOT_NULL
NOT_BLANK
MANDATORY_COMPLETENESS
```

chỉ một rule là primary scoring rule.

Conflict resolution chạy trước Dimension Score.

---

## 6.6. Dimension Score

```text
dimension_score =
Σ(rule_score × effective_rule_weight)
/
Σ(effective_rule_weight)
```

Chỉ gồm rule:

- measured;
- score_enabled;
- không bị loại do conflict;
- không phải gate-only.

Nếu chưa đo được:

```text
dimension_score = null
dimension_status = not_measured
```

---

## 6.7. Dataset Score và Coverage

```text
dataset_score =
Σ(dimension_score × normalized_dimension_weight)
/
Σ(normalized_dimension_weight của dimension measured)
```

Bổ sung:

```text
measured_dimension_count
total_dimension_count
measurement_coverage
score_status
```

Ví dụ:

```text
DQ Score: 92.5
Measured dimensions: 2/6
Measurement coverage: 33%
Status: provisional
```

Policy gợi ý:

```text
coverage >= 0.67
→ final

0.33 <= coverage < 0.67
→ provisional

coverage < 0.33
→ insufficient_coverage
```

---

## 6.8. Severity và Criticality

```text
effective_rule_weight =
base_rule_weight
× severity_weight
× criticality_weight
```

Criticality lấy mức cao nhất, không nhân chồng role.

Ví dụ:

```text
Business Key = 1.50
CDE = 1.40
Mandatory = 1.25
Identifier = 1.15
Normal = 1.00
```

Các trọng số phải được:

- version;
- snapshot;
- sensitivity test;
- quản lý tập trung.

---

## 6.9. Quality Gate

Quality Gate độc lập với Dataset Score.

Thứ tự:

```text
FAIL
> WARNING
> SCORE STATUS
```

Ví dụ:

```text
Dataset Score = 93
Critical Business Key rule failed
→ Final status = FAIL
```

Nên phân biệt:

```text
hard_gate
soft_gate
```

---

## 6.10. Policy Snapshot

Mỗi score run lưu:

```text
policy_id
policy_revision
dimension_weights
severity_weights
criticality_weights
gate_thresholds
formula_revision
rounding_policy
```

---

## 6.11. Validation Scope

Lưu:

```text
validation_scope
sample_size
sample_ratio
random_seed
coverage
```

Giá trị:

```text
full
sampled
```

Dashboard phải phân biệt điểm full và sampled.

---

# 7. Issue Samples

Mỗi rule score cần evidence mẫu:

```text
record_key
column_name
actual_value_masked
expected_condition
issue_type
rule_code
```

Cấu hình:

```text
MAX_ISSUE_SAMPLES_PER_RULE = 20
```

GX và Python phải chuẩn hóa về cùng contract.

---

# 8. Thay đổi PostgreSQL

## 8.1. Profiling

Bổ sung hoặc chuẩn hóa:

```text
metric_scope
metric_source
is_approximate
sample_size
sample_ratio
random_seed
coverage_estimate
profile_confidence
```

Column profile bổ sung:

```text
trimmed_blank_count
distinct_count_including_null
non_null_count
uniqueness_ratio
inferred_type_confidence
inferred_type_evidence_jsonb
semantic_candidates_jsonb
top_values_jsonb
patterns_jsonb
length_summary_jsonb
numeric_summary_jsonb
miscast_examples_jsonb
```

## 8.2. Scoring

Bổ sung:

```text
measurement_coverage
measured_dimension_count
total_dimension_count
score_status
policy_snapshot_jsonb
validation_scope
formula_revision
```

Rule history bổ sung:

```text
conflict_group
primary_scoring_rule
score_enabled
measurement_status_reason
```

---

# 9. Dashboard

## 9.1. Profiling View

Hiển thị:

- Physical dtype
- Inferred type
- Type confidence
- Null
- Blank
- Distinct
- Uniqueness ratio
- Miscast
- Top values
- Pattern
- Length summary
- Numeric summary
- Metric scope

## 9.2. Scoring View

Hiển thị:

- Rule Score
- Measurement status
- Evaluated records
- Null policy
- Severity
- Criticality
- Effective weight
- Contribution
- Conflict status
- Issue samples

## 9.3. Dataset Score

Hiển thị:

```text
DQ Score
Quality Gate
Measured dimensions
Measurement coverage
Validation scope
Scoring policy revision
```

---

# 10. Kế hoạch Triển khai

## Phase 0 — Baseline

- Chạy toàn bộ tests.
- Lưu profiling/scoring output hiện tại.
- Tạo golden fixtures.
- Tạo Git tag.

## Phase 1 — Chuẩn hóa Profiling Metric

- Null
- Blank
- Distinct
- Uniqueness
- Inferred type
- Miscast
- Top values
- Pattern
- Length
- Numeric summary

## Phase 2 — Scan Scope và Sampling

- Full/sample/approximate metadata
- Reproducible sampling
- Resource budget
- Wide dataset lightweight profile

## Phase 3 — Semantic Evidence

- Semantic confidence
- Alternatives
- Evidence
- Unknown/ambiguous policy

## Phase 4 — Canonical Scoring Correctness

- Null policy
- Not applicable
- Not measured
- Evaluated count
- Rule Score golden tests

## Phase 5 — Conflict và Coverage

- Conflict group
- Primary scoring rule
- Measurement coverage
- Provisional score
- Gate precedence

## Phase 6 — Policy Snapshot

- Policy revision
- Formula revision
- Weight snapshot
- Rounding policy

## Phase 7 — Issue Samples và Dashboard

- Persist issue samples
- Profiling evidence UI
- Score coverage UI
- Rule contribution UI

## Phase 8 — PostgreSQL Integration Tests

- Migration
- Repository
- Transaction
- Save/load profile
- Save/load measurement
- Calculate and reload score history

---

# 11. Test Strategy

## Profiling Golden Tests

- Null vs blank
- Whitespace blank
- Distinct excluding null
- All-null column
- Leading-zero identifier
- Mixed type
- Miscast
- Sampled top values
- Pattern stability
- Numeric outlier

## Scoring Golden Tests

- 90 passed / 10 failed
- Missing with fail policy
- Missing with ignore policy
- Not applicable excluded
- Evaluated count = 0
- Rule not measured
- Conflict rules
- Gate-only rule
- Coverage 2/6
- Score high but gate fail

## Parity Tests

- GX và Python trả equivalent canonical measurement.
- Cùng canonical input cho cùng score.
- Cùng policy snapshot tái tạo cùng score.

## Integration Tests

```text
PostgreSQL
→ save profile
→ save validation
→ calculate score
→ save history
→ dashboard reload
```

---

# 12. Tiêu chí Nghiệm thu

## Profiling

- Null và blank tách rõ.
- Distinct và uniqueness dùng công thức thống nhất.
- Inferred type có confidence và evidence.
- Miscast không gộp với missing.
- Top values, pattern, length và numeric summary có metric scope.
- Sampling tái lập được.
- Dataset nhiều cột không deep profile toàn bộ mặc định.

## Scoring

- Not applicable không vào mẫu số.
- Not measured không thành 0.
- Null policy được snapshot.
- Không double-count conflict rules.
- Dataset Score có coverage.
- Policy được snapshot.
- Gate fail ưu tiên hơn score status.
- Full và sampled score được phân biệt.

## Dashboard

- Hiển thị evidence profiling.
- Hiển thị contribution từng rule.
- Hiển thị measurement coverage.
- Hiển thị issue samples.
- Hiển thị scoring policy revision.

---

# 13. Kết luận

Ưu tiên cải thiện:

```text
Chuẩn hóa profiling metric
→ chuẩn hóa scan scope
→ semantic evidence
→ chốt canonical scoring
→ conflict và coverage
→ policy snapshot
→ issue samples
→ dashboard
```

Trước khi phát triển LLM cần chốt:

1. Profiling có evidence rõ ràng và sampling tái lập được.
2. Scoring có golden tests, measurement coverage và không double-count.

Khi đó deterministic recommendation mới có đầu vào đủ tin cậy và Dataset DQ Score mới có ý nghĩa nghiệp vụ rõ ràng.

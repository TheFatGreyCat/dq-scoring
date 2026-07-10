# KẾ HOẠCH LÀM SẠCH VÀ CẢI TIẾN HỆ THỐNG DQ SCORING
## Ưu tiên cleanup, Adaptive Profiling và chuẩn bị phương án thử nghiệm LLM local 4B

## 1. Mục đích

Kế hoạch được chia thành ba mục tiêu theo thứ tự ưu tiên:

1. **Làm sạch hệ thống hiện tại**
   - Loại bỏ các thành phần chỉ phục vụ quá trình chuyển đổi từ kiến trúc cũ.
   - Loại bỏ sample dataset được tạo sẵn trong runtime.
   - Loại bỏ giao diện nhập trực tiếp PostgreSQL URL.
   - Giữ nguyên pipeline đang hoạt động và không làm ảnh hưởng đến kết quả validation, scoring và dashboard.

2. **Cải thiện profiling và rule recommendation**
   - Thu thập thêm thông tin về dataset và cột.
   - Áp dụng full scan hoặc sampling theo kích thước dataset.
   - Có chiến lược riêng cho dataset nhiều cột.
   - Chuẩn hóa Rule Catalog và Rule Template.
   - Cải thiện deterministic recommender trước khi sử dụng LLM.

3. **Lập phương án thử nghiệm LLM local 4B**
   - Chưa tích hợp LLM vào runtime trong giai đoạn này.
   - Chỉ xác định kiến trúc, input/output, prompt, điều kiện gọi LLM và tiêu chí đánh giá.
   - Chỉ triển khai sau khi profiling và deterministic recommender đã có baseline rõ ràng.

Luồng triển khai trong giai đoạn hiện tại:

```text
Cleanup hệ thống
→ Adaptive Profiling
→ Semantic Detection
→ Deterministic Rule Recommendation
→ Rule Review
→ Dataset Rule Binding
→ GX / Python Validation
→ Canonical Measurement
→ Scoring
→ Quality Gate
```

Luồng LLM chỉ là phương án nghiên cứu tiếp theo:

```text
Profile Context
→ Selective Local LLM 4B
→ Structured Output Validation
→ Rule Review
```

---

# 2. Nguyên tắc triển khai

- Cleanup phải thực hiện trước khi thêm module mới.
- Mỗi bước cleanup phải có characterization test hoặc regression test.
- PostgreSQL là runtime database chính.
- Chỉ xóa importer và mã chuyển đổi dùng một lần; không xóa migration runner quản lý schema PostgreSQL hiện tại.
- Profiling phải hoạt động độc lập với LLM.
- Deterministic recommender phải tạo được baseline trước khi thử nghiệm LLM.
- Không gọi LLM cho mọi cột.
- Không gửi toàn bộ dataset hoặc toàn bộ schema rộng vào prompt.
- Rule Catalog là nguồn sự thật của rule.
- LLM không được tạo rule code hoặc code validation mới.
- Hạn chế sử dụng tên gọi theo phiên bản; ưu tiên gọi theo chức năng.

---

# 3. Phạm vi thực hiện

## 3.1. Thực hiện trong kế hoạch này

- Kiểm kê và loại bỏ code chuyển tiếp không còn dùng.
- Loại bỏ SQLite runtime nếu còn tồn tại.
- Loại bỏ importer chuyển dữ liệu từ storage cũ.
- Loại bỏ rule YAML riêng từng dataset.
- Loại bỏ scoring cũ và compatibility adapter.
- Loại bỏ sample dataset runtime.
- Loại bỏ form nhập PostgreSQL URL.
- Thêm System Health Panel.
- Cải thiện profiling.
- Xử lý dataset nhiều dòng và nhiều cột.
- Cải thiện semantic detection.
- Chuẩn hóa Rule Catalog và Rule Template.
- Cải thiện deterministic rule recommendation.
- Xây ground truth và benchmark.
- Lập thiết kế thử nghiệm LLM local 4B.

## 3.2. Chưa thực hiện trong giai đoạn này

- Tích hợp LLM vào orchestration chính.
- Gọi Ollama trong runtime production/demo chính.
- Tự động binding rule bằng LLM.
- Lưu LLM analysis vào PostgreSQL.
- Batch persistence riêng cho LLM.
- Fine-tuning.
- RAG.
- Agent tự vận hành pipeline.
- LLM tự sinh GX/Python code.

---

# 4. Giai đoạn 1 — Baseline và kiểm kê hệ thống

## 4.1. Mục tiêu

Xác định chính xác thành phần nào đang được runtime sử dụng trước khi xóa code.

## 4.2. Công việc

### Chạy baseline

- Chạy toàn bộ unit test.
- Chạy pipeline end-to-end:
  - register dataset;
  - profile;
  - recommend rules;
  - save bindings;
  - validate;
  - score;
  - dashboard.
- Lưu output baseline:
  - profiling result;
  - recommendation result;
  - measurement result;
  - score;
  - quality gate;
  - dashboard row.

### Tạo characterization tests

Bổ sung test cho các hành vi đang có:

- Register CSV.
- Load dataset version.
- Profiling baseline.
- Rule recommendation baseline.
- GX validation.
- Python custom validation.
- Canonical measurement.
- Scoring và Quality Gate.
- Dashboard repository/ViewModel.

### Kiểm kê dependency

Tìm các reference đến:

```text
sqlite
legacy
import_legacy
old scoring
sample generator
sample bootstrap
database URL input
compatibility adapter
per-dataset YAML
feature flag cũ
```

Phân loại:

```text
KEEP
REWRITE
MOVE
DELETE
```

## 4.3. Điều kiện hoàn thành

- Toàn bộ test baseline pass.
- Có danh sách file và chức năng cần xóa.
- Có Git tag hoặc branch rollback.
- Có ít nhất một end-to-end fixture tái hiện pipeline hiện tại.

---

# 5. Giai đoạn 2 — Làm sạch hệ thống

## 5.1. Loại bỏ sample dataset runtime

Xóa khỏi runtime:

- Nút tạo sample dataset.
- Dataset mẫu tự động insert khi khởi động.
- Sample rule bindings sinh sẵn.
- Logic UI phụ thuộc tên dataset demo.
- Seed data chỉ dùng để hiển thị dashboard.

Không xóa dữ liệu phục vụ phát triển. Chuyển chúng sang:

```text
tests/fixtures/
examples/
scripts/load_demo_data.py
```

Kết quả mong muốn:

- Runtime không tự sinh dữ liệu.
- Developer vẫn có thể nạp dữ liệu demo bằng lệnh rõ ràng.
- Regression test vẫn có fixture ổn định.

## 5.2. Loại bỏ giao diện nhập PostgreSQL URL

Không cho người dùng nhập DSN trực tiếp trên Streamlit.

Database connection lấy từ:

```text
DQ_DATABASE_URL
```

hoặc cấu hình server-side.

### Thay thế bằng System Health Panel

Hiển thị:

- PostgreSQL status.
- Database name.
- Host alias.
- Schema status.
- Rule Catalog status.
- Last health check.
- Runtime storage path status.
- Local LLM status chỉ để chuẩn bị, mặc định `Not configured`.

Các nút:

- Refresh status.
- Test PostgreSQL.
- Reload Rule Catalog.
- Open setup guide.

Không hiển thị:

- Password.
- Full connection string.
- Secret environment variables.

## 5.3. Loại bỏ code chuyển tiếp

### Xóa

- SQLite runtime repository.
- SQLite runtime config.
- Importer chuyển metadata/rule từ storage cũ.
- Script chuyển YAML/SQLite cũ sang PostgreSQL.
- Per-dataset YAML runtime loader.
- Mapping chỉ phục vụ format rule cũ.
- Compatibility dataframe/model adapter không còn caller.
- Scoring cũ.
- Hàm scoring trực tiếp từ raw evaluator output.
- Legacy CLI aliases.
- Feature flags chỉ dùng cho giai đoạn chuyển tiếp.
- Test chỉ kiểm tra importer dùng một lần.

### Giữ

- PostgreSQL repository.
- PostgreSQL migration runner.
- Các migration tạo schema runtime hiện tại.
- Dataset metadata và dataset version.
- Rule Catalog.
- Dataset Rule Binding.
- GX runner.
- Python custom-rule runner.
- Canonical Measurement.
- Scoring Engine.
- Quality Gate.
- Orchestration facade.
- Test fixtures.
- Rule Catalog bootstrap.

Lưu ý:

> Không xóa cơ chế schema migration PostgreSQL. Chỉ xóa các script/importer dùng để chuyển dữ liệu từ kiến trúc cũ sang hệ thống hiện tại.

## 5.4. Làm sạch validation

Không xóa toàn bộ Python evaluator.

### Chuyển sang GX

- Not null.
- Regex.
- Domain.
- Range.
- Length.
- Type.
- Single-column uniqueness.

### Giữ Python

- Cross-field comparison.
- Conditional required.
- Composite uniqueness.
- Full-row duplicate.
- Freshness.
- Schema drift.
- Custom reference lookup.

## 5.5. Làm sạch dashboard

Tạo ViewModel hiện tại:

```python
class DatasetDashboardRow:
    dataset_id: str
    dataset_name: str
    dataset_version_id: str
    dq_score: float | None
    score_status: str
    quality_gate_status: str
    last_run_at: datetime | None
```

Luồng:

```text
PostgreSQL
→ Repository
→ Dashboard ViewModel
→ Streamlit
```

Không còn:

```text
PostgreSQL
→ compatibility dataframe
→ Streamlit
```

## 5.6. Điều kiện hoàn thành

- PostgreSQL là runtime database duy nhất.
- Dashboard không dùng adapter cũ.
- Runtime không tự tạo sample dataset.
- UI không có ô nhập DSN.
- Pipeline end-to-end giữ nguyên kết quả baseline hoặc có thay đổi được giải thích.
- Static search không còn runtime import tới code chuyển tiếp.

---

# 6. Giai đoạn 3 — Cải thiện Adaptive Profiling

## 6.1. Mục tiêu

Mở rộng profiling nhưng không triển khai toàn bộ metric phức tạp ngay từ đầu.

Chia thành ba tầng:

```text
Tier 1: schema và basic statistics
Tier 2: semantic và pattern
Tier 3: cross-column và advanced analysis
```

## 6.2. Tier 1 — Basic profile

### Dataset-level

- Row count.
- Column count.
- File size.
- Estimated memory usage.
- Missing cell ratio.
- Duplicate row ratio.
- Schema fingerprint.
- Scan duration.

### Column-level

- Original name.
- Normalized name.
- Physical dtype.
- Inferred logical type.
- Null count và ratio.
- Blank count và ratio.
- Distinct count và ratio.
- String length summary.
- Numeric parse ratio.
- Datetime parse ratio.
- Boolean parse ratio.

Tier 1 chạy trên mọi dataset.

## 6.3. Tier 2 — Semantic và pattern

- Pattern signatures.
- Top values.
- Character-class distribution.
- Leading-zero ratio.
- Whitespace ratio.
- Case distribution.
- Masked examples.
- Semantic candidates.
- Semantic confidence.
- Key likelihood.
- Mandatory candidate.
- Categorical likelihood.

Tier 2 chạy:

- Full scan với dataset nhỏ.
- Sample với dataset lớn.
- Selective deep scan với cột ambiguous.

## 6.4. Tier 3 — Advanced analysis

- Cross-column relationship.
- Composite-key candidate.
- Start/end relationship.
- Created/updated relationship.
- Numeric calculation relationship.
- Conditional dependency.
- Outlier summary.

Tier 3 không chạy mặc định cho mọi cột. Chỉ chạy khi:

- Tên cột cho thấy có quan hệ.
- Semantic group phù hợp.
- Người dùng yêu cầu.
- Deterministic recommender cần thêm evidence.
- Cột được đánh dấu critical.

---

# 7. Chiến lược scan theo số dòng

## 7.1. Full scan

Chạy full scan nếu dataset nằm trong ngân sách tài nguyên.

Không chỉ dựa trên row count. Sử dụng:

```text
row_count
column_count
file_size
estimated_memory
dtype_distribution
configured_time_budget
```

Giá trị baseline để thử nghiệm:

```text
FULL_SCAN_ROW_LIMIT = 100_000
FULL_SCAN_SIZE_LIMIT = 100 MB
```

## 7.2. Sampling

Dataset lớn dùng sample hỗn hợp:

```text
random sample
+ head rows
+ tail rows
+ null-heavy rows
+ duplicate candidates
+ rare-value candidates nếu chi phí cho phép
```

Cấu hình baseline:

```text
sample_ratio = 0.05
min_sample = 5_000
max_sample = 50_000
```

## 7.3. Metric luôn chạy toàn bộ khi chi phí thấp

- Row count.
- Null count.
- Schema metadata.
- Basic duplicate metadata.
- Basic distinct approximation.

## 7.4. Metric dùng sample

- Pattern mining.
- Top values chi tiết.
- Semantic examples.
- Outlier detection.
- Cross-field evidence.

## 7.5. Profile metadata

Lưu:

```text
scan_mode
sample_method
sample_size
sample_ratio
random_seed
coverage_estimate
profile_confidence
```

Trong giai đoạn đầu, `profile_confidence` không dùng công thức tùy ý để auto-bind. Chỉ dùng như metadata mô tả chất lượng scan.

---

# 8. Xử lý dataset có nhiều cột

## 8.1. Nguyên tắc

Dataset nhiều cột không đồng nghĩa phải phân tích sâu tất cả các cột.

Quy trình:

```text
Lightweight scan toàn bộ schema
→ phân nhóm cột
→ tính priority
→ deep profile cột cần thiết
→ deterministic recommendation
→ review
```

## 8.2. Lightweight schema scan

Chạy trên tất cả các cột:

```text
column_name
normalized_name
physical_dtype
inferred_type
null_ratio
distinct_ratio
basic length
parse ratio
basic pattern
field role nếu có
```

## 8.3. Column grouping

Nhóm:

- Identifier.
- Contact.
- Datetime.
- Numeric.
- Financial.
- Categorical.
- Free text.
- Constant/near-constant.
- Unknown/ambiguous.

## 8.4. Priority

Baseline:

```text
ColumnPriority =
SemanticUncertainty
+ FieldCriticality
+ RuleAmbiguity
+ CrossFieldPotential
```

Không cần chốt trọng số ngay. Trong giai đoạn đầu có thể dùng rule-based priority:

```text
critical field
→ ambiguous semantic
→ unclear name
→ multiple rule candidates
→ cross-field potential
→ normal column
```

## 8.5. Chính sách theo số lượng cột

| Số cột | Cách xử lý |
|---:|---|
| ≤ 50 | Profile bình thường |
| 51–200 | Lightweight scan toàn bộ, deep profile theo nhóm |
| 201–500 | Priority-based profiling, giới hạn advanced metrics |
| > 500 | Budget-based profiling, chỉ deep profile cột critical/ambiguous |

## 8.6. Cross-column analysis

Không chạy all-pairs.

Luồng:

```text
name filter
→ type compatibility
→ semantic group
→ shortlist
→ relation check
```

Chỉ so sánh:

- Datetime với datetime.
- Numeric với numeric.
- Identifier với identifier.
- Các cột trong cùng semantic group.
- Các cột có metadata hoặc tên gợi ý quan hệ.

## 8.7. Điều kiện hoàn thành

- Có fixture ít nhất 300 cột.
- Không chạy advanced profile cho toàn bộ cột mặc định.
- Không chạy all-pairs.
- Có thống kê:
  - total columns;
  - lightweight-profiled;
  - deep-profiled;
  - skipped advanced analysis.

---

# 9. Giai đoạn 4 — Cải thiện Rule Catalog

## 9.1. Mục tiêu

Chuẩn hóa rule để deterministic recommender đủ chính xác trước khi thử nghiệm LLM.

## 9.2. Rule Template đề xuất

```yaml
rule_code: IDENTIFIER_UNIQUE
rule_name: Identifier must be unique

rule_category: general
dimension: Uniqueness

management_scope: framework
target_scope: column
evaluation_scope: column_aggregate

operator: unique

backend_support:
  - gx
  - python

applicability:
  any:
    - semantic_type: identifier
    - field_role: business_key
  conditions:
    min_distinct_ratio: 0.90
    allowed_inferred_types:
      - string
      - integer

exclusions:
  column_name_patterns:
    - category_id
    - type_id

parameters_schema:
  mostly:
    type: number
    minimum: 0
    maximum: 1

defaults:
  mostly: 1.0
  severity: high
  null_policy: separate
  score_enabled: true
  gate_enabled: false
  scoring_method: pass_ratio

recommendation:
  priority: 80
  auto_bind_allowed: false
  requires_user_review: true

conflict_group: identifier_uniqueness

catalog_tags:
  - identifier
  - uniqueness

template_status: active

description_for_recommendation: >
  Apply when a column represents a record identifier or business key
  and values are expected to be unique.
```

## 9.3. Trường cần chuẩn hóa

- `backend_support`.
- `parameters_schema`.
- `applicability`.
- `exclusions`.
- `conflict_group`.
- `catalog_tags`.
- `template_status`.
- `recommendation.priority`.
- `requires_user_review`.
- `description_for_recommendation`.

## 9.4. Conflict policy

Ví dụ:

```text
NOT_NULL
NOT_BLANK
MANDATORY_COMPLETENESS
```

Policy:

- Ưu tiên rule cụ thể hơn.
- Không để nhiều rule cùng trừ điểm một lỗi.
- Companion rule có thể chỉ validation.
- Conflict resolution chạy ở cấp dataset.
- Auto-bind tạm thời tắt trong giai đoạn cải thiện.

---

# 10. Giai đoạn 5 — Deterministic Rule Recommendation

## 10.1. Candidate filtering

Lọc Rule Catalog theo:

- target scope;
- evaluation scope;
- physical/inferred type;
- semantic type;
- required columns;
- field roles;
- exclusions;
- backend support;
- template status.

## 10.2. Candidate score

Baseline:

```text
deterministic_score =
0.25 × name_match
+ 0.20 × type_match
+ 0.25 × semantic_match
+ 0.20 × profile_match
+ 0.10 × role_match
```

Trọng số phải được calibration bằng ground truth.

## 10.3. Rule ambiguity

Ghi nhận:

```text
top_rule_score
second_rule_score
score_margin
candidate_count
```

Nếu `score_margin` thấp, cột được đánh dấu `needs_review`.

## 10.4. Decision policy trong giai đoạn này

```text
high deterministic confidence
→ pre-select suggestion

medium/ambiguous
→ user review

low confidence
→ diagnostic only
```

Chưa auto-bind bằng confidence tự động.

## 10.5. Điều kiện hoàn thành

- Recommendation chạy hoàn toàn không cần LLM.
- Mỗi candidate có score và reason.
- Không đề xuất rule không applicable.
- Có benchmark Precision@K/Recall@K.
- Có danh sách cột ambiguous để phục vụ LLM feasibility study.

---

# 11. Giai đoạn 6 — Đánh giá baseline

## 11.1. Ground truth

Tạo tập dữ liệu gồm:

- Dataset ít cột.
- Dataset nhiều cột.
- Cột viết tắt.
- Cột đổi tên.
- Wrong dtype.
- Mixed type.
- Null, duplicate và format error.
- Cột critical.
- Cross-field candidates.
- Cột có nhiều semantic candidate.

Nhãn:

```text
expected semantic type
expected applicable rules
forbidden rules
expected parameters
needs_review
```

## 11.2. Metrics

### Semantic detection

- Accuracy.
- Macro F1.
- Per-class precision/recall.

### Rule recommendation

- Precision@3.
- Recall@3.
- Mean Reciprocal Rank.
- Wrong recommendation rate.
- User acceptance rate.
- Conflict rate.

### Performance

- Profiling duration.
- Full scan/sample duration.
- Wide dataset duration.
- Deep-profiled column ratio.
- Recommendation duration.

## 11.3. Điều kiện để nghiên cứu LLM tiếp

Chỉ thực hiện LLM spike nếu:

- Deterministic baseline đã ổn định.
- Có tập ambiguous columns.
- Rule Catalog đủ rule để rerank.
- Có holdout dataset.
- Có tiêu chí đo LLM cải thiện hay không.

---

# 12. Phương án thử nghiệm LLM local 4B
## Chưa triển khai trong runtime

## 12.1. Mục tiêu

Đánh giá xem local LLM 4B có cải thiện recommendation trên các cột khó hay không.

Không dùng LLM cho:

- Mọi cột.
- Full dataset scan.
- Tất cả General Rules rõ ràng.
- Tự động binding.
- Tự sinh rule hoặc code validation.

## 12.2. Điều kiện gọi LLM dự kiến

LLM chỉ xử lý cột thỏa ít nhất một điều kiện:

1. Semantic confidence thấp.
2. Tên cột viết tắt, khó hiểu hoặc không rõ nghĩa.
3. Có nhiều semantic candidate gần nhau.
4. Cột được đánh dấu Business Key, CDE hoặc Mandatory.
5. Cột có khả năng tham gia cross-field rule.
6. Deterministic recommender trả nhiều rule có điểm gần nhau.
7. Cột critical nhưng profiling chưa đủ evidence.

Điều kiện logic:

```text
llm_required =
semantic_confidence < threshold
OR unclear_column_name
OR semantic_candidate_ambiguity
OR critical_field
OR cross_field_potential
OR rule_score_margin < margin_threshold
```

## 12.3. Dataset nhiều cột

Không gửi toàn bộ schema.

Quy trình dự kiến:

```text
Lightweight scan
→ deterministic recommendation
→ select ambiguous/critical columns
→ group columns
→ batch 5–8 columns
→ LLM reranking
```

Giới hạn thử nghiệm:

```text
max columns per request = 8
max candidates per column = 5–8
max columns per dataset = 50 hoặc 100
max context tokens = 4.000–6.000
concurrency = 1
```

Khi vượt budget:

- Giữ deterministic result.
- Critical columns được đưa vào manual review.
- Không làm pipeline fail.

## 12.4. Prompt dự kiến

```text
ROLE
Bạn là bộ xếp hạng rule chất lượng dữ liệu.

TASK
Với từng cột, chọn tối đa 3 rule phù hợp nhất từ candidate_rules.

CONSTRAINTS
- Chỉ dùng rule_code trong candidate_rules.
- Không tạo rule mới.
- Không sinh code.
- Nếu thiếu thông tin, requires_review=true.
- Business/Technical/Cross-field Rule luôn requires_review=true.
- Reason tối đa 30 từ.
- Không trả văn bản ngoài JSON.

INPUT
- dataset_summary
- column_profiles
- related_columns
- candidate_rules

OUTPUT
JSON theo schema.
```

## 12.5. Output contract dự kiến

```python
class RuleSuggestion:
    rule_code: str
    confidence: float
    reason: str
    suggested_parameters: dict
    requires_review: bool
    risk_flags: list[str]

class ColumnRecommendation:
    column_name: str
    semantic_type: str
    semantic_confidence: float
    recommendations: list[RuleSuggestion]
```

## 12.6. Kiểm soát đầu ra

```text
LLM response
→ JSON parsing
→ schema validation
→ candidate-list validation
→ rule lookup
→ applicability validation
→ parameter validation
→ conflict check
→ manual review
```

Reject nếu:

- Rule không thuộc candidate list.
- Output sai schema.
- Confidence ngoài 0–1.
- Target column không tồn tại.
- Parameter sai schema.
- Rule không applicable.
- LLM yêu cầu auto-bind Business/Technical/Cross-field Rule.

## 12.7. Tiêu chí go/no-go

So sánh:

```text
Deterministic only
vs
Deterministic + selective LLM
```

Chỉ triển khai nếu LLM:

- Tăng Precision@3 hoặc Recall@3 trên ambiguous columns.
- Giảm thời gian manual review.
- Không tăng wrong recommendation rate.
- Structured output pass ổn định.
- Latency chấp nhận được.
- Không cần gửi dữ liệu nhạy cảm.
- Có thể chạy trên phần cứng mục tiêu.

Nếu không đạt, giữ deterministic recommender và manual review.

---

# 13. Thay đổi giao diện

## 13.1. Onboarding

Luồng:

```text
1. Upload CSV
2. Profiling
3. Review semantic type
4. Confirm metadata
5. Review rule suggestions
6. Save bindings
7. Run validation and scoring
```

Chưa thêm bước LLM vào UI chính.

## 13.2. System Health Panel

Hiển thị:

- PostgreSQL status.
- Schema status.
- Rule Catalog status.
- Runtime config.
- Local LLM status: `Not implemented` hoặc `Experimental`, nếu cần hiển thị roadmap.

## 13.3. Dataset nhiều cột

Hiển thị:

```text
Total columns
Lightweight-profiled
Deep-profiled
Needs review
Rules suggested
Advanced analysis skipped
```

Có:

- Group view.
- Filter.
- Pagination.
- Bulk confirm semantic type.
- Bulk accept/reject rule suggestions.

---

# 14. Kế hoạch triển khai tổng thể

## Phase 0 — Baseline và characterization tests

- Tạo Git tag.
- Chạy tests.
- Ghi output baseline.
- Tạo dependency inventory.

## Phase 1 — Cleanup runtime

- Xóa sample runtime.
- Xóa PostgreSQL URL input.
- Thêm System Health Panel.
- Xóa importer và SQLite runtime.
- Xóa compatibility adapter.
- Xóa scoring cũ.
- Giữ schema migration PostgreSQL.
- Chạy regression tests.

## Phase 2 — Adaptive Profiling tối thiểu

- Tier 1 metrics.
- Full scan/sample policy.
- Profile metadata.
- Reproducible sampling.

## Phase 3 — Wide Dataset Strategy

- Lightweight scan.
- Column grouping.
- Priority.
- Selective deep profiling.
- Cross-field shortlist.
- UI summary.

## Phase 4 — Semantic và Rule Catalog

- Tier 2 profiling.
- Semantic confidence.
- Rule Template chuẩn hóa.
- Applicability.
- Exclusions.
- Conflict groups.

## Phase 5 — Deterministic Recommender

- Candidate filtering.
- Candidate scoring.
- Rule ambiguity.
- Review workflow.
- Benchmark.

## Phase 6 — Advanced profiling có kiểm soát

- Cross-field.
- Composite-key candidates.
- Outlier analysis.
- Chỉ chạy theo signal hoặc user request.

## Phase 7 — LLM feasibility study

- Chuẩn bị ambiguous-column set.
- Chạy local model offline/experimental.
- So sánh baseline.
- Ra quyết định go/no-go.

---

# 15. Test Strategy

## Cleanup tests

- Runtime không dùng SQLite.
- CLI không gọi importer cũ.
- Không load per-dataset YAML.
- Runtime không tạo sample dataset.
- UI không hiển thị DSN.
- Pipeline output không đổi ngoài phần được chấp thuận.

## Profiling tests

- Full scan.
- Sampling.
- Reproducible random seed.
- Mixed dtype.
- Null/blank.
- Wide dataset 300+ columns.
- Selective deep profiling.
- No all-pairs cross-field scan.

## Rule tests

- Applicability.
- Exclusions.
- Parameter schema.
- Conflict group.
- Backend support.
- Candidate score.
- Rule ambiguity.

## End-to-end tests

```text
Upload
→ Profile
→ Semantic Detection
→ Recommend
→ Review
→ Bind
→ Validate
→ Score
```

## LLM study tests

Chỉ dùng trong feasibility branch:

- Prompt builder.
- JSON schema.
- Invalid output rejection.
- Candidate-list enforcement.
- Sensitive-data masking.
- Timeout handling.

---

# 16. Rủi ro và kiểm soát

| Rủi ro | Kiểm soát |
|---|---|
| Cleanup làm gãy pipeline | Characterization tests, Git tag, xóa theo caller |
| Xóa nhầm migration cần thiết | Chỉ xóa importer chuyển tiếp, giữ schema migration |
| Profiling quá nặng | Tiered profiling và resource budget |
| Sampling sai lệch | Mixed sampling và lưu coverage metadata |
| Dataset nhiều cột | Lightweight scan, grouping, selective deep profile |
| Cross-field bùng nổ | Không all-pairs, chỉ shortlist |
| Rule recommendation sai | Applicability, exclusions, conflict policy và review |
| LLM không tạo giá trị | Chỉ làm feasibility study sau deterministic baseline |
| LLM trả lan man | Prompt ngắn và structured JSON |
| Gọi LLM quá nhiều | Selective invocation và budget |
| Lộ dữ liệu | Masking, local model, không gửi raw data |

---

# 17. Tiêu chí nghiệm thu

## Cleanup

- Không còn SQLite runtime.
- Không còn importer chuyển tiếp.
- Không còn scoring cũ.
- Không còn per-dataset YAML runtime.
- Không còn compatibility adapter.
- Không còn sample runtime.
- Không còn PostgreSQL URL input.
- Schema migration PostgreSQL vẫn hoạt động.
- Pipeline end-to-end pass.

## Profiling

- Có Tier 1 và Tier 2 rõ ràng.
- Có full scan/sample policy.
- Có xử lý wide dataset.
- Có reproducible sampling.
- Có profile metadata.
- Advanced analysis không chạy mặc định cho mọi cột.

## Rule recommendation

- Rule Template có applicability và exclusions.
- Deterministic recommender chạy độc lập.
- Có ambiguity score/margin.
- Có review workflow.
- Có benchmark.

## LLM feasibility plan

- Có điều kiện lựa chọn cột.
- Có prompt ngắn.
- Có output schema.
- Có validation policy.
- Có wide-dataset budget.
- Có tiêu chí go/no-go.
- Chưa ảnh hưởng runtime chính.

---

# 18. Kết luận

Thứ tự triển khai:

```text
Cleanup
→ Adaptive Profiling
→ Wide Dataset Handling
→ Rule Catalog Improvement
→ Deterministic Recommendation
→ Baseline Evaluation
→ LLM Feasibility Study
```

Trong giai đoạn hiện tại, hệ thống chưa tích hợp LLM.

LLM local 4B chỉ được lập phương án thử nghiệm sau khi:

- hệ thống đã được làm sạch;
- profiling đã ổn định;
- Rule Catalog đã rõ applicability;
- deterministic recommender đã có baseline;
- có tập cột ambiguous để đánh giá.

Cách tiếp cận này giảm rủi ro over-engineering, tránh làm thay đổi quá nhiều module cùng lúc và cho phép chứng minh rõ LLM có thực sự cải thiện recommendation hay không trước khi tích hợp.

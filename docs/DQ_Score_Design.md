# Tài liệu thiết kế triển khai Module phát hiện lỗi phổ biến và tính DQ Core Score

**Dự án:** Chấm điểm Chất lượng Dữ liệu (DQ Scoring)  
**Module:** Rules Engine + Scoring Engine Integration  
**Hạng mục:** Tích hợp module phát hiện lỗi phổ biến, chạy thử trên dataset mẫu và tính điểm DQ Core Score  
**Giai đoạn:** Phase 1 – Khung đo lường và hệ thống tính điểm cơ bản  
**Tài liệu liên quan:** `DQ_Framework`, `DQ_Scoring_Model`, `Profiling_Pipeline_Design`, `Rules_Engine_Design`

|Phiên bản|Ngày|Người thực hiện|Mô tả thay đổi|
|---|---|---|---|
|1.0|01/07/2026|Nguyễn Hoàng Tùng|Khởi tạo tài liệu thiết kế triển khai module phát hiện lỗi phổ biến và tính DQ Core Score|

## 1. Giới thiệu

### 1.1 Mục đích

Tài liệu này mô tả thiết kế triển khai cho hạng mục **tích hợp module phát hiện lỗi phổ biến**, chạy thử trên dataset mẫu và tính điểm chất lượng dữ liệu ở mức **DQ Core Score** trong Phase 1.

Trong tài liệu này, thuật ngữ **DQ Score** được hiểu là **DQ Core Score** – điểm chất lượng kỹ thuật tổng hợp của dataset, được tính từ các dimension chất lượng dữ liệu như Completeness, Validity, Uniqueness, Timeliness, Accuracy Proxy và Consistency.

`TrustScore` và `Final Dataset Score` chưa thuộc phạm vi triển khai chính của hạng mục này. Các điểm này chỉ được tích hợp khi hệ thống đã có đủ metadata, certification hoặc dữ liệu vận hành tương ứng.

Hạng mục này tập trung vào các lỗi dữ liệu phổ biến, có thể phát hiện bằng rule rõ ràng:

- Lỗi thiếu dữ liệu: `null`, `blank`.
    
- Lỗi trùng lặp: duplicate key, duplicate row.
    
- Lỗi sai định dạng: email sai format, phone sai format.
    
- Lỗi sai kiểu dữ liệu: giá trị không ép được về kiểu kỳ vọng.
    
- Lỗi freshness cơ bản: dữ liệu vượt ngưỡng cập nhật cho phép.
    
- Lỗi giá trị ngoài khoảng hợp lý đơn giản: ví dụ `age` nằm ngoài khoảng `[0, 120]`.
    

Tài liệu này là **tài liệu thiết kế triển khai**, không phải báo cáo kết quả chạy thực tế. Tài liệu mô tả cần xây dựng gì, luồng xử lý như thế nào, output mong muốn là gì và cần kiểm thử ra sao.

### 1.2 Mục tiêu triển khai

Mục tiêu của hạng mục gồm:

- Tích hợp Rules Engine với dataset mẫu và rule config.
    
- Cấu hình bộ rule phát hiện lỗi phổ biến.
    
- Chuẩn hóa kết quả kiểm tra thành `Rule Evaluation Result`.
    
- Chuyển kết quả rule sang Scoring Engine.
    
- Tính `RuleScore`, `DimensionScore` và `DQ Core Score`.
    
- Thiết kế báo cáo kiểm thử để xác nhận module hoạt động đúng phạm vi Phase 1.
    

Mục tiêu không phải là phát hiện mọi lỗi dữ liệu nâng cao, mà là xây dựng một luồng kiểm tra nền tảng, deterministic, explainable và có thể mở rộng.

## 2. Phạm vi triển khai Phase 1

### 2.1 Trong phạm vi

|Nhóm lỗi|Mô tả|Dimension liên quan|
|---|---|---|
|Null / blank|Trường bắt buộc bị thiếu giá trị|Completeness|
|Duplicate key|Khóa định danh bị trùng|Uniqueness|
|Duplicate row|Dòng dữ liệu trùng hoàn toàn|Uniqueness|
|Format sai|Email, số điện thoại, mã định danh sai pattern|Validity|
|Sai kiểu dữ liệu|Giá trị không ép được sang kiểu kỳ vọng|Validity|
|Range / plausibility đơn giản|Giá trị nằm ngoài khoảng hợp lý|Accuracy Proxy|
|Freshness cơ bản|Dữ liệu vượt ngưỡng cập nhật cho phép|Timeliness|

### 2.2 Ngoài phạm vi

Các nội dung sau chưa triển khai trong hạng mục này:

- Cross-system matching với CRM, KYC hoặc core system.
    
- Fuzzy matching / near-duplicate detection.
    
- AI-assisted anomaly detection.
    
- Data drift detection nâng cao.
    
- Workflow phê duyệt rule nhiều cấp.
    
- Streaming validation realtime.
    
- Root-cause analysis tự động.
    
- Tự động sinh official rule trong lúc chạy Rules Engine.
    
- Tính `TrustScore` đầy đủ dựa trên usage/feedback.
    
- Tính `Final Dataset Score` đầy đủ nếu chưa có đủ metadata/certification.
    

Các nội dung trên được đưa sang Phase 2 hoặc giai đoạn production hardening.

## 3. Căn cứ thiết kế

Hạng mục triển khai dựa trên 4 tài liệu nền:

|Tài liệu|Vai trò|
|---|---|
|`DQ_Framework`|Định nghĩa 6 trụ cột chất lượng dữ liệu và phạm vi đo lường Phase 1|
|`DQ_Scoring_Model`|Định nghĩa công thức tính `RuleScore`, `DimensionScore`, `DQ Core Score`|
|`Profiling_Pipeline_Design`|Cung cấp Profile Result, Candidate Rule và thống kê dataset/cột|
|`Rules_Engine_Design`|Định nghĩa rule config, rule execution và `Rule Evaluation Result`|

Luồng tích hợp đầy đủ:

```text
Dataset mẫu
→ Profiling Pipeline
→ Rules Engine
→ Rule Evaluation Result
→ Scoring Engine
→ DQ Core Score
→ Báo cáo kiểm thử / Dashboard
```

Trong trường hợp rule config đã được chuẩn bị sẵn, Profiling Pipeline có thể được dùng như bước tiền xử lý hoặc tham khảo, không bắt buộc nằm trong mỗi lần chạy Rules Engine.

Luồng tối thiểu cho hạng mục này:

```text
Dataset mẫu
→ Rules Engine
→ Rule Evaluation Result
→ Scoring Engine
→ DQ Core Score
→ Báo cáo kiểm thử
```

## 4. Kiến trúc tích hợp

### 4.1 Vai trò của từng module

|Module|Vai trò|
|---|---|
|Profiling Pipeline|Đọc dataset, trích xuất thống kê, sinh candidate rule và anomaly flag|
|Rules Engine|Chạy rule chính thức đã được cấu hình và sinh `Rule Evaluation Result`|
|Scoring Engine|Tính `RuleScore`, `DimensionScore` và `DQ Core Score`|
|Dashboard / Report|Hiển thị kết quả kiểm tra, lỗi phổ biến, điểm số và trạng thái dataset|

### 4.2 Nguyên tắc tích hợp

- Profiling Pipeline không trực tiếp tính điểm DQ.
    
- Candidate rule từ Profiling Pipeline chỉ là gợi ý, không tự động ảnh hưởng đến điểm.
    
- Rules Engine chỉ chạy rule có `status = active`.
    
- Chỉ rule có `score_enabled = true` mới được đưa sang Scoring Engine.
    
- Rules Engine không tính `RuleScore`, `DimensionScore`, `DQ Core Score`, `FinalScore` hoặc `quality_status`.
    
- Scoring Engine chỉ tính điểm từ `Rule Evaluation Result`.
    
- Mỗi rule phải có một dimension chính để tránh double-count.
    
- Rule monitoring có thể chạy nhưng không ảnh hưởng đến `DQ Core Score`.
    
- Các dimension hoặc rule chưa đo được phải được đánh dấu `not_measured`, không gán điểm 0.
    

## 5. Input triển khai

### 5.1 Dataset config

Dataset config mô tả dataset cần kiểm tra.

Thông tin tối thiểu:

|Trường|Mô tả|
|---|---|
|`dataset_id`|Định danh dataset|
|`dataset_name`|Tên dataset|
|`dataset_type`|Loại dataset: master_data, transaction, log_event, reference_data, default|
|`source_type`|Loại nguồn dữ liệu, ví dụ CSV hoặc Parquet|
|`storage_path`|Đường dẫn dữ liệu|
|`declared_schema`|Schema khai báo|
|`primary_key`|Khóa chính|
|`mandatory_fields`|Các trường bắt buộc|
|`timestamp_column`|Cột thời gian dùng cho freshness|
|`sla_config`|Cấu hình SLA hoặc freshness|

Ví dụ dataset mẫu:

```yaml
dataset_id: customer_master
dataset_name: Customer Master
dataset_type: master_data
source_type: csv
storage_path: data/customer_master.csv

primary_key:
  - customer_id

mandatory_fields:
  - customer_id
  - full_name
  - email
  - phone_number

timestamp_column: updated_at

sla_config:
  max_freshness_lag_hours: 24
```

### 5.2 Rule config

Rule config là danh sách rule chính thức được Rules Engine chạy.

Một rule cần có tối thiểu:

|Trường|Mô tả|
|---|---|
|`rule_id`|Định danh rule|
|`rule_name`|Tên rule|
|`dataset_id`|Dataset áp dụng|
|`target_column`|Cột áp dụng, nếu có|
|`dimension`|Dimension chính|
|`rule_type`|Loại rule|
|`parameters`|Tham số rule|
|`null_policy`|`fail` hoặc `ignore`|
|`threshold`|Ngưỡng đánh giá rule|
|`severity`|Mức độ nghiêm trọng|
|`execution_backend`|pandas, gx, sql hoặc spark|
|`status`|active, draft, inactive, deprecated|
|`score_enabled`|Có đưa rule vào Scoring Engine hay không|

Quy ước:

```text
status = active         → rule được Rules Engine chạy
score_enabled = true    → rule được đưa sang Scoring Engine để tính điểm
score_enabled = false   → rule chỉ dùng cho monitoring/dashboard
```

### 5.3 Scoring config

Scoring config quy định trọng số dimension và cách tổng hợp điểm.

Ví dụ với dataset loại `master_data`:

```yaml
dataset_type: master_data

dimension_weights:
  Completeness: 0.25
  Validity: 0.25
  Consistency: 0.15
  Timeliness: 0.10
  Uniqueness: 0.15
  Accuracy: 0.10
```

Nếu một dimension không có rule đo được, dimension đó được đánh dấu `not_measured` và trọng số được tái chuẩn hóa cho các dimension còn lại.

## 6. Bộ rule cần triển khai

### 6.1 Rule phát hiện null / blank

Mục tiêu: phát hiện trường bắt buộc bị thiếu dữ liệu.

|Thuộc tính|Giá trị|
|---|---|
|Dimension|Completeness|
|Rule type|`not_null`, `not_blank`|
|Trạng thái lỗi|`empty`|
|Áp dụng cho|Mandatory fields, CDE fields|

Ví dụ:

```yaml
rule_id: DQ-COMP-CUSTOMER-001
rule_name: Customer ID must not be null
dataset_id: customer_master
target_column: customer_id
dimension: Completeness
rule_type: not_null
null_policy: fail
threshold: 99
severity: critical
execution_backend: pandas
status: active
score_enabled: true
```

```yaml
rule_id: DQ-COMP-PHONE-001
rule_name: Phone number must not be blank
dataset_id: customer_master
target_column: phone_number
dimension: Completeness
rule_type: not_blank
null_policy: fail
threshold: 95
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

### 6.2 Rule phát hiện duplicate

Mục tiêu: phát hiện khóa hoặc bản ghi bị trùng.

|Thuộc tính|Giá trị|
|---|---|
|Dimension|Uniqueness|
|Rule type|`uniqueness`, `composite_uniqueness`, `full_row_duplicate`|
|Trạng thái lỗi|`failed`|
|Áp dụng cho|Primary key, composite key, business key, full-row duplicate|

Ví dụ kiểm tra khóa định danh:

```yaml
rule_id: DQ-UNIQ-CUSTOMER-001
rule_name: Customer ID uniqueness check
dataset_id: customer_master
target_column: customer_id
dimension: Uniqueness
rule_type: uniqueness
parameters:
  key_columns:
    - customer_id
null_policy: ignore
threshold: 99
severity: critical
execution_backend: pandas
status: active
score_enabled: true
```

Ví dụ kiểm tra dòng trùng hoàn toàn:

```yaml
rule_id: DQ-UNIQ-DUPROW-001
rule_name: Full row duplicate check
dataset_id: customer_master
dimension: Uniqueness
rule_type: full_row_duplicate
parameters:
  max_duplicate_ratio: 1
null_policy: ignore
threshold: 99
severity: medium
execution_backend: pandas
status: active
score_enabled: true
```

Rule type chuẩn trong Phase 1 cho kiểm tra dòng trùng hoàn toàn là `full_row_duplicate`. Tên rule type này cần được thống nhất giữa code, rule config và tài liệu.

### 6.3 Rule phát hiện format sai

Mục tiêu: phát hiện giá trị có dữ liệu nhưng sai định dạng.

|Thuộc tính|Giá trị|
|---|---|
|Dimension|Validity|
|Rule type|`regex`, `length`, `type_check`|
|Trạng thái lỗi|`failed`, `miscast`|
|Áp dụng cho|Email, số điện thoại, mã định danh, ngày tháng|

Ví dụ kiểm tra email:

```yaml
rule_id: DQ-VALI-EMAIL-001
rule_name: Email format check
dataset_id: customer_master
target_column: email
dimension: Validity
rule_type: regex
parameters:
  pattern: "^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$"
null_policy: ignore
threshold: 98
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

Ví dụ kiểm tra số điện thoại:

```yaml
rule_id: DQ-VALI-PHONE-001
rule_name: Phone number format check
dataset_id: customer_master
target_column: phone_number
dimension: Validity
rule_type: regex
parameters:
  pattern: "^[0-9]{10}$"
null_policy: ignore
threshold: 98
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

Ví dụ kiểm tra kiểu dữ liệu tuổi:

```yaml
rule_id: DQ-VALI-AGE-TYPE-001
rule_name: Age must be integer
dataset_id: customer_master
target_column: age
dimension: Validity
rule_type: type_check
parameters:
  expected_type: integer
null_policy: ignore
threshold: 98
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

### 6.4 Rule phát hiện giá trị ngoài khoảng hợp lý

Mục tiêu: kiểm tra dữ liệu có nằm trong khoảng hợp lý nghiệp vụ hay không.

|Thuộc tính|Giá trị|
|---|---|
|Dimension|Accuracy Proxy|
|Rule type|`plausibility_range`|
|Trạng thái lỗi|`failed`, `miscast`|
|Áp dụng cho|Tuổi, số tiền, tỉ lệ phần trăm, số lượng|

Ví dụ:

```yaml
rule_id: DQ-ACCU-AGE-001
rule_name: Age plausibility check
dataset_id: customer_master
target_column: age
dimension: Accuracy
rule_type: plausibility_range
parameters:
  min_value: 0
  max_value: 120
null_policy: ignore
threshold: 95
severity: medium
execution_backend: pandas
status: active
score_enabled: true
```

Lưu ý: Đây là Accuracy Proxy, không phải Accuracy đầy đủ vì chưa đối chiếu với nguồn ground truth.

### 6.5 Rule freshness cơ bản

Mục tiêu: kiểm tra dữ liệu có quá cũ so với ngưỡng SLA hay không.

Có hai cách triển khai:

|Cách triển khai|Evaluation unit|Khi nào dùng|
|---|---|---|
|Dataset-level freshness|`dataset_run`|Kiểm tra toàn dataset có cập nhật đúng hạn không|
|Row-level staleness|`record`|Kiểm tra từng bản ghi có quá cũ không|

Trong Phase 1, nếu rule tên là `Dataset freshness check`, nên dùng `evaluation_unit = dataset_run`.

Ví dụ dataset-level freshness:

```yaml
rule_id: DQ-TIME-UPDATED-001
rule_name: Dataset freshness check
dataset_id: customer_master
target_column: updated_at
dimension: Timeliness
rule_type: freshness
parameters:
  max_freshness_lag_hours: 24
  freshness_time_basis: updated_at
  evaluation_unit: dataset_run
null_policy: ignore
threshold: 95
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

Nếu muốn kiểm tra từng bản ghi, nên đổi tên rule rõ hơn:

```yaml
rule_id: DQ-TIME-UPDATED-ROW-001
rule_name: Row-level updated_at freshness check
dataset_id: customer_master
target_column: updated_at
dimension: Timeliness
rule_type: freshness
parameters:
  max_freshness_lag_hours: 24
  freshness_time_basis: updated_at
  evaluation_unit: record
null_policy: ignore
threshold: 95
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

## 7. Phụ thuộc triển khai

Các thành phần triển khai tối thiểu cần có:

|Thành phần|Vai trò|
|---|---|
|`dataset_loader`|Đọc dataset từ CSV/Parquet|
|`dataset_config_loader`|Đọc dataset config|
|`rule_loader`|Đọc rule config YAML/JSON|
|`rule_config_validator`|Validate rule trước khi chạy|
|`rule_executor`|Điều phối evaluator theo `rule_type`|
|`completeness_evaluator`|Xử lý rule `not_null`, `not_blank`|
|`validity_evaluator`|Xử lý rule `regex`, `length`, `type_check`|
|`uniqueness_evaluator`|Xử lý rule `uniqueness`, `composite_uniqueness`, `full_row_duplicate`|
|`timeliness_evaluator`|Xử lý rule `freshness`|
|`accuracy_proxy_evaluator`|Xử lý rule `plausibility_range`|
|`result_normalizer`|Chuẩn hóa `passed`, `failed`, `miscast`, `empty`, `not_applicable`|
|`rule_result_store`|Lưu output Rules Engine|
|`scoring_engine`|Tính `RuleScore`, `DimensionScore`, `DQ Core Score`|
|`score_store`|Lưu output Scoring Engine|
|`test_report_generator`|Sinh báo cáo kiểm thử hoặc output summary|

Trong Phase 1, các thành phần này có thể triển khai bằng Python, Pandas và SQLite/JSON. Spark, API service hoặc workflow orchestration nâng cao chưa bắt buộc.

## 8. Luồng xử lý triển khai

### 8.1 Luồng tổng quát

```text
Step 1: Load dataset mẫu
Step 2: Load dataset config
Step 3: Load rule config
Step 4: Validate rule config
Step 5: Rules Engine chạy các rule active
Step 6: Chuẩn hóa kết quả thành Rule Evaluation Result
Step 7: Lưu rule_run, rule_config snapshot, rule_evaluation_result, rule_issue_sample
Step 8: Chuyển Rule Evaluation Result sang Scoring Engine
Step 9: Scoring Engine tính RuleScore, DimensionScore và DQ Core Score
Step 10: Sinh báo cáo kiểm thử / dashboard output
```

### 8.2 Luồng Rules Engine

```text
Rule config
→ Rule config validation
→ Rule execution
→ Status classification
→ Result aggregation
→ Rule Evaluation Result
```

Rules Engine chỉ sinh count:

```text
passed
failed
miscast
empty
not_applicable
total_records_in_scope
measurement_status
```

Rules Engine không sinh:

```text
RuleScore
DimensionScore
DQ_Core
FinalScore
quality_status
```

### 8.3 Luồng Scoring Engine

```text
Rule Evaluation Result
→ RuleScore
→ DimensionScore
→ DQ Core Score
→ Dataset Score History / Dashboard
```

Scoring Engine sử dụng công thức trong `DQ_Scoring_Model` để tính điểm.

## 9. Thiết kế output

### 9.1 Output từ Rules Engine

|Output|Mô tả|
|---|---|
|`rule_run`|Metadata của lần chạy Rules Engine|
|`rule_config`|Snapshot rule được sử dụng trong lần chạy|
|`rule_evaluation_result`|Kết quả đếm theo từng rule|
|`rule_issue_sample`|Mẫu lỗi phục vụ debug/dashboard|

Ví dụ `rule_evaluation_result`:

```json
{
  "rule_run_id": "RRUN_20260701_001",
  "rule_id": "DQ-VALI-EMAIL-001",
  "dataset_id": "customer_master",
  "target_column": "email",
  "dimension": "Validity",
  "evaluation_unit": "record",
  "passed": 9,
  "failed": 1,
  "miscast": 0,
  "empty": 0,
  "not_applicable": 0,
  "total_records_in_scope": 10,
  "threshold": 98,
  "measurement_status": "measured"
}
```

Ví dụ trên chỉ minh họa format output, không phải kết quả chạy thực tế.

### 9.2 Output từ Scoring Engine

|Output|Mô tả|
|---|---|
|`rule_score_history`|Điểm từng rule|
|`dimension_score_history`|Điểm theo từng dimension|
|`dataset_score_history`|DQ Core Score và trạng thái chất lượng dataset|

Ví dụ output ở cấp rule:

```json
{
  "run_id": "SRUN_20260701_001",
  "dataset_id": "customer_master",
  "rule_id": "DQ-VALI-EMAIL-001",
  "dimension": "Validity",
  "rule_score": 90.0,
  "threshold": 98,
  "quality_status": "fail"
}
```

Ví dụ trên chỉ minh họa format output, không phải kết quả chạy thực tế.

## 10. Công thức tính điểm

### 10.1 RuleScore

```text
RuleScore = passed / total_records_in_scope × 100
```

Trong đó:

```text
total_records_in_scope = passed + failed + miscast + empty
```

`not_applicable` không được đưa vào mẫu số.

Nếu `total_records_in_scope = 0`, rule không được tính điểm và cần được đánh dấu `not_measured` hoặc `skipped` tùy nguyên nhân.

### 10.2 DimensionScore

Trong Phase 1, sử dụng weighted average:

```text
DimensionScore = Σ (normalized_rule_weight_i × RuleScore_i)
```

Nếu chưa có trọng số riêng cho từng rule, có thể dùng trung bình cộng các rule thuộc cùng dimension.

Chỉ các rule có `measurement_status = measured` mới được đưa vào công thức.

### 10.3 DQ Core Score

```text
DQ_Core = Σ (dimension_weight_i × DimensionScore_i)
```

Nếu một dimension không có rule đo được, dimension đó không bị gán điểm 0. Dimension đó được đánh dấu `not_measured` và trọng số được tái chuẩn hóa cho các dimension còn lại.

Trong phạm vi tài liệu này, điểm tổng hợp cần triển khai là `DQ Core Score`. `FinalScore` không bắt buộc trong hạng mục này.

## 11. Thiết kế kiểm thử

### 11.1 Mục tiêu kiểm thử

Kiểm thử nhằm xác nhận:

- Dataset config được load đúng.
    
- Rule config được load đúng.
    
- Rule config được validate trước khi chạy.
    
- Rules Engine chỉ chạy rule có `status = active`.
    
- Rule `score_enabled = false` không được đưa vào Scoring Engine.
    
- Module phát hiện được lỗi null/blank.
    
- Module phát hiện được lỗi duplicate.
    
- Module phát hiện được lỗi format sai.
    
- Module phát hiện được lỗi sai kiểu dữ liệu.
    
- Module phân loại đúng `passed`, `failed`, `miscast`, `empty`, `not_applicable`.
    
- Rule thiếu cột hoặc thiếu metadata được đánh dấu `not_measured`.
    
- Scoring Engine tính đúng `RuleScore`, `DimensionScore`, `DQ Core Score`.
    
- Dimension/rule `not_measured` không bị gán điểm 0 sai bản chất.
    

### 11.2 Test case đề xuất

|Test case|Mục tiêu|Kết quả kỳ vọng|Loại|
|---|---|---|---|
|TC01|Load dataset mẫu|Dataset được đọc thành công|Integration|
|TC02|Load rule config|Rule config được đọc thành công|Unit/Integration|
|TC03|Validate rule config hợp lệ|Rule hợp lệ được chấp nhận|Unit|
|TC04|Validate rule config thiếu field|Rule thiếu field bắt buộc bị đánh dấu lỗi|Unit|
|TC05|Chạy rule `not_null`|Null/blank được ghi nhận `empty`|Unit|
|TC06|Chạy rule uniqueness|Key trùng được ghi nhận `failed`|Unit|
|TC07|Chạy rule full-row duplicate|Dòng trùng được ghi nhận `failed`|Unit|
|TC08|Chạy rule regex email|Email sai format được ghi nhận `failed`|Unit|
|TC09|Chạy rule regex phone|Phone sai format được ghi nhận `failed`|Unit|
|TC10|Chạy rule type check|Giá trị không parse được ghi nhận `miscast`|Unit|
|TC11|Tính RuleScore|`RuleScore = passed / total_records_in_scope × 100`|Unit|
|TC12|Tính DimensionScore|Chỉ rule `measured` được đưa vào công thức|Unit|
|TC13|Tái chuẩn hóa trọng số|Dimension `not_measured` bị loại khỏi công thức|Unit|
|TC14|Tính DQ Core Score|DQ Core Score tính đúng theo trọng số dimension|Integration|
|TC15|Kiểm tra monitoring rule|Rule `score_enabled = false` không vào DQ Core Score|Integration|
|TC16|Rule thiếu target column|Rule được đánh dấu `not_measured`, không được đưa vào tính điểm|Unit|
|TC17|Freshness dataset-level|Rule freshness dùng đúng `evaluation_unit = dataset_run`|Unit/Integration|

Lưu ý: Bảng trên là **test case đề xuất**. Khi chạy thật, cần cập nhật trạng thái thành `Pass`, `Fail` hoặc `Blocked` theo kết quả kiểm thử thực tế.

### 11.3 Mẫu ghi nhận kết quả kiểm thử thực tế

Khi chạy kiểm thử, báo cáo kết quả nên ghi theo mẫu sau:

|Thuộc tính|Giá trị|
|---|---|
|Dataset|`customer_master`|
|Số bản ghi|`<cập nhật sau khi chạy>`|
|Số rule active|`<cập nhật sau khi chạy>`|
|Số rule measured|`<cập nhật sau khi chạy>`|
|Số rule not_measured|`<cập nhật sau khi chạy>`|
|Số rule skipped|`<cập nhật sau khi chạy>`|
|Số issue samples|`<cập nhật sau khi chạy>`|
|Output database|`<đường dẫn SQLite / database>`|
|Output JSON|`<đường dẫn JSON artifact>`|
|Test command|`<lệnh chạy test>`|
|Test result|`<số test pass/fail>`|

### 11.4 Mẫu bảng tổng hợp kiểm thử

|Nhóm kiểm thử|Số test|Pass|Fail|Ghi chú|
|---|--:|--:|--:|---|
|Data loading|`<n>`|`<n>`|`<n>`||
|Rule config|`<n>`|`<n>`|`<n>`||
|Error detection|`<n>`|`<n>`|`<n>`||
|Scoring|`<n>`|`<n>`|`<n>`||
|Integration|`<n>`|`<n>`|`<n>`||
|**Tổng**|`<n>`|`<n>`|`<n>`||

## 12. Tiêu chí hoàn thành

Hạng mục được xem là hoàn thành khi đạt các tiêu chí sau:

- Có dataset config mẫu cho `customer_master`.
    
- Có rule config mẫu cho các lỗi phổ biến.
    
- Rules Engine chạy được các rule `status = active`.
    
- Rule config được validate trước khi chạy.
    
- Kết quả kiểm tra được chuẩn hóa thành `Rule Evaluation Result`.
    
- Có output `rule_run`, `rule_config`, `rule_evaluation_result`, `rule_issue_sample`.
    
- Scoring Engine đọc được `Rule Evaluation Result`.
    
- Scoring Engine tính được `RuleScore`, `DimensionScore`, `DQ Core Score`.
    
- Rule/dimension `not_measured` không bị gán điểm 0.
    
- Rule `score_enabled = false` không ảnh hưởng đến DQ Core Score.
    
- Có báo cáo kiểm thử ghi rõ test case, kết quả chạy và lỗi phát hiện được.
    

## 13. Deliverables

|Hạng mục|Mô tả|
|---|---|
|Tài liệu thiết kế triển khai|Tài liệu này|
|Dataset config mẫu|File cấu hình dataset `customer_master`|
|Rule config mẫu|Bộ rule phát hiện null, duplicate, format sai, type check, freshness|
|Rules Engine output|`rule_run`, `rule_config`, `rule_evaluation_result`, `rule_issue_sample`|
|Scoring Engine output|`rule_score_history`, `dimension_score_history`, `dataset_score_history`|
|Báo cáo kiểm thử|Tổng hợp kết quả test và kết quả chạy thử trên dataset mẫu|
|README hướng dẫn chạy|Cách chạy module, chạy test và xem output|

## 14. Rủi ro và lưu ý triển khai

|Rủi ro / Lưu ý|Ảnh hưởng|Biện pháp xử lý|
|---|---|---|
|Rule type trong tài liệu không khớp code|Rule chạy lỗi|Chuẩn hóa tên rule type giữa config, code và docs|
|Lẫn Rules Engine và Scoring Engine|Sai trách nhiệm module|Tách output Rules Engine và output Scoring Engine|
|Dùng số liệu minh họa như kết quả thật|Báo cáo thiếu chính xác|Tách rõ “kết quả thực tế” và “ví dụ minh họa”|
|Freshness lẫn dataset-level và row-level|Đếm sai đơn vị đánh giá|Khai báo rõ `evaluation_unit`|
|Null bị tính lỗi nhiều lần|Double-count trong điểm|Dùng `null_policy` và dimension chính|
|Rule monitoring bị tính điểm|Sai DQ Core Score|Kiểm tra `score_enabled = false`|
|Dimension chưa đo bị gán 0|Điểm bị phạt sai|Dùng `not_measured` và tái chuẩn hóa trọng số|
|Chưa đủ metadata dataset|Một số rule không chạy được|Đánh dấu `not_measured` và bổ sung metadata cần thiết|

## 15. Kết luận

Tài liệu này định nghĩa thiết kế triển khai cho module phát hiện lỗi phổ biến và tính DQ Core Score trong Phase 1.

Luồng cốt lõi:

```text
Dataset mẫu
→ Rules Engine chạy rule chính thức
→ Rule Evaluation Result
→ Scoring Engine tính DQ Core Score
→ Báo cáo kiểm thử / Dashboard
```

Thiết kế này bảo đảm hệ thống phát hiện được các lỗi phổ biến như null/blank, duplicate, format sai, sai kiểu dữ liệu và freshness cơ bản; đồng thời giữ đúng ranh giới giữa Profiling Pipeline, Rules Engine và Scoring Engine.

Đây là nền tảng để mở rộng sang các rule nâng cao, kiểm thử nhiều dataset hơn, lưu lịch sử điểm và hiển thị DQ Score trên Dashboard trong các bước tiếp theo.
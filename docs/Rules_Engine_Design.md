# Tài liệu Thiết kế Rules Engine Module

**Dự án:** Chấm điểm Chất lượng Dữ liệu (DQ Scoring)  
**Module:** Sàn giao dịch dữ liệu và Datalake tập trung  
**Phiên bản:** 1.0.1  
**Ngày:** 25/06/2026  
**Giai đoạn:** Phase 1 – Khung đo lường và hệ thống tính điểm cơ bản  
**Tài liệu liên quan:** `DQ_Framework`, `DQ_Scoring_Model`, `Profiling_Pipeline_Design`

| Phiên bản | Ngày       | Người thực hiện   | Mô tả thay đổi                                                                                                              |
| --------- | ---------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------- |
| 1.0       | 23/06/2026 | Nguyễn Hoàng Tùng | Khởi tạo tài liệu thiết kế Rules Engine Module                                                                              |
| 1.0.1     | 25/06/2026 | Nguyễn Hoàng Tùng | Chuẩn hóa rule status, thêm `score_enabled`, tách `quality_status` sang Scoring Engine và bổ sung bước validate rule config |

## 1. Giới thiệu

### 1.1 Mục đích

Tài liệu này mô tả thiết kế kỹ thuật cho Rules Engine Module trong hệ thống DQ Scoring. Rules Engine là thành phần chịu trách nhiệm chạy các quy tắc kiểm tra chất lượng dữ liệu đã được cấu hình, chuẩn hóa kết quả kiểm tra và cung cấp đầu vào chính thức cho Scoring Engine.

Rules Engine đóng vai trò trung gian giữa Profiling Pipeline và Scoring Engine:

```
- Raw Data / Dataset
- Profiling Pipeline
- Rules Engine
- Scoring Engine
- Dashboard / Data Catalog
```

Trong Phase 1, Rules Engine tập trung vào việc:

- Lập trình bộ rule kiểm tra dữ liệu theo từng loại dữ liệu.
- Chạy các rule chính thức đã được cấu hình.
- Sinh `Rule Evaluation Result` theo định dạng chuẩn.
- Phân loại kết quả kiểm tra thành `passed`, `failed`, `miscast`, `empty`, `not_applicable`.
- Cung cấp dữ liệu đầu vào để Scoring Engine tính `RuleScore`, `DimensionScore` và `DQ Core Score`.

Rules Engine không trực tiếp tính điểm tổng hợp. Việc tính điểm thuộc trách nhiệm của Scoring Engine theo tài liệu `DQ_Scoring_Model`.

### 1.2 Căn cứ thiết kế

Tài liệu này được xây dựng dựa trên ba tài liệu nền:

|Tài liệu|Vai trò|
|---|---|
|`DQ_Framework`|Định nghĩa 6 trụ cột chất lượng dữ liệu và phạm vi đo lường Phase 1|
|`DQ_Scoring_Model`|Định nghĩa RuleScore, trạng thái đo lường rule và cách Scoring Engine tổng hợp điểm|
|`Profiling_Pipeline_Design`|Định nghĩa Profile Result, Candidate Rule và cách Profiling Pipeline cung cấp đầu vào cho Rules Engine|

### 1.3 Vị trí trong kiến trúc tổng thể

```
1. [Raw Data / Dataset]

2. [Profiling Pipeline]
   - Trích xuất thống kê
   - Sinh Profile Result
   - Sinh Candidate Rule

3. [Rules Engine]
   - Đọc rule config chính thức
   - Validate rule config
   - Chạy rule trên dataset
   - Chuẩn hóa kết quả kiểm tra
   - Sinh Rule Evaluation Result

4. [Scoring Engine]
   - Tính Rule Score
   - Xác định pass / warning / fail ở cấp rule
   - Tổng hợp Dimension Score
   - Tính DQ Core Score

5. [Dashboard / Data Catalog]
```

Lưu ý: Candidate rule từ Profiling Pipeline chỉ là gợi ý. Candidate rule chỉ được Rules Engine chạy như rule chính thức khi đã được Data Steward xem xét và chuyển thành `rule_config` có trạng thái `active`.

### 1.4 Phạm vi Phase 1

Trong Phase 1, Rules Engine tập trung vào các rule deterministic, có thể cấu hình rõ ràng và dễ giải thích.

|Nhóm công việc|Phạm vi Phase 1|
|---|---|
|Rule configuration|Quản lý rule bằng YAML/JSON; database table có thể bổ sung nếu cần|
|Rule template|Xây dựng bộ rule mẫu theo loại dữ liệu và dimension|
|Rule validation|Kiểm tra rule config trước khi chạy|
|Rule execution|Chạy rule trên dataset bằng Python/GX/Pandas; SQL dùng khi phù hợp|
|Result normalization|Chuẩn hóa kết quả thành `passed`, `failed`, `miscast`, `empty`, `not_applicable`|
|Output schema|Sinh `rule_run`, `rule_config`, `rule_evaluation_result`, `rule_issue_sample`|
|Scoring integration|Cung cấp kết quả chính thức cho Scoring Engine|
|Dashboard support|Cung cấp issue summary và sample lỗi để hiển thị|

### 1.5 Ngoài phạm vi Phase 1

Các nội dung sau chưa thuộc phạm vi triển khai chính của Rules Engine trong Phase 1:

- Workflow phê duyệt rule nhiều cấp.
- Rule recommendation bằng AI/ML.
- Tự động phê duyệt candidate rule.
- Cross-system matching với CRM, KYC hoặc core system.
- Fuzzy matching hoặc near-duplicate detection.
- Streaming validation realtime.
- Rule dependency graph phức tạp.
- Root-cause analysis tự động.
- Production-level rule versioning/branching.

Các nội dung trên có thể được mở rộng ở Phase 2 hoặc giai đoạn production hardening.

## 2. Nguyên tắc thiết kế

### 2.1 Rule-based, deterministic và explainable

Rules Engine trong Phase 1 sử dụng các rule rõ ràng, có thể giải thích được và có thể tái chạy khi cần.

Ví dụ:

```
customer_id không được null
email phải đúng định dạng
age phải nằm trong khoảng hợp lý
order_date không được lớn hơn current_date
customer_id không được trùng
end_date phải >= start_date
```

Mỗi rule cần trả lời được:

- Rule kiểm tra điều gì?
- Áp dụng cho dataset/cột nào?
- Thuộc dimension nào?
- Phạm vi áp dụng rule là gì?
- Số lượng bản ghi pass/fail là bao nhiêu?
- Lỗi thuộc loại nào?
- Rule có được đưa vào Scoring Engine hay chỉ dùng để cảnh báo?

### 2.2 Config-driven, hạn chế hardcode

Rules Engine không nên hardcode rule trực tiếp trong code xử lý. Thay vào đó, rule được khai báo bằng config.

Trong Phase 1, rule config mặc định có thể lưu bằng:

- YAML file.
- JSON file.

Các hình thức như database table, Data Catalog metadata hoặc Rule Registry nội bộ có thể bổ sung ở giai đoạn sau khi cần quản trị rule tập trung.

Code của Rules Engine chỉ nên triển khai các **rule template** và cơ chế chạy rule. Nội dung cụ thể như tên cột, threshold, regex, domain list, scope filter nên nằm trong config.

### 2.3 Mỗi rule thuộc một dimension chính

Một rule có thể liên quan đến nhiều dimension, nhưng khi dùng để tính điểm, mỗi rule cần được gán một `dimension` chính để tránh double-count.

Ví dụ:

```
Nếu order_status = "DELIVERED" thì delivery_date không được null
```

Rule này có thể liên quan đến Completeness và Consistency. Trong rule config, cần chọn một dimension chính, ví dụ `Consistency` nếu mục tiêu là kiểm tra logic trạng thái đơn hàng.

Không nên tạo hai rule giống hệt nhau ở hai dimension khác nhau nếu cả hai đều được đưa vào DQ Core Score.

### 2.4 Không tính điểm trực tiếp trong Rules Engine

Rules Engine chỉ sinh kết quả kiểm tra rule. Công thức tính `RuleScore`, `quality_status`, `DimensionScore` và `DQ Core Score` thuộc Scoring Engine.

Rules Engine output:

```
passed
failed
miscast
empty
not_applicable
total_records_in_scope
threshold
measurement_status
```

Scoring Engine sử dụng các count này để tính:

```
RuleScore = passed_records / total_records_in_scope × 100
```

Quy ước Phase 1: Rules Engine không cần tính `quality_status = pass / warning / fail`. Trạng thái này nên được Scoring Engine hoặc Dashboard xác định sau khi có `RuleScore`.

### 2.5 Chuẩn hóa trạng thái đánh giá rule

Mỗi bản ghi trong phạm vi chạy rule cần được phân loại vào một trạng thái duy nhất.

| Trạng thái       | Ý nghĩa                                             |
| ---------------- | --------------------------------------------------- |
| `passed`         | Bản ghi thỏa mãn rule                               |
| `failed`         | Bản ghi vi phạm rule                                |
| `miscast`        | Giá trị sai kiểu hoặc không thể ép kiểu để đánh giá |
| `empty`          | Giá trị null/blank trong rule yêu cầu có giá trị    |
| `not_applicable` | Bản ghi không thuộc phạm vi áp dụng rule            |

Thứ tự phân loại đề xuất:

```
1. Nếu record không thuộc scope rule → not_applicable
2. Nếu giá trị null/blank và null_policy = fail → empty
3. Nếu không thể ép kiểu hoặc sai kiểu → miscast
4. Nếu đúng kiểu nhưng vi phạm điều kiện → failed
5. Nếu thỏa điều kiện → passed
```

### 2.6 Null policy thống nhất

Mỗi rule cần khai báo `null_policy`.

|`null_policy`|Ý nghĩa|Cách xử lý|
|---|---|---|
|`fail`|Null/blank là lỗi|Ghi vào `empty`, tính vào `total_records_in_scope`|
|`ignore`|Null/blank không thuộc phạm vi rule|Ghi vào `not_applicable`, không tính vào mẫu số|

Ví dụ:

|Rule|`null_policy`|
|---|---|
|`email` không được null|`fail`|
|`email` phải đúng regex|`ignore`, nếu null đã được kiểm tra ở Completeness|
|`tax_code` không được null nếu `customer_type = BUSINESS`|`fail`|

Khi nhiều rule áp dụng trên cùng một cột, cần cấu hình `null_policy` và `dimension` để tránh cùng một lỗi null/blank bị trừ điểm ở nhiều rule.

## 3. Đầu vào của Rules Engine

### 3.1 Dataset đầu vào

Rules Engine có thể chạy trên:

| Nguồn dữ liệu  | Ví dụ                                   |
| -------------- | --------------------------------------- |
| File           | CSV, Parquet, JSON                      |
| Database table | PostgreSQL, MySQL, SQL Server           |
| Datalake table | Parquet, Delta Lake                     |
| Data product   | Nhóm bảng đã đăng ký trong Data Catalog |

Thông tin tối thiểu cần có:

|Trường|Mô tả|
|---|---|
|`dataset_id`|Định danh dataset|
|`dataset_name`|Tên dataset|
|`source_path`|Đường dẫn hoặc table nguồn|
|`dataset_version`|Phiên bản dataset nếu có|
|`declared_schema`|Schema khai báo|
|`dataset_type`|master_data, transaction, log_event, reference_data, default|

### 3.2 Metadata đầu vào

Rules Engine cần metadata để xác định rule nào có thể chạy.

| Metadata             | Vai trò                                                 |
| -------------------- | ------------------------------------------------------- |
| `mandatory_fields`   | Sinh/chạy completeness rule                             |
| `cde_fields`         | Ưu tiên rule trên Critical Data Elements                |
| `primary_key`        | Chạy uniqueness rule                                    |
| `composite_key`      | Chạy composite uniqueness rule                          |
| `business_key`       | Chạy business key uniqueness rule                       |
| `timestamp_column`   | Chạy freshness/timeliness rule                          |
| `sla_config`         | Chạy SLA rule                                           |
| `declared_data_type` | Chạy type check                                         |
| `regex_pattern`      | Chạy format check                                       |
| `domain_values`      | Chạy domain check                                       |
| `expected_range`     | Chạy range/plausibility rule                            |
| `reference_table`    | Chạy referential integrity rule trong cùng data product |

### 3.3 Rule config đầu vào

Rule config là đầu vào quan trọng nhất của Rules Engine. Một rule tối thiểu cần có các trường sau:

| Trường              | Mô tả                                                          |
| ------------------- | -------------------------------------------------------------- |
| `rule_id`           | Định danh duy nhất của rule                                    |
| `rule_name`         | Tên rule                                                       |
| `description`       | Mô tả rule                                                     |
| `dataset_id`        | Dataset áp dụng                                                |
| `target_table`      | Bảng áp dụng, nếu có                                           |
| `target_column`     | Cột áp dụng, nếu có                                            |
| `dimension`         | Dimension chính của rule                                       |
| `rule_type`         | Loại rule: not_null, regex, range, domain, uniqueness, ...     |
| `scope_filter`      | Điều kiện áp dụng rule                                         |
| `parameters`        | Tham số rule như regex, min, max, domain list                  |
| `null_policy`       | fail hoặc ignore                                               |
| `threshold`         | Ngưỡng tính điểm rule, do Scoring Engine sử dụng               |
| `severity`          | low, medium, high, critical                                    |
| `execution_backend` | gx, pandas, sql, spark                                         |
| `status`            | draft, active, inactive, deprecated                            |
| `created_by`        | Người tạo rule                                                 |
| `created_at`        | Thời điểm tạo                                                  |
| `updated_at`        | Thời điểm cập nhật                                             |
| `score_enabled`     | Rule có được đưa vào Scoring Engine để tính DQ Score hay không |

Trong Phase 1, Rules Engine chỉ chạy các rule có `status = active`. Tuy nhiên, chỉ rule có `score_enabled = true` mới được đưa vào Scoring Engine để tính DQ Score. Các rule có `score_enabled = false` chỉ dùng để monitoring hoặc hiển thị cảnh báo.

#### 3.3.1 Quy trình tạo một rule

Một rule mới nên được tạo theo các bước sau:

1. Xác định dataset và cột cần kiểm tra.
2. Xác định vấn đề chất lượng dữ liệu cần phát hiện.
3. Chọn dimension chính của rule.
4. Chọn `rule_type` phù hợp.
5. Khai báo `parameters` cho rule.
6. Chọn `null_policy` để tránh tính lỗi null trùng lặp.
7. Xác định `threshold` và `severity`.
8. Xác định rule có được tính điểm hay không bằng `score_enabled`.
9. Đặt `status = active` nếu rule được phép chạy chính thức.
10. Validate rule config trước khi đưa vào Rules Engine.

Ví dụ:
- Nếu muốn kiểm tra email sai định dạng, chọn dimension `Validity`, `rule_type = regex`, `null_policy = ignore`.
- Nếu muốn kiểm tra email bị thiếu, tạo rule riêng với dimension `Completeness`, `rule_type = not_null`, `null_policy = fail`.

#### 3.3.2 Phân loại scoring rule và monitoring rule

| Loại rule | `score_enabled` | Mục đích | Có vào DQ Core Score không? |
|---|---:|---|---|
| Scoring rule | true | Kiểm tra chất lượng dữ liệu chính thức | Có |
| Monitoring rule | false | Cảnh báo, quan sát, hỗ trợ dashboard | Không |

Ví dụ:
- `email must match regex` → scoring rule.
- `customer_id must be unique` → scoring rule.
- `row_count_check` khi chưa có ngưỡng nghiệp vụ rõ ràng → monitoring rule.
- `schema_check` phục vụ Metadata Check → monitoring rule, trừ khi được cấu hình tính vào Validity.

### 3.4 Candidate rule từ Profiling Pipeline

Candidate rule từ Profiling Pipeline có thể trở thành rule chính thức nếu được Data Steward xem xét và chuyển thành rule config.

Luồng tối giản Phase 1:

```
Candidate Rule
- Data Steward review thủ công
- Active Rule Config
- Rules Engine execution
- Rule Evaluation Result
- Scoring Engine
```

Trong Phase 1, việc review candidate rule có thể thực hiện thủ công bằng cách Data Steward cập nhật file YAML/JSON rule config. Hệ thống chưa cần xây dựng workflow approval nhiều cấp.

## 4. Bộ rule template Phase 1

### 4.1 Tổng quan rule template

Rules Engine Phase 1 nên cung cấp một bộ rule template đủ dùng cho các loại dữ liệu phổ biến.

| Nhóm dữ liệu   | Rule template chính                                   |
| -------------- | ----------------------------------------------------- |
| String/Text    | not_null, not_blank, regex, length, allowed_values    |
| Numeric        | type_check, range, non_negative, plausibility_range   |
| Date/Datetime  | type_check, date_range, not_future_date, freshness    |
| Categorical    | domain, allowed_values, domain_lookup                 |
| Identifier/Key | not_null, uniqueness, composite_uniqueness            |
| Boolean        | type_check, allowed_values                            |
| Dataset-level  | duplicate_row_check, freshness_check, row_count_check |
| Cross-field    | comparison, conditional_required                      |
| Reference      | referential_integrity                                 |

Lưu ý: `row_count_check` mặc định là monitoring rule, không tính vào DQ Core Score. Chỉ tính vào Consistency nếu nghiệp vụ định nghĩa rõ `expected_row_count`, threshold và phạm vi áp dụng.

### 4.2 String/Text rules

Áp dụng cho các cột dạng chuỗi như `email`, `phone_number`, `full_name`, `address`, `country_code`.

| Rule type        | Mô tả                                           | Dimension chính |
| ---------------- | ----------------------------------------------- | --------------- |
| `not_null`       | Giá trị không được null                         | Completeness    |
| `not_blank`      | Không được là chuỗi rỗng hoặc toàn khoảng trắng | Completeness    |
| `regex`          | Giá trị phải khớp pattern                       | Validity        |
| `length`         | Độ dài phải nằm trong khoảng cho phép           | Validity        |
| `allowed_values` | Giá trị phải thuộc danh sách hợp lệ             | Validity        |

Ví dụ:

```
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
execution_backend: gx
status: active
score_enabled: true
```

### 4.3 Numeric rules

Áp dụng cho dữ liệu số như `amount`, `age`, `quantity`, `discount_rate`.

| Rule type            | Mô tả                                          | Dimension chính |
| -------------------- | ---------------------------------------------- | --------------- |
| `type_check`         | Giá trị phải ép được sang numeric              | Validity        |
| `range`              | Giá trị nằm trong miền hợp lệ theo rule/schema | Validity        |
| `non_negative`       | Giá trị không được âm                          | Validity        |
| `greater_than`       | Giá trị phải lớn hơn một ngưỡng                | Validity        |
| `plausibility_range` | Giá trị nằm trong khoảng hợp lý nghiệp vụ      | Accuracy Proxy  |

Quy ước:

- `range` dùng cho Validity khi kiểm tra miền giá trị hợp lệ.
- `plausibility_range` dùng cho Accuracy Proxy khi kiểm tra khoảng giá trị hợp lý về mặt nghiệp vụ.

Ví dụ:

```
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

### 4.4 Date/Datetime rules

Áp dụng cho các cột như `created_at`, `updated_at`, `transaction_date`, `event_time`.

|Rule type|Mô tả|Dimension chính|
|---|---|---|
|`type_check`|Giá trị phải parse được sang date/datetime|Validity|
|`date_range`|Ngày nằm trong khoảng cho phép|Validity|
|`not_future_date`|Ngày không được lớn hơn ngày hiện tại|Validity|
|`freshness`|Dữ liệu phải đủ mới theo timestamp|Timeliness|
|`sla_check`|Dataset cập nhật đúng SLA|Timeliness|

Ví dụ:

```
rule_id: DQ-TIME-UPDATED-001
rule_name: Dataset freshness check
dataset_id: customer_master
target_column: updated_at
dimension: Timeliness
rule_type: freshness
parameters:
  max_freshness_lag_hours: 24
  freshness_time_basis: updated_at
null_policy: ignore
threshold: 95
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

### 4.5 Categorical/Domain rules

Áp dụng cho các cột có tập giá trị hữu hạn như `gender`, `status`, `country_code`, `order_status`.

|Rule type|Mô tả|Dimension chính|
|---|---|---|
|`domain`|Giá trị phải thuộc danh sách hợp lệ|Validity|
|`allowed_values`|Giá trị thuộc tập cấu hình tĩnh|Validity|
|`domain_lookup`|Giá trị tồn tại trong danh sách tham chiếu nhỏ/code list|Validity|

Lưu ý: `domain_lookup` dùng cho code list hoặc reference list nhỏ. Nếu kiểm tra khóa giữa bảng con và bảng cha, sử dụng `referential_integrity`.

Ví dụ:

```
rule_id: DQ-VALI-STATUS-001
rule_name: Order status domain check
dataset_id: orders
target_column: order_status
dimension: Validity
rule_type: domain
parameters:
  allowed_values:
    - PENDING
    - PAID
    - CANCELLED
    - DELIVERED
null_policy: ignore
threshold: 99
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

Nếu `order_status` là trường bắt buộc, cần tạo rule Completeness riêng với `rule_type: not_null` và `null_policy: fail`.

### 4.6 Identifier/Key rules

Áp dụng cho khóa định danh như `customer_id`, `order_id`, `transaction_id`, `product_id`.

|Rule type|Mô tả|Dimension chính|
|---|---|---|
|`not_null`|Key không được null|Completeness|
|`uniqueness`|Key không được trùng|Uniqueness|
|`composite_uniqueness`|Tổ hợp key không được trùng|Uniqueness|
|`business_key_uniqueness`|Business key duy nhất trong phạm vi nghiệp vụ|Uniqueness|

Ví dụ:

```
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

### 4.7 Cross-field rules

Áp dụng cho logic giữa nhiều cột trong cùng một bản ghi.

|Rule type|Mô tả|Dimension chính|
|---|---|---|
|`comparison`|So sánh hai cột|Consistency|
|`conditional_required`|Nếu điều kiện A đúng thì cột B bắt buộc có giá trị|Consistency|
|`business_logic`|Logic nghiệp vụ đơn giản|Consistency|

Ví dụ comparison rule:

```
rule_id: DQ-CONS-DATE-001
rule_name: End date must be after start date
dataset_id: contract
dimension: Consistency
rule_type: comparison
parameters:
  left_column: end_date
  operator: ">="
  right_column: start_date
null_policy: ignore
threshold: 98
severity: high
execution_backend: pandas
status: active
score_enabled: true
```

Ví dụ conditional rule:

```
rule_id: DQ-CONS-ORDER-001
rule_name: Delivered order must have delivery date
dataset_id: orders
dimension: Consistency
rule_type: conditional_required
scope_filter: "order_status = 'DELIVERED'"
target_column: delivery_date
parameters:
  required_column: delivery_date
null_policy: fail
threshold: 98
severity: high
execution_backend: sql
status: active
score_enabled: true
```

### 4.8 Dataset-level rules

Áp dụng cho toàn bộ dataset.

| Rule type             | Mô tả                                       | Dimension chính                                                                                         |
| --------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `duplicate_row_check` | Tỉ lệ dòng trùng không vượt ngưỡng          | Uniqueness                                                                                              |
| `schema_check`        | Schema thực tế khớp schema khai báo         | Metadata Check; chỉ tính vào Validity nếu `score_enabled = true` và rule được cấu hình là scoring rule. |
| `freshness_check`     | Dataset được cập nhật trong ngưỡng cho phép | Timeliness                                                                                              |
| `row_count_check`     | Row count không lệch quá ngưỡng             | Monitoring; chỉ tính Consistency nếu nghiệp vụ quy định                                                 |

Ví dụ:

```
rule_id: DQ-UNIQ-DUPROW-001
rule_name: Full row duplicate check
dataset_id: customer_master
dimension: Uniqueness
rule_type: duplicate_row_check
parameters:
  max_duplicate_ratio: 1
null_policy: ignore
threshold: 99
severity: medium
execution_backend: pandas
status: active
score_enabled: true
```

```
rule_id: DQ-MON-ROWCOUNT-001
rule_name: Row count monitoring check
dataset_id: orders
dimension: Consistency
rule_type: row_count_check
parameters:
  expected_row_count: 100000
  max_deviation_percent: 20
null_policy: ignore
threshold:
severity: medium
execution_backend: pandas
status: active
score_enabled: false
```

### 4.9 Referential integrity rules

Áp dụng cho các bảng có quan hệ trực tiếp trong cùng data product.

|Rule type|Mô tả|Dimension chính|
|---|---|---|
|`referential_integrity`|Foreign key trong bảng con phải tồn tại trong bảng cha|Consistency|

Ví dụ:

```
rule_id: DQ-CONS-FK-001
rule_name: Orders customer_id must exist in customers
dataset_id: sales_data_product
target_table: orders
dimension: Consistency
rule_type: referential_integrity
parameters:
  child_table: orders
  child_key: customer_id
  parent_table: customers
  parent_key: customer_id
null_policy: ignore
threshold: 99
severity: critical
execution_backend: sql
status: active
score_enabled: true
```

Lưu ý: Referential integrity chỉ thuộc Phase 1 nếu bảng cha và bảng con nằm trong cùng dataset group hoặc cùng data product. Nếu cần đối chiếu sang hệ thống độc lập như CRM/KYC/core system, kiểm tra này thuộc Phase 2.

## 5. Ánh xạ rule template với 6 dimension

| Dimension      | Rule type Phase 1                                                                     |
| -------------- | ------------------------------------------------------------------------------------- |
| Completeness   | not_null, not_blank, conditional_required nếu mục tiêu là bắt buộc dữ liệu            |
| Validity       | type_check, regex, length, range, domain, allowed_values, date_range, not_future_date |
| Uniqueness     | uniqueness, composite_uniqueness, business_key_uniqueness, duplicate_row_check        |
| Consistency    | comparison, conditional_required, business_logic, referential_integrity               |
| Timeliness     | freshness, sla_check                                                                  |
| Accuracy Proxy | plausibility_range                                                                    |

Lưu ý: Accuracy Proxy không phải Accuracy đầy đủ. Các rule này chỉ kiểm tra dữ liệu có hợp lý hay không, chưa kết luận dữ liệu đúng với thực tế.

## 6. Luồng xử lý của Rules Engine

### 6.1 Tổng quan luồng xử lý

Rules Engine gồm 9 bước chính:

```
Step 1: Load active rules
Step 2: Validate rule config
Step 3: Load dataset / table
Step 4: Resolve rule scope
Step 5: Execute rule
Step 6: Classify evaluation status
Step 7: Aggregate rule result
Step 8: Store Rule Evaluation Result
Step 9: Send result to Scoring Engine
```

### 6.2 Step 1 – Load active rules

Rules Engine chỉ load các rule thỏa điều kiện:

```
status = active
dataset_id phù hợp với dataset đang chạy
```

Các rule có trạng thái `draft`, `inactive`, `deprecated` không được chạy trong scoring run chính thức.

Trong các rule được load, chỉ rule có `score_enabled = true` mới được chuyển sang Scoring Engine. Rule có `score_enabled = false` vẫn có thể được chạy để phục vụ monitoring, dashboard hoặc cảnh báo, nhưng không đóng góp vào DQ Core Score.

### 6.3 Step 2 – Validate rule config

Sau khi load rule, Rules Engine cần kiểm tra rule config trước khi chạy.

Các kiểm tra tối thiểu:

| Kiểm tra             | Mô tả                                                                                                                                          |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Required fields      | Rule có đủ `rule_id`, `dataset_id`, `rule_type`, `status`, `score_enabled`; nếu `score_enabled = true` thì phải có `dimension` và `threshold`. |
| Target existence     | `target_column` hoặc `target_table` tồn tại trong dataset                                                                                      |
| Rule type support    | `rule_type` có evaluator tương ứng                                                                                                             |
| Parameter validity   | `parameters` đúng định dạng với `rule_type`                                                                                                    |
| Null policy validity | `null_policy` thuộc `fail` hoặc `ignore`                                                                                                       |
| Dimension validity   | `dimension` thuộc 6 dimension đã định nghĩa                                                                                                    |
| Status validity      | `status` hợp lệ                                                                                                                                |

Nếu rule config không hợp lệ, rule được đánh dấu `measurement_status = not_measured` và ghi `error_message`.

### 6.4 Step 3 – Load dataset / table

Rules Engine đọc dataset theo thông tin từ dataset config.

|Điều kiện|Cách xử lý|
|---|---|
|Dataset nhỏ/vừa|Dùng GX hoặc Pandas|
|Dataset trong database|Dùng SQL query|
|Dataset lớn|Dùng SQL hoặc Spark nếu thật sự cần|
|Dataset trong datalake|Dùng Parquet/Delta reader|

Quy ước Phase 1: execution mặc định là GX/Pandas. SQL dùng cho database hoặc referential integrity đơn giản. Spark là phương án mở rộng khi dataset lớn.

### 6.5 Step 4 – Resolve rule scope

Mỗi rule cần xác định rõ phạm vi áp dụng.

|Rule|Scope|
|---|---|
|`email` không được null|Toàn bộ dataset|
|`tax_code` bắt buộc nếu `customer_type = BUSINESS`|Chỉ record có `customer_type = BUSINESS`|
|`delivery_date` bắt buộc nếu order delivered|Chỉ record có `order_status = DELIVERED`|
|`customer_id` trong orders phải tồn tại trong customers|Bảng orders, khóa customer_id|

Các bản ghi nằm ngoài scope được ghi nhận là `not_applicable`.

### 6.6 Step 5 – Execute rule

Rules Engine gọi đúng evaluator theo `rule_type` và `execution_backend`.

Ví dụ mapping:

|`rule_type`|Evaluator|
|---|---|
|`not_null`|CompletenessEvaluator|
|`regex`|RegexEvaluator|
|`range`|RangeEvaluator|
|`plausibility_range`|AccuracyProxyEvaluator|
|`domain`|DomainEvaluator|
|`uniqueness`|UniquenessEvaluator|
|`comparison`|CrossFieldEvaluator|
|`freshness`|TimelinessEvaluator|
|`referential_integrity`|ReferentialIntegrityEvaluator|

### 6.7 Step 6 – Classify evaluation status

Sau khi chạy rule, mỗi record hoặc đơn vị đánh giá được phân loại thành:

```
passed
failed
miscast
empty
not_applicable
```

Với dataset-level rule như SLA hoặc row count, đơn vị đánh giá có thể là:

```
dataset_run
update_event
key
record
```

Phase 1 không cần lưu từng record status đầy đủ nếu dữ liệu lớn. Hệ thống chỉ cần lưu count tổng hợp và một số mẫu lỗi để dashboard hiển thị.

### 6.8 Step 7 – Aggregate rule result

Rules Engine tổng hợp số lượng:

```
passed_count
failed_count
miscast_count
empty_count
not_applicable_count
total_records_in_scope
```

Trong đó:

```
total_records_in_scope = passed + failed + miscast + empty
```

`not_applicable` không được đưa vào mẫu số tính điểm.

### 6.9 Step 8 – Store Rule Evaluation Result

Rules Engine lưu kết quả vào bảng `rule_evaluation_result`.

Kết quả này là đầu vào chính thức cho Scoring Engine.

### 6.10 Step 9 – Send result to Scoring Engine

Scoring Engine sử dụng `rule_evaluation_result` để tính `RuleScore`.

Rules Engine không cần biết trọng số dimension hoặc cách tính `DQ Core Score`.

## 7. Thiết kế Output Schema

### 7.1 Bảng `rule_run`

Bảng `rule_run` lưu thông tin một lần chạy Rules Engine.

| Trường                   | Kiểu     | Mô tả                                  |
| ------------------------ | -------- | -------------------------------------- |
| `rule_run_id`            | string   | Định danh lần chạy Rules Engine        |
| `profiling_run_id`       | string   | Mã lần profiling liên quan, nếu có     |
| `dataset_id`             | string   | Dataset được kiểm tra                  |
| `dataset_version`        | string   | Phiên bản dataset, nếu có              |
| `run_timestamp`          | datetime | Thời điểm chạy                         |
| `execution_engine`       | string   | gx, pandas, sql, spark                 |
| `status`                 | string   | success, failed, partial               |
| `total_rules`            | int      | Tổng số rule được chạy                 |
| `rules_succeeded`        | int      | Số rule chạy thành công                |
| `rules_execution_failed` | int      | Số rule bị lỗi khi chạy                |
| `error_message`          | string   | Thông tin lỗi nếu toàn bộ run thất bại |

### 7.2 Bảng `rule_config`

Bảng `rule_config` lưu cấu hình rule chính thức.

| Trường              | Kiểu     | Mô tả                                                                                                   |
| ------------------- | -------- | ------------------------------------------------------------------------------------------------------- |
| `rule_id`           | string   | Định danh rule                                                                                          |
| `rule_name`         | string   | Tên rule                                                                                                |
| `description`       | string   | Mô tả rule                                                                                              |
| `dataset_id`        | string   | Dataset áp dụng                                                                                         |
| `target_table`      | string   | Bảng áp dụng                                                                                            |
| `target_column`     | string   | Cột áp dụng                                                                                             |
| `dimension`         | string   | Dimension chính                                                                                         |
| `rule_type`         | string   | Loại rule                                                                                               |
| `scope_filter`      | string   | Điều kiện áp dụng rule                                                                                  |
| `parameters`        | object   | Tham số rule                                                                                            |
| `null_policy`       | string   | fail, ignore                                                                                            |
| `threshold`         | float    | Ngưỡng tính điểm rule; bắt buộc nếu `score_enabled = true`, có thể null nếu rule chỉ dùng để monitoring |
| `severity`          | string   | low, medium, high, critical                                                                             |
| `execution_backend` | string   | gx, pandas, sql, spark                                                                                  |
| `status`            | string   | draft, active, inactive, deprecated                                                                     |
| `created_by`        | string   | Người tạo                                                                                               |
| `created_at`        | datetime | Thời điểm tạo                                                                                           |
| `updated_at`        | datetime | Thời điểm cập nhật                                                                                      |
| `score_enabled`     | boolean  | Rule có được đưa vào Scoring Engine để tính DQ Score hay không                                          |

Trong Phase 1, chỉ rule có `status = active` và `score_enabled = true` mới được đưa vào Scoring Engine. Các rule có `score_enabled = false` chỉ dùng để monitoring hoặc hiển thị cảnh báo.

### 7.3 Bảng `rule_evaluation_result`

Bảng `rule_evaluation_result` là output chính của Rules Engine.

| Trường                   | Kiểu     | Mô tả                                                                                                   |
| ------------------------ | -------- | ------------------------------------------------------------------------------------------------------- |
| `rule_run_id`            | string   | Định danh lần chạy Rules Engine                                                                         |
| `rule_id`                | string   | Định danh rule                                                                                          |
| `dataset_id`             | string   | Dataset được kiểm tra                                                                                   |
| `target_table`           | string   | Bảng áp dụng                                                                                            |
| `target_column`          | string   | Cột áp dụng                                                                                             |
| `dimension`              | string   | Dimension của rule                                                                                      |
| `evaluation_unit`        | string   | record, key, dataset_run, update_event                                                                  |
| `passed`                 | int      | Số đơn vị đánh giá đạt                                                                                  |
| `failed`                 | int      | Số đơn vị đánh giá lỗi                                                                                  |
| `miscast`                | int      | Số đơn vị sai kiểu hoặc không thể đánh giá                                                              |
| `empty`                  | int      | Số đơn vị null/blank trong scope                                                                        |
| `not_applicable`         | int      | Số đơn vị ngoài scope                                                                                   |
| `total_records_in_scope` | int      | Tổng đơn vị được tính vào RuleScore                                                                     |
| `threshold`              | float    | Ngưỡng tính điểm rule; bắt buộc nếu `score_enabled = true`, có thể bỏ trống nếu `score_enabled = false` |
| `measurement_status`     | string   | measured, not_measured, skipped                                                                         |
| `error_message`          | string   | Lỗi khi chạy rule, nếu có                                                                               |
| `evaluated_at`           | datetime | Thời điểm đánh giá                                                                                      |

Lưu ý: `quality_status` không được lưu như output chính của Rules Engine trong Phase 1. Trạng thái `pass`, `warning`, `fail` nên được Scoring Engine hoặc Dashboard xác định sau khi có `RuleScore`.

### 7.4 Bảng `rule_issue_sample`

Bảng `rule_issue_sample` lưu một số mẫu lỗi để phục vụ dashboard và debug. Không cần lưu toàn bộ bản ghi lỗi trong Phase 1.

|Trường|Kiểu|Mô tả|
|---|---|---|
|`rule_run_id`|string|Định danh lần chạy|
|`rule_id`|string|Định danh rule|
|`dataset_id`|string|Dataset được kiểm tra|
|`record_key`|string|Khóa bản ghi lỗi, nếu có|
|`target_column`|string|Cột liên quan|
|`actual_value`|string|Giá trị thực tế|
|`expected_condition`|string|Điều kiện kỳ vọng|
|`issue_type`|string|failed, miscast, empty|
|`sampled_at`|datetime|Thời điểm ghi nhận mẫu lỗi|

Lưu ý:

- Phase 1 chỉ cần lưu số lượng mẫu lỗi giới hạn, ví dụ tối đa 20–100 mẫu cho mỗi rule failed.
- Nếu dữ liệu chứa thông tin nhạy cảm, `actual_value` cần được mask hoặc không lưu.
- Dashboard nên ưu tiên hiển thị `record_key`, `issue_type`, `target_column` và mô tả lỗi thay vì toàn bộ dữ liệu thô.

## 8. Chuẩn hóa trạng thái rule

### 8.1 Measurement status

`measurement_status` cho biết rule có được đo thành công hay không.

|Trạng thái|Ý nghĩa|
|---|---|
|`measured`|Rule đã chạy và có đủ dữ liệu để tính điểm|
|`not_measured`|Rule chưa đủ dữ liệu, thiếu metadata hoặc lỗi không thể đánh giá|
|`skipped`|Rule bị bỏ qua có chủ đích|

Nếu `measurement_status != measured`, Scoring Engine không nên tính RuleScore cho rule đó.

### 8.2 Quality status

`quality_status` là trạng thái chất lượng của rule sau khi có `RuleScore`.

Trong Phase 1, `quality_status` không phải output bắt buộc của Rules Engine. Trạng thái này nên được xác định bởi Scoring Engine hoặc Dashboard dựa trên `RuleScore` và `threshold`.

Quy ước tham khảo:

```
pass    nếu RuleScore >= threshold
warning nếu RuleScore >= threshold - warning_margin
fail    nếu RuleScore < threshold - warning_margin
```

Ví dụ:

```
threshold = 98
warning_margin = 3

pass    nếu RuleScore >= 98
warning nếu 95 <= RuleScore < 98
fail    nếu RuleScore < 95
```

### 8.3 Xử lý rule không chạy được

Nếu rule không chạy được do thiếu cột, thiếu metadata hoặc lỗi execution:

```
measurement_status = not_measured
passed = 0
failed = 0
miscast = 0
empty = 0
not_applicable = 0
total_records_in_scope = 0
error_message = lý do lỗi
```

Không gán RuleScore = 0 cho rule không đo được.

## 9. Tích hợp với Profiling Pipeline

### 9.1 Profile Result làm ngữ cảnh, không phải kết quả scoring

Profiling Pipeline cung cấp thống kê như:

- `null_ratio`
- `distinct_count`
- `uniqueness_ratio`
- `pattern_frequency`
- `min_value`, `max_value`
- `freshness_lag`

Rules Engine có thể dùng các thống kê này để:

- Ưu tiên rule cần chạy.
- Giúp Data Steward xem xét candidate rule.
- Hiển thị ngữ cảnh khi rule failed.
- Tạo rule config từ candidate rule đã được duyệt.

Tuy nhiên, Rules Engine không nên suy trực tiếp `passed/failed` từ Profile Result sample nếu chưa chạy rule chính thức trên phạm vi kiểm tra đã khai báo.

### 9.2 Candidate rule được duyệt

Candidate rule sau khi được Data Steward xem xét cần được chuyển thành `rule_config` chính thức.

Ví dụ candidate rule:

```
{
  "candidate_rule_id": "CAND-VALI-EMAIL-001",
  "dataset_id": "customer_master",
  "column_name": "email",
  "dimension": "Validity",
  "rule_type": "regex",
  "proposed_threshold": 0.95,
  "confidence": 0.90,
  "status": "pending_review"
}
```

Sau khi được chấp nhận, Data Steward có thể tạo hoặc cập nhật rule config:

```
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
execution_backend: gx
status: active
score_enabled: true
```

## 10. Tích hợp với Scoring Engine

### 10.1 Output chính thức cho Scoring Engine

Scoring Engine đọc bảng `rule_evaluation_result`.

Ví dụ output:

```
{
  "rule_run_id": "RRUN_20260625_001",
  "rule_id": "DQ-VALI-EMAIL-001",
  "dataset_id": "customer_master",
  "target_column": "email",
  "dimension": "Validity",
  "evaluation_unit": "record",
  "passed": 950000,
  "failed": 30000,
  "miscast": 0,
  "empty": 20000,
  "not_applicable": 0,
  "total_records_in_scope": 1000000,
  "threshold": 98,
  "measurement_status": "measured"
}
```

Scoring Engine tính:

```
RuleScore = passed / total_records_in_scope × 100
```

### 10.2 Không double-count rule

Rules Engine cần đảm bảo mỗi rule có đúng một dimension chính.

Nếu một rule có thể thuộc nhiều dimension, Data Steward cần chọn dimension chính trong `rule_config`.

Ví dụ:

```
rule_id: DQ-CONS-ORDER-001
rule_name: Delivered order must have delivery date
dimension: Consistency
```

Không nên đồng thời tạo một rule giống hệt ở Completeness nếu kết quả của hai rule đều được tính vào DQ Core Score.

## 11. Tích hợp với Dashboard

Dashboard có thể sử dụng output của Rules Engine và Scoring Engine để hiển thị:

|Thành phần|Nguồn dữ liệu|
|---|---|
|Failed rules|Scoring Engine xác định từ RuleScore/threshold|
|Warning rules|Scoring Engine hoặc Dashboard xác định từ RuleScore/threshold|
|Not measured rules|Rules Engine – `measurement_status = not_measured`|
|Issue samples|Rules Engine – `rule_issue_sample`|
|Dimension issue summary|Scoring Engine + Rules Engine|
|Critical issues|Rule config `severity = critical` kết hợp với RuleScore/quality status|

Dashboard Phase 1 nên hiển thị:

- Tổng số rule đã chạy.
- Số rule pass/warning/fail.
- Số rule không đo được.
- Danh sách rule failed.
- Mẫu lỗi cho từng rule failed.
- Số bản ghi lỗi theo rule.
- Dimension bị ảnh hưởng.

Lưu ý: Dashboard cần phân biệt rõ số lượng rule lỗi và số lượng bản ghi lỗi để tránh diễn giải sai chất lượng dataset.

## 12. Công nghệ và công cụ triển khai

|Thành phần|Công nghệ đề xuất|
|---|---|
|Ngôn ngữ|Python|
|Rule config|YAML/JSON trong Phase 1|
|Execution mặc định|Great Expectations + Pandas|
|Execution tùy chọn|SQL cho database rule hoặc referential integrity đơn giản|
|Execution mở rộng|PySpark khi dataset lớn|
|Output store|Parquet / Delta Lake / Database table|
|Dashboard|Streamlit, Power BI, Superset hoặc dashboard nội bộ|

### 12.1 Cấu trúc module đề xuất

```
rules_engine/
  config/
    rules/
      customer_master_rules.yaml
      orders_rules.yaml

  core/
    rule_loader.py
    rule_config_validator.py
    rule_executor.py
    result_normalizer.py
    issue_sampler.py

  evaluators/
    completeness_evaluator.py
    validity_evaluator.py
    uniqueness_evaluator.py
    consistency_evaluator.py
    timeliness_evaluator.py
    accuracy_proxy_evaluator.py

  outputs/
    rule_run_writer.py
    rule_result_writer.py
    issue_sample_writer.py
```

### 12.2 Interface xử lý tối giản

```python
class RuleEvaluator:
    def evaluate(self, dataframe, rule_config) -> dict:
        """
        Return normalized counts:
        passed, failed, miscast, empty, not_applicable, total_records_in_scope
        """
        pass
```

Rules Engine có thể gọi evaluator tương ứng theo `rule_type`.

## 13. Kế hoạch triển khai Phase 1

|#|Công việc|Kết quả đầu ra|
|---|---|---|
|1|Chốt rule config schema|Mẫu YAML/JSON rule|
|2|Cài đặt rule loader|Đọc rule từ config|
|3|Cài đặt rule config validator|Kiểm tra rule config trước khi chạy|
|4|Cài đặt evaluator cho Completeness|not_null, not_blank|
|5|Cài đặt evaluator cho Validity|type, regex, length, range, domain|
|6|Cài đặt evaluator cho Uniqueness|uniqueness, composite uniqueness|
|7|Cài đặt evaluator cho Consistency|comparison, conditional_required|
|8|Cài đặt evaluator cho Timeliness|freshness, SLA check cơ bản|
|9|Cài đặt evaluator cho Accuracy Proxy|plausibility_range|
|10|Cài đặt result normalizer|Chuẩn hóa passed/failed/miscast/empty/not_applicable|
|11|Cài đặt output writer|Ghi `rule_run`, `rule_evaluation_result`, `rule_issue_sample`|
|12|Tích hợp với Scoring Engine mock|Tính thử RuleScore|
|13|Tích hợp với Dashboard mock|Hiển thị failed rules và issue samples|
|14|Demo trên dataset mẫu|End-to-end Phase 1|

## 14. Deliverables

|Hạng mục|Mô tả|
|---|---|
|Tài liệu thiết kế Rules Engine|Tài liệu này|
|Rule config schema|Định dạng YAML/JSON cho rule|
|Bộ rule template Phase 1|Completeness, Validity, Uniqueness, Consistency, Timeliness, Accuracy Proxy|
|Source code Rules Engine|Code Python chạy rule và sinh output|
|Dataset mẫu|Dataset dùng để kiểm thử|
|Rule config mẫu|Bộ rule cho dataset mẫu|
|Rule Evaluation Result mẫu|Output dùng cho Scoring Engine|
|README hướng dẫn chạy|Cách cấu hình, chạy Rules Engine và xem kết quả|

## 15. Rủi ro và giả định

|Rủi ro / Giả định|Ảnh hưởng|Biện pháp giảm thiểu|
|---|---|---|
|Metadata thiếu hoặc sai|Rule không chạy được hoặc chạy sai scope|Đánh dấu `not_measured`, yêu cầu bổ sung metadata|
|Rule config sai|Kết quả đánh giá sai|Validate rule config trước khi chạy|
|Null bị tính lỗi nhiều lần|Điểm bị phạt trùng|Dùng `null_policy` và gán dimension chính cho mỗi rule|
|Candidate rule chưa phù hợp nghiệp vụ|Rule gây sai điểm|Chỉ chạy candidate rule sau khi được chuyển thành active rule config|
|Dataset lớn|Rule chạy chậm|Dùng SQL/Spark khi cần; không dùng sample để tính RuleScore chính thức nếu chưa cấu hình sample-based|
|Rule SQL join gây nhân bản dòng|Đếm sai số lỗi|Dùng evaluation key và `COUNT(DISTINCT)` khi cần|
|Thiếu bảng tham chiếu|Referential integrity không chạy được|Đánh dấu rule `not_measured`|
|Dữ liệu nhạy cảm xuất hiện trong issue sample|Rò rỉ thông tin nhạy cảm|Mask hoặc không lưu `actual_value`|
|Dashboard hiểu nhầm số rule lỗi và số bản ghi lỗi|Diễn giải sai chất lượng dataset|Hiển thị rõ rule count và failed record count|

## 16. Phụ lục

### 16.1 Ví dụ file rule config

```
rules:
  - rule_id: DQ-COMP-CUSTOMER-001
    rule_name: Customer ID must not be null
    dataset_id: customer_master
    target_column: customer_id
    dimension: Completeness
    rule_type: not_null
    null_policy: fail
    threshold: 99
    severity: critical
    execution_backend: gx
    status: active
    score_enabled: true

  - rule_id: DQ-VALI-EMAIL-001
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
    execution_backend: gx
    status: active
    score_enabled: true

  - rule_id: DQ-UNIQ-CUSTOMER-001
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

  - rule_id: DQ-ACCU-AGE-001
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

### 16.2 Ví dụ Rule Evaluation Result

```
{
  "rule_run_id": "RRUN_20260625_001",
  "rule_id": "DQ-VALI-EMAIL-001",
  "dataset_id": "customer_master",
  "target_column": "email",
  "dimension": "Validity",
  "evaluation_unit": "record",
  "passed": 950000,
  "failed": 30000,
  "miscast": 0,
  "empty": 20000,
  "not_applicable": 0,
  "total_records_in_scope": 1000000,
  "threshold": 98,
  "measurement_status": "measured",
  "evaluated_at": "2026-06-25T02:00:00Z"
}
```

### 16.3 Ví dụ Issue Sample

```
{
  "rule_run_id": "RRUN_20260625_001",
  "rule_id": "DQ-VALI-EMAIL-001",
  "dataset_id": "customer_master",
  "record_key": "CUS001",
  "target_column": "email",
  "actual_value": "abc@@mail",
  "expected_condition": "Valid email regex",
  "issue_type": "failed",
  "sampled_at": "2026-06-25T02:00:00Z"
}
```


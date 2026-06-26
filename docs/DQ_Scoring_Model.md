# Tài liệu Mô hình Tính điểm Chất lượng Dữ liệu

**Dự án:** Chấm điểm Chất lượng Dữ liệu (DQ Scoring)  
**Module:** Sàn giao dịch dữ liệu và Datalake tập trung  
**Phiên bản:** 1.0.1  
**Ngày:** 16/06/2026  
**Tài liệu liên quan:** DQ_Framework

| Phiên bản | Ngày       | Người thực hiện   | Mô tả thay đổi                                                                        |
| --------- | ---------- | ----------------- | ------------------------------------------------------------------------------------- |
| 1.0       | 11/06/2026 | Nguyễn Hoàng Tùng | Khởi tạo tài liệu                                                                     |
| 1.0.1     | 16/06/2026 | Nguyễn Hoàng Tùng | Cập nhật RuleScore, TrustScore Phase 1, Final Score, Score History và luồng tính điểm |

## 1. Giới thiệu

### 1.1 Mục đích

Tài liệu này mô tả mô hình tính điểm chất lượng dữ liệu trong hệ thống DQ Scoring. Mục tiêu chính là quy đổi kết quả kiểm tra chất lượng dữ liệu thành các điểm số chuẩn hóa trên thang 0–100, từ đó giúp người dùng, Data Steward và người mua dataset đánh giá nhanh chất lượng dữ liệu.

Mô hình tính điểm được tổ chức theo ba cấp độ chính:
1. **Rule Score** – Điểm của từng rule kiểm tra chất lượng dữ liệu.
2. **Dimension Score** – Điểm tổng hợp cho từng trụ cột chất lượng dữ liệu.
3. **DQ Core Score** – Điểm chất lượng kỹ thuật tổng hợp của dataset.

Ngoài ra, tài liệu cũng mô tả khung tính Marketplace Trust Score và cách kết hợp với DQ Core Score để tạo Final Dataset Score hiển thị trên Data Catalog hoặc sàn giao dịch dữ liệu.

Tài liệu này trả lời câu hỏi: “Từ kết quả kiểm tra rule, hệ thống tính điểm chất lượng dataset như thế nào?”

Các định nghĩa về 6 trụ cột chất lượng dữ liệu được mô tả trong tài liệu `DQ_Framework`.

### 1.2 Phạm vi

Tài liệu này áp dụng cho:
- Dataset được quản lý trong datalake tập trung.
- Dataset được công bố trên sàn giao dịch dữ liệu.
- Kết quả kiểm tra từ Rules Engine.
- Kết quả metadata/certification phục vụ Trust Score.
- Dashboard hiển thị DQ Score, Final Score và issue breakdown.

Trong Phase 1, mô hình tập trung vào:
- Công thức tính điểm deterministic và explainable.
- Rule-based scoring.
- Weighted average cho Dimension Score.
- DQ Core Score theo 6 dimension.
- Trust Score Phase 1 dựa trên Metadata và Certification.
- Score History làm nền tảng cho monitoring và Phase 2.

Các kỹ thuật nâng cao như anomaly scoring, drift-aware scoring, usage/feedback-based trust scoring đầy đủ sẽ được mở rộng ở Phase 2.

### 1.3 Nguyên tắc thiết kế

| Nguyên tắc             | Mô tả                                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Chuẩn hóa 0–100        | Mọi điểm số đều được quy về thang 0–100 để dễ so sánh và tổng hợp                                                   |
| Pass-rate làm nền      | Rule Score chủ yếu dựa trên tỉ lệ bản ghi vượt qua rule                                                             |
| Explainable            | Mỗi điểm số có thể truy vết về dimension, rule và số lượng bản ghi lỗi                                              |
| Trọng số cấu hình được | Trọng số rule, dimension và Final Score có thể điều chỉnh theo loại dataset                                         |
| Tách biệt trách nhiệm  | Profiling Pipeline sinh thống kê; Rules Engine chạy rule; Scoring Engine tính điểm                                  |
| Không double-count     | Mỗi rule cần được gán một dimension chính để tránh tính điểm trùng lặp                                              |
| Tái chuẩn hóa trọng số | Nếu thiếu dữ liệu đo ở một thành phần, hệ thống loại thành phần đó khỏi công thức và tái chuẩn hóa trọng số còn lại |

## 2. Cấp 1 – Rule Score

### 2.1 Định nghĩa

**Rule Score** là điểm số của một rule kiểm tra chất lượng dữ liệu cụ thể. Rule Score phản ánh tỉ lệ bản ghi trong phạm vi áp dụng của rule thỏa mãn điều kiện kiểm tra.

Ví dụ:

| Rule                           | Dimension      |
| ------------------------------ | -------------- |
| `customer_id` không được null  | Completeness   |
| `email` phải đúng định dạng    | Validity       |
| `customer_id` không được trùng | Uniqueness     |
| `end_date >= start_date`       | Consistency    |
| Dataset cập nhật đúng SLA      | Timeliness     |
| `age` nằm trong `[0, 120]`     | Accuracy Proxy |

### 2.2 Trạng thái kết quả kiểm tra rule

Khi Rules Engine chạy một rule, mỗi bản ghi trong phạm vi kiểm tra có thể rơi vào một trong các trạng thái sau:

| Trạng thái       | Mô tả                                                             | Có tính vào `total_records_in_scope` không? |
| ---------------- | ----------------------------------------------------------------- | ------------------------------------------- |
| `passed`         | Bản ghi thỏa mãn điều kiện của rule                               | Có                                          |
| `failed`         | Bản ghi vi phạm điều kiện của rule                                | Có                                          |
| `miscast`        | Bản ghi có giá trị sai kiểu dữ liệu, không thể đánh giá chính xác | Có                                          |
| `empty`          | Bản ghi có giá trị null/blank tại trường liên quan                | Có, nếu rule yêu cầu trường đó có giá trị   |
| `not_applicable` | Bản ghi không thuộc phạm vi áp dụng của rule                      | Không                                       |

`not_applicable` đặc biệt quan trọng với các rule có điều kiện.

Ví dụ:

```
Nếu customer_type = "BUSINESS" thì tax_code không được null
```

Trong rule này:
- Bản ghi có `customer_type = "BUSINESS"` thuộc phạm vi kiểm tra.
- Bản ghi có `customer_type != "BUSINESS"` là `not_applicable` và không được đưa vào mẫu số.

#### 2.2.1 Nguyên tắc phân loại trạng thái rule

Các trạng thái `passed`, `failed`, `miscast`, `empty` và `not_applicable` phải được thiết kế theo nguyên tắc loại trừ lẫn nhau trong phạm vi một rule. Mỗi bản ghi chỉ được gán đúng một trạng thái cho một lần chạy rule.

Thứ tự phân loại đề xuất:
1. Nếu bản ghi không thuộc điều kiện áp dụng rule → `not_applicable`.
2. Nếu giá trị null/blank và rule yêu cầu giá trị → `empty`.
3. Nếu giá trị không thể ép kiểu hoặc sai kiểu dữ liệu → `miscast`.
4. Nếu giá trị đúng kiểu nhưng vi phạm điều kiện rule → `failed`.
5. Nếu thỏa mãn điều kiện rule → `passed`.

Nguyên tắc này giúp đảm bảo trong phạm vi một rule:

```
evaluated_records = passed + failed + miscast + empty + not_applicable
```

Trong đó:

```
total_records_in_scope = passed + failed + miscast + empty
```

`not_applicable` không được đưa vào mẫu số tính RuleScore.

Lưu ý: Với các rule không áp dụng ở cấp bản ghi đơn lẻ, ví dụ SLA rule, dataset-level rule hoặc referential integrity check qua nhiều bảng, hệ thống cần định nghĩa rõ đơn vị đánh giá là `record`, `row`, `key`, `update_event` hoặc `dataset_run`.

Ví dụ với rule `amount >= 0`:
- `amount = null` → `empty`
- `amount = "abc"` → `miscast`
- `amount = -100` → `failed`
- `amount = 500` → `passed`

### 2.3 Công thức Rule Score

Công thức cơ bản:

```
RuleScore = passed_records / total_records_in_scope × 100
```

Trong đó:

```
total_records_in_scope = passed + failed + miscast + empty
```

Các bản ghi `not_applicable` không được đưa vào `total_records_in_scope`.

| Thành phần               | Ý nghĩa                                                 |
| ------------------------ | ------------------------------------------------------- |
| `passed_records`         | Số bản ghi thỏa mãn rule                                |
| `total_records_in_scope` | Tổng số bản ghi thuộc phạm vi kiểm tra rule             |
| `failed`                 | Bản ghi vi phạm rule                                    |
| `miscast`                | Bản ghi sai kiểu dữ liệu                                |
| `empty`                  | Bản ghi null/blank trong phạm vi rule                   |
| `not_applicable`         | Bản ghi không thuộc phạm vi rule, không tính vào mẫu số |

### 2.4 Cách xử lý `empty` và `miscast`

Cách xử lý `empty` và `miscast` phụ thuộc vào loại rule:

| Loại rule           | Cách xử lý                                                                                   |
| ------------------- | -------------------------------------------------------------------------------------------- |
| Completeness rule   | `empty` thường được xem là lỗi                                                               |
| Validity rule       | `miscast` thường được xem là lỗi                                                             |
| Conditional rule    | Bản ghi không thỏa điều kiện áp dụng được xem là `not_applicable`                            |
| Optional field rule | Nếu field optional và không nằm trong rule config, bản ghi có thể được loại khỏi scope       |
| Accuracy Proxy rule | Giá trị không thể kiểm tra có thể được phân loại là `miscast` hoặc `not_applicable` tùy rule |

Nguyên tắc chung: mỗi rule cần khai báo rõ `scope`, điều kiện áp dụng và cách xử lý null/blank.

#### 2.4.1 Chính sách xử lý null/blank của rule  
  
Mỗi rule nên khai báo `null_policy` để xác định cách xử lý giá trị null hoặc blank. Đây là cấu hình quan trọng để tránh việc một giá trị null bị trừ điểm lặp lại ở nhiều dimension.  

| `null_policy` | Ý nghĩa                                                                                | Ảnh hưởng đến RuleScore                                                      | Ví dụ sử dụng                                                               |
| ------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `fail`        | Null/blank được xem là lỗi                                                             | Ghi vào `empty` và tính vào `total_records_in_scope`                         | Rule Completeness: `customer_id` không được null                            |
| `ignore`      | Null/blank không thuộc phạm vi kiểm tra                                                | Ghi vào `not_applicable`, không tính vào `total_records_in_scope`            | Rule Validity: chỉ kiểm tra regex email với các email có giá trị            |

Ví dụ:
- Rule `email không được null` → `null_policy = fail`.
- Rule `email phải đúng định dạng` → có thể dùng `null_policy = ignore` nếu null đã được tính ở rule Completeness.
- Rule `tax_code không được null nếu customer_type = "BUSINESS"` → `null_policy = fail`, nhưng chỉ trong scope `customer_type = "BUSINESS"`.

Nguyên tắc triển khai: mỗi rule cần khai báo tối thiểu `scope`, `dimension`, `null_policy`, `threshold` và `target_column`.


### 2.5 Công thức cho SQL-based Rule

Với rule triển khai bằng SQL, cần quy ước rõ query trả về bản ghi vi phạm, bản ghi đạt hay kết quả đã được phân loại theo failure type.

#### Trường hợp 1: SQL query trả về bản ghi không đạt

Nếu query chỉ trả về các bản ghi không đạt, hệ thống có thể tính rule theo dạng nhị phân:

```
non_passed_records = number_of_output_records  
passed_records = total_records_in_scope - non_passed_records  
RuleScore = passed_records / total_records_in_scope × 100
```

Tương đương:

```
RuleScore = (1 - non_passed_records / total_records_in_scope) × 100
```

Trong trường hợp này, `non_passed_records` có thể bao gồm `failed`, `miscast` hoặc `empty`, nhưng SQL chưa phân biệt được từng loại lỗi.

#### Trường hợp 2: SQL query trả về bản ghi đạt

Nếu query trả về các bản ghi đạt:

```
passed_records = number_of_output_records
RuleScore = passed_records / total_records_in_scope × 100
```

#### Trường hợp 3: SQL query trả về kết quả đã phân loại lỗi (Phase 2)

Để phục vụ explainability tốt hơn, SQL-based rule nên trả thêm `failure_type` hoặc trạng thái đánh giá.

Ví dụ:

| record_id | rule_id            | evaluation_status |
| --------- | ------------------ | ----------------- |
| 001       | DQ-VALI-AMOUNT-001 | passed            |
| 002       | DQ-VALI-AMOUNT-001 | failed            |
| 003       | DQ-VALI-AMOUNT-001 | miscast           |
| 004       | DQ-VALI-AMOUNT-001 | empty             |
| 005       | DQ-VALI-AMOUNT-001 | not_applicable    |

Kết quả cuối cùng cần được chuẩn hóa về dạng:

```
passed + failed + miscast + empty + not_applicable
```

Lưu ý:
- `total_records_in_scope` chỉ bao gồm `passed + failed + miscast + empty`.
- `not_applicable` không được đưa vào mẫu số.
- Nếu SQL query chỉ trả danh sách bản ghi lỗi, hệ thống vẫn tính được RuleScore nhưng khả năng giải thích nguyên nhân lỗi sẽ thấp hơn.

Yêu cầu kỹ thuật đối với SQL-based rule:
- Query output phải có định danh bản ghi hoặc khóa đánh giá, ví dụ `record_id`, `primary_key`, `business_key` hoặc `evaluation_key`.
- Mỗi bản ghi/khóa đánh giá chỉ được xuất hiện một lần trong kết quả của một rule.
- Nếu query có join gây nhân bản dòng, cần dùng `COUNT(DISTINCT evaluation_key)` thay vì `COUNT(*)`.
- Với referential integrity rule, đơn vị đánh giá nên là khóa ngoại hoặc bản ghi con cần kiểm tra.
- Với dataset-level rule hoặc SLA rule, đơn vị đánh giá có thể không phải là record mà là `dataset_run` hoặc `update_event`.

### 2.6 Ví dụ Rule Score

**Rule:** `order_id` không được null trong bảng `orders`.

| Metric                          | Giá trị                         |
| ------------------------------- | ------------------------------- |
| Tổng bản ghi                    | 10,000                          |
| `passed` – `order_id` khác null | 9,850                           |
| `empty` – `order_id` null       | 150                             |
| `failed`                        | 0                               |
| `miscast`                       | 0                               |
| `not_applicable`                | 0                               |
| `total_records_in_scope`        | 10,000                          |
| **Rule Score**                  | **9,850 / 10,000 × 100 = 98.5** |

Nhận xét: Rule Score = 98.5 cho thấy rule đạt mức khá cao, nhưng vẫn có 150 bản ghi thiếu `order_id` cần được xem xét.

### 2.7 Ví dụ Conditional Rule

**Rule:** Nếu `customer_type = "BUSINESS"` thì `tax_code` không được null.

| Metric                                       | Giá trị                        |
| -------------------------------------------- | ------------------------------ |
| Tổng bản ghi                                 | 10,000                         |
| Bản ghi `customer_type = "BUSINESS"`         | 2,000                          |
| Bản ghi `customer_type != "BUSINESS"`        | 8,000                          |
| `passed` – business customer có `tax_code`   | 1,900                          |
| `empty` – business customer thiếu `tax_code` | 100                            |
| `not_applicable`                             | 8,000                          |
| `total_records_in_scope`                     | 2,000                          |
| **Rule Score**                               | **1,900 / 2,000 × 100 = 95.0** |


## 3. Cấp 2 – Dimension Score

### 3.1 Định nghĩa

**Dimension Score** là điểm tổng hợp cho một trụ cột chất lượng dữ liệu, được tính từ tập hợp các Rule Score thuộc cùng dimension.

Các dimension được lấy từ DQ_Framework:

| Dimension                 | Tên tiếng Việt                           |
| ------------------------- | ---------------------------------------- |
| Completeness              | Tính đầy đủ                              |
| Accuracy / Accuracy Proxy | Tính chính xác / Tính chính xác đại diện |
| Consistency               | Tính nhất quán                           |
| Timeliness                | Tính thời sự                             |
| Uniqueness                | Tính duy nhất                            |
| Validity                  | Tính hợp lệ                              |

Trong Phase 1, Accuracy thường được tính dưới dạng Accuracy Proxy thông qua `plausibility_rate`, range check hoặc statistical bounds.

### 3.2 Công thức Weighted Average

Công thức mặc định trong Phase 1 là weighted average:

```
DimensionScore = Σ (w_i × RuleScore_i)
```

Với điều kiện:

```
Σ w_i = 1.0
```

Trong đó:

| Thành phần       | Ý nghĩa                             |
| ---------------- | ----------------------------------- |
| `RuleScore_i`    | Điểm của rule thứ i trong dimension |
| `w_i`            | Trọng số của rule thứ i             |
| `DimensionScore` | Điểm tổng hợp của dimension         |

Nếu chưa có lý do nghiệp vụ để phân biệt trọng số giữa các rule, có thể dùng trọng số bằng nhau:

```
DimensionScore = (RuleScore_1 + RuleScore_2 + ... + RuleScore_n) / n
```

#### 3.2.1 Lưu ý khi rule có phạm vi kiểm tra khác nhau

Weighted average theo rule giúp dễ cấu hình và dễ giải thích, nhưng có thể gây sai lệch nếu các rule có `total_records_in_scope` chênh lệch quá lớn.

Ví dụ:
- Rule A áp dụng cho 100 bản ghi, RuleScore = 50.
- Rule B áp dụng cho 1,000,000 bản ghi, RuleScore = 99.

Nếu dùng trọng số bằng nhau:

```text
DimensionScore = (50 + 99) / 2 = 74.5
```

Điểm này có thể phạt quá nặng nếu Rule A chỉ áp dụng cho một subset nhỏ.

Trong Phase 1, hệ thống có thể dùng weighted average theo rule để đơn giản hóa. Tuy nhiên, khi các rule có scope chênh lệch lớn, nên cân nhắc một trong hai cách:
1. Cấu hình trọng số rule theo mức độ quan trọng nghiệp vụ.
2. Dùng evaluation-weighted average trong trường hợp các rule có ý nghĩa tương đương.

Công thức evaluation-weighted average tham khảo:

```
DimensionScore = Σ passed_records_i / Σ total_records_in_scope_i × 100
```

Cách này tổng hợp theo tổng số lượt đánh giá rule, không phải số bản ghi duy nhất. Một bản ghi xuất hiện trong nhiều rule có thể được tính nhiều lần.

Lưu ý: evaluation-weighted average chỉ phù hợp khi các rule có cùng ý nghĩa nghiệp vụ hoặc khi chấp nhận việc một bản ghi được đánh giá nhiều lần. Nếu các rule đánh giá các CDE khác nhau, nên ưu tiên trọng số do Data Steward cấu hình.

### 3.3 Tái chuẩn hóa trọng số rule

Nếu một rule trong dimension chưa có dữ liệu đo hoặc chưa được chạy, rule đó được loại khỏi phép tính và trọng số của các rule còn lại được tái chuẩn hóa.

```
normalized_rule_weight_i = original_rule_weight_i / Σ original_rule_weight_j
```

Trong đó `j` là các rule có dữ liệu đo hợp lệ.

Sau đó:

```
DimensionScore = Σ (normalized_rule_weight_i × RuleScore_i)
```

Ví dụ: dimension Completeness có 3 rule với trọng số 0.5, 0.3, 0.2. Nếu rule thứ 3 chưa chạy, trọng số được tái chuẩn hóa:

```
Rule 1: 0.5 / (0.5 + 0.3) = 0.625
Rule 2: 0.3 / (0.5 + 0.3) = 0.375
```


Rule chưa chạy hoặc không đủ dữ liệu không nên được gán điểm 0. Thay vào đó, rule đó được gán trạng thái `not_measured` và bị loại khỏi phép tính Dimension Score trong lần chạy hiện tại.  
  
Các trạng thái đo lường của rule:  
  
| Trạng thái     | Ý nghĩa                                                          |
| -------------- | ---------------------------------------------------------------- |
| `measured`     | Rule đã chạy và có đủ dữ liệu để tính điểm                       |
| `not_measured` | Rule chưa có dữ liệu đo, thiếu metadata hoặc chưa được kích hoạt |
| `skipped`      | Rule bị bỏ qua có chủ đích trong lần chạy hiện tại               |
  
Chỉ các rule có trạng thái `measured` mới được đưa vào công thức tính Dimension Score.  
  
Nếu tất cả rule trong một dimension đều ở trạng thái `not_measured` hoặc `skipped`, Dimension Score không được gán bằng 0. Dimension đó được đánh dấu là `not_measured`.

### 3.4 Phương pháp lỗi tích lũy – Phase 2

Với các rule độc lập, có thể sử dụng phương pháp nhân xác suất không lỗi:

```
DimensionScore = Π (1 - frequency_i) × 100
```

Trong đó:

| Thành phần        | Ý nghĩa                        |
| ----------------- | ------------------------------ |
| `frequency_i`     | Tỉ lệ lỗi của rule thứ i       |
| `1 - frequency_i` | Tỉ lệ không lỗi của rule thứ i |

Ví dụ: Một cột `email` thuộc dimension Validity có 2 rule Validity độc lập:

- Rule 1: Email đúng định dạng – lỗi 10% (`frequency = 0.10`)
- Rule 2: Email không chứa ký tự cấm hoặc khoảng trắng – lỗi 5% (`frequency = 0.05`)

```
DimensionScore_Validity = (1 - 0.10) × (1 - 0.05) × 100
                        = 0.90 × 0.95 × 100
                        = 85.5
```

Lưu ý:
- Phase 1 sử dụng weighted average.
- Phương pháp lỗi tích lũy chỉ nên dùng ở Phase 2.
- Cần thận trọng vì phương pháp này giả định các lỗi tương đối độc lập.
- Nếu các rule có quan hệ phụ thuộc, phương pháp này có thể làm điểm bị phạt quá nặng.

### 3.5 Ví dụ Dimension Score – Completeness

Bảng `customer_master` có 3 rule thuộc dimension Completeness:

| Rule ID     | Mô tả                                               | Rule Score | Trọng số |
| ----------- | --------------------------------------------------- | ---------- | -------- |
| DQ-COMP-001 | `customer_id`, `full_name`, `email` không được null | 98.0       | 0.50     |
| DQ-COMP-002 | `country_code` không được null                      | 99.5       | 0.30     |
| DQ-COMP-003 | `phone_number` không được null                      | 94.0       | 0.20     |

```
Completeness Score = (0.50 × 98.0) + (0.30 × 99.5) + (0.20 × 94.0)
                   = 49.0 + 29.85 + 18.8
                   = 97.65
```



## 4. Cấp 3 – DQ Core Score

### 4.1 Định nghĩa

**DQ Core Score** là điểm chất lượng kỹ thuật tổng hợp của dataset. Điểm này được tính từ các Dimension Score có trọng số.

DQ Core Score phản ánh chất lượng dữ liệu theo các khía cạnh kỹ thuật và nghiệp vụ cơ bản, bao gồm completeness, validity, consistency, timeliness, uniqueness và accuracy proxy.

DQ Core Score được sử dụng bởi:
- Data Engineer.
- Data Steward.
- Dataset Owner.
- Dashboard DQ Monitoring.
- Data Catalog / Data Marketplace.

### 4.2 Trọng số dimension mặc định

Trọng số dưới đây là gợi ý mặc định cho Phase 1. Trọng số có thể điều chỉnh theo loại dataset và yêu cầu nghiệp vụ.

| Dimension                 | Tên tiếng Việt            | Trọng số mặc định | Ghi chú                                                                   |
| ------------------------- | ------------------------- | ----------------- | ------------------------------------------------------------------------- |
| Completeness              | Tính đầy đủ               | 20%               | Yếu tố cơ bản ảnh hưởng trực tiếp đến khả năng sử dụng                    |
| Validity                  | Tính hợp lệ               | 20%               | Dễ kiểm tra bằng rule, phổ biến trong lỗi dữ liệu                         |
| Consistency               | Tính nhất quán            | 15%               | Quan trọng trong dataset có nhiều trường hoặc nhiều bảng liên quan        |
| Timeliness                | Tính thời sự              | 15%               | Ảnh hưởng trực tiếp đến giá trị sử dụng của dataset                       |
| Uniqueness                | Tính duy nhất             | 10%               | Quan trọng với khóa định danh và chống duplicate                          |
| Accuracy / Accuracy Proxy | Tính chính xác / đại diện | 20%               | Phase 1 dùng plausibility check; nếu chưa có rule thì loại khỏi tính toán |
| **Tổng**                  |                           | **100%**          |                                                                           |

### 4.3 Công thức tính DQ Core Score

```
DQ_Core = Σ (dimension_weight_i × DimensionScore_i)
```

Với trọng số mặc định:

```
DQ_Core = 0.20 × S_Comp
        + 0.20 × S_Valid
        + 0.15 × S_Cons
        + 0.15 × S_Time
        + 0.10 × S_Uniq
        + 0.20 × S_Accu
```

Trong đó:

| Ký hiệu   | Ý nghĩa                            |
| --------- | ---------------------------------- |
| `S_Comp`  | Completeness Score                 |
| `S_Valid` | Validity Score                     |
| `S_Cons`  | Consistency Score                  |
| `S_Time`  | Timeliness Score                   |
| `S_Uniq`  | Uniqueness Score                   |
| `S_Accu`  | Accuracy hoặc Accuracy Proxy Score |

### 4.4 Tái chuẩn hóa trọng số dimension

Nếu một dimension chưa có rule, chưa đủ metadata hoặc chưa đủ dữ liệu đo, dimension đó được loại khỏi phép tính DQ Core Score. Trọng số của các dimension còn lại được tái chuẩn hóa để tổng bằng 100%.

Dimension chưa có dữ liệu đo không được gán điểm 0. Thay vào đó, dimension được gán trạng thái `not_measured` và bị loại khỏi công thức tính DQ Core Score trong lần chạy hiện tại.

Các trạng thái đo lường của dimension:

| Trạng thái | Ý nghĩa |
|---|---|
| `measured` | Dimension có ít nhất một rule hợp lệ và đủ dữ liệu để tính điểm |
| `not_measured` | Dimension chưa có rule, thiếu metadata hoặc không đủ dữ liệu đo |
| `skipped` | Dimension bị bỏ qua có chủ đích theo cấu hình dataset |

Chỉ các dimension có trạng thái `measured` mới được đưa vào công thức DQ Core Score.

Công thức:

```
normalized_dimension_weight_i = original_dimension_weight_i / Σ original_dimension_weight_j
```

Trong đó `j` là các dimension có dữ liệu đo hợp lệ.

Sau đó:

```
DQ_Core = Σ (normalized_dimension_weight_i × DimensionScore_i)
```

Ví dụ: Nếu Accuracy Proxy chưa có rule trong Phase 1, loại Accuracy khỏi công thức. Tổng trọng số còn lại:

```
20% + 20% + 15% + 15% + 10% = 80%
```

Trọng số mới:

| Dimension    | Trọng số gốc | Trọng số sau tái chuẩn hóa |
| ------------ | ------------ | -------------------------- |
| Completeness | 20%          | 20 / 80 = 25.00%           |
| Validity     | 20%          | 20 / 80 = 25.00%           |
| Consistency  | 15%          | 15 / 80 = 18.75%           |
| Timeliness   | 15%          | 15 / 80 = 18.75%           |
| Uniqueness   | 10%          | 10 / 80 = 12.50%           |

Nếu tất cả dimension đều ở trạng thái `not_measured`, hệ thống không tính `DQ_Core`. Khi đó dataset cần được đánh dấu là `not_scored` hoặc `insufficient_metadata`, thay vì hiển thị điểm 0.

### 4.5 Điều chỉnh trọng số theo loại dataset

| Loại dataset                   | Completeness | Validity | Consistency | Timeliness | Uniqueness | Accuracy / Accuracy Proxy |
| ------------------------------ | ------------ | -------- | ----------- | ---------- | ---------- | ------------------------- |
| Giao dịch tài chính            | 20%          | 20%      | 15%         | 20%        | 15%        | 10%                       |
| Hồ sơ khách hàng / Master Data | 25%          | 25%      | 15%         | 10%        | 15%        | 10%                       |
| Log / Event Data               | 15%          | 15%      | 10%         | 30%        | 20%        | 10%                       |
| Reference Data                 | 15%          | 30%      | 20%         | 10%        | 15%        | 10%                       |
| Mặc định                       | 20%          | 20%      | 15%         | 15%        | 10%        | 20%                       |

Lưu ý: Bảng trọng số trên là đề xuất ban đầu. Khi triển khai, trọng số nên được quản lý trong metadata hoặc file cấu hình thay vì hardcode trong hệ thống.

### 4.6 Ví dụ tính DQ Core Score

Dataset: `customer_master`  
Loại dataset: Master Data

| Dimension         | Score  | Trọng số Master Data | Điểm đóng góp |
| ----------------- | ------ | -------------------- | ------------- |
| Completeness      | 97.65  | 25%                  | 24.41         |
| Validity          | 92.00  | 25%                  | 23.00         |
| Consistency       | 96.00  | 15%                  | 14.40         |
| Timeliness        | 100.00 | 10%                  | 10.00         |
| Uniqueness        | 99.50  | 15%                  | 14.93         |
| Accuracy Proxy    | 88.00  | 10%                  | 8.80          |
| **DQ Core Score** |        | **100%**             | **95.54**     |

```
DQ_Core = 24.41 + 23.00 + 14.40 + 10.00 + 14.93 + 8.80
        = 95.54
```


## 5. Marketplace Trust Score

### 5.1 Định nghĩa

**Marketplace Trust Score** phản ánh mức độ tín nhiệm của dataset trên sàn giao dịch dữ liệu. Khác với DQ Core Score, Trust Score không chỉ đo chất lượng kỹ thuật của dữ liệu mà còn phản ánh chất lượng metadata, mức độ chứng nhận, hành vi sử dụng và phản hồi từ người mua dataset.

Trust Score giúp người mua dataset đánh giá nhanh:
- Dataset có được mô tả đầy đủ không.
- Dataset có owner/steward rõ ràng không.
- Dataset có được chứng nhận không.
- Dataset có được sử dụng hoặc đánh giá tích cực không.
- Dataset có đáng tin để giao dịch hoặc tích hợp vào pipeline không.

### 5.2 Thành phần Trust Score đầy đủ

Công thức đầy đủ dự kiến sử dụng từ Phase 2 trở đi, khi sàn giao dịch đã có dữ liệu usage, transaction và feedback.

| Thành phần                 | Mô tả                                                                    | Trọng số đầy đủ |
| -------------------------- | ------------------------------------------------------------------------ | --------------- |
| Metadata / Discoverability | Đầy đủ mô tả, schema, owner, tag, lineage, access policy, sample preview | 40%             |
| Usage / Transactions       | Số lượt xem, số lần sử dụng, số giao dịch mua, tần suất tái sử dụng      | 25%             |
| Feedback / Reputation      | Rating trung bình, tỉ lệ dispute, nhận xét từ người mua                  | 25%             |
| Certification              | Được Data Steward hoặc Dataset Owner phê duyệt và gắn nhãn certified     | 10%             |
| **Tổng**                   |                                                                          | **100%**        |

Công thức đầy đủ:

```
TrustScore = 0.40 × S_Metadata
           + 0.25 × S_Usage
           + 0.25 × S_Feedback
           + 0.10 × S_Cert
```

### 5.3 Trust Score Phase 1

Trong Phase 1, hệ thống chưa có đủ dữ liệu vận hành từ sàn giao dịch, do đó chưa sử dụng `S_Usage` và `S_Feedback` trong công thức tính điểm chính thức.

Hai thành phần này không được gán bằng 0 trong công thức Phase 1. Thay vào đó, chúng được loại khỏi phạm vi tính điểm và trọng số được tái chuẩn hóa cho các thành phần còn lại.

Phase 1 chỉ sử dụng:

| Thành phần                 | Trọng số gốc | Trọng số Phase 1 sau tái chuẩn hóa |
| -------------------------- | ------------ | ---------------------------------- |
| Metadata / Discoverability | 40%          | 80%                                |
| Certification              | 10%          | 20%                                |
| Usage / Transactions       | 25%          | Chưa tính                          |
| Feedback / Reputation      | 25%          | Chưa tính                          |

Công thức Phase 1:

```
TrustScore_Phase1 = 0.80 × S_Metadata + 0.20 × S_Cert
```

Trong đó:

| Thành phần   | Ý nghĩa                              |
| ------------ | ------------------------------------ |
| `S_Metadata` | Điểm chất lượng metadata của dataset |
| `S_Cert`     | Điểm chứng nhận/phê duyệt dataset    |
| `S_Usage`    | Chưa tính trong Phase 1              |
| `S_Feedback` | Chưa tính trong Phase 1              |

Lưu ý:
- Khi Phase 2 có đủ dữ liệu usage và feedback, hệ thống chuyển sang công thức Trust Score đầy đủ.
- Cách tính chi tiết `S_Metadata` nên được mô tả trong tài liệu Dataset Metadata Requirements.
- `S_Cert` có thể là điểm nhị phân hoặc điểm theo cấp độ chứng nhận.

### 5.4 Gợi ý cách tính các thành phần Phase 1

#### Metadata Score

Ví dụ cấu trúc `S_Metadata`:

| Nhóm metadata              | Gợi ý trọng số |
| -------------------------- | -------------- |
| Mô tả dataset              | 20%            |
| Schema/column description  | 25%            |
| Owner/Data Steward         | 15%            |
| Tags/domain/category       | 10%            |
| Lineage/source information | 15%            |
| Access policy/license      | 10%            |
| Sample preview             | 5%             |

#### Certification Score

Gợi ý:

| Trạng thái chứng nhận | `S_Cert` |
| --------------------- | -------- |
| Certified             | 100      |
| Reviewed              | 70       |
| Draft / Not certified | 0        |

Cách xử lý `S_Cert` trong Phase 1 phụ thuộc vào mức độ hoàn thiện của quy trình certification.

- Trường hợp 1 – Đã có quy trình review/certify:  
	- Nếu dataset chưa được chứng nhận, `S_Cert = 0`.  
	- Đây là cơ chế phạt có chủ đích để khuyến khích dataset được Data Steward review hoặc certify.  

- Trường hợp 2 – Chưa có quy trình certification:  
	- `S_Cert` được xem là `not_measured`.  
	- TrustScore Phase 1 chỉ tính bằng `S_Metadata`.  
	- Khi đó:  
```
TrustScore_Phase1 = S_Metadata
```

Quy ước Phase 1: nếu đã có bước Data Steward review tối thiểu, `S_Cert` được tính theo trạng thái chứng nhận của dataset. Nếu chưa có quy trình review/certify, `S_Cert` được xem là `not_measured` để tránh phạt sai các dataset chưa thể được chứng nhận.

## 6. Final Dataset Score

### 6.1 Định nghĩa

**Final Dataset Score** là điểm tổng hợp cuối cùng được hiển thị trên Data Catalog hoặc sàn giao dịch dữ liệu. Điểm này kết hợp:
- **DQ Core Score** – chất lượng kỹ thuật của dataset.
- **Marketplace Trust Score** – mức độ tín nhiệm của dataset trên sàn.

Final Dataset Score phục vụ người mua dataset và người dùng cuối khi cần đánh giá nhanh dataset có đáng tin cậy để sử dụng hay không.

### 6.2 Công thức Final Score

Công thức tổng quát:

```
FinalScore = α × DQ_Core + (1 - α) × TrustScore
```

Trong Phase 1, đề xuất:

```
FinalScore = 0.70 × DQ_Core + 0.30 × TrustScore
```

Trong đó:

| Thành phần   | Ý nghĩa                         |
| ------------ | ------------------------------- |
| `DQ_Core`    | Điểm chất lượng kỹ thuật        |
| `TrustScore` | Điểm tín nhiệm dataset          |
| `α`          | Tỉ trọng dành cho DQ Core Score |
| `1 - α`      | Tỉ trọng dành cho Trust Score   |

Với Phase 1:

```
α = 0.70
1 - α = 0.30
```

Lý do: Phase 1 ưu tiên chất lượng kỹ thuật của dữ liệu, trong khi Trust Score mới ở mức metadata/certification, chưa có usage và feedback thực tế.

#### 6.2.1 Xử lý khi thiếu thành phần điểm

Nếu một thành phần chưa đủ dữ liệu đo, hệ thống cần xử lý theo nguyên tắc tái chuẩn hóa trọng số hoặc không hiển thị FinalScore nếu thiếu thành phần cốt lõi.

| Trường hợp | Cách xử lý |
|---|---|
| Có cả `DQ_Core` và `TrustScore` | Tính theo công thức `0.70 × DQ_Core + 0.30 × TrustScore` |
| Có `DQ_Core`, chưa có `TrustScore` | `FinalScore = DQ_Core`, đồng thời hiển thị TrustScore là `not_measured` |
| Chưa có `DQ_Core`, có `TrustScore` | Không nên hiển thị FinalScore chất lượng; chỉ hiển thị TrustScore tham khảo |
| Cả hai đều thiếu | Dataset ở trạng thái `not_scored` |

Không nên gán điểm 0 cho thành phần chưa đo được, vì điều này làm sai bản chất chất lượng dữ liệu.

### 6.3 Phân loại điểm và badge hiển thị

| Final Score | Badge        | Màu        | Ý nghĩa cho người mua                            |
| ----------- | ------------ | ---------- | ------------------------------------------------ |
| 90 – 100    | Excellent    | Xanh đậm   | Chất lượng xuất sắc, phù hợp để sử dụng ngay     |
| 80 – 89     | Reliable     | Xanh lá    | Chất lượng tốt, tin cậy cho hầu hết use case     |
| 65 – 79     | Acceptable   | Xanh dương | Chấp nhận được, nên kiểm tra thêm trước khi dùng |
| 50 – 64     | At Risk      | Vàng       | Có vấn đề đáng kể, cần đánh giá kỹ               |
| 0 – 49      | Needs Review | Đỏ         | Không nên dùng cho mục đích quan trọng           |

Lưu ý: 
- Ngưỡng badge có thể được điều chỉnh theo chính sách vận hành của sàn giao dịch dữ liệu. 
- Badge nên được xác định dựa trên điểm raw trước khi làm tròn hiển thị. 
- Ví dụ, `FinalScore = 89.95` vẫn thuộc badge Reliable nếu hệ thống chưa áp dụng chính sách làm tròn để phân loại. 
- Điểm hiển thị có thể được làm tròn đến 1 hoặc 2 chữ số thập phân.

### 6.4 Ví dụ tính Final Dataset Score

Dataset: `customer_master`

| Thành phần    | Giá trị | Trọng số |
| ------------- | ------- | -------- |
| DQ Core Score | 95.54   | 70%      |
| Trust Score   | 78.00   | 30%      |

```
FinalScore = (0.70 × 95.54) + (0.30 × 78.00)
           = 66.88 + 23.40
           = 90.28
```

Kết quả:

| Final Score | Badge     |
| ----------- | --------- |
| 90.28       | Excellent |

**Kết luận:** Dataset đạt badge **Excellent**, có chất lượng tổng hợp cao và đủ điều kiện tin cậy để giao dịch trên sàn.



## 7. Kiến trúc luồng tính điểm

### 7.1 Luồng tổng quát

```
1. [Raw Data / Dataset]
        
2. [Profiling Pipeline]
   - Đọc dữ liệu
   - Trích xuất thống kê dataset/cột
   - Sinh Profile Result, Candidate Rule, Anomaly Flag
        
3. [Rules Engine]
   - Chạy các rule chính thức
   - Sinh Rule Evaluation Result:
     passed / failed / miscast / empty / not_applicable
        
4. [Scoring Engine]
   - Tính Rule Score
   - Tổng hợp Dimension Score
   - Tính DQ Core Score
        
5. [Metadata & Certification Check]
   - Tính S_Metadata
   - Tính S_Cert
   - Tính TrustScore_Phase1
        
6. [Final Dataset Score]
   - FinalScore = 0.70 × DQ_Core + 0.30 × TrustScore
        
7. [Dashboard / Data Catalog / API]
   - Badge
   - Score breakdown
   - Failed rules
   - Issue summary
   - Score history
```

### 7.2 Vai trò từng module

| Module              | Vai trò                                                             |
| ------------------- | ------------------------------------------------------------------- |
| Profiling Pipeline  | Trích xuất thống kê, profile result, candidate rule và anomaly flag |
| Rules Engine        | Chạy rule chính thức và tạo Rule Evaluation Result                  |
| Scoring Engine      | Tính Rule Score, Dimension Score và DQ Core Score                   |
| Metadata Check      | Kiểm tra metadata, sample preview, owner, schema, lineage           |
| Certification Check | Kiểm tra trạng thái chứng nhận dataset                              |
| Dashboard           | Hiển thị điểm số, badge, issue breakdown và lịch sử điểm            |

Lưu ý: Rules Engine không nằm bên trong Profiling Pipeline. Profiling Pipeline chỉ tạo dữ liệu đầu vào và gợi ý; Rules Engine mới quyết định rule chính thức và sinh kết quả kiểm tra để Scoring Engine tính điểm.

## 8. Lưu lịch sử điểm số

### 8.1 Mục đích

Score History được sử dụng để:
- Theo dõi chất lượng dataset theo thời gian.
- Hiển thị trend chart trên dashboard.
- Phân tích nguyên nhân điểm tăng/giảm.
- Làm baseline cho phát hiện anomaly và data drift trong Phase 2.
- Hỗ trợ audit và giải thích điểm số.

Để đảm bảo explainability, hệ thống nên lưu lịch sử điểm ở ba cấp:
1. Rule-level score history.
2. Dimension-level score history.
3. Dataset-level score history.

### 8.2 Bảng `score_run`

Lưu thông tin mỗi lần chạy scoring.

| Trường              | Kiểu     | Mô tả                                   |
| ------------------- | -------- | --------------------------------------- |
| `run_id`            | string   | Định danh duy nhất của lần chạy scoring |
| `dataset_id`        | string   | Định danh dataset                       |
| `dataset_version`   | string   | Phiên bản dataset, nếu có               |
| `run_timestamp`     | datetime | Thời điểm chạy scoring                  |
| `profiling_run_id`  | string   | Mã lần chạy profiling liên quan         |
| `status`            | string   | success, failed, partial                |
| `execution_context` | string   | batch, manual, scheduled, API           |

### 8.3 Bảng `rule_score_history`

Lưu kết quả điểm ở cấp rule.

| Trường                   | Kiểu   | Mô tả                               |
| ------------------------ | ------ | ----------------------------------- |
| `run_id`                 | string | Định danh lần chạy                  |
| `dataset_id`             | string | Định danh dataset                   |
| `rule_id`                | string | Định danh rule                      |
| `dimension`              | string | Dimension của rule                  |
| `target_column`          | string | Cột áp dụng, nếu có                 |
| `passed`                 | int    | Số bản ghi đạt                      |
| `failed`                 | int    | Số bản ghi lỗi                      |
| `miscast`                | int    | Số bản ghi sai kiểu                 |
| `empty`                  | int    | Số bản ghi null/blank trong scope   |
| `not_applicable`         | int    | Số bản ghi không thuộc phạm vi rule |
| `total_records_in_scope` | int    | Tổng số bản ghi thuộc phạm vi rule  |
| `rule_score`             | float  | Điểm rule                           |
| `threshold`              | float  | Ngưỡng rule                         |
| `measurement_status`     | string | measured, not_measured, skipped     |
| `quality_status`         | string | pass, warning, fail                 |

### 8.4 Bảng `dimension_score_history`

Lưu kết quả điểm ở cấp dimension.

| Trường                      | Kiểu    | Mô tả                                          |
| --------------------------- | ------- | ---------------------------------------------- |
| `run_id`                    | string  | Định danh lần chạy                             |
| `dataset_id`                | string  | Định danh dataset                              |
| `dimension`                 | string  | Tên dimension                                  |
| `dimension_score`           | float   | Điểm dimension                                 |
| `original_dimension_weight` | float   | Trọng số dimension ban đầu trước tái chuẩn hóa |
| `dimension_weight`          | float   | Trọng số dimension sau tái chuẩn hóa           |
| `is_measured`               | boolean | Dimension có được tính vào DQ Core hay không   |
| `measurement_status`        | string  | measured, not_measured, skipped                |
| `rules_total`               | int     | Tổng số rule thuộc dimension                   |
| `rules_failed`              | int     | Số rule thất bại                               |
| `rules_warning`             | int     | Số rule cảnh báo                               |
| `rules_passed`              | int     | Số rule đạt                                    |

Lưu ý: `rules_failed`, `rules_warning` và `rules_passed` là số lượng rule theo trạng thái, không phải số lượng bản ghi lỗi. Số lượng bản ghi lỗi được lưu ở bảng `rule_score_history`.

### 8.5 Bảng `dataset_score_history`

Lưu kết quả điểm tổng hợp cấp dataset.

| Trường                  | Kiểu     | Mô tả                                                   |
| ----------------------- | -------- | ------------------------------------------------------- |
| `run_id`                | string   | Định danh lần chạy                                      |
| `dataset_id`            | string   | Định danh dataset                                       |
| `dataset_version`       | string   | Phiên bản dataset, nếu có                               |
| `run_timestamp`         | datetime | Thời điểm chạy scoring                                  |
| `dq_core_score`         | float    | DQ Core Score                                           |
| `trust_score`           | float    | Marketplace Trust Score                                 |
| `final_score`           | float    | Final Dataset Score                                     |
| `badge`                 | string   | Excellent, Reliable, Acceptable, At Risk, Needs Review  |
| `quality_gate_status`   | string   | pass, warning, fail                                     |
| `total_records`         | int      | Tổng số bản ghi được kiểm tra                           |
| `rules_total`           | int      | Tổng số rule                                            |
| `rules_failed`          | int      | Tổng số rule thất bại                                   |

Các trường dữ liệu mở rộng có thể bổ sung ở Phase 2 hoặc khi dashboard cần giải thích sâu hơn:

| Trường                  | Kiểu     | Mô tả                                                   |
| ----------------------- | -------- | ------------------------------------------------------- |
| `s_metadata`            | float    | Metadata Score                                          |
| `s_cert`                | float    | Certification Score                                     |
| `certification_status`  | string   | certified, reviewed, draft, not_certified, not_measured |
| `trust_score_status`    | string   | measured, partial, not_measured                         |
| `dq_core_weight`        | float    | Trọng số DQ Core trong Final Score                      |
| `trust_score_weight`    | float    | Trọng số Trust Score trong Final Score                  |
| `measured_dimensions`   | array    | Danh sách dimension được tính vào DQ Core               |
| `excluded_dimensions`   | array    | Danh sách dimension bị loại khỏi DQ Core                |
| `top_failed_dimensions` | object   | Các dimension có vấn đề nổi bật                         |
| `score_level`           | string   | dataset                                                 |

#### 8.5.1 Quality Gate Status

Ngoài badge hiển thị cho người mua, hệ thống nên có `quality_gate_status` để phục vụ vận hành pipeline và kiểm soát phát hành dataset.

| `quality_gate_status` | Ý nghĩa |
|---|---|
| `pass` | Dataset đạt ngưỡng chất lượng tối thiểu |
| `warning` | Dataset có vấn đề nhưng vẫn có thể sử dụng với cảnh báo |
| `fail` | Dataset không đạt ngưỡng chất lượng, cần review trước khi công bố hoặc giao dịch |

Trong Phase 1, nếu chưa có cấu hình critical rule hoặc critical dimension, `quality_gate_status` có thể xác định theo `DQ_Core`: 

| Điều kiện            | `quality_gate_status` |
| -------------------- | --------------------- |
| `DQ_Core >= 80`      | pass                  |
| `65 <= DQ_Core < 80` | warning               |
| `DQ_Core < 65`       | fail                  |

Khi Rules Engine hỗ trợ đánh dấu critical rule hoặc critical dimension, điều kiện quality gate có thể được mở rộng:

| Điều kiện mở rộng                                                                     | `quality_gate_status` |
| ------------------------------------------------------------------------------------- | --------------------- |
| `DQ_Core >= 80`, không có critical rule fail, không có critical dimension dưới ngưỡng | pass                  |
| `65 <= DQ_Core < 80` hoặc có critical warning                                         | warning               |
| `DQ_Core < 65` hoặc có critical rule fail                                             | fail                  |

`quality_gate_status` phục vụ vận hành nội bộ, còn `badge` phục vụ hiển thị cho người mua dataset.

### 8.6 Sử dụng Score History trong Phase 2

Trong Phase 2, Score History có thể được dùng để:
- Phát hiện score drift.
- Phát hiện dimension nào giảm điểm bất thường.
- Phát hiện rule nào thường xuyên thất bại.
- Tạo cảnh báo tự động khi điểm giảm dưới ngưỡng.
- So sánh chất lượng giữa các phiên bản dataset.
- Gợi ý root cause ban đầu trên dashboard.



## 9. Nguyên tắc hiển thị trên Dashboard

Dashboard nên hỗ trợ drill-down theo nhiều cấp:

```
Final Dataset Score
        ↓
DQ Core Score / Trust Score
        ↓
Dimension Score
        ↓
Rule Score
        ↓
Failed records / issue examples
```

Các thành phần nên hiển thị trong Phase 1:

| Thành phần          | Mô tả                                                  |
| ------------------- | ------------------------------------------------------ |
| Final Score         | Điểm tổng hợp cuối cùng                                |
| Badge               | Excellent, Reliable, Acceptable, At Risk, Needs Review |
| DQ Core Score       | Điểm chất lượng kỹ thuật                               |
| Trust Score         | Điểm tín nhiệm dataset                                 |
| Dimension breakdown | Điểm theo 6 dimension                                  |
| Failed rules        | Danh sách rule không đạt                               |
| Warning rules       | Danh sách rule gần ngưỡng cảnh báo                     |
| Score trend         | Lịch sử điểm theo lần chạy                             |
| Metadata status     | Mức độ đầy đủ metadata                                 |
| Issue summary       | Tổng hợp lỗi nổi bật                                   |

Dashboard cần phân biệt rõ:
- Số lượng rule lỗi.
- Số lượng bản ghi lỗi.
- Dimension bị giảm điểm.
- Rule critical bị fail.
- Dimension hoặc rule bị `not_measured`.

Điều này giúp người dùng không hiểu nhầm rằng một rule failed luôn tương đương với số lượng bản ghi lỗi lớn.
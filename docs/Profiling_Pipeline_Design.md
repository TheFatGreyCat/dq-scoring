# Tài liệu Thiết kế Pipeline Profiling Dữ liệu

**Dự án:** Chấm điểm Chất lượng Dữ liệu (DQ Scoring)  
**Module:** Sàn giao dịch dữ liệu và Datalake tập trung  
**Phiên bản:** 1.0.1  
**Ngày:** 24/06/2026  
**Giai đoạn:** Phase 1 – Khung đo lường và hệ thống tính điểm cơ bản  
**Tài liệu liên quan:** `DQ_Framework`, `DQ_Scoring_Model`

| Phiên bản | Ngày       | Người thực hiện   | Mô tả thay đổi                                                                                                                               |
| --------- | ---------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.0       | 18/06/2026 | Nguyễn Hoàng Tùng | Khởi tạo tài liệu thiết kế Pipeline Profiling                                                                                                |
| 1.0.1     | 24/06/2026 | Nguyễn Hoàng Tùng | Cập nhật thiết kế theo DQ_Framework và DQ_Scoring_Model; tinh gọn phạm vi Phase 1, output schema và tích hợp với Rules Engine/Scoring Engine |

## 1. Giới thiệu

### 1.1 Mục đích

Tài liệu này mô tả thiết kế kỹ thuật cho **Pipeline Profiling** trong hệ thống DQ Scoring. Pipeline Profiling là thành phần có nhiệm vụ tự động đọc dataset, quét dữ liệu, trích xuất đặc trưng thống kê ở cấp dataset và cấp cột, phát hiện các dấu hiệu bất thường cơ bản và sinh dữ liệu đầu vào chuẩn hóa cho các module phía sau.

Pipeline Profiling đóng vai trò là bước đầu tiên trong chuỗi xử lý chất lượng dữ liệu:

```
- Raw Data / Dataset
- Profiling Pipeline
- Rules Engine
- Scoring Engine
- Dashboard / Data Catalog
```

Trong Phase 1, Pipeline Profiling **không trực tiếp tính** `RuleScore`, `DimensionScore`, `DQ Core Score` hoặc `Final Dataset Score`. Pipeline chỉ tạo ra:

- `Profile Result`
- `Candidate Rule`
- `Anomaly Flag`
- Thống kê phục vụ Metadata Check / Trust Score

Các điểm số chính thức được tính bởi Scoring Engine theo tài liệu `DQ_Scoring_Model`.

### 1.2 Căn cứ thiết kế

Tài liệu này được xây dựng dựa trên hai tài liệu nền:

|Tài liệu|Vai trò|
|---|---|
|`DQ_Framework`|Định nghĩa 6 trụ cột chất lượng dữ liệu: Completeness, Accuracy, Consistency, Timeliness, Uniqueness, Validity|
|`DQ_Scoring_Model`|Định nghĩa cách tính điểm từ Rule Score → Dimension Score → DQ Core Score → Trust Score → Final Dataset Score|

Pipeline Profiling phải bảo đảm kết quả đầu ra có thể hỗ trợ 6 dimension trong `DQ_Framework`, đồng thời tương thích với cách tính điểm trong `DQ_Scoring_Model`.

### 1.3 Vị trí trong kiến trúc tổng thể

```
1. [Raw Data / Dataset]

2. [Profiling Pipeline]
   - Đọc dữ liệu
   - Lấy mẫu nếu cần
   - Trích xuất thống kê dataset/cột
   - Sinh Profile Result
   - Sinh Candidate Rule
   - Sinh Anomaly Flag

3. [Rules Engine]
   - Chạy rule chính thức
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

7. [Dashboard / Data Catalog / API]
```

Lưu ý: Pipeline Profiling không thay thế Rules Engine. Candidate rule do Pipeline Profiling sinh ra chỉ là gợi ý và chưa ảnh hưởng đến DQ Score cho đến khi được phê duyệt hoặc được cấu hình thành rule chính thức.

### 1.4 Phạm vi Phase 1

Trong Phase 1, Pipeline Profiling tập trung vào:

|Nhóm công việc|Phạm vi Phase 1|
|---|---|
|Data loading|Đọc dataset từ file, database hoặc datalake|
|Sampling|Full scan với dataset nhỏ/vừa; sampling với dataset lớn|
|Schema profiling|So sánh schema khai báo và schema thực tế|
|Column profiling|Tính null ratio, distinct count, min/max, pattern, type inference|
|Dataset profiling|Tính row count, duplicate row, freshness lag, volume anomaly|
|Candidate rule generation|Gợi ý rule dựa trên thống kê quan sát được|
|Basic anomaly detection|Phát hiện bất thường cơ bản bằng thống kê|
|Output schema|Chuẩn hóa output cho Rules Engine, Scoring Engine và Dashboard|

## 2. Nguyên tắc thiết kế

### 2.1 GX-first, Spark-on-demand

Chiến lược công nghệ của Pipeline Profiling trong Phase 1 là:

```
Great Expectations-first
Spark-on-demand
```

Điều này có nghĩa là:

- Great Expectations được chọn làm framework chính cho profiling/validation cơ bản.
- Với dataset nhỏ và vừa, pipeline ưu tiên chạy bằng GX với Pandas Execution Engine.
- Spark không bị loại bỏ, nhưng chỉ dùng khi dataset lớn, dữ liệu đã nằm trong môi trường Spark hoặc cần xử lý phân tán.
- Output của pipeline phải giữ nguyên cấu trúc bất kể execution engine là GX/Pandas, GX/Spark hay PySpark.

### 2.2 Tách biệt trách nhiệm giữa các module

|Module|Trách nhiệm|
|---|---|
|Pipeline Profiling|Trích xuất thống kê, sinh candidate rule, phát hiện anomaly cơ bản|
|Rules Engine|Chạy rule chính thức và sinh Rule Evaluation Result|
|Scoring Engine|Tính RuleScore, DimensionScore, DQ Core Score và Final Score|
|Metadata Check|Kiểm tra metadata, schema, owner, sample preview, certification|
|Dashboard|Hiển thị điểm số, thống kê, issue breakdown và lịch sử chất lượng|

Pipeline Profiling chỉ tạo dữ liệu đầu vào. Việc quyết định rule nào được tính điểm thuộc trách nhiệm của Rules Engine và Data Steward.

Lưu ý về Great Expectations: trong Phase 1, GX có thể được dùng để profiling hoặc chạy một số expectation kỹ thuật. Tuy nhiên, mọi kết quả có ảnh hưởng đến DQ Score phải được chuẩn hóa qua Rules Engine thành Rule Evaluation Result. Scoring Engine không tính điểm trực tiếp từ GX raw validation result hoặc Profile Result thô.

### 2.3 Deterministic và Explainable

Phase 1 ưu tiên các chỉ số dễ hiểu, dễ kiểm chứng và có thể giải thích trực tiếp:

- `row_count`
- `null_count`, `null_ratio`
- `blank_count`
- `distinct_count`, `uniqueness_ratio`
- `min`, `max`, `mean`, `std`
- `p25`, `p50`, `p75`, `p99`
- `pattern_frequency`
- `inferred_data_type`
- `miscast_count`
- `duplicate_row_count`
- `freshness_lag`
- `volume_deviation_rate`

Các chỉ số này giúp Data Steward, Data Engineer và người dùng cuối hiểu được tình trạng dữ liệu mà không cần mô hình AI phức tạp.

### 2.4 Candidate rule không tự động ảnh hưởng đến điểm số

Candidate rule do Pipeline Profiling sinh ra chỉ có trạng thái đề xuất. Rule này không được dùng để tính DQ Score cho đến khi được phê duyệt hoặc được thêm vào rule config.

Nguyên tắc này giúp tránh trường hợp rule tự sinh không phù hợp nghiệp vụ nhưng vẫn làm thay đổi điểm chất lượng dữ liệu.

### 2.5 Output chuẩn hóa, không phụ thuộc execution engine

Dù pipeline chạy bằng GX/Pandas, GX/Spark hay PySpark, output cuối cùng phải được chuẩn hóa về cùng một nhóm bảng/schema:

- `profiling_run`
- `dataset_profile`
- `column_profile`
- `candidate_rule`
- `anomaly_flag`

Điều này giúp các module downstream không cần quan tâm pipeline đã chạy bằng engine nào.

## 3. Lựa chọn công nghệ triển khai

### 3.1 Bối cảnh lựa chọn

Dung lượng cụ thể của dataset trên sàn giao dịch dữ liệu hoặc datalake tập trung chưa được xác định rõ trong Phase 1. Vì vậy, việc mặc định sử dụng Spark cho mọi dataset có thể làm tăng tài nguyên, chi phí và độ phức tạp triển khai.

Ngược lại, nếu chỉ dùng Pandas/GX local thì hệ thống có thể gặp giới hạn khi dataset lớn. Vì vậy, thiết kế cần cân bằng giữa triển khai nhanh và khả năng mở rộng.

### 3.2 Great Expectations

|Tiêu chí|Đánh giá|
|---|---|
|Vai trò chính|Framework profiling và validation|
|Phù hợp Phase 1|Cao|
|Tài nguyên sử dụng|Thấp đến trung bình với Pandas|
|Explainability|Cao|
|Tích hợp rule|Tốt, có expectation rõ ràng|
|Khả năng scale|Có thể mở rộng qua Spark Execution Engine|

Lợi thế chính:

- Dễ triển khai trên dataset mẫu.
- Không bắt buộc dùng big data engine.
- Có sẵn nhiều expectation.
- Kết quả dễ đọc và dễ giải thích.
- Phù hợp với định hướng deterministic, explainable trong Phase 1.

### 3.3 Apache Spark

|Tiêu chí|Đánh giá|
|---|---|
|Vai trò chính|Engine xử lý dữ liệu phân tán|
|Phù hợp dataset lớn|Cao|
|Phù hợp dataset nhỏ/vừa|Không tối ưu nếu phải khởi tạo cluster|
|Tài nguyên sử dụng|Trung bình đến cao|
|Khả năng SQL/aggregate|Mạnh|
|Độ phức tạp triển khai|Cao hơn GX/Pandas|
|Vai trò Phase 1|Backend mở rộng, không phải mặc định|

Spark phù hợp khi dataset quá lớn cho Pandas/GX local, dữ liệu đã nằm sẵn trong Spark/Delta Lake hoặc profiling cần chạy nhiều aggregate trên dữ liệu lớn.

### 3.4 Chiến lược lựa chọn execution engine

|Điều kiện dataset|Execution engine đề xuất|
|---|---|
|Dataset nhỏ/vừa, file CSV/Excel/Parquet đơn giản|GX + Pandas|
|Dataset trong SQL database|GX + SQLAlchemy hoặc SQL trực tiếp|
|Dataset lớn, vượt bộ nhớ local|GX + Spark hoặc PySpark|
|Dataset đã nằm trong Spark/Delta Lake|Spark hoặc GX Spark Execution Engine|
|Cần chạy nhiều aggregate lớn|Spark|
|Demo Phase 1 trên dataset mẫu|GX + Pandas|

### 3.5 Ngưỡng chuyển đổi sang Spark

Phase 1 chưa đặt ngưỡng cứng tuyệt đối. Tuy nhiên, có thể dùng các tiêu chí sau:

|Dấu hiệu|Hành động|
|---|---|
|Pipeline bị lỗi do thiếu bộ nhớ|Chuyển sang GX/Spark hoặc PySpark|
|Profiling chạy quá lâu so với SLA vận hành|Dùng Spark hoặc tăng sampling|
|Dataset có hàng chục triệu dòng trở lên|Ưu tiên Spark|
|Dữ liệu đã nằm trong Delta Lake/Spark table|Dùng Spark để tránh di chuyển dữ liệu|
|Dataset nhỏ/vừa, chạy ổn định|Giữ GX/Pandas|

## 4. Đầu vào của Pipeline

### 4.1 Dataset đầu vào

Pipeline có thể nhận dataset từ nhiều nguồn:

|Nguồn dữ liệu|Ví dụ|
|---|---|
|File|CSV, Excel, JSON, Parquet|
|Database|PostgreSQL, MySQL, SQL Server|
|Datalake|Parquet, Delta Lake, object storage|
|Data product|Dataset đã đăng ký trên sàn giao dịch dữ liệu|

Thông tin tối thiểu cần có:

| Trường            | Mô tả                                                                      |
| ----------------- | -------------------------------------------------------------------------- |
| `dataset_id`      | Định danh duy nhất của dataset                                             |
| `dataset_name`    | Tên dataset                                                                |
| `source_type`     | Loại nguồn dữ liệu                                                         |
| `storage_path`    | Đường dẫn hoặc kết nối đến dữ liệu                                         |
| `declared_schema` | Schema được khai báo trong metadata                                        |
| `dataset_type`    | Loại dataset: master_data, transaction, log_event, reference_data, default |

### 4.2 Metadata đầu vào

Pipeline cần metadata để hiểu ngữ cảnh dataset và sinh candidate rule chính xác hơn.

|Metadata|Vai trò|
|---|---|
|`primary_key`|Hỗ trợ uniqueness profiling|
|`composite_key`|Hỗ trợ composite uniqueness|
|`business_key`|Hỗ trợ business key uniqueness|
|`mandatory_fields`|Hỗ trợ completeness profiling|
|`cde_fields`|Xác định các trường quan trọng cần ưu tiên|
|`timestamp_column`|Hỗ trợ freshness/timeliness profiling|
|`sla_config`|Hỗ trợ đánh giá SLA hoặc freshness|
|`expected_range`|Hỗ trợ Accuracy Proxy / plausibility|
|`domain_values`|Hỗ trợ Validity/domain profiling|
|`dataset_owner`|Phục vụ governance|
|`data_steward`|Người duyệt candidate rule|

### 4.3 Cấu hình profiling

|Tham số|Mô tả|Giá trị đề xuất Phase 1|
|---|---|---|
|`execution_mode`|Engine chạy pipeline|`gx_pandas`, `gx_spark`, `pyspark`|
|`sampling_method`|Phương pháp lấy mẫu|`full_scan`, `random`, `stratified`|
|`sample_fraction`|Tỉ lệ lấy mẫu|5–10% nếu dataset lớn|
|`min_sample_size`|Số dòng mẫu tối thiểu|Tùy quy mô dataset|
|`random_seed`|Seed để tái lập kết quả|Cố định theo `dataset_id`|
|`enable_pattern_detection`|Bật phát hiện pattern|`true`|
|`enable_candidate_rule_generation`|Bật sinh candidate rule|`true`|
|`enable_basic_anomaly_detection`|Bật phát hiện anomaly cơ bản|`true`|
|`baseline_window`|Số lần chạy lịch sử dùng làm baseline|7 hoặc 30 lần chạy gần nhất|

## 5. Thiết kế chi tiết Pipeline

### 5.1 Tổng quan luồng xử lý

Pipeline gồm 8 bước chính:

```
Step 1: Data Loading
Step 2: Data Sampling
Step 3: Schema Profiling
Step 4: Column-level Profiling
Step 5: Dataset-level Profiling
Step 6: Candidate Rule Generation
Step 7: Basic Anomaly Detection
Step 8: Generate & Store Profile Result
```

### 5.2 Step 1 – Data Loading

Pipeline đọc dữ liệu từ nguồn được khai báo trong dataset config.

|Điều kiện|Cách xử lý|
|---|---|
|Dataset nhỏ/vừa|Đọc bằng GX + Pandas|
|Dataset lớn|Đọc bằng GX Spark Execution Engine hoặc PySpark|
|Dataset dạng file|Đọc từ `storage_path`|
|Dataset dạng database|Đọc qua connection string/query|
|Dataset trên datalake|Đọc bằng Parquet/Delta/Spark reader|

Kết quả của bước này là một DataFrame hoặc Batch có thể sử dụng cho các bước profiling tiếp theo.

### 5.3 Step 2 – Data Sampling

Sampling được sử dụng khi dataset quá lớn hoặc profiling full scan không cần thiết.

|Trường hợp|Cách xử lý|
|---|---|
|Dataset nhỏ|Full scan|
|Dataset lớn|Random sampling|
|Dataset có phân nhóm quan trọng|Stratified sampling|
|Cần đảm bảo reproducibility|Dùng `random_seed` cố định|

Thông tin sampling cần được lưu trong bảng `profiling_run` để phục vụ truy vết.

Lưu ý về sampling và scoring:

- Nếu profiling chạy trên sample, các chỉ số trong `column_profile` và `dataset_profile` chỉ được xem là thống kê ước lượng.
- Các metric sinh từ sample không được dùng trực tiếp để tính RuleScore chính thức, trừ khi rule được cấu hình rõ là sample-based.
- Rule Evaluation Result chính thức nên được tạo bởi Rules Engine trên toàn bộ `total_records_in_scope` hoặc trên phạm vi kiểm tra đã được khai báo rõ.
- Dashboard cần hiển thị rõ metric được tính từ full scan hay sample để tránh hiểu nhầm.

Nói cách khác:

```
sampled_profile_metric ≠ official_rule_evaluation_result
```

### 5.4 Step 3 – Schema Profiling

Schema Profiling so sánh schema khai báo trong metadata với schema thực tế của dataset.

| Kiểm tra           | Mô tả                                                |
| ------------------ | ---------------------------------------------------- |
| Schema existence   | Dataset có schema khai báo hay không                 |
| Column existence   | Cột khai báo có tồn tại trong dữ liệu thực tế không  |
| Extra column       | Có cột phát sinh ngoài schema khai báo không         |
| Data type mismatch | Kiểu dữ liệu thực tế khác kiểu dữ liệu khai báo      |
| Nullable mismatch  | Cột mandatory có nhiều giá trị null bất thường không |

Kết quả schema profiling hỗ trợ Metadata Check, Validity và Completeness.

### 5.5 Step 4 – Column-level Profiling

Pipeline tính thống kê cho từng cột.

|Nhóm thống kê|Chỉ số|Dimension liên quan|
|---|---|---|
|Completeness|`null_count`, `null_ratio`, `blank_count`|Completeness|
|Uniqueness|`distinct_count`, `uniqueness_ratio`|Uniqueness|
|Numeric distribution|`min`, `max`, `mean`, `std`, `p25`, `p50`, `p75`, `p99`|Accuracy Proxy / Validity|
|Type profiling|`declared_data_type`, `inferred_data_type`, `miscast_count`|Validity|
|Pattern profiling|`pattern_frequency`, `length_distribution`|Validity|
|Value distribution|`top_values`, `value_frequency`|Validity / Consistency|
|Time profiling|`min_timestamp`, `max_timestamp`, `freshness_lag`|Timeliness|

Ví dụ:

|Cột|Thống kê phát hiện|
|---|---|
|`email`|2% null, 95% khớp pattern email|
|`phone_number`|90% có độ dài 10 ký tự|
|`customer_id`|uniqueness ratio = 99.8%|
|`age`|min = 0, max = 119, mean = 34.2|
|`updated_at`|freshness lag = 3 giờ|

### 5.6 Step 5 – Dataset-level Profiling

Ngoài thống kê theo cột, pipeline cần tính thống kê ở cấp dataset.

|Chỉ số|Mô tả|Ứng dụng|
|---|---|---|
|`row_count`|Tổng số dòng|Dashboard, volume monitoring|
|`column_count`|Tổng số cột|Metadata overview|
|`duplicate_row_count`|Số dòng trùng hoàn toàn|Uniqueness|
|`duplicate_row_ratio`|Tỉ lệ dòng trùng|Cảnh báo duplicate|
|`last_updated_timestamp`|Thời điểm cập nhật mới nhất|Timeliness|
|`profiling_timestamp`|Thời điểm pipeline thực hiện profiling|Traceability|
|`freshness_time_basis`|Cơ sở tính freshness: `event_time`, `updated_at` hoặc `ingestion_time`|Timeliness|
|`freshness_lag`|Độ trễ dữ liệu|Dashboard / Timeliness|
|`expected_row_count`|Số dòng kỳ vọng từ baseline hoặc metadata|Volume anomaly|
|`volume_deviation_rate`|Tỉ lệ lệch volume so với baseline|Monitoring-only|
|`profile_duration_seconds`|Thời gian chạy profiling|Monitoring hiệu năng|

Công thức freshness:

```
freshness_lag = profiling_timestamp - selected_freshness_timestamp
```

Trong đó `selected_freshness_timestamp` được xác định theo `freshness_time_basis`.

Công thức volume anomaly:

```
volume_deviation_rate = |row_count_current - expected_row_count| / expected_row_count × 100
```

Lưu ý: `volume_deviation_rate` là tín hiệu monitoring ở cấp dataset, không phải rule consistency chính thức, trừ khi nghiệp vụ định nghĩa rule cụ thể về volume dữ liệu.

### 5.7 Step 6 – Candidate Rule Generation

Dựa trên thống kê quan sát được, Pipeline Profiling sinh candidate rule để Data Steward xem xét.

|Tín hiệu từ profiling|Candidate rule gợi ý|Dimension|
|---|---|---|
|Cột có `null_ratio` rất thấp|Cột nên được kiểm tra not null|Completeness|
|Cột có `uniqueness_ratio` gần 100%|Cột có thể là khóa định danh|Uniqueness|
|Cột số có min/max ổn định|Rule range/plausibility|Accuracy Proxy / Validity|
|Cột có pattern email chiếm đa số|Rule regex email|Validity|
|Cột có tập giá trị nhỏ và ổn định|Rule domain/in-set|Validity|
|Cột timestamp có max gần hiện tại|Rule freshness/timeliness|Timeliness|

Điều kiện sinh candidate rule:

Pipeline chỉ sinh candidate rule khi tín hiệu profiling đủ rõ ràng và vượt ngưỡng tin cậy tối thiểu.

Ví dụ:

- Chỉ gợi ý not-null rule nếu `null_ratio` thấp hơn ngưỡng cấu hình.
- Chỉ gợi ý uniqueness rule nếu `uniqueness_ratio` gần 100%.
- Chỉ gợi ý regex rule nếu một pattern chiếm tỉ lệ đủ lớn, ví dụ từ 90% trở lên.
- Chỉ gợi ý domain rule nếu số lượng giá trị phân biệt nhỏ và ổn định.
- Chỉ gợi ý range rule nếu min/max hoặc percentile cho thấy khoảng giá trị tương đối ổn định.

Candidate rule không nên được sinh chỉ dựa trên tín hiệu yếu hoặc một quan sát không đủ rõ ràng.

Trạng thái candidate rule:

|Trạng thái|Ý nghĩa|
|---|---|
|`pending_review`|Rule mới được đề xuất, chưa được duyệt|
|`approved`|Rule đã được duyệt và có thể đưa vào Rules Engine|
|`rejected`|Rule bị từ chối|
|`deprecated`|Rule không còn phù hợp|

Candidate rule chưa được dùng để tính điểm nếu chưa được phê duyệt.

### 5.8 Step 7 – Basic Anomaly Detection

Trong Phase 1, Pipeline Profiling chỉ phát hiện bất thường cơ bản bằng thống kê, chưa sử dụng mô hình AI/ML nâng cao.

|Loại anomaly|Phương pháp Phase 1|Ví dụ|
|---|---|---|
|Completeness anomaly|So sánh `null_ratio` với baseline hoặc ngưỡng cấu hình|`email` null_ratio tăng từ 2% lên 15%|
|Volume anomaly|So sánh `row_count_current` với `expected_row_count`|Số dòng giảm 40% so với baseline|
|Pattern anomaly|So sánh `pattern_frequency` với baseline hoặc ngưỡng cấu hình|Tỉ lệ phone 10 số giảm mạnh|
|Numeric outlier|IQR hoặc z-score cơ bản|`amount` âm hoặc quá lớn|
|Type anomaly|Tăng `miscast_count`|Cột `amount` xuất hiện nhiều string|

Mức độ nghiêm trọng:

|Severity|Ý nghĩa|
|---|---|
|`low`|Bất thường nhẹ, cần theo dõi|
|`medium`|Có khả năng ảnh hưởng chất lượng dữ liệu|
|`high`|Rủi ro cao, cần kiểm tra ngay|

Lưu ý: Khi chưa có baseline lịch sử, pipeline có thể dùng threshold tĩnh trong cấu hình. Baseline lịch sử sẽ được tích lũy dần từ các lần chạy thành công.

### 5.9 Step 8 – Generate & Store Profile Result

Sau khi hoàn tất profiling, pipeline sinh output chuẩn hóa và lưu vào Profile Store.

Profile Result gồm:

- Thông tin lần chạy profiling.
- Thống kê cấp dataset.
- Thống kê cấp cột.
- Candidate rule.
- Anomaly flag.
- Metadata phục vụ traceability.

Profile Result được lưu theo khóa:

```
(dataset_id, run_id, run_timestamp)
```

Dữ liệu lịch sử được sử dụng cho:

- So sánh baseline cơ bản.
- Hiển thị dashboard.
- Theo dõi xu hướng chất lượng.
- Chuẩn bị cho drift detection và anomaly detection nâng cao trong Phase 2.

## 6. Thiết kế Output Schema

### 6.1 Bảng `profiling_run`

|Trường|Kiểu|Mô tả|
|---|---|---|
|`run_id`|string|Định danh lần chạy profiling|
|`dataset_id`|string|Định danh dataset|
|`dataset_version`|string|Phiên bản dataset, nếu có|
|`run_timestamp`|datetime|Thời điểm chạy profiling|
|`execution_engine`|string|`gx_pandas`, `gx_spark`, `pyspark`|
|`source_path`|string|Đường dẫn file, table hoặc nguồn dữ liệu được đọc|
|`schema_version`|string|Phiên bản schema khai báo trong metadata, nếu có|
|`sampling_method`|string|`full_scan`, `random`, `stratified`|
|`is_sampled`|boolean|Cho biết lần chạy profiling có sử dụng sampling hay không|
|`sample_fraction`|float|Tỉ lệ sample thực tế nếu có sampling|
|`sample_size`|int|Số dòng được profiling|
|`total_rows`|int|Tổng số dòng dataset|
|`status`|string|`success`, `failed`, `partial`|
|`error_message`|string|Thông tin lỗi nếu chạy thất bại|

Ghi chú: Các trường `source_path`, `schema_version`, `is_sampled` và `sample_fraction` giúp truy vết pipeline đã profile nguồn dữ liệu nào và có sử dụng sampling hay không. Các thông tin chi tiết hơn như snapshot ID, partition filter hoặc file hash có thể bổ sung ở giai đoạn production/Phase 2 nếu cần.

### 6.2 Bảng `dataset_profile`

|Trường|Kiểu|Mô tả|
|---|---|---|
|`run_id`|string|Định danh lần chạy|
|`dataset_id`|string|Định danh dataset|
|`row_count`|int|Tổng số dòng|
|`column_count`|int|Tổng số cột|
|`duplicate_row_count`|int|Số dòng trùng hoàn toàn|
|`duplicate_row_ratio`|float|Tỉ lệ dòng trùng|
|`last_updated_timestamp`|datetime|Thời điểm cập nhật mới nhất theo metadata hoặc dữ liệu nguồn|
|`profiling_timestamp`|datetime|Thời điểm pipeline thực hiện profiling|
|`freshness_time_basis`|string|Cơ sở tính freshness: `event_time`, `updated_at` hoặc `ingestion_time`|
|`freshness_lag`|float|Độ trễ dữ liệu|
|`expected_row_count`|int|Số dòng kỳ vọng từ baseline hoặc metadata|
|`volume_deviation_rate`|float|Tỉ lệ lệch volume so với baseline|
|`profile_duration_seconds`|float|Thời gian chạy profiling|

Ghi chú về `freshness_lag`:

`freshness_lag` phải được tính dựa trên timestamp được cấu hình trong metadata, không mặc định dùng một cột bất kỳ.

```
freshness_lag = profiling_timestamp - selected_freshness_timestamp
```

Trong đó `selected_freshness_timestamp` được xác định bởi `freshness_time_basis`.

### 6.3 Bảng `column_profile`

|Trường|Kiểu|Mô tả|
|---|---|---|
|`run_id`|string|Định danh lần chạy|
|`dataset_id`|string|Định danh dataset|
|`column_name`|string|Tên cột|
|`declared_data_type`|string|Kiểu dữ liệu khai báo|
|`inferred_data_type`|string|Kiểu dữ liệu suy luận|
|`null_count`|int|Số giá trị null|
|`null_ratio`|float|Tỉ lệ null|
|`blank_count`|int|Số giá trị blank|
|`distinct_count`|int|Số giá trị phân biệt|
|`uniqueness_ratio`|float|Tỉ lệ duy nhất|
|`min_value`|string|Giá trị nhỏ nhất|
|`max_value`|string|Giá trị lớn nhất|
|`mean_value`|float|Giá trị trung bình|
|`std_value`|float|Độ lệch chuẩn|
|`p25`|float|Phân vị 25|
|`p50`|float|Phân vị 50|
|`p75`|float|Phân vị 75|
|`p99`|float|Phân vị 99|
|`top_values`|object|Danh sách giá trị xuất hiện nhiều|
|`pattern_frequency`|object|Phân phối pattern|
|`length_distribution`|object|Phân phối độ dài chuỗi|
|`miscast_count`|int|Số giá trị sai kiểu|

### 6.4 Bảng `candidate_rule`

|Trường|Kiểu|Mô tả|
|---|---|---|
|`candidate_rule_id`|string|Định danh candidate rule|
|`run_id`|string|Định danh lần chạy|
|`dataset_id`|string|Định danh dataset|
|`column_name`|string|Cột áp dụng, nếu có|
|`dimension`|string|Dimension liên quan|
|`rule_type`|string|`not_null`, `regex`, `range`, `uniqueness`, `domain`, `freshness`|
|`expectation_type`|string|Loại expectation tương ứng trong GX, nếu có|
|`proposed_threshold`|float|Ngưỡng đề xuất|
|`confidence`|float|Độ tin cậy của rule gợi ý|
|`evidence`|object|Các thống kê làm cơ sở đề xuất rule, ví dụ `null_ratio`, `uniqueness_ratio`, `pattern_frequency`, `min_value`, `max_value`|
|`status`|string|`pending_review`, `approved`, `rejected`, `deprecated`|
|`created_at`|datetime|Thời điểm tạo candidate rule|

Ghi chú: `confidence` không phải điểm chất lượng dữ liệu. Đây chỉ là độ tin cậy của đề xuất rule do Pipeline Profiling sinh ra. Candidate rule có `confidence` cao vẫn cần được Data Steward phê duyệt trước khi trở thành rule chính thức trong Rules Engine.

### 6.5 Bảng `anomaly_flag`

|Trường|Kiểu|Mô tả|
|---|---|---|
|`anomaly_id`|string|Định danh anomaly|
|`run_id`|string|Định danh lần chạy|
|`dataset_id`|string|Định danh dataset|
|`column_name`|string|Cột liên quan, nếu có|
|`anomaly_type`|string|`null_spike`, `pattern_shift`, `volume_anomaly`, `numeric_outlier`, `type_anomaly`|
|`severity`|string|`low`, `medium`, `high`|
|`description`|string|Mô tả bất thường|
|`current_value`|string|Giá trị hiện tại|
|`baseline_value`|string|Giá trị baseline hoặc threshold dùng để so sánh|
|`detected_at`|datetime|Thời điểm phát hiện|

## 7. Ánh xạ Profiling Output với 6 Dimension

|Profiling output|Dimension liên quan|Vai trò|
|---|---|---|
|`null_count`, `null_ratio`, `blank_count`|Completeness|Gợi ý và hỗ trợ rule mandatory field|
|`min`, `max`, `mean`, `std`, `p25`, `p75`, `p99`|Accuracy Proxy|Hỗ trợ plausibility/range check|
|`pattern_frequency`, `length_distribution`|Validity|Gợi ý regex/format/length rule|
|`inferred_data_type`, `miscast_count`|Validity|Phát hiện type mismatch|
|`top_values`, `value_frequency`|Validity / Consistency|Gợi ý domain check hoặc rule nghiệp vụ|
|`distinct_count`, `uniqueness_ratio`|Uniqueness|Gợi ý unique key/business key|
|`duplicate_row_count`, `duplicate_row_ratio`|Uniqueness|Phát hiện dòng trùng hoàn toàn|
|`freshness_lag`, `last_updated_timestamp`|Timeliness|Hỗ trợ đánh giá độ mới dữ liệu|
|`volume_deviation_rate`|Consistency / Monitoring|Cảnh báo volume anomaly ở cấp dataset|

Lưu ý: Một profiling signal có thể hỗ trợ nhiều dimension. Khi được chuyển thành rule chính thức, mỗi rule cần được gán một dimension chính để tránh double-count trong Scoring Model.

## 8. Tích hợp với Rules Engine, Scoring Engine và Dashboard

### 8.1 Tích hợp với Rules Engine

Rules Engine sử dụng kết quả profiling để:

- Xác định cột có vấn đề.
- Chạy rule đã cấu hình.
- Tiếp nhận candidate rule đã được phê duyệt.
- Sinh Rule Evaluation Result.

Ví dụ ánh xạ:

|Profile Result|Rules Engine sử dụng|
|---|---|
|`null_ratio`|Chạy rule not null|
|`pattern_frequency`|Chạy rule regex|
|`distinct_count`, `uniqueness_ratio`|Chạy rule uniqueness|
|`min_value`, `max_value`|Chạy rule range|
|`freshness_lag`|Chạy rule timeliness|

Lưu ý: Ví dụ dưới đây là Rule Evaluation Result do Rules Engine tạo ra từ rule chính thức. Đây không phải output trực tiếp của Pipeline Profiling.

```
{
  "rule_id": "DQ-VALI-EMAIL-001",
  "dataset_id": "customer_master",
  "column_name": "email",
  "dimension": "Validity",
  "passed": 950000,
  "failed": 30000,
  "miscast": 0,
  "empty": 20000,
  "not_applicable": 0,
  "total_records_in_scope": 1000000
}
```

### 8.2 Tích hợp với Scoring Engine

Scoring Engine không tính điểm trực tiếp từ Profile Result thô. Scoring Engine sử dụng Rule Evaluation Result do Rules Engine tạo ra.

```
Profile Result
    ↓
Rules Engine
    ↓
Rule Evaluation Result
    ↓
Scoring Engine
    ↓
RuleScore → DimensionScore → DQ Core Score
```

Cách thiết kế này bảo đảm:

- Pipeline Profiling chỉ chịu trách nhiệm profiling.
- Rules Engine chịu trách nhiệm kiểm tra rule.
- Scoring Engine chịu trách nhiệm tính điểm.
- Điểm số có thể truy vết về từng rule cụ thể.

### 8.3 Tích hợp với Metadata Check / Trust Score

Profile Result đóng góp vào Metadata Check thông qua:

|Tín hiệu|Vai trò|
|---|---|
|Schema thực tế|Kiểm tra dataset có mô tả schema hay không|
|Sample preview|Giúp người mua xem nhanh dữ liệu|
|Column statistics|Đánh giá sơ bộ chất lượng dataset|
|Freshness lag|Hiển thị độ mới dữ liệu|
|Candidate rule coverage|Đánh giá mức độ có thể kiểm soát chất lượng|

Trong Phase 1, các tín hiệu này hỗ trợ tính `S_Metadata`, từ đó đóng góp vào Trust Score.

### 8.4 Tích hợp với Dashboard

Dashboard có thể sử dụng:

|Nguồn|Dữ liệu hiển thị|
|---|---|
|`dataset_profile`|Row count, duplicate ratio, freshness lag, volume anomaly|
|`column_profile`|Null ratio, uniqueness ratio, pattern, type inference|
|`candidate_rule`|Danh sách rule đề xuất|
|`anomaly_flag`|Danh sách cảnh báo|
|Scoring Engine|DQ Core Score, Final Score, Dimension Score|
|Score History|Biểu đồ xu hướng điểm số|

Dashboard Phase 1 nên hiển thị:

- Danh sách dataset.
- DQ Core Score và Final Dataset Score.
- Điểm theo 6 dimension.
- Danh sách rule failed.
- Danh sách anomaly flag.
- Thống kê null ratio theo cột.
- Thống kê freshness.
- Lịch sử điểm số theo lần chạy.

## 9. Công nghệ và công cụ triển khai

|Thành phần|Công nghệ đề xuất|
|---|---|
|Ngôn ngữ|Python|
|Framework chính|Great Expectations|
|Execution engine mặc định|GX + Pandas Execution Engine|
|Execution engine mở rộng|GX + Spark Execution Engine / PySpark|
|Xử lý dataset lớn|Apache Spark|
|Lưu trữ Profile Result|Parquet / Delta Lake / Database table|
|Cấu hình pipeline|YAML / JSON|
|Orchestration Phase 1|Chạy thủ công hoặc scheduler hiện có|
|Dashboard|Streamlit, Power BI, Superset hoặc dashboard nội bộ|

### 9.1 Kiến trúc triển khai Phase 1

```
[Dataset Config]
        ↓
[GX Profiling Job]
        ↓
[Profile Result Store]
        ↓
[Rules Engine]
        ↓
[Scoring Engine]
        ↓
[Dashboard]
```

### 9.2 Kiến trúc mở rộng khi dùng Spark

```
[Dataset Config]
        ↓
[GX / Spark Profiling Job]
        ↓
[Spark Cluster]
        ↓
[Profile Result Store: Delta / Parquet]
        ↓
[Rules Engine]
        ↓
[Scoring Engine]
        ↓
[Dashboard / Data Catalog]
```

## 10. Kế hoạch triển khai Phase 1

|#|Công việc|Kết quả đầu ra|
|---|---|---|
|1|Chốt cấu trúc Pipeline Profiling và output schema|Tài liệu thiết kế|
|2|Chuẩn bị dataset mẫu và metadata config|Dataset demo + config|
|3|Cài đặt Data Loading|Module đọc dữ liệu|
|4|Cài đặt Sampling|Module lấy mẫu dữ liệu|
|5|Cài đặt Schema Profiling|Kết quả schema profiling|
|6|Cài đặt Column-level Profiling|Bảng `column_profile`|
|7|Cài đặt Dataset-level Profiling|Bảng `dataset_profile`|
|8|Cài đặt Candidate Rule Generation|Bảng `candidate_rule`|
|9|Cài đặt Basic Anomaly Detection|Bảng `anomaly_flag`|
|10|Lưu Profile Result vào Profile Store|Output chuẩn hóa|
|11|Tích hợp thử với Rules Engine và Dashboard mock|Demo end-to-end Phase 1|
|12|Đánh giá hiệu năng và điều kiện scale Spark|Báo cáo khuyến nghị scale|

## 11. Deliverables

|Hạng mục|Mô tả|
|---|---|
|Tài liệu thiết kế Pipeline Profiling|Tài liệu này|
|Source code Pipeline Profiling|Code Python/GX triển khai các bước profiling|
|Dataset mẫu|Dataset dùng để demo và kiểm thử|
|Metadata/config mẫu|File YAML/JSON mô tả dataset và profiling config|
|Profile Result Schema|Đặc tả bảng `profiling_run`, `dataset_profile`, `column_profile`, `candidate_rule`, `anomaly_flag`|
|Sample Profiling Report|Báo cáo kết quả profiling trên dataset mẫu|
|README hướng dẫn chạy|Cách cài đặt, chạy pipeline và xem kết quả|
|Ghi chú scale Spark|Điều kiện và hướng mở rộng sang GX/Spark hoặc PySpark|

## 12. Rủi ro và giả định

|Rủi ro / Giả định|Ảnh hưởng|Biện pháp giảm thiểu|
|---|---|---|
|Chưa xác định dung lượng dataset thực tế|Khó chọn engine tối ưu ngay từ đầu|Dùng GX/Pandas làm mặc định, giữ Spark làm phương án mở rộng|
|Dataset quá lớn so với bộ nhớ local|Pipeline chậm hoặc lỗi bộ nhớ|Dùng sampling, GX/Spark hoặc PySpark|
|Sampling không đại diện|Thống kê profiling bị lệch|Tăng sample size hoặc dùng stratified sampling|
|Metadata thiếu hoặc sai|Candidate rule kém chính xác|Bổ sung bước kiểm tra metadata đầu vào|
|Candidate rule sinh quá nhiều|Data Steward khó duyệt|Gán confidence, evidence và chỉ hiển thị rule có độ tin cậy cao|
|Chưa có baseline lịch sử|Khó phát hiện anomaly chính xác|Dùng threshold tĩnh trong giai đoạn đầu, tích lũy baseline dần|
|Pattern detection chưa chính xác|Gợi ý rule sai|Candidate rule phải được duyệt trước khi sử dụng chính thức|
|Spark cluster chưa sẵn sàng|Khó xử lý dataset lớn|Chỉ dùng Spark khi thật sự cần, ưu tiên GX/Pandas cho Phase 1|

## 13. Phụ lục

### 13.1 Ví dụ cấu hình dataset

```
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
  expected_frequency: daily
  max_freshness_lag_hours: 24

profiling_config:
  execution_mode: gx_pandas
  sampling_method: full_scan
  enable_pattern_detection: true
  enable_candidate_rule_generation: true
  enable_basic_anomaly_detection: true
```

### 13.2 Ví dụ Profile Result rút gọn

```
{
  "run_id": "RUN_20260624_001",
  "dataset_id": "customer_master",
  "run_timestamp": "2026-06-24T02:00:00Z",
  "execution_engine": "gx_pandas",
  "dataset_profile": {
    "row_count": 1000000,
    "column_count": 8,
    "duplicate_row_count": 120,
    "freshness_lag": 3.5,
    "volume_deviation_rate": 2.3
  },
  "column_profile": [
    {
      "column_name": "email",
      "null_ratio": 0.02,
      "distinct_count": 998000,
      "uniqueness_ratio": 0.998,
      "pattern_frequency": {
        "valid_email_format": 0.95,
        "invalid_format": 0.05
      }
    }
  ],
  "candidate_rules": [
    {
      "candidate_rule_id": "CAND-VALI-EMAIL-001",
      "rule_type": "regex",
      "dimension": "Validity",
      "expectation_type": "expect_column_values_to_match_regex",
      "column_name": "email",
      "proposed_threshold": 0.95,
      "confidence": 0.90,
      "evidence": {
        "valid_email_format_ratio": 0.95,
        "invalid_format_ratio": 0.05
      },
      "status": "pending_review"
    }
  ],
  "anomaly_flags": [
    {
      "anomaly_type": "pattern_shift",
      "severity": "medium",
      "description": "Tỉ lệ invalid email tăng từ 2% lên 5% so với baseline"
    }
  ]
}
```

### 13.3 Ví dụ candidate rule

```
{
  "candidate_rule_id": "CAND-VALI-EMAIL-001",
  "dataset_id": "customer_master",
  "column_name": "email",
  "dimension": "Validity",
  "rule_type": "regex",
  "expectation_type": "expect_column_values_to_match_regex",
  "proposed_threshold": 0.95,
  "confidence": 0.90,
  "evidence": {
    "valid_email_format_ratio": 0.95,
    "invalid_format_ratio": 0.05
  },
  "status": "pending_review"
}
```

### 13.4 Ví dụ anomaly flag

```
{
  "anomaly_id": "ANOM-EMAIL-001",
  "dataset_id": "customer_master",
  "column_name": "email",
  "anomaly_type": "pattern_shift",
  "severity": "medium",
  "description": "Tỉ lệ email sai định dạng tăng từ 2% lên 5% so với baseline",
  "current_value": "5%",
  "baseline_value": "2%",
  "detected_at": "2026-06-24T02:00:00Z"
}
```

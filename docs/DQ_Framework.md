# Tài liệu Khung Chất lượng Dữ liệu

**Dự án:** Chấm điểm Chất lượng Dữ liệu (DQ Scoring)  
**Module:** Sàn giao dịch dữ liệu và Datalake tập trung  
**Phiên bản:** 1.0.1  
**Ngày:** 16/06/2026  
**Giai đoạn:** Phase 1 – Khung đo lường và hệ thống tính điểm cơ bản  

| Phiên bản | Ngày       | Người thực hiện   | Mô tả thay đổi                                         |
| --------- | ---------- | ----------------- | ------------------------------------------------------ |
| 1.0       | 11/06/2026 | Nguyễn Hoàng Tùng | Khởi tạo tài liệu                                      |
| 1.0.1     | 16/06/2026 | Nguyễn Hoàng Tùng | Cập nhật phạm vi Phase 1 và hoàn thiện mô tả 6 trụ cột |

## 1. Giới thiệu

### 1.1 Mục đích

Tài liệu này định nghĩa Khung Chất lượng Dữ liệu (Data Quality Framework) cho Sàn giao dịch dữ liệu và Datalake tập trung. Khung này được xây dựng dựa trên 6 trụ cột chất lượng dữ liệu phổ biến trong thực tiễn:
- Accuracy – Tính chính xác
- Completeness – Tính đầy đủ
- Consistency – Tính nhất quán
- Timeliness – Tính thời sự
- Uniqueness – Tính duy nhất
- Validity – Tính hợp lệ

Tài liệu này đóng vai trò là nền tảng để:
- Chuẩn hóa cách hiểu về chất lượng dữ liệu giữa các bên liên quan.
- Xác định các dimension cần đo lường trong hệ thống DQ Scoring.
- Làm cơ sở để thiết kế rule kiểm tra chất lượng dữ liệu.
- Làm đầu vào cho mô hình tính điểm trong tài liệu `DQ_Scoring_Model`.
- Hỗ trợ xây dựng Pipeline Profiling, Rules Engine và Dashboard DQ Score trong Phase 1.

Trong phạm vi tài liệu này, trọng tâm là trả lời câu hỏi: “Cần đo chất lượng dữ liệu theo những khía cạnh nào và phạm vi đo lường ra sao?” 

Công thức tính điểm chi tiết, trọng số và cách tổng hợp điểm được mô tả trong tài liệu `DQ_Scoring_Model`.

### 1.2 Phạm vi áp dụng

Tài liệu này áp dụng cho các dataset được quản lý trong datalake tập trung và/hoặc sàn giao dịch dữ liệu.

Phạm vi đánh giá bao gồm:

| Cấp độ             | Mô tả                                                             |
| ------------------ | ----------------------------------------------------------------- |
| Rule level         | Từng điều kiện kiểm tra chất lượng dữ liệu cụ thể                 |
| Column level       | Các cột hoặc thuộc tính quan trọng trong dataset, đặc biệt là CDE |
| Row level          | Logic dữ liệu trong cùng một bản ghi                              |
| Dataset level      | Bảng, view, file hoặc data product độc lập                        |
| Data product level | Nhóm bảng/dataset có liên quan trực tiếp với nhau                 |
| Cross-system level | So sánh dữ liệu giữa các hệ thống độc lập; chủ yếu thuộc Phase 2  |

**Phạm vi Phase 1:**  
Phase 1 tập trung vào các phương pháp đo lường deterministic, explainable và có thể triển khai bằng rule/config rõ ràng. Hệ thống chưa phụ thuộc mạnh vào AI hoặc mô hình học máy.

Trong Phase 1, framework ưu tiên:
- Kiểm tra null/blank trên mandatory fields và CDE.
- Kiểm tra type, format, length, range và domain value.
- Kiểm tra logic nghiệp vụ đơn giản trong cùng dataset/data product.
- Kiểm tra uniqueness của primary key, composite key hoặc business key.
- Tính freshness, staleness và SLA compliance nếu có đủ metadata.
- Sử dụng Accuracy Proxy thông qua plausibility check thay vì đo Accuracy trực tiếp với ground truth.

Các kiểm tra nâng cao như cross-system validation, fuzzy matching, AI-assisted anomaly detection và drift monitoring tự động được đưa sang Phase 2.

### 1.3 Thuật ngữ và ký hiệu

| Thuật ngữ         | Định nghĩa                                                                                                                  |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Data Quality (DQ) | Mức độ dữ liệu phù hợp với mục đích sử dụng đã định                                                                         |
| Dimension         | Trụ cột hoặc khía cạnh dùng để đo lường chất lượng dữ liệu                                                                  |
| Rule / Check      | Điều kiện cụ thể dùng để kiểm tra một vấn đề chất lượng dữ liệu                                                             |
| CDE               | Critical Data Element – trường dữ liệu quan trọng với nghiệp vụ                                                             |
| Mandatory field   | Trường bắt buộc phải có giá trị trong một use case cụ thể                                                                   |
| Optional field    | Trường có thể để trống mà không ảnh hưởng đến điểm chất lượng, trừ khi được cấu hình là bắt buộc                            |
| Pass rate         | Tỉ lệ bản ghi thỏa mãn một rule kiểm tra                                                                                    |
| DQ Score          | Điểm chất lượng dữ liệu được chuẩn hóa trên thang 0–100                                                                     |
| Rule Score        | Điểm của một rule kiểm tra cụ thể                                                                                           |
| Dimension Score   | Điểm tổng hợp của một trụ cột chất lượng dữ liệu                                                                            |
| DQ Core Score     | Điểm chất lượng kỹ thuật tổng hợp từ các Dimension Score                                                                    |
| Trust Score       | Điểm tín nhiệm của dataset trên sàn giao dịch, dựa trên metadata, certification, usage và feedback                          |
| Final Score       | Điểm hiển thị cuối cùng, được kết hợp có trọng số từ DQ Core Score và Trust Score                                           |
| SLA               | Service Level Agreement – cam kết về tần suất hoặc thời điểm cập nhật dữ liệu                                               |
| Freshness Lag     | Độ trễ giữa thời điểm hiện tại và thời điểm dữ liệu được cập nhật gần nhất                                                  |
| Baseline          | Giá trị lịch sử hoặc ngưỡng tham chiếu dùng để so sánh chất lượng dữ liệu theo thời gian                                    |
| Accuracy Proxy    | Chỉ số đại diện cho Accuracy trong Phase 1, thường dựa trên plausibility check thay vì đối chiếu trực tiếp với ground truth |

## 2. Định nghĩa 6 Trụ cột Chất lượng Dữ liệu

### 2.1 Completeness – Tính đầy đủ

**Định nghĩa**  
Completeness đo lường mức độ dữ liệu được điền đầy đủ tại các trường cần thiết cho mục đích sử dụng của dataset. Một bản ghi được xem là không đầy đủ nếu thiếu giá trị ở các trường được xác định là bắt buộc, ví dụ trường khóa định danh, trường ngày giao dịch, trường thông tin liên hệ hoặc các trường CDE (Critical Data Element) có vai trò quan trọng với nghiệp vụ.

Completeness không yêu cầu mọi cột trong dataset đều phải có giá trị. Các trường tùy chọn có thể để trống mà không ảnh hưởng đến điểm Completeness, trừ khi trường đó được khai báo là bắt buộc cho một use case cụ thể.

**Ý nghĩa trong bối cảnh dự án**
- Dataset có Completeness thấp làm giảm khả năng sử dụng dữ liệu trong báo cáo, phân tích, tính toán KPI và các pipeline downstream.
- Dữ liệu thiếu ở các trường quan trọng có thể khiến bản ghi không thể truy vết, không thể liên kết với bảng khác hoặc không thể sử dụng cho nghiệp vụ.
- Trên sàn giao dịch dữ liệu, người mua cần biết mức độ đầy đủ của dataset để đánh giá dataset có đáp ứng được nhu cầu sử dụng hay không.
- Completeness là một trong các chỉ số nền tảng vì dữ liệu thiếu thường ảnh hưởng trực tiếp đến các dimension khác như Validity, Consistency và Accuracy.

**Ví dụ minh họa**

| Vấn đề           | Mô tả                                                                                                     |
| ---------------- | --------------------------------------------------------------------------------------------------------- |
| Bảng khách hàng  | Nhiều bản ghi thiếu `customer_id`, `email` hoặc `phone_number`, khiến khó định danh và liên hệ khách hàng |
| Bảng giao dịch   | Một số bản ghi thiếu `order_id` hoặc `transaction_date`, khiến không thể truy vết giao dịch               |
| Bảng sản phẩm    | Thiếu `product_code` hoặc `category`, gây khó khăn khi phân loại và tổng hợp báo cáo                      |
| Bảng log sự kiện | Thiếu `event_time` hoặc `user_id`, khiến không thể phân tích hành vi người dùng theo thời gian            |

**Loại kiểm tra phổ biến**

| Loại kiểm tra                      | Mô tả                                                                  |
| ---------------------------------- | ---------------------------------------------------------------------- |
| Mandatory field check              | Kiểm tra các trường bắt buộc không được null hoặc blank                |
| CDE completeness check             | Kiểm tra mức độ đầy đủ của các trường dữ liệu quan trọng với nghiệp vụ |
| Conditional completeness check     | Kiểm tra trường bắt buộc trong một điều kiện cụ thể                    |
| Dataset-level completeness summary | Tổng hợp tỉ lệ đầy đủ của các trường mandatory/CDE trong dataset       |

Ví dụ về conditional completeness:

```
Nếu order_status = "DELIVERED" thì delivery_date không được null
```

```
Nếu customer_type = "BUSINESS" thì tax_code không được null
```

Lưu ý: Một số rule có thể nằm ở ranh giới giữa nhiều dimension, ví dụ conditional completeness và consistency. Khi triển khai scoring, mỗi rule cần được gán một dimension chính để tránh tính điểm trùng lặp.

**Metric chính trong Phase 1**
Metric chính của Completeness trong Phase 1 là `completeness_rate`.

```
completeness_rate = non_null_records_in_scope / total_records_in_scope × 100
```

Trong đó:

| Thành phần                  | Ý nghĩa                                                                     |
| --------------------------- | --------------------------------------------------------------------------- |
| `non_null_records_in_scope` | Số bản ghi có giá trị không null/blank tại trường được kiểm tra             |
| `total_records_in_scope`    | Tổng số bản ghi nằm trong phạm vi kiểm tra                                  |
| `records_in_scope`          | Có thể là toàn bộ dataset hoặc một tập bản ghi thỏa mãn điều kiện nghiệp vụ |

Áp dụng cho:
- Các trường được khai báo là mandatory.
- Các trường CDE có ảnh hưởng trực tiếp đến nghiệp vụ.
- Các trường bắt buộc theo điều kiện cụ thể của use case.

Ví dụ:

| Rule                                                            | Công thức                                                                                        |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `email` không được null                                         | `email_completeness_rate = records_with_email / total_records × 100`                             |
| `transaction_date` không được null                              | `transaction_date_completeness_rate = records_with_transaction_date / total_records × 100`       |
| Nếu `customer_type = "BUSINESS"` thì `tax_code` không được null | `tax_code_completeness_rate = business_customers_with_tax_code / total_business_customers × 100` |

**Ghi chú Phase 1 / Phase 2**
- Phase 1 chỉ tính Completeness cho các trường mandatory hoặc CDE được khai báo trong metadata/rule config.
- Optional fields không được tính vào Completeness Score, trừ khi được cấu hình là bắt buộc cho một use case cụ thể.
- Conditional completeness có thể được triển khai trong Phase 1 nếu rule nghiệp vụ đơn giản và có thể cấu hình rõ ràng.
- Weighted completeness, trong đó các CDE quan trọng hơn có trọng số cao hơn, được đưa sang Phase 2 hoặc giai đoạn mở rộng.

### 2.2 Accuracy – Tính chính xác

**Định nghĩa**  
Accuracy đo lường mức độ dữ liệu phản ánh đúng thực tế, đúng đối tượng và đúng sự kiện ngoài đời thực. Một giá trị được xem là accurate khi nó khớp với nguồn tham chiếu đáng tin cậy, ví dụ hệ thống nghiệp vụ gốc, hồ sơ KYC, CRM, core system hoặc nguồn dữ liệu chuẩn bên ngoài.

**Ý nghĩa trong bối cảnh dự án**
- Accuracy là dimension quan trọng nhưng khó đo nhất vì thường cần nguồn đối chiếu đáng tin cậy, còn gọi là ground truth.
- Với sàn giao dịch dữ liệu, Accuracy giúp người mua đánh giá dataset có phản ánh đúng đối tượng/sự kiện thực tế hay không.
- Trong Phase 1, hệ thống chưa thực hiện đối chiếu đầy đủ với ground truth. Do đó, Accuracy chỉ được đo ở mức proxy, thông qua các kiểm tra hợp lý thống kê hoặc khoảng giá trị kỳ vọng.
- Accuracy trực tiếp thông qua cross-system reference check sẽ được mở rộng ở Phase 2.

**Ví dụ minh họa**

| Vấn đề                   | Mô tả                                                                                                                                                           |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hệ thống KYC             | Số CMND/CCCD trong dataset không khớp với thông tin đã xác minh trong hệ thống KYC                                                                              |
| CRM                      | Địa chỉ khách hàng trong dataset khác với địa chỉ đã được xác nhận trong CRM                                                                                    |
| Dữ liệu giao dịch        | Số tiền giao dịch trong dataset khác với bản ghi giao dịch gốc trong core system                                                                                |
| Kiểm tra hợp lý thống kê | Tuổi khách hàng = 250 hoặc số tiền giao dịch âm là các giá trị không hợp lý, nhưng việc loại bỏ các giá trị này chưa đủ để kết luận dữ liệu hoàn toàn chính xác |

**Loại kiểm tra phổ biến**
- **Direct accuracy check:** So sánh dữ liệu với nguồn tham chiếu đáng tin cậy như KYC, CRM, core banking, hệ thống giao dịch gốc hoặc registry bên ngoài.
- **Cross-system reference check:** So sánh cùng một thông tin giữa các hệ thống khác nhau.
- **Statistical plausibility check:** Kiểm tra giá trị có nằm trong khoảng hợp lý hay không, ví dụ tuổi không âm, tuổi không vượt quá 120, số tiền giao dịch không âm.
- **Business plausibility check:** Kiểm tra giá trị có phù hợp với ngưỡng nghiệp vụ cơ bản hay không, ví dụ `transaction_amount` không âm, `discount_rate` nằm trong khoảng 0–100%, hoặc `age` nằm trong khoảng 0–120.

**Metric chính (Phase 1)**
Do Accuracy theo nghĩa đầy đủ cần nguồn ground truth để đối chiếu, Phase 1 chưa đo trực tiếp Accuracy. Thay vào đó, hệ thống sử dụng metric đại diện là **plausibility_rate** để đo mức độ hợp lý của dữ liệu.
```
plausibility_rate = records_within_expected_bounds / total_records_in_scope × 100
```

Trong đó:

| Thành phần                       | Ý nghĩa                                                                            |
| -------------------------------- | ---------------------------------------------------------------------------------- |
| `records_within_expected_bounds` | Số bản ghi có giá trị nằm trong khoảng hợp lý hoặc thỏa mãn điều kiện plausibility |
| `total_records_in_scope`         | Tổng số bản ghi nằm trong phạm vi kiểm tra                                         |
| `expected_bounds`                | Khoảng giá trị hợp lý được khai báo hoặc suy ra từ baseline                        |

Giới hạn hợp lý có thể được xác định bằng:

| Loại bound         | Mô tả                                                                                   |
| ------------------ | --------------------------------------------------------------------------------------- |
| Range tĩnh         | Khoảng `[min_value, max_value]` do Data Steward khai báo                                |
| Statistical bounds | Khoảng thống kê như `mean ± 3×std` hoặc IQR, tính từ baseline lịch sử khi có đủ dữ liệu |
| Business bounds    | Khoảng hoặc điều kiện hợp lý theo nghiệp vụ                                             |

Ví dụ:

| Cột                  | Expected bounds      | Ý nghĩa                                                         |
| -------------------- | -------------------- | --------------------------------------------------------------- |
| `AGE`                | `[0, 120]`           | Tuổi khách hàng phải nằm trong khoảng hợp lý                    |
| `TRANSACTION_AMOUNT` | `[0, 1,000,000,000]` | Số tiền giao dịch không được âm và không vượt ngưỡng bất thường |
| `DISCOUNT_RATE`      | `[0, 100]`           | Tỉ lệ giảm giá phải nằm trong khoảng 0–100%                     |

**Lưu ý quan trọng**  
`plausibility_rate` không phải là Accuracy đầy đủ. Metric này chỉ cho biết dữ liệu có hợp lý về mặt thống kê hoặc nghiệp vụ cơ bản hay không. Một giá trị nằm trong khoảng hợp lý vẫn có thể sai so với thực tế nếu không được đối chiếu với nguồn ground truth.

Ví dụ: `AGE = 35` là giá trị hợp lý, nhưng chưa chắc chính xác nếu tuổi thật của khách hàng là 42. Vì vậy, trong Phase 1, điểm Accuracy nên được hiểu là Accuracy Proxy Score, không phải kết luận tuyệt đối về tính chính xác của dữ liệu.

**Ghi chú Phase 1 / Phase 2**
- Phase 1: đo Accuracy ở mức proxy bằng `plausibility_rate`, range check và statistical bounds.
- Phase 2: mở rộng sang direct accuracy check bằng cách đối chiếu với KYC, CRM, core system hoặc nguồn tham chiếu bên ngoài.
- Nếu dataset chưa có đủ rule hoặc metadata để đo Accuracy Proxy, dimension Accuracy có thể được loại khỏi công thức DQ Core Score và trọng số được phân bổ lại cho các dimension còn lại theo DQ_Scoring_Model.
  
### 2.3 Consistency – Tính nhất quán

**Định nghĩa**  
Consistency đo lường mức độ dữ liệu thống nhất và không mâu thuẫn trong cùng một dataset, giữa các cột trong cùng một bản ghi, hoặc giữa các bảng có quan hệ trực tiếp trong cùng một data product.

Một dataset được xem là có tính nhất quán khi các giá trị liên quan với nhau không vi phạm logic nghiệp vụ đã định nghĩa. Lưu ý: dữ liệu có thể nhất quán nhưng vẫn không chính xác. Ví dụ, hai bảng cùng ghi khách hàng có trạng thái `ACTIVE`, nhưng trạng thái này vẫn có thể sai nếu khách hàng thực tế đã ngừng hoạt động.

**Ý nghĩa trong bối cảnh dự án**
- Consistency giúp phát hiện các mâu thuẫn logic trong dữ liệu, ví dụ ngày kết thúc nhỏ hơn ngày bắt đầu, trạng thái đơn hàng không phù hợp với ngày giao hàng, hoặc khóa ngoại không tồn tại trong bảng tham chiếu.
- Trong sàn giao dịch dữ liệu/datalake tập trung, dữ liệu không nhất quán làm giảm độ tin cậy của dataset, gây sai lệch báo cáo và ảnh hưởng đến các pipeline downstream.
- Phase 1 tập trung vào consistency trong phạm vi có thể kiểm soát được: cùng một bảng, cùng một dataset hoặc một nhóm bảng thuộc cùng data product. So sánh giữa các hệ thống độc lập như CRM, KYC, core system được đưa sang Phase 2.

**Ví dụ minh họa**

| Vấn đề                      | Mô tả                                                                                          |
| --------------------------- | ---------------------------------------------------------------------------------------------- |
| Mâu thuẫn ngày tháng        | `end_date` nhỏ hơn `start_date` trong cùng một bản ghi                                         |
| Mâu thuẫn trạng thái        | `order_status = "DELIVERED"` nhưng `delivery_date` bị null                                     |
| Mâu thuẫn giá trị nghiệp vụ | `discount_amount` lớn hơn `order_amount`                                                       |
| Lỗi khóa tham chiếu         | `customer_id` trong bảng `orders` không tồn tại trong bảng `customers` thuộc cùng data product |
| Biến động số lượng bản ghi  | Số dòng của dataset giảm mạnh so với lần chạy trước mà không có lý do hợp lệ                   |

**Loại kiểm tra phổ biến**

| Loại kiểm tra                | Mô tả                                                                              | Phạm vi |
| ---------------------------- | ---------------------------------------------------------------------------------- | ------- |
| Cross-field logic check      | Kiểm tra logic giữa nhiều cột trong cùng một bản ghi                               | Phase 1 |
| Business rule consistency    | Kiểm tra dữ liệu có tuân thủ quy tắc nghiệp vụ nội bộ của dataset không            | Phase 1 |
| Referential integrity check  | Kiểm tra khóa ngoại có tồn tại trong bảng tham chiếu thuộc cùng data product không | Phase 1 |
| Dataset volume anomaly check | Phát hiện biến động bất thường về số lượng bản ghi so với baseline kỳ vọng         | Phase 1 |
| Cross-system matching        | So sánh cùng một thực thể giữa các hệ thống độc lập như CRM, KYC, core system      | Phase 2 |

**Metric chính (Phase 1)**
Phase 1 sử dụng `consistency_rate` để đo tỉ lệ bản ghi vượt qua các kiểm tra consistency đã được cấu hình.
```
consistency_rate = records_passing_consistency_checks / total_records_in_scope × 100
```

Trong đó:

| Thành phần                           | Ý nghĩa                                                                       |
| ------------------------------------ | ----------------------------------------------------------------------------- |
| `records_passing_consistency_checks` | Số bản ghi thỏa mãn các rule consistency                                      |
| `total_records_in_scope`             | Tổng số bản ghi nằm trong phạm vi kiểm tra                                    |
| `consistency_checks`                 | Tập rule kiểm tra logic nội bộ, cross-field hoặc referential integrity cơ bản |

Loại kiểm tra được triển khai trong Phase 1:
  (a) Cross-field logic check: 
  Kiểm tra mối quan hệ logic giữa các cột trong cùng một bản ghi.
  
  Ví dụ: 
  - end_date >= start_date
  - order_status = "DELIVERED" thì delivery_date không được null
  - discount_amount <= order_amount
	 
  (b) Business rule consistency: 
  Kiểm tra dữ liệu có tuân thủ các quy tắc nghiệp vụ cơ bản hay không.
  
  Ví dụ:
  - Nếu account_status = "CLOSED" thì closed_date không được null
  - Nếu payment_status = "PAID" thì paid_amount phải lớn hơn 0
	  
  (c) Referential integrity check: 
  Kiểm tra khóa tham chiếu giữa các bảng có quan hệ trực tiếp và cùng thuộc phạm vi quản lý của một data product.
  
  Ví dụ:
- `customer_id` trong bảng `orders` phải tồn tại trong bảng `customers`
- `product_id` trong bảng `order_items` phải tồn tại trong bảng `products`

Lưu ý: Kiểm tra referential integrity chỉ thuộc Phase 1 nếu bảng tham chiếu có sẵn trong cùng dataset group hoặc cùng data product. Nếu phải đối chiếu với hệ thống nguồn độc lập, kiểm tra này được xem là cross-system matching và được chuyển sang Phase 2.

**Metric bổ sung ở cấp dataset**

Ngoài `consistency_rate`, hệ thống có thể theo dõi **Dataset Volume Anomaly Indicator** như một tín hiệu cảnh báo ở cấp dataset. Chỉ số này không được tính trực tiếp vào `consistency_rate`, mà dùng để phát hiện bất thường về số lượng bản ghi giữa các lần chạy profiling hoặc ingestion.

Thay vì chỉ so sánh với lần chạy liền trước, hệ thống nên so sánh `row_count_current` với một baseline kỳ vọng.

```
volume_deviation_rate = |row_count_current - expected_row_count| / expected_row_count × 100
```

Trong đó:

|Thành phần|Ý nghĩa|
|---|---|
|`row_count_current`|Số bản ghi của dataset tại lần chạy hiện tại|
|`expected_row_count`|Số bản ghi kỳ vọng, được xác định từ baseline lịch sử hoặc metadata|
|`volume_deviation_rate`|Tỉ lệ lệch của số bản ghi hiện tại so với giá trị kỳ vọng|

`expected_row_count` có thể được xác định bằng một trong các cách sau:

| Cách xác định baseline     | Mô tả                                                         | Phù hợp                                               |
| -------------------------- | ------------------------------------------------------------- | ----------------------------------------------------- |
| Metadata-based baseline    | Giá trị kỳ vọng được khai báo trong metadata hoặc SLA dữ liệu | Dataset có volume ổn định hoặc đã biết trước quy mô   |
| Historical median baseline | Trung vị `row_count` của N lần chạy thành công gần nhất       | Phase 1, dễ triển khai và ít bị ảnh hưởng bởi outlier |
| Historical mean baseline   | Trung bình `row_count` của N lần chạy gần nhất                | Dataset có volume ổn định                             |
| Seasonal baseline          | Baseline theo chu kỳ ngày/tuần/tháng                          | Phase 2, phù hợp dataset có seasonality               |

Ví dụ:

| Tình huống                          | Diễn giải                                                      |
| ----------------------------------- | -------------------------------------------------------------- |
| `volume_deviation_rate = 3%`        | Số lượng bản ghi gần với baseline, có thể xem là bình thường   |
| `volume_deviation_rate = 40%`       | Dataset có biến động lớn, cần cảnh báo kiểm tra pipeline nguồn |
| `volume_deviation_rate > threshold` | Sinh `volume_anomaly_flag` để hiển thị trên dashboard          |

Trong Phase 1, có thể cấu hình threshold đơn giản:

```
volume_anomaly_flag = true nếu volume_deviation_rate > configured_threshold
```

Ví dụ:

```
configured_threshold = 30%
```

Lưu ý:
- Nếu chưa có baseline lịch sử, lần chạy đầu tiên được ghi nhận làm baseline ban đầu.
- Nếu `expected_row_count = 0` hoặc chưa xác định được baseline, hệ thống không tính `volume_deviation_rate` và chỉ hiển thị `row_count_current`.
- Dataset volume anomaly là tín hiệu cảnh báo vận hành/profiling, không phải rule consistency chính thức, trừ khi nghiệp vụ định nghĩa rõ rule về volume dữ liệu.

**Ghi chú Phase 1 / Phase 2**
- Phase 1: kiểm tra cross-field logic, business rule consistency, referential integrity cơ bản trong cùng data product; đồng thời theo dõi Dataset Volume Anomaly Indicator như một tín hiệu cảnh báo ở cấp dataset.
- Phase 2: mở rộng sang cross-system matching, lineage-aware consistency và so sánh cùng một thực thể giữa nhiều hệ thống nguồn.

### 2.4 Timeliness – Tính thời sự

**Định nghĩa**  
Timeliness đo lường mức độ dữ liệu được cập nhật đúng thời điểm, sẵn sàng khi cần và đáp ứng yêu cầu về độ trễ đã cam kết. Một dataset được xem là có tính thời sự tốt khi dữ liệu không bị lỗi thời so với nhu cầu sử dụng và được cập nhật theo đúng tần suất hoặc SLA đã khai báo.

Dữ liệu có thể đầy đủ, hợp lệ và chính xác tại thời điểm ghi nhận, nhưng vẫn mất giá trị sử dụng nếu không còn đủ mới. Ví dụ, dữ liệu tồn kho của ngày hôm qua có thể không phù hợp cho quyết định bán hàng theo thời gian thực.

**Ý nghĩa trong bối cảnh dự án**
- Timeliness giúp người dùng biết dataset có đủ mới để phục vụ báo cáo, phân tích hoặc vận hành nghiệp vụ hay không.
- Với dữ liệu giao dịch tài chính, độ trễ vài giờ có thể chấp nhận được tùy use case; với dữ liệu realtime như cảnh báo gian lận, trạng thái tồn kho hoặc log hệ thống, độ trễ vài phút đã có thể ảnh hưởng lớn.
- Trên sàn giao dịch dữ liệu, người mua cần biết rõ dataset được cập nhật gần nhất khi nào, tần suất cập nhật ra sao và có đáp ứng SLA đã cam kết hay không.
- Timeliness phụ thuộc không chỉ vào dữ liệu trong bảng, mà còn phụ thuộc vào metadata như `timestamp_column`, `expected_update_frequency`, `SLA` và lịch sử các lần cập nhật dataset.

**Ví dụ minh họa**

|Vấn đề|Mô tả|
|---|---|
|Vi phạm SLA cập nhật|Dataset `Daily_Transactions` cam kết cập nhật trước 09:00 sáng hằng ngày, nhưng 3 ngày gần nhất đều cập nhật sau 11:00|
|Dữ liệu đứng yên|Dataset log hệ thống không có bản ghi mới trong 24 giờ, trong khi hệ thống vẫn đang hoạt động bình thường|
|Dữ liệu lỗi thời theo bản ghi|Một số bản ghi tồn kho có `last_updated_at` cách thời điểm hiện tại hơn 48 giờ|
|Không có thông tin cập nhật|Dataset không khai báo cột thời gian cập nhật hoặc không có metadata về tần suất cập nhật|

**Loại kiểm tra phổ biến**

| Loại kiểm tra        | Mô tả                                                                    |
| -------------------- | ------------------------------------------------------------------------ |
| Last update check    | Kiểm tra thời điểm cập nhật gần nhất của dataset                         |
| Freshness check      | Tính độ trễ giữa thời điểm hiện tại và thời điểm cập nhật mới nhất       |
| Data arrival check   | Kiểm tra dataset có bản ghi mới trong khoảng thời gian kỳ vọng hay không |
| SLA compliance check | Kiểm tra các lần cập nhật có đáp ứng SLA đã khai báo hay không           |
| Staleness check      | Kiểm tra tỉ lệ bản ghi đã quá cũ so với ngưỡng cho phép                  |

**Metric chính trong Phase 1**
Trong Phase 1, Timeliness được đo ở hai mức:
1. **Metric hiển thị tức thời**: `freshness_lag`
2. **Metric tính điểm khi có đủ metadata và lịch sử cập nhật**: `sla_compliance_rate`

#### 1. Freshness Lag
`freshness_lag` đo độ trễ giữa thời điểm hiện tại và thời điểm cập nhật mới nhất của dataset.

```
freshness_lag = current_timestamp - last_updated_timestamp
```

Trong đó:

| Thành phần               | Ý nghĩa                                              |
| ------------------------ | ---------------------------------------------------- |
| `current_timestamp`      | Thời điểm hệ thống thực hiện kiểm tra                |
| `last_updated_timestamp` | Thời điểm cập nhật mới nhất của dataset hoặc bản ghi |
| `freshness_lag`          | Khoảng thời gian dữ liệu đã bị trễ so với hiện tại   |

Ví dụ:

| Dataset              | `last_updated_timestamp` | `freshness_lag` | Diễn giải                        |
| -------------------- | ------------------------ | --------------- | -------------------------------- |
| `daily_transactions` | 08:30 hôm nay            | 1 giờ           | Dữ liệu còn mới                  |
| `inventory_status`   | 2 ngày trước             | 48 giờ          | Có nguy cơ lỗi thời              |
| `system_logs`        | 30 phút trước            | 30 phút         | Phù hợp với dữ liệu gần realtime |

`freshness_lag` chủ yếu dùng để hiển thị trên Dashboard hoặc Data Catalog dưới dạng:

```
Dữ liệu được cập nhật 3 giờ trước
```

#### 2. SLA Compliance Rate
`sla_compliance_rate` đo tỉ lệ các lần cập nhật dataset đáp ứng SLA đã khai báo trong một cửa sổ quan sát.

```
sla_compliance_rate = successful_updates_within_SLA / total_expected_updates × 100
```

Trong đó:

| Thành phần                      | Ý nghĩa                                                            |
| ------------------------------- | ------------------------------------------------------------------ |
| `successful_updates_within_SLA` | Số lần dataset được cập nhật đúng hoặc trước thời điểm SLA cam kết |
| `total_expected_updates`        | Tổng số lần dataset được kỳ vọng cập nhật trong cửa sổ quan sát    |
| `SLA`                           | Cam kết cập nhật, ví dụ cập nhật hằng ngày trước 09:00             |
| `observation_window`            | Cửa sổ quan sát, ví dụ 7 ngày hoặc 30 ngày gần nhất                |

Ví dụ:

| Điều kiện                | Giá trị                                    |
| ------------------------ | ------------------------------------------ |
| SLA                      | Dataset phải cập nhật trước 09:00 mỗi ngày |
| Cửa sổ quan sát          | 7 ngày gần nhất                            |
| Số lần kỳ vọng cập nhật  | 7                                          |
| Số lần cập nhật đúng SLA | 6                                          |
| `sla_compliance_rate`    | `6 / 7 × 100 = 85.71%`                     |

**Điều kiện để tính Timeliness trong Phase 1**
Để tính được `sla_compliance_rate`, hệ thống cần có đủ các thông tin sau:

| Thông tin cần có                  | Mô tả                                                                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `timestamp_column`                | Cột thể hiện thời điểm cập nhật hoặc phát sinh dữ liệu, ví dụ `updated_at`, `created_at`, `event_time` |
| `SLA`                             | Cam kết cập nhật, ví dụ hằng ngày trước 09:00                                                          |
| `expected_update_frequency`       | Tần suất cập nhật kỳ vọng: realtime, hourly, daily, weekly                                             |
| `run_history` hoặc `load_history` | Lịch sử các lần cập nhật hoặc lịch sử các lần pipeline chạy                                            |
| `timezone`                        | Múi giờ dùng để đánh giá SLA                                                                           |

Nếu chưa có `run_history` hoặc `load_history`, hệ thống chỉ nên tính và hiển thị `freshness_lag`, chưa nên kết luận đầy đủ về `sla_compliance_rate`.

**Staleness Ratio**
Với các dataset cần đánh giá độ mới ở cấp bản ghi, có thể sử dụng thêm `staleness_ratio`.

```
staleness_ratio = records_not_updated_within_threshold / total_records × 100
```

Trong đó:

| Thành phần                             | Ý nghĩa                                                   |
| -------------------------------------- | --------------------------------------------------------- |
| `records_not_updated_within_threshold` | Số bản ghi có thời điểm cập nhật vượt quá ngưỡng cho phép |
| `total_records`                        | Tổng số bản ghi được kiểm tra                             |
| `threshold`                            | Ngưỡng độ mới tối đa, ví dụ 24 giờ hoặc 7 ngày            |

Ví dụ:

| Dataset            | Rule                                                        | Diễn giải                                      |
| ------------------ | ----------------------------------------------------------- | ---------------------------------------------- |
| `inventory_status` | Mỗi bản ghi phải được cập nhật trong vòng 24 giờ            | Phát hiện sản phẩm có thông tin tồn kho quá cũ |
| `price_table`      | Giá phải được cập nhật trong vòng 1 ngày                    | Phát hiện giá không còn đủ mới                 |
| `customer_status`  | Trạng thái khách hàng phải được cập nhật trong vòng 30 ngày | Phát hiện bản ghi lâu chưa được rà soát        |

**Ghi chú Phase 1 / Phase 2**
- Phase 1: tính `freshness_lag`, `staleness_ratio` nếu có timestamp ở cấp bản ghi, và `sla_compliance_rate` nếu có SLA metadata cùng lịch sử cập nhật.
- Nếu thiếu SLA hoặc lịch sử cập nhật, Timeliness chỉ được hiển thị ở mức thông tin tham khảo, chưa dùng để tính điểm chính thức.
- Drift monitoring trên chuỗi thời gian Timeliness, phát hiện xu hướng trễ SLA tăng dần và alerting tự động được đưa sang Phase 2.

### 2.5 Uniqueness – Tính duy nhất

**Định nghĩa**  
Uniqueness đo lường mức độ dữ liệu không bị trùng lặp trong phạm vi một dataset. Một bản ghi hoặc một thực thể được xem là duy nhất khi nó có thể được phân biệt rõ ràng với các bản ghi khác thông qua khóa định danh, khóa nghiệp vụ hoặc tổ hợp nhiều trường.

Trong bối cảnh chất lượng dữ liệu, Uniqueness thường tập trung vào việc kiểm tra:
- Khóa chính hoặc khóa định danh có bị trùng hay không.
- Một thực thể có xuất hiện nhiều lần trong dataset hay không.
- Một tổ hợp trường có đảm bảo tính duy nhất theo quy tắc nghiệp vụ hay không.
- Dataset có chứa các dòng trùng lặp hoàn toàn hay không.

Lưu ý: Uniqueness không đồng nghĩa với Completeness. Một khóa định danh bị null là vấn đề Completeness hoặc Validity, trong khi một khóa định danh xuất hiện nhiều lần là vấn đề Uniqueness. Tuy nhiên, trong thực tế hai loại lỗi này thường cần được kiểm tra cùng nhau để đánh giá chất lượng khóa định danh.

**Ý nghĩa trong bối cảnh dự án**
- Bản ghi trùng lặp có thể gây double-count trong báo cáo, làm sai lệch KPI, thống kê và kết quả phân tích.
- Khóa định danh bị trùng làm giảm khả năng truy vết, liên kết dữ liệu và tích hợp với các bảng/hệ thống khác.
- Trong các pipeline downstream, dữ liệu trùng có thể gây lỗi join, gửi thông báo nhiều lần, tính phí sai hoặc tạo nhiều hồ sơ cho cùng một thực thể.
- Trên sàn giao dịch dữ liệu, dataset có tỉ lệ duplicate cao làm giảm giá trị sử dụng và độ tin cậy của nhà cung cấp dữ liệu.

**Ví dụ minh họa**

|Vấn đề|Mô tả|
|---|---|
|Khóa khách hàng bị trùng|`customer_id = CUS001` xuất hiện nhiều lần trong bảng `customer_master`|
|Khóa giao dịch bị trùng|`transaction_id` xuất hiện 2 lần trong bảng giao dịch, gây nguy cơ ghi nhận trùng giao dịch|
|Trùng tổ hợp khóa nghiệp vụ|Cùng một `customer_id`, `product_id`, `order_date` xuất hiện nhiều lần dù nghiệp vụ chỉ cho phép một bản ghi|
|Dòng trùng hoàn toàn|Hai hoặc nhiều dòng có toàn bộ giá trị giống nhau do lỗi ETL|
|Gửi thông báo lặp|Một khách hàng xuất hiện nhiều lần trong danh sách chiến dịch marketing, dẫn đến gửi email/SMS nhiều lần|

**Loại kiểm tra phổ biến**

| Loại kiểm tra                              | Mô tả                                                                                                               |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| Primary key uniqueness check               | Kiểm tra khóa chính không được xuất hiện nhiều hơn một lần                                                          |
| Primary key completeness check (companion) | Theo dõi khóa chính có bị null/blank hay không để đánh giá chất lượng khóa định danh; điểm chính thuộc Completeness |
| Composite key uniqueness check             | Kiểm tra tổ hợp nhiều cột không bị trùng                                                                            |
| Business key uniqueness check              | Kiểm tra khóa nghiệp vụ như số CCCD, mã số thuế, email, số điện thoại có bị trùng ngoài mong đợi không              |
| Full-row duplicate check                   | Kiểm tra các dòng trùng hoàn toàn                                                                                   |
| Near-duplicate detection                   | Phát hiện các bản ghi gần giống nhau, ví dụ cùng người nhưng tên viết khác nhau; thuộc Phase 2                      |

**Metric chính trong Phase 1**
Trong Phase 1, Uniqueness tập trung vào các kiểm tra có thể xác định rõ bằng rule hoặc metadata, bao gồm primary key, composite key, business key và duplicate row.

#### 1. Primary Key Uniqueness Rate
`pk_uniqueness_rate` đo tỉ lệ bản ghi có khóa chính không null và không bị trùng.

```
pk_uniqueness_rate = records_with_non_duplicate_pk / total_non_null_pk_records × 100
```

Trong đó:

| Thành phần                      | Ý nghĩa                                                                            |
| ------------------------------- | ---------------------------------------------------------------------------------- |
| `records_with_non_duplicate_pk` | Số bản ghi có khóa chính không null và khóa đó chỉ xuất hiện một lần trong dataset |
| `total_non_null_pk_records`     | Tổng số bản ghi có khóa chính không null                                           |
| `duplicate_pk_records`          | Số bản ghi có khóa chính không null nhưng khóa đó xuất hiện nhiều hơn một lần      |

Lưu ý: Công thức này loại các bản ghi có khóa chính null ra khỏi mẫu số để tách riêng lỗi trùng khóa và lỗi thiếu khóa. Các bản ghi có khóa chính null nên được đánh giá ở rule Completeness hoặc Validity.

Ví dụ:

| Chỉ số                                                | Giá trị                        |
| ----------------------------------------------------- | ------------------------------ |
| Tổng số dòng                                          | 10,000                         |
| Số dòng có `customer_id` null                         | 100                            |
| Số dòng có `customer_id` không null                   | 9,900                          |
| Số dòng có `customer_id` không null và không bị trùng | 9,850                          |
| `pk_uniqueness_rate`                                  | `9,850 / 9,900 × 100 = 99.49%` |

#### 2. Primary Key Completeness Rate
Dù thuộc Completeness, chỉ số này nên được theo dõi cùng Uniqueness để đánh giá chất lượng khóa định danh.

```
pk_completeness_rate = non_null_pk_records / total_records × 100
```

Ví dụ:

```
customer_id không được null
```

Nếu một dataset có `pk_uniqueness_rate` cao nhưng nhiều khóa chính bị null, thì chất lượng khóa định danh vẫn chưa đạt yêu cầu.

#### 3. Composite Key Uniqueness Rate
Với các dataset không có một khóa chính đơn lẻ, có thể dùng tổ hợp nhiều cột để xác định tính duy nhất. `composite_uniqueness_rate` đo tỉ lệ bản ghi có tổ hợp khóa không null và không bị trùng.

```
composite_uniqueness_rate = records_with_non_duplicate_composite_key / total_non_null_composite_key_records × 100
```

Trong đó:

| Thành phần                                 | Ý nghĩa                                                                               |
| ------------------------------------------ | ------------------------------------------------------------------------------------- |
| `records_with_non_duplicate_composite_key` | Số bản ghi có tổ hợp khóa không null và tổ hợp đó chỉ xuất hiện một lần trong dataset |
| `total_non_null_composite_key_records`     | Tổng số bản ghi có đầy đủ giá trị cho các cột trong composite key                     |
| `duplicate_composite_key_records`          | Số bản ghi có composite key không null nhưng tổ hợp khóa xuất hiện nhiều hơn một lần  |

Ví dụ composite key:

```
(customer_id, product_id, order_date)
```

```
(account_id, transaction_time, transaction_amount)
```

Composite key chỉ nên được sử dụng khi tổ hợp trường đó có ý nghĩa định danh rõ ràng trong nghiệp vụ. Nếu một phần của composite key bị null, lỗi đó nên được đánh giá ở Completeness hoặc Validity thay vì Uniqueness.

#### 4. Business Key Uniqueness Rate
Một số trường không phải khóa chính kỹ thuật nhưng có yêu cầu duy nhất theo nghiệp vụ. `business_key_uniqueness_rate` đo tỉ lệ bản ghi có business key không null và không bị trùng.

|Business key|Ví dụ rule|
|---|---|
|`citizen_id`|Một số CCCD chỉ thuộc về một khách hàng|
|`tax_code`|Một mã số thuế chỉ thuộc về một doanh nghiệp|
|`email`|Một email chỉ gắn với một tài khoản đang hoạt động|
|`phone_number`|Một số điện thoại không được gắn cho nhiều khách hàng active, tùy use case|

Công thức:

```
business_key_uniqueness_rate = records_with_non_duplicate_business_key / total_non_null_business_key_records × 100
```

Trong đó:

|Thành phần|Ý nghĩa|
|---|---|
|`records_with_non_duplicate_business_key`|Số bản ghi có business key không null và giá trị business key đó chỉ xuất hiện một lần trong phạm vi kiểm tra|
|`total_non_null_business_key_records`|Tổng số bản ghi có business key không null trong phạm vi kiểm tra|
|`duplicate_business_key_records`|Số bản ghi có business key không null nhưng giá trị business key xuất hiện nhiều hơn một lần|

Lưu ý: Business key uniqueness phụ thuộc mạnh vào use case. Ví dụ, một `phone_number` có thể không được trùng giữa các khách hàng đang active, nhưng có thể được phép xuất hiện lại trong lịch sử hoặc trong nhóm khách hàng đã inactive. Vì vậy, rule cần khai báo rõ phạm vi áp dụng.

#### 5. Full-row Duplicate Rate
`duplicate_rate` đo tỉ lệ dòng bị trùng hoàn toàn trong dataset.

```
duplicate_rate = duplicate_rows / total_rows × 100
```

Trong đó:

|Thành phần|Ý nghĩa|
|---|---|
|`duplicate_rows`|Số dòng trùng hoàn toàn với ít nhất một dòng khác|
|`total_rows`|Tổng số dòng trong dataset|

Metric này nên được dùng như một chỉ số cảnh báo ở cấp dataset. Không phải mọi dataset đều yêu cầu full-row uniqueness tuyệt đối, vì một số dataset log/event hoặc snapshot có thể cho phép nhiều dòng giống nhau trong một số trường hợp nghiệp vụ.

**Phân biệt lỗi Completeness và Uniqueness đối với khóa định danh**

|Loại lỗi|Dimension chính|Ví dụ|
|---|---|---|
|Khóa chính bị null|Completeness / Validity|`customer_id` bị trống|
|Khóa chính bị trùng|Uniqueness|`customer_id = CUS001` xuất hiện 3 lần|
|Dòng trùng hoàn toàn|Uniqueness|Hai dòng có toàn bộ giá trị giống nhau|
|Cùng thực thể nhưng dữ liệu hơi khác nhau|Phase 2 / Near-duplicate|`Nguyen Van A` và `Nguyễn Văn A` có thể là cùng một người|

**Ghi chú Phase 1 / Phase 2**
- Phase 1: kiểm tra primary key uniqueness, primary key completeness, composite key uniqueness, business key uniqueness và full-row duplicate.
- Các rule Uniqueness cần dựa trên metadata như `primary_key`, `composite_key`, `business_key` hoặc rule config.
- Full-row duplicate rate có thể dùng để cảnh báo, nhưng việc có tính vào RuleScore hay không phụ thuộc vào loại dataset và quy tắc nghiệp vụ.
- Phase 2: mở rộng sang near-duplicate/fuzzy matching để phát hiện các bản ghi gần giống nhau nhưng không trùng hoàn toàn.

### 2.6 Validity – Tính hợp lệ

**Định nghĩa**  
Validity đo lường mức độ dữ liệu tuân thủ đúng các quy tắc đã được định nghĩa về kiểu dữ liệu, định dạng, miền giá trị, khoảng giá trị và ràng buộc nghiệp vụ. Một giá trị được xem là hợp lệ khi nó nằm trong phạm vi cho phép và phù hợp với cấu trúc hoặc quy tắc mà dataset yêu cầu.

Dữ liệu có thể đầy đủ nhưng vẫn không hợp lệ. Ví dụ, trường `phone_number` không bị null nhưng chứa chữ cái; trường `email` có giá trị nhưng không đúng định dạng email; trường `order_date` có dữ liệu nhưng lại nhỏ hơn ngày hệ thống bắt đầu vận hành.

Validity khác với Accuracy. Một giá trị hợp lệ chưa chắc đã chính xác với thực tế. Ví dụ, số điện thoại `0912345678` có đúng định dạng 10 chữ số, nhưng chưa chắc là số điện thoại thật của khách hàng.

**Ý nghĩa trong bối cảnh dự án**
- Validity giúp phát hiện các lỗi dữ liệu phổ biến như sai kiểu dữ liệu, sai định dạng, ngoài miền giá trị hoặc vi phạm ràng buộc đơn giản.
- Đây là dimension phù hợp để triển khai bằng Rules Engine vì nhiều rule có thể được mô tả rõ ràng dưới dạng type check, regex, range check hoặc domain check.
- Trong sàn giao dịch dữ liệu, Validity giúp người mua đánh giá dataset có thể sử dụng trực tiếp hay cần làm sạch dữ liệu trước khi dùng.
- Trong Phase 1, hệ thống có thể tự động hóa một phần bằng rule template và profiling, nhưng các domain rule hoặc business constraint vẫn cần metadata/config hoặc Data Steward phê duyệt.

**Ví dụ minh họa**

|Vấn đề|Mô tả|
|---|---|
|Sai kiểu dữ liệu|Cột `amount` được kỳ vọng là số nhưng chứa giá trị dạng text|
|Sai định dạng|`email` không đúng định dạng email hoặc `phone_number` không đủ 10 chữ số|
|Ngoài khoảng giá trị|`discount_rate` nhỏ hơn 0 hoặc lớn hơn 100|
|Ngày không hợp lệ|`order_date` nhỏ hơn ngày hệ thống bắt đầu hoạt động hoặc lớn hơn ngày hiện tại|
|Mã danh mục sai|`country_code` không thuộc danh sách mã quốc gia hợp lệ|
|Giá trị trạng thái không hợp lệ|`order_status` có giá trị ngoài danh sách `PENDING`, `PAID`, `CANCELLED`, `DELIVERED`|

**Loại kiểm tra phổ biến**

| Loại kiểm tra       | Mô tả                                               | Ví dụ                               |
| ------------------- | --------------------------------------------------- | ----------------------------------- |
| Data type check     | Kiểm tra giá trị có đúng kiểu dữ liệu kỳ vọng không | `amount` phải là numeric            |
| Format check        | Kiểm tra giá trị có đúng định dạng hoặc regex không | `email` phải đúng định dạng email   |
| Length check        | Kiểm tra độ dài giá trị                             | `phone_number` phải có 10 chữ số    |
| Range check         | Kiểm tra giá trị có nằm trong khoảng cho phép không | `age` nằm trong `[0, 120]`          |
| Domain check        | Kiểm tra giá trị có thuộc danh sách hợp lệ không    | `country_code` thuộc reference list |
| Date validity check | Kiểm tra ngày tháng có hợp lệ theo ngữ cảnh không   | `order_date <= current_date`        |
| Constraint check    | Kiểm tra ràng buộc đơn giản theo nghiệp vụ          | `discount_rate` không vượt quá 100  |

**Metric chính trong Phase 1**
Metric chính của Validity trong Phase 1 là `validity_rate`.

```
validity_rate = records_passing_validity_rules / total_records_in_scope × 100
```

Trong đó:

| Thành phần                       | Ý nghĩa                                                                  |
| -------------------------------- | ------------------------------------------------------------------------ |
| `records_passing_validity_rules` | Số bản ghi thỏa mãn rule validity được cấu hình                          |
| `total_records_in_scope`         | Tổng số bản ghi nằm trong phạm vi kiểm tra                               |
| `validity_rules`                 | Tập rule kiểm tra kiểu dữ liệu, định dạng, range, domain hoặc constraint |

Validity có thể được tính ở cấp cột hoặc cấp dataset.

```
validity_rate_per_column = records_passing_validity_rules_for_column / total_records_in_scope × 100
```

```
validity_rate_per_dataset = AVG(validity_rate của các CDE có validity rule)
```

Ví dụ:

| Rule                                     | Công thức / Cách tính                                   |
| ---------------------------------------- | ------------------------------------------------------- |
| `email` phải đúng định dạng              | `valid_email_records / total_records × 100`             |
| `phone_number` phải có 10 chữ số         | `valid_phone_records / total_records × 100`             |
| `amount` phải là số và không âm          | `valid_amount_records / total_records × 100`            |
| `country_code` phải thuộc reference list | `records_with_valid_country_code / total_records × 100` |

**Các nhóm rule Validity trong Phase 1**

| Nhóm rule    | Ví dụ                                    | Nguồn cấu hình           |
| ------------ | ---------------------------------------- | ------------------------ |
| Type check   | `amount` phải là numeric                 | Schema / metadata        |
| Format check | `email` phải khớp regex email            | Rule template / config   |
| Length check | `phone_number` phải có 10 chữ số         | Rule template / config   |
| Range check  | `age` nằm trong `[0, 120]`               | Metadata / Data Steward  |
| Domain check | `country_code` thuộc danh sách hợp lệ    | Reference table / config |
| Date check   | `order_date` không lớn hơn ngày hiện tại | Rule template / config   |

**Tự động hóa trong Phase 1**
Trong Phase 1, Validity có thể được tự động hóa ở mức cơ bản thông qua:
- Rule template cho các kiểu dữ liệu phổ biến như email, số điện thoại, ngày tháng, số tiền.
- Metadata hoặc schema để xác định kiểu dữ liệu kỳ vọng.
- Reference table hoặc config file để kiểm tra domain value.
- Profiling Pipeline để phát hiện pattern phổ biến và gợi ý candidate rule.

Ví dụ:

| Tín hiệu từ profiling                                     | Candidate rule có thể gợi ý          |
| --------------------------------------------------------- | ------------------------------------ |
| 95% giá trị trong cột khớp pattern email                  | Gợi ý rule kiểm tra email format     |
| Cột chỉ có các giá trị `M`, `F`, `O`                      | Gợi ý domain check                   |
| Cột số có giá trị chủ yếu trong `[0, 100]`                | Gợi ý range check                    |
| Cột có tên chứa `phone` và phần lớn giá trị dài 10 chữ số | Gợi ý rule phone number length/regex |

Lưu ý: Candidate rule do hệ thống gợi ý chưa tự động trở thành rule chính thức. Các rule ảnh hưởng đến DQ Score cần được cấu hình trong Rules Engine hoặc được Data Steward phê duyệt.

**Phân biệt Validity với các dimension khác**

| Trường hợp                                      | Dimension chính                    |
| ----------------------------------------------- | ---------------------------------- |
| Giá trị bị null ở trường bắt buộc               | Completeness                       |
| Giá trị có dữ liệu nhưng sai định dạng          | Validity                           |
| Giá trị nằm ngoài khoảng hợp lý                 | Validity / Accuracy Proxy tùy rule |
| Giá trị đúng định dạng nhưng sai so với thực tế | Accuracy                           |
| Hai trường trong cùng bản ghi mâu thuẫn logic   | Consistency                        |
| Khóa định danh xuất hiện nhiều lần              | Uniqueness                         |

**Ghi chú Phase 1 / Phase 2**
- Phase 1: tập trung vào type check, format check, length check, range check, domain check và date validity check.
- Domain/lookup list nên được lưu trong reference table hoặc file cấu hình, không hardcode trực tiếp trong rule.
- Rule template có thể giúp giảm công sức viết rule thủ công, nhưng không thay thế hoàn toàn metadata nghiệp vụ hoặc phê duyệt của Data Steward.
- Phase 2: mở rộng sang AI-assisted validity, semantic type inference và phát hiện pattern lỗi mới chưa được định nghĩa trước.

## 3. Bảng tổng hợp 6 trụ cột

Bảng dưới đây tổng hợp 6 trụ cột chất lượng dữ liệu, câu hỏi cốt lõi, metric chính trong Phase 1 và threshold mặc định đề xuất.

Lưu ý: Threshold trong bảng chỉ là giá trị mặc định ban đầu. Khi triển khai thực tế, threshold cần được cấu hình theo loại dataset, mức độ quan trọng của CDE, đặc thù nghiệp vụ và yêu cầu sử dụng dữ liệu.

| #   | Trụ cột      | Tên tiếng Việt | Câu hỏi cốt lõi                                                   | Metric chính trong Phase 1                                                                          | Threshold mặc định đề xuất |
| --- | ------------ | -------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | -------------------------- |
| 1   | Completeness | Tính đầy đủ    | Các trường bắt buộc/CDE có được điền đầy đủ không?                | `completeness_rate` trên mandatory fields hoặc CDE                                                  | ≥ 95%                      |
| 2   | Accuracy     | Tính chính xác | Dữ liệu có phản ánh đúng thực tế không?                           | Phase 1 dùng `plausibility_rate` làm metric đại diện cho Accuracy Proxy                                                 | ≥ 90%                      |
| 3   | Consistency  | Tính nhất quán | Dữ liệu có mâu thuẫn logic trong cùng dataset/data product không? | `consistency_rate` trên cross-field rule, business rule và referential integrity cơ bản             | ≥ 90%                      |
| 4   | Timeliness   | Tính thời sự   | Dữ liệu có đủ mới và có đáp ứng SLA cập nhật không?               | `freshness_lag`; `sla_compliance_rate` nếu có SLA và lịch sử cập nhật                               | ≥ 95% nếu tính được SLA    |
| 5   | Uniqueness   | Tính duy nhất  | Khóa định danh hoặc bản ghi có bị trùng lặp không?                | `pk_uniqueness_rate`, `composite_uniqueness_rate`, `business_key_uniqueness_rate`, `duplicate_rate` | ≥ 99% với key quan trọng   |
| 6   | Validity     | Tính hợp lệ    | Dữ liệu có đúng kiểu, định dạng, miền giá trị và ràng buộc không? | `validity_rate` trên type/format/range/domain/date rule                                             | ≥ 98%                      |

### 3.1 Ghi chú về threshold

Các threshold ở trên không nên áp dụng cứng cho mọi dataset. Ví dụ:

| Loại dataset         | Lưu ý khi cấu hình threshold                                                                           |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| Master Data          | Cần threshold cao cho Completeness, Validity và Uniqueness vì dữ liệu thường dùng làm nguồn tham chiếu |
| Transaction Data     | Cần chú trọng Timeliness, Completeness, Validity và Consistency                                        |
| Log/Event Data       | Có thể chấp nhận một số trường optional bị null, nhưng cần kiểm soát Timeliness và volume anomaly      |
| Survey/Feedback Data | Có thể có nhiều giá trị thiếu hợp lệ, cần phân biệt mandatory field và optional field                  |
| Reference Data       | Cần Validity, Domain check và Consistency cao vì dùng làm bảng tham chiếu                              |

Threshold cuối cùng nên được quản lý trong rule config hoặc metadata, thay vì hardcode trong hệ thống.

## 4. Phân cấp áp dụng

Khung đo lường chất lượng dữ liệu được áp dụng theo nhiều cấp độ, từ rule cụ thể đến điểm tổng hợp toàn dataset.

```
Tầng 1 – Rule Level
    Mỗi rule kiểm tra một điều kiện chất lượng dữ liệu cụ thể.
    Ví dụ:
        DQ-COMP-001: customer_id không được null
        DQ-VALI-002: email phải đúng định dạng
        DQ-UNIQ-001: customer_id không được trùng
        DQ-TIME-001: dataset phải cập nhật trước thời điểm SLA

        Rule Result:
            passed / failed / miscast / empty

        Rule Score:
            RuleScore = passed_records / total_records_in_scope × 100


Tầng 2 – Dimension Level
    Các rule cùng thuộc một trụ cột được tổng hợp thành Dimension Score.
    Ví dụ:
        Completeness Score = tổng hợp các rule thuộc Completeness
        Accuracy Proxy Score = tổng hợp các rule plausibility thuộc Accuracy
        Consistency Score = tổng hợp các rule thuộc Consistency
        Timeliness Score = tổng hợp các rule thuộc Timeliness
        Uniqueness Score = tổng hợp các rule thuộc Uniqueness
        Validity Score = tổng hợp các rule thuộc Validity


Tầng 3 – Dataset Level
    Các Dimension Score được tổng hợp thành DQ Core Score của dataset.

        DQ Core Score = Σ (dimension_weight × Dimension Score)
```

Phương pháp tính điểm chi tiết, cách xử lý trọng số và cách tái phân bổ trọng số khi một dimension chưa có đủ rule được mô tả trong tài liệu **DQ_Scoring_Model**.

### 4.1 Cấp áp dụng theo phạm vi dữ liệu

Ngoài phân cấp tính điểm, mỗi rule cũng cần xác định rõ phạm vi áp dụng.

| Cấp áp dụng         | Mô tả                                                        | Ví dụ                                                          |
| ------------------- | ------------------------------------------------------------ | -------------------------------------------------------------- |
| Column Level        | Rule áp dụng cho một cột cụ thể                              | `email` không được null, `phone_number` phải có 10 chữ số      |
| Row Level           | Rule kiểm tra logic trong cùng một bản ghi                   | `end_date >= start_date`                                       |
| Table/Dataset Level | Rule áp dụng cho toàn bộ bảng/dataset                        | Không có dòng trùng hoàn toàn, row count không giảm bất thường |
| Data Product Level  | Rule áp dụng cho nhóm bảng liên quan trong cùng data product | `customer_id` trong `orders` phải tồn tại trong `customers`    |
| Cross-system Level  | Rule so sánh giữa các hệ thống độc lập                       | Đối chiếu thông tin khách hàng với CRM/KYC; thuộc Phase 2      |

### 4.2 Metadata tối thiểu để áp dụng rule

Để triển khai rule và tính điểm chính xác, mỗi dimension cần một số metadata tối thiểu.

| Dimension      | Metadata tối thiểu cần có                                                                             |
| -------------- | ----------------------------------------------------------------------------------------------------- |
| Completeness   | `mandatory_fields`, danh sách CDE, điều kiện áp dụng rule nếu có                                      |
| Accuracy Proxy | `expected_range`, `business_bounds`, baseline thống kê nếu có                                         |
| Consistency    | `cross_field_rules`, `business_rules`, `reference_table` nếu kiểm tra referential integrity           |
| Timeliness     | `timestamp_column`, `SLA`, `expected_update_frequency`, `run_history` hoặc `load_history`, `timezone` |
| Uniqueness     | `primary_key`, `composite_key`, `business_key`, quy định có cho phép duplicate hay không              |
| Validity       | `declared_data_type`, `regex_pattern`, `domain_values`, `reference_list`, `range_config`              |

Nếu thiếu metadata bắt buộc cho một dimension, hệ thống có thể:
- Chỉ hiển thị metric tham khảo.
- Không tính dimension đó vào DQ Core Score.
- Hoặc yêu cầu Data Steward bổ sung metadata/rule config.

## 5. Phạm vi đo lường theo giai đoạn

Bảng dưới đây mô tả phạm vi đo lường của từng dimension trong Phase 1 và hướng mở rộng ở Phase 2.

| Dimension    | Phase 1 – Nền tảng đo lường cơ bản                                                                                                                           | Phase 2 – Mở rộng nâng cao                                                                               |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| Completeness | Null/blank check trên mandatory fields và CDE; conditional completeness đơn giản nếu có rule config                                                          | Weighted completeness theo mức độ quan trọng của CDE; population completeness theo pattern hoặc use case |
| Accuracy     | Chưa đo Accuracy trực tiếp bằng ground truth; sử dụng Accuracy Proxy thông qua `plausibility_rate`, range check, business bounds và statistical bounds       | Cross-reference với ground truth như KYC, CRM, core system hoặc external registry                        |
| Consistency  | Cross-field logic trong cùng bản ghi; business rule consistency; referential integrity cơ bản trong cùng data product; Dataset volume anomaly check dựa trên baseline `expected_row_count` ở vai trò monitoring-only | Cross-system matching; lineage-aware consistency; so sánh cùng thực thể giữa nhiều hệ thống nguồn        |
| Timeliness   | Tính `freshness_lag`; tính `sla_compliance_rate` nếu có SLA và lịch sử cập nhật; tính `staleness_ratio` nếu có timestamp ở cấp bản ghi                       | Drift monitoring trên chuỗi thời gian; phát hiện xu hướng trễ SLA; alerting tự động                      |
| Uniqueness   | Primary key uniqueness; composite/business key uniqueness; full-row duplicate check; tách riêng lỗi key null và key duplicate                                | Near-duplicate/fuzzy matching; entity resolution; similarity-based duplicate detection                   |
| Validity     | Type check, format check, length check, range check, domain/lookup check, date validity check                                                                | AI-assisted validity; semantic type inference; phát hiện pattern lỗi mới chưa được định nghĩa trước      |

### 5.1 Nguyên tắc phân kỳ

Phase 1 tập trung vào các kiểm tra có thể triển khai bằng rule rõ ràng, thống kê cơ bản và metadata/config. Mục tiêu là xây dựng bộ công cụ DQ Scoring nền tảng có khả năng phân tích dataset mẫu, phát hiện lỗi phổ biến, tính điểm chất lượng và hiển thị báo cáo trực quan.

Phase 2 mở rộng sang các kỹ thuật nâng cao hơn như data drift detection, outlier detection bằng mô hình học máy, fuzzy matching, cross-system validation, alerting tự động và tích hợp sâu vào Data Catalog/API.

### 5.2 Ranh giới giữa Phase 1 và Phase 2

| Nội dung                      | Phase 1                                           | Phase 2                                                   |
| ----------------------------- | ------------------------------------------------- | --------------------------------------------------------- |
| Rule-based validation         | Có                                                | Có, mở rộng thêm                                          |
| Profiling thống kê cơ bản     | Có                                                | Có                                                        |
| Candidate rule từ profiling   | Có, nhưng cần phê duyệt                           | Có thể tự động hóa cao hơn                                |
| AI/ML anomaly detection       | Chưa phải trọng tâm                               | Có                                                        |
| Drift detection nâng cao      | Chỉ lưu baseline và cảnh báo đơn giản             | Có monitoring/alerting                                    |
| Cross-system reference check  | Chưa triển khai chính                             | Có                                                        |
| Trust Score từ usage/feedback | Chưa tính vào điểm chính thức; chỉ thiết kế khung | Tính khi sàn có đủ dữ liệu usage, transaction và feedback |
| Dashboard giải thích lỗi      | Có bản cơ bản                                     | Có bản nâng cao, có trend và root-cause hint              |

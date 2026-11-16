# CHƯƠNG 1: KHẢO SÁT BỐI CẢNH VÀ XÁC ĐỊNH PHẠM VI HỆ THỐNG

**Đề tài:** Chấm điểm Chất lượng dữ liệu (DQ Scoring System)  
**Mã hồ sơ:** AD-001-SCOPE  
**Phiên bản:** 1.7  
**Ngày:** 2026-09-24  
**Trạng thái:** Review Candidate  
**Tiêu chuẩn chất lượng:** ISO/IEC/IEEE 29148:2018 (Requirements Engineering)  

---

## THÔNG TIN VÀ KIỂM SOÁT TÀI LIỆU

### Lịch sử phiên bản và phê duyệt

| Phiên bản | Ngày | Tóm tắt thay đổi | Trạng thái | Tác giả / Người sửa |
| :--- | :--- | :--- | :--- | :--- |
| **0.1** | 2026-08-20 | Khởi tạo khảo sát bối cảnh, bài toán và các năng lực Data Quality | Draft | Nguyễn Hoàng Tùng |
| **0.2** | 2026-08-24 | Chuẩn hóa thuật ngữ `Canonical Quality Result`, bổ sung Evidence Registry và các chiều chất lượng | Draft | Nguyễn Hoàng Tùng |
| **0.3** | 2026-08-25 | Thu gọn phạm vi v1.0: cô lập Outlier IQR advisory, bỏ runtime API/IAM phức tạp, bổ sung Decision Log | Review Candidate | Nguyễn Hoàng Tùng |
| **1.0** | 2026-08-27 | Khóa phạm vi v1.0, chuẩn hóa BUC-001..BUC-008, chốt 10 quyết định phạm vi và nghiệm thu Approved Baseline | **Approved Baseline** | Nguyễn Hoàng Tùng |
| **1.1** | 2026-08-28 | Chuẩn hóa định danh; tách vai trò Owner/Steward và luồng Draft/Approve; đồng bộ Gate và ma trận truy vết với SRS v1.1 | Review Candidate | Nguyễn Hoàng Tùng |
| **1.2** | 2026-09-04 | Đồng bộ async runtime với PostgreSQL 16: phân định API/Worker, cơ chế lease/retry/cancel và hợp đồng SourceAdapter | Review Candidate | Nguyễn Hoàng Tùng |
| **1.3** | 2026-09-08 | Khóa mô hình đơn nút với PostgreSQL 16 và DuckDB in-process; chuẩn hóa 6 chiều chất lượng DAMA/ISO; đồng bộ 108 yêu cầu SRS | Review Candidate | Nguyễn Hoàng Tùng |
| **1.5** | 2026-09-16 | Mở rộng bài toán Đa thuê bao cho Data Marketplace (BR-018, BR-019); cập nhật quy tắc phê duyệt và bảo vệ dữ liệu nhạy cảm | Review Candidate | Nguyễn Hoàng Tùng |
| **1.6** | 2026-09-17 | Bổ sung Mẫu Đánh giá theo Domain và ranh giới LLM Advisory; đồng bộ 6 cấp Quality Gate | Approved Specification | Nguyễn Hoàng Tùng |
| **1.7** | 2026-09-24 | Chuẩn hóa kiến trúc đích k3s đơn nút, ngân sách tối đa 8GB RAM toàn nút, bảo toàn snapshot gốc qua manifest (không compact/coalesce), hợp đồng điều phối Worker - tính toán Spark - công bố Assessment, và định nghĩa SLA end-to-end có điều kiện benchmark | **Review Candidate** | Nguyễn Hoàng Tùng |

### Biên bản phê duyệt Baseline v1.0 (lịch sử)

| Vai trò | Họ và tên | Trách nhiệm | Quyết định | Ngày phê duyệt |
| :--- | :--- | :--- | :--- | :--- |
| **Project Owner / Author** | Nguyễn Hoàng Tùng | Chịu trách nhiệm nội dung, kiến trúc và hiện thực hóa | **Approved** | 2026-08-27 |
| **Requirements Reviewer / Approver** | Mentor / Hội đồng thẩm định | Thẩm định tính khả thi, phương pháp luận và nghiệm thu | **Approved** | 2026-08-27 |

> Phiên bản 1.7 hiện là **Review Candidate** (đặc tả kiến trúc thiết kế mục tiêu, chưa phải phần mềm đã triển khai/kiểm thử) và chờ vòng thẩm định độc lập.

---

## 1. KẾT QUẢ KHẢO SÁT VÀ PHÂN TÍCH HIỆN TRẠNG

### 1.1. Bối cảnh và Nhu cầu thực tế

Trong kỷ nguyên dữ liệu lớn và kiến trúc phân tán (Data Mesh / Data Fabric), dữ liệu trở thành tài sản trọng yếu thúc đẩy các quyết định kinh doanh, hệ thống phân tích BI và mô hình học máy (Machine Learning). Tuy nhiên, các tổ chức đang đối mặt với thách thức nghiêm trọng về độ tin cậy của dữ liệu:
- Dữ liệu thu thập từ nhiều nguồn dị biệt (CSV, Parquet, RDBMS, CDC stream) thường xuyên bị thiếu hụt (nulls), sai lệch định dạng, trùng lặp khóa hoặc vi phạm ràng buộc nghiệp vụ.
- Đánh giá chất lượng dữ liệu hiện nay chủ yếu mang tính rời rạc, cục bộ bằng các câu lệnh SQL kiểm tra thủ công hoặc các kịch bản kiểm thử riêng lẻ trong từng pipeline ETL/ELT.
- Thiếu một khung chuẩn hóa để lượng hóa chất lượng dữ liệu thành **Điểm chất lượng (DQ Score)** có khả năng giải thích, so sánh và kiểm toán minh bạch.

Hệ thống DQ Scoring được xây dựng nhằm giải quyết bài toán:
1. Tự động lập hồ sơ dữ liệu (Data Profiling) và trích xuất các đặc trưng thống kê nền tảng.
2. Phân loại yêu cầu theo taxonomy **6 chiều chất lượng dữ liệu chuẩn mực**; chỉ công bố score cho chiều có đủ phép đo, không mặc định rằng cả sáu chiều luôn đo được.
3. Kết hợp mô hình xác định (Deterministic Rule-based Validation) với mô hình thống kê (Statistical Outlier Detection) để phát hiện cả lỗi quy tắc đã biết và giá trị dị biệt chưa lường trước.
4. Tổng hợp bằng chứng thành bộ chỉ số minh bạch: **DQ Score**, **Dimension Scores**, **Coverage (Độ bao phủ)**, **Quality Gate (Cổng chất lượng)** và **Bounded Evidence (Bằng chứng có kiểm soát)**.
5. Cung cấp giao diện Dashboard trực quan hóa và kiểm tra kết quả cục bộ.

Phiên bản 1.0 cung cấp một quy trình đánh giá khép kín, tự động và có thể tái lập từ Snapshot đến Assessment, với kiến trúc phân tách rạch ròi giữa Control Plane (FastAPI + Worker điều phối bền vững qua PostgreSQL 16) và Compute Plane (Apache Spark trên k3s làm động cơ tính toán vector hóa/pushdown duy nhất), loại bỏ các cơ chế streaming thời gian thực (Kafka/Flink) hoặc IAM phân tán ngoài phạm vi v1.0.

Bài toán thực tế không dừng lại ở việc đếm số dòng lỗi, mà trả lời câu hỏi cốt lõi của người sử dụng dữ liệu:
> *"Bộ dữ liệu này đạt bao nhiêu điểm? Điểm số được hình thành từ những bằng chứng nào? Bao nhiêu phần trăm yêu cầu chất lượng đã thực sự được kiểm chứng, và còn rủi ro tiềm ẩn nào trước khi đưa vào vận hành?"*

---

### 1.2. Nguồn thông tin khảo sát và Evidence Registry

Thông tin trong hồ sơ được thu thập và thẩm định từ các nguồn tài liệu kỹ thuật, tiêu chuẩn quốc tế và tài sản nghiên cứu nội bộ:

#### 1.2.1. Bảng danh mục bằng chứng (Evidence Registry)

| Mã bằng chứng | Tên nguồn tài liệu / Tiêu chuẩn | Kết luận và Quyết định được hỗ trợ | Trạng thái thẩm định |
| :--- | :--- | :--- | :--- |
| **EVD-INT-001** | `docs/PROJECT_BRIEF_DQ_SCORING.md` (v0.6) | Mục tiêu hệ thống, phạm vi phát hành v1.0, 3 năng lực cốt lõi (Scoring, Outlier, Drift) và mô hình trách nhiệm | `[XÁC NHẬN]` Chính thức phê duyệt |
| **EVD-INT-002** | Kịch bản dữ liệu tham chiếu & Workload Profile | Kịch bản tải 4–10 triệu bản ghi/giờ từ hệ thống ngoài; được sử dụng làm cơ sở bối cảnh đối sánh benchmark | `[XÁC NHẬN]` Tham chiếu bối cảnh |
| **EVD-EXT-001** | [The Government Data Quality Framework](https://www.gov.uk/government/publications/the-government-data-quality-framework) & DAMA DMBOK2 | Khung 6 chiều chất lượng dữ liệu: Completeness, Accuracy, Consistency, Timeliness, Uniqueness, Validity | `[XÁC NHẬN]` Chuẩn mực quốc tế |
| **EVD-EXT-002** | [City of Chicago Taxi Trips Dataset](https://data.cityofchicago.org/Transportation/Taxi-Trips-2023/e55j-2ewb) | Bộ dữ liệu công khai ứng viên cho Vertical Slice v1.0 (Lát cắt tháng 01/2023 có cấu trúc bảng, tọa độ, timestamp, tiền tệ) | `[XÁC NHẬN]` Nguồn mở công khai |
| **EVD-TH-001** | `docs/theory/DQ_SCORING_THEORY.md` | Cơ sở lý thuyết toán học: Semantics phép đo, Invariants, Denominator handling, Coverage, Gate precedence | `[XÁC NHẬN]` Nền tảng thuật toán |
| **EVD-RES-001** | Khảo sát Sản phẩm Đối thủ Thương mại Digna | Bằng chứng khảo sát sản phẩm thương mại đối thủ (Digna); tham khảo mô hình trình bày trạng thái kiểm tra và drill-down | `[XÁC NHẬN]` Tham khảo UX/UI |

---

### 1.3. Quy trình nghiệp vụ Chất lượng Dữ liệu

#### 1.3.1. Biên hệ thống (System Boundary)

DQ Scoring bắt đầu trách nhiệm khi tiếp nhận một tệp dữ liệu bảng (CSV/Parquet) hoặc tham chiếu vị trí dữ liệu kèm metadata nguồn. Hệ thống kết thúc trách nhiệm khi công bố Bản đánh giá bất biến (**Immutable Assessment**) và xuất báo cáo. Hệ thống tuyệt đối không can thiệp làm thay đổi hoặc làm sạch dữ liệu nguồn.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   BÊN NGOÀI HỆ THỐNG                                    │
│                                                                                         │
│  ┌───────────────────────┐   ┌───────────────────────┐   ┌───────────────────────────┐  │
│  │ Data Source Provider  │   │  Data Steward (Draft) │   │   Data Owner (Approve)    │  │
│  │(CSV/Parquet Snapshots)│   │(Rules/Policy Proposal)│   │ (Review & Activate Policy)│  │
│  └───────────┬───────────┘   └───────────┬───────────┘   └─────────────┬─────────────┘  │
└──────────────┼───────────────────────────┼─────────────────────────────┼────────────────┘
               │ Dữ liệu & Provenance      │ Đề xuất cấu hình Draft      │ Quyết định phê duyệt
               ▼                           ▼                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                             BIÊN HỆ THỐNG DQ SCORING v1.0                               │
│                                                                                         │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Dataset Store & Registry (Lưu trữ snapshot bất biến & phát hiện schema)        │  │
│  └─────────────────────────────────────┬─────────────────────────────────────────────┘  │
│                                        ▼                                                │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 2. Profiling Engine (Tính Canonical Metrics qua Apache Spark trên k3s)            │  │
│  └─────────────────────────────────────┬─────────────────────────────────────────────┘  │
│                                        ▼                                                │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 3. Validation & Detection (Rule Engine + IQR Outlier Detector Advisory)           │  │
│  │    --> Tạo tập hợp CANONICAL QUALITY RESULTS                                      │  │
│  └─────────────────────────────────────┬─────────────────────────────────────────────┘  │
│                                        ▼                                                │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 4. Score Engine (Tổng hợp Rule/Dimension/DQ Score, Coverage, Quality Gate)        │  │
│  └─────────────────────────────────────┬─────────────────────────────────────────────┘  │
│                                        ▼                                                │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 5. Local Dashboard (Trực quan hóa Scorecard & Drill-down Bằng chứng Bounded)       │  │
│  └───────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────┬────────────────────────────────────────────────┘
                                         │ Scorecard & Bằng chứng
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   BÊN NGOÀI HỆ THỐNG                                    │
│                                                                                         │
│                               ┌─────────────────┐                                       │
│                               │ Dataset Consumer│ (Đọc báo cáo & quyết định sử dụng)    │
│                               └─────────────────┘                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 1.3.2. Danh mục Đối tượng Nghiệp vụ chính

| Đối tượng | Ý nghĩa nghiệp vụ |
| :--- | :--- |
| **Data Asset** | Tài sản dữ liệu logic cần quản lý vòng đời và đánh giá chất lượng (ví dụ: `chicago_taxi_trips`). |
| **Dataset Snapshot** | Phiên bản dữ liệu vật lý cụ thể, bất biến, gắn với mã băm SHA-256 nội dung và schema detected. |
| **Canonical Metrics** | Tập chỉ số thống kê (row count, null rate, distinct count, min/max, distribution) tính toán 1 lần duy nhất qua Profiling. |
| **Quality Rule** | Quy tắc kiểm tra kỳ vọng xác định (deterministic expectation) thuộc một trong 6 chiều chất lượng. |
| **Scoring Policy** | Chính sách tính điểm: trọng số quy tắc, trọng số chiều, ngưỡng công bố điểm (Coverage ≥ 80%) và điều kiện Quality Gate. |
| **Outlier Configuration** | Cấu hình tham số phát hiện ngoại lệ IQR (cột số mục tiêu, hệ số $k=1.5$). |
| **Evaluation Run** | Một lần thực thi đánh giá khép kín trên 1 Snapshot với bộ Ruleset, Scoring Policy và Outlier Config đã đóng băng. |
| **Canonical Quality Result** | Kết quả chuẩn hóa từ từng Rule hoặc Detector, chứa status, counts, metric, configuration hash và bounded evidence. |
| **Assessment** | Phiên bản kết quả đánh giá cuối cùng bất biến, bao gồm DQ Score, đúng 6 Dimension Results (score có thể `null`), Coverage, Quality Gate, config hashes, `assessment_hash` và Bounded Evidence. |

#### 1.3.3. Luồng nghiệp vụ chuẩn hóa (End-to-End Workflow)

1. **Đăng ký Snapshot:** Tiếp nhận tệp CSV/Parquet hoặc tham chiếu bảng Delta Lake; hệ thống kiểm tra cấu trúc, xác thực mã băm SHA-256 nội dung tệp, trích xuất lược đồ (schema) và lưu trữ snapshot bất biến trong Dataset Store.
2. **Lập hồ sơ dữ liệu (Profiling):** Quét toàn bộ (full scan) snapshot bằng động cơ Apache Spark trên k3s, tính toán tập chỉ số `Canonical Metrics` dùng chung một lần duy nhất.
3. **Thực thi Đánh giá (Validation & Detection):**
   - *Nhánh 1 (Rule Engine):* Thực thi các quy tắc xác định thuộc 5 nhóm quy tắc lõi, phân loại từng bản ghi thành các kết quả loại trừ lẫn nhau: `passed`, `failed`, `missing`, `miscast`, `not_applicable`.
   - *Nhánh 2 (IQR Outlier Detector):* Tính toán tứ phân vị ($Q1, Q3, IQR$) trên các cột số mục tiêu và gắn cờ các giá trị nằm ngoài $[Q1 - 1.5 \cdot IQR, Q3 + 1.5 \cdot IQR]$.
4. **Chuẩn hóa Kết quả:** Hợp nhất toàn bộ kết quả kiểm tra thành tập `Canonical Quality Results` có cấu trúc đồng nhất và gắn vết mã băm cấu hình.
5. **Tổng hợp Điểm số và Đánh giá Cổng chất lượng:**
   - Tính toán Rule Scores dựa trên mẫu số hợp lệ theo `null_policy`.
   - Tạo đúng 6 Dimension Results; chiều không áp dụng hoặc không đo được có score `null`, không bị ép thành 0.
   - Tính DQ Score tái chuẩn hóa trên các chiều `MEASURED` và công bố chỉ số Độ bao phủ (Coverage) độc lập.
   - Với Run hợp lệ, đánh giá Cổng Chất lượng (Quality Gate) trong bộ nhớ theo thứ tự ưu tiên 6 cấp bậc: (1) `ERROR` (phát sinh lỗi kỹ thuật `FAILED_TO_MEASURE` trên quy tắc bắt buộc trong Run đã hoàn tất) $\rightarrow$ (2) Critical `FAIL` (có quy tắc sống còn bị vi phạm) $\rightarrow$ (3) `INSUFFICIENT_EVIDENCE` (Coverage < 80% hoặc thiếu phép đo bắt buộc) $\rightarrow$ (4) `FAIL` (DQ Score < 60) $\rightarrow$ (5) `WARN` (60 $\le$ DQ Score < 80) $\rightarrow$ (6) `PASS` (DQ Score $\ge$ 80). Run gặp lỗi hạ tầng kỹ thuật (`FAILED`) không tạo Assessment hay Gate.
6. **Công bố Bản đánh giá Nguyên tử (Atomic Publication):** Lưu trữ đồng thời `Immutable Assessment`, Dimension Results, Canonical Results, Publication Event và cập nhật trạng thái Run sang `SUCCEEDED` trong một giao dịch cơ sở dữ liệu PostgreSQL duy nhất có kiểm tra quyền Lease Fencing; kết quả sẵn sàng phục vụ truy vấn qua API Gateway và trực quan hóa trên Dashboard.

---

### 1.4. Kịch bản đo lường tham chiếu và Xử lý Ca biên (Boundary Semantics)

Dựa trên kịch bản dữ liệu giao thông đô thị và các tập dữ liệu lớn (4–10 triệu dòng):
- **Phân loại mẫu số (Denominator Invariant):** Điểm quy tắc được tính bằng tỷ lệ số bản ghi đạt trên số bản ghi *đủ điều kiện đo lường* (records in scope).
- **Quy tắc Null Policy:**
  - `fail`: Bản ghi missing/null bị tính là vi phạm (`failed`).
  - `ignore`: Bỏ qua bản ghi missing khỏi mẫu số (chuyển sang `not_applicable`).
  - `separate`: Báo cáo tỷ lệ missing riêng biệt.
  - `not_applicable`: Bản ghi không thuộc phạm vi kiểm tra không đóng góp vào mẫu số.
- **Xử lý Mẫu số bằng 0 (Zero Denominator):** Khi không có bản ghi nào đủ điều kiện đo, quy tắc trả về trạng thái `NOT_APPLICABLE` hoặc `NOT_MEASURABLE`, **tuyệt đối không tự động gán điểm 0 hoặc điểm 100**.
- **Cách ly Lỗi hệ thống:** Lỗi đọc Snapshot, hỏng kết nối CSDL, lỗi phân giải hạ tầng trong Profiling hoặc Scoring cốt lõi làm Run `FAILED` với `EXECUTION_ERROR` và không tạo Assessment. Riêng lỗi Outlier Detector sinh tín hiệu cảnh báo (`ADVISORY`) với trạng thái `FAILED_TO_MEASURE` trọng số 0; Rule Results và Assessment vẫn được công bố bình thường.

---

### 1.5. Lựa chọn Mô hình DQ cho Hệ thống

Khảo sát 4 mô hình giải pháp Data Quality phổ biến trên thị trường:

| Mô hình | Đặc điểm & Năng lực chính | Mức độ phù hợp với đề tài |
| :--- | :--- | :--- |
| **1. Data Profiling** | Khám phá cấu trúc, phân phối, kiểu dữ liệu, null rate | Cần thiết làm tầng nền (Compute Layer) nhưng chưa đủ để kết luận chất lượng |
| **2. Data Validation & Scoring** | Kiểm tra theo kỳ vọng (Expectations), tính điểm và đánh giá Quality Gate | **Trọng tâm cốt lõi của đề tài** |
| **3. Data Cleansing & Remediation** | Tự động sửa, chuẩn hóa hoặc xóa bản ghi lỗi | **Nằm ngoài phạm vi** (tránh rủi ro làm biến dạng dữ liệu nghiệp vụ) |
| **4. Data Monitoring & Observability** | Giám sát streaming liên tục, quản lý cảnh báo, incident ticket | Phạm vi mở rộng sau v1.0 |

**Mô hình được lựa chọn:** **Hybrid Data Validation & Scoring** (Kết hợp Kiểm tra Quy tắc Xác định và Phát hiện Ngoại lệ Thống kê).
- *Rule Engine (P0):* Kiểm tra các kỳ vọng xác định đã biết trước.
- *IQR Outlier Detector (P0 Advisory):* Phát hiện bất thường phân phối trên cột số; đóng vai trò cảnh báo (`ADVISORY`), có trọng số đóng góp bằng 0 và không làm thay đổi DQ Score hay Quality Gate trong v1.0 nhằm đảm bảo an toàn tuyệt đối.

---

### 1.6. Sáu Chiều Chất lượng Dữ liệu trong v1.0

Hệ thống áp dụng 6 chiều chất lượng chuẩn mực:

```
                  ┌──────────────────────────────────────────────┐
                  │          6 CHIỀU CHẤT LƯỢNG DỮ LIỆU          │
                  └──────────────────────┬───────────────────────┘
         ┌──────────────────┬────────────┴───────┬──────────────────┐
         ▼                  ▼                    ▼                  ▼
  ┌──────────────┐   ┌──────────────┐     ┌──────────────┐   ┌──────────────┐
  │ Completeness │   │   Validity   │     │  Uniqueness  │   │ Consistency  │
  │ (Tính đầy đủ)│   │(Tính hợp lệ) │     │(Tính duy nhất│   │(Tính nhất    │
  └──────────────┘   └──────────────┘     └──────────────┘   │    quán)     │
         ▲                                                   └──────────────┘
         │                  ┌──────────────┐     ┌──────────────┐   ▲
         └──────────────────┤  Timeliness  │     │   Accuracy   │───┘
                            │(Tính kịp thời│     │(Độ chính xác │
                            │   / tươi mới)│     │    Proxy)    │
                            └──────────────┘     └──────────────┘
```

1. **Completeness (Tính đầy đủ):** Đánh giá mức độ thiếu hụt dữ liệu (Null / Blank checks trên các trường bắt buộc).
2. **Validity (Tính hợp lệ):** Đánh giá việc tuân thủ định dạng, kiểu dữ liệu, biểu thức chính quy (Regex) và miền giá trị (Domain/Range).
3. **Uniqueness (Tính duy nhất):** Đánh giá tính không trùng lặp của khóa chính đơn cột hoặc tổ hợp khóa (Composite Key).
4. **Consistency (Tính nhất quán):** Đánh giá ràng buộc logic chéo giữa các cột trong cùng bản ghi (Cross-field Comparison, ví dụ: `dropoff_time >= pickup_time`).
5. **Timeliness (Tính kịp thời / Tươi mới):** Đánh giá độ trễ dữ liệu hoặc khoảng thời gian từ lúc phát sinh đến lúc đánh giá (Freshness/Latency checks).
6. **Accuracy Proxy (Tính chính xác đại diện):** Đánh giá tính hợp lý nội tại của dữ liệu (Plausibility checks) khi chưa có nguồn dữ liệu đối chuẩn bên ngoài (Ground Truth).

Sáu chiều trên là taxonomy của sản phẩm. Hệ thống định nghĩa nghiêm ngặt và duy nhất 6 chiều chất lượng dữ liệu nói trên bám sát khung chuẩn DAMA DMBOK2 và ISO/IEC 25012; tuyệt đối không mở rộng hay định nghĩa thêm bất kỳ chiều chất lượng thứ 7 nào ngoài chuẩn này. Chiều có rule hợp lệ mang `MEASURED`; chiều được policy xác nhận không áp dụng mang `NOT_APPLICABLE` và bị loại khỏi denominator; chiều policy yêu cầu nhưng thiếu reference/SLA/metadata mang `NOT_MEASURABLE`, score `null` và làm giảm Coverage.

---

### 1.7. Mục tiêu của Hệ thống

#### 1.7.1. Mục tiêu Nghiệp vụ (Business Goals)
- **BG-001:** Chuẩn hóa phương pháp đánh giá chất lượng giữa các tập dữ liệu khác nhau.
- **BG-002:** Tự động hóa hoàn toàn quy trình lập hồ sơ, kiểm tra và tính điểm, loại bỏ thao tác thủ công.
- **BG-003:** Hỗ trợ người dùng ra quyết định sử dụng dữ liệu dựa trên Scorecard minh bạch.
- **BG-004:** Truy vết được kết luận điểm số đến từng snapshot, cấu hình và bằng chứng cụ thể.
- **BG-005:** Phân biệt rõ ràng lỗi dữ liệu, thiếu bằng chứng đo lường và lỗi thực thi hệ thống.
- **BG-006:** Phát hiện đồng thời lỗi vi phạm quy tắc xác định và các tín hiệu ngoại lệ thống kê.
- **BG-007:** Cung cấp giao diện trực quan hóa Scorecard phục vụ nghiệm thu và demo cục bộ.
- **BG-008:** Đảm bảo tính tái lập (Reproducibility): cùng dữ liệu và cấu hình luôn tạo ra cùng kết quả.

---

### 1.8. Bên liên quan (Stakeholders) và Tác nhân (Actors)

#### 1.8.1. Ma trận Stakeholders

| Stakeholder | Nhu cầu chính | Quyền hạn và Trách nhiệm | Mức ảnh hưởng |
| :--- | :--- | :--- | :--- |
| **Data Engineer** | Chạy đánh giá tự động trong pipeline; kiểm tra tính toàn vẹn | Vận hành run, cấu hình snapshot, theo dõi lỗi | Rất cao (Cốt lõi) |
| **Data Owner** | Phê duyệt tiêu chí, ngưỡng chất lượng và chịu trách nhiệm cuối về mức chất lượng chấp nhận được | Phê duyệt Ruleset, Critical Rules và Scoring Policy trước khi đưa vào Run | Rất cao (Cốt lõi) |
| **Data Steward** | Soạn thảo quy tắc, theo dõi Coverage và kết quả chưa xử lý, đề xuất Baseline | Khai báo Ruleset, Null Policy, trọng số; submit cấu hình để Data Owner phê duyệt | Rất cao (Cốt lõi) |
| **Dataset Consumer** | Hiểu chất lượng dữ liệu trước khi mua hoặc tích hợp | Đọc Scorecard, xem độ bao phủ và cảnh báo | Cao (Persona tham chiếu) |
| **Domain Expert** | Thẩm định các tín hiệu ngoại lệ bất thường | Xác nhận quy tắc nghiệp vụ và ý nghĩa dị biệt | Trung bình (Tư vấn) |
| **Project Owner / Mentor** | Đánh giá tính đúng đắn khoa học và nghiệm thu đồ án | Phê duyệt Baseline tài liệu và kết quả kiểm chứng | Tối cao |

#### 1.8.2. Danh mục Tác nhân trực tiếp (Actor Catalog)

| Mã Actor | Tên Actor | Loại Actor | Vai trò tương tác trong v1.0 |
| :--- | :--- | :--- | :--- |
| **ACT-H-001** | Data Engineer (Local Operator) | Con người (Chính) | Đăng ký dataset, cấu hình run, kích hoạt đánh giá và xem kết quả |
| **ACT-H-002** | Data Owner | Con người (Chính) | Phê duyệt Ruleset, Critical Rules và Scoring Policy; chịu trách nhiệm cuối về mức chất lượng chấp nhận được |
| **ACT-H-003** | Data Steward | Con người (Chính) | Soạn thảo Ruleset, cấu hình Null Policy, gán trọng số, theo dõi Coverage; submit cấu hình để Owner phê duyệt |
| **ACT-H-004** | Dataset Consumer | Con người (Phụ) | Đọc Scorecard và drill-down bằng chứng vi phạm trên Dashboard |
| **ACT-H-005** | Domain Expert | Con người (Tư vấn) | Thẩm định tín hiệu Outlier IQR advisory theo góc độ nghiệp vụ |
| **ACT-S-001** | Data Source Provider | Hệ thống ngoài | Cung cấp file CSV/Parquet nguồn và metadata |

*(Lưu ý: Hệ thống DQ Scoring là đối tượng được xây dựng, không tự đóng vai trò Actor của chính nó).*

---

### 1.9. Các trường hợp sử dụng nghiệp vụ chính (Business Use Cases)

| Mã BUC | Tên trường hợp sử dụng | Tác nhân chính | Mục tiêu đạt được |
| :--- | :--- | :--- | :--- |
| **BUC-001** | Đăng ký Data Asset và Khởi tạo Snapshot | Data Engineer / Operator | Tiếp nhận tệp CSV/Parquet, tính SHA-256, trích xuất schema tự động qua Spark trên k3s và lưu trữ snapshot bất biến cùng metadata PostgreSQL 16 |
| **BUC-002** | Soạn thảo Ruleset và Scoring Policy (Draft) | Data Steward | Khai báo quy tắc, Null Policy, trọng số, gate conditions; lưu cấu hình ở trạng thái DRAFT có hash định danh |
| **BUC-003** | Phê duyệt Ruleset và Scoring Policy (Approve) | Data Owner | Xem xét và phê duyệt độc lập RulesetRevision và ScoringPolicyRevision; chuyển sang trạng thái ACTIVE |
| **BUC-004** | Khởi tạo và Thực thi Lượt Đánh giá Bất đồng bộ | Data Engineer / Operator | Quản lý vòng đời async qua hàng đợi PostgreSQL 16; worker claim lease, profiling, validation, outlier và công bố kết quả nguyên tử |
| **BUC-005** | Tổng hợp Điểm số và Đánh giá Cổng chất lượng | Hệ thống (Tự động trong BUC-004) | Tính Rule/Dimension/DQ Score, Coverage và Quality Gate theo thứ tự ưu tiên nghiêm ngặt (bước SEQ-007 nội bộ trong UC-005) |
| **BUC-006** | Xem Scorecard và Drill-down Bằng chứng | Dataset Consumer / Operator | Hiển thị điểm số tổng hợp từ PostgreSQL 16, chi tiết 6 chiều chất lượng và dòng lỗi mẫu che mờ (Bounded Evidence) |
| **BUC-007** | Xem và Thẩm định Tín hiệu Ngoại lệ IQR (Advisory) | Data Steward / Domain Expert | Xem xét và thẩm định các giá trị số dị biệt do thuật toán Tukey IQR phát hiện ở chế độ cảnh báo |
| **BUC-008** | Xuất Báo cáo Đánh giá (Assessment Export) | Data Engineer / Operator | Xuất kết quả đánh giá bất biến ra JSON Canonical / Markdown Summary phục vụ lưu trữ và tích hợp |

---

### 1.10. Phạm vi Hệ thống v1.0

#### 1.10.1. Nằm trong Phạm vi v1.0 (In-Scope)
- Hỗ trợ dữ liệu bảng dạng tệp **CSV (UTF-8)**, **Apache Parquet** và bảng **Delta Lake** (truy cập chế độ chỉ đọc snapshot).
- Xử lý Batch Snapshot qua runtime bất đồng bộ với PostgreSQL 16 làm cơ sở dữ liệu bền vững (durable store); mô hình tiến trình phân tách giữa API Gateway và Worker execution.
- Động cơ đo lường chuẩn hóa: **Apache Spark trên cụm k3s đơn nút (Single-Node k3s)** thực thi vectorization và pushdown query trực tiếp trên snapshot, quản lý vòng đời đo lường thông qua `SparkApplication` và cổng trừu tượng `IComputeEnginePort`; phân tách rạch ròi giữa Control Plane (Worker điều phối) và Compute Plane (Spark tính toán).
- Đăng ký Data Asset và Dataset Snapshot bất biến: hỗ trợ tập dữ liệu đơn tệp hoặc nhiều tệp gốc (multi-file raw snapshot) kèm file manifest JSON liệt kê đường dẫn, kích thước, định dạng và mã băm SHA-256 từng tệp; bảo toàn nguyên vẹn 100% byte dữ liệu nguồn, tuyệt đối không can thiệp sửa đổi, coalesce hay chuyển đổi định dạng dữ liệu gốc trước khi đánh giá.
- Tự động Profiling dữ liệu tính `Canonical Metrics` dùng chung một lần duy nhất.
- Thực thi Rule Engine với 5 nhóm quy tắc xác định lõi (P0).
- Thực thi IQR Outlier Detector đơn biến trên cột số ở chế độ cảnh báo (`ADVISORY`), trọng số 0.
- Chuẩn hóa đầu ra thành `Canonical Quality Results` gắn mã băm cấu hình.
- Tạo Rule Scores, đúng 6 Dimension Results với score nullable, DQ Score, Coverage và Quality Gate theo 6 cấp bậc ưu tiên.
- Đóng gói `Immutable Assessment` nguyên tử gắn cứng các mã băm cấu hình và cam kết giao dịch PostgreSQL duy nhất do Worker công bố sau khi đối soát lease fencing.
- Cung cấp REST API Gateway (FastAPI) và giao diện Dashboard (Streamlit) để tiếp nhận, theo dõi, hủy và trực quan hóa kết quả Evaluation Run bất đồng bộ.
- Quản lý vòng đời lượt chạy `QUEUED → LEASED → RUNNING → SUCCEEDED/FAILED/CANCELLED`, cơ chế khóa fencing chống xung đột ghi đè, kiểm tra tín hiệu duy trì hoạt động (heartbeat watchdog), tự động khôi phục lease, bounded retry và xử lý yêu cầu trùng lặp (idempotency per tenant).
- Khống chế trần tài nguyên trên nút tham chiếu cơ sở: **Tối đa 8 GB RAM cho toàn bộ nút k3s** (~3 GB cho OS/k3s/PostgreSQL/MinIO/API/Worker, ~4 GB cho SparkApplication driver + executor + JVM overhead, ~1 GB dự phòng hệ thống). Hỗ trợ tối đa **1 Spark run tích cực tại một thời điểm** trên profile này; các run tiếp theo xếp hàng trong PostgreSQL.
- Cơ chế bảo vệ dữ liệu nhạy cảm hai tầng: Tầng 1 che mờ PII tại nguồn trước khi ghi CSDL (`EvidenceRedactor`) và Tầng 2 che mờ động theo quyền khi truy xuất (`SensitiveDataMasker`).
- Kiến trúc Đa thuê bao phân lập dữ liệu (Shared-Schema Multi-Tenancy) với khóa ngoại ghép `(tenant_id, id)` và namespace cô lập cho Data Marketplace.
- Bộ kiểm chứng Golden Datasets và Kế hoạch Benchmark đo đạc tài nguyên thực tế.

#### 1.10.2. Nằm ngoài Phạm vi v1.0 (Out-of-Scope)
- Tự động sửa, xóa hoặc làm sạch dữ liệu nguồn (Data Cleansing/Remediation) nhằm bảo vệ tính nguyên vẹn của dữ liệu gốc.
- Tự ý coalesce/compact làm biến đổi cấu trúc hoặc định dạng các tệp nguồn trong snapshot gốc.
- Nền tảng quản trị dòng dữ liệu đồ thị chuyên sâu (Data Lineage Graph Engine) và hệ thống tạo vé sự cố (Incident Management System).
- Xử lý dữ liệu luồng thời gian thực (Real-time Streaming Ingestion).
- Đánh giá dữ liệu phi cấu trúc (Hình ảnh, Âm thanh, Video, Văn bản tự do).
- AI/LLM tự ý sửa điểm, đổi rule hoặc can thiệp phán quyết Quality Gate (LLM chỉ hỗ trợ dưới dạng Trợ lý Cố vấn - LLM Advisory gợi ý cấu hình mẫu và giải thích lỗi, mọi cấu hình phải do con người phê duyệt).
- Tích hợp đồng bộ hai chiều trực tiếp với các Data Catalog thương mại độc quyền (các cổng tích hợp bên ngoài được thiết kế qua cổng trừu tượng Outbox/Connector).
- Hàng đợi phân tán phụ thuộc nặng (Kafka, RabbitMQ, Celery); cơ chế hàng đợi bền vững trên PostgreSQL 16 (`FOR UPDATE SKIP LOCKED`) là cấu hình chuẩn mực của hệ thống.
- Tự động trừ điểm từ Outlier hoặc Drift (tính năng giám sát phân phối Drift chuyển sang giai đoạn mở rộng).
- Cụm phân tán nhiều nút vật lý và tự động co giãn đa lane KEDA (chuyển sang profile mở rộng doanh nghiệp trong tương lai).

---

### 1.11. Danh mục Năng lực cần xây dựng (Capabilities)

| Mã | Tên năng lực | Input chính | Output chính | Mức ưu tiên |
| :--- | :--- | :--- | :--- | :--- |
| **CAP-001** | Dataset Store & Registry | File CSV/Parquet, Delta snapshot, manifest JSON | Snapshot bất biến, SHA-256 từng tệp, Detected Schema | P0 (Bắt buộc) |
| **CAP-002** | Snapshot Profiler | Dataset Snapshot nguyên bản | Canonical Metrics (row count, nulls, distincts, min/max) | P0 (Bắt buộc) |
| **CAP-003** | Deterministic Rule Engine | Snapshot nguyên bản, Ruleset, Null Policy | Rule Results (passed, failed, missing, miscast, not_applicable) | P0 (Bắt buộc) |
| **CAP-004** | IQR Outlier Detector | Snapshot nguyên bản, Numeric Columns, $k=1.5$ | Outlier Signals, Bounds, Affected counts (Advisory) | P0 (Advisory) |
| **CAP-005** | Score Engine | Canonical Quality Results, Policy | DQ Score, 6 Dimension Scores, Coverage, Quality Gate | P0 (Bắt buộc) |
| **CAP-006** | Durable Runtime & Immutable Store | RunSpec, leases, events, results, Config Hashes | Async lifecycle, Fencing và Immutable Assessment Record | P0 (Bắt buộc) |
| **CAP-007** | REST API Gateway & Dashboard | HTTP Commands, Run events, Assessment | Tiếp nhận bất đồng bộ, Scorecard trực quan & Masked Evidence | P0 (Bắt buộc) |
| **CAP-008** | Sensitive Data & Multi-Tenant Guard | Dữ liệu mẫu vi phạm, Tenant context | Redacted Evidence trong CSDL, Masked DTOs theo quyền | P0 (Bắt buộc) |
| **CAP-009** | Governance Catalog Templates & LLM Advisory | Domain templates, prompt, column metadata | Bản mẫu Ruleset/Policy tái sử dụng, gợi ý quy tắc an toàn | P1 (Hỗ trợ) |
| **CAP-010** | Drift & Baseline Detector | Snapshot, Approved Baseline | Data Drift Signals, phân tích lệch phân phối | Post-1.0 |

---

### 1.12. Khóa 13 Quyết định Phạm vi Cốt lõi (Scope Decisions)

Dựa trên quá trình rà soát phạm vi, 13 quyết định sau được chốt chính thức cho hệ thống:

1. **Mô hình trách nhiệm:** Dự án được thực hiện bởi Project Owner (`Nguyễn Hoàng Tùng`) và thẩm định bởi Mentor / Hội đồng; các quyết định v1.0 là approved baseline cho hồ sơ đặc tả kiến trúc trước khi bước vào giai đoạn cài đặt mã nguồn.
2. **Tập dữ liệu Vertical Slice:** Sử dụng lát cắt tháng 01/2023 từ *City of Chicago Taxi Trips 2023* (chứa đầy đủ định danh, timestamps, tọa độ khu vực và trường tiền tệ).
3. **Giới hạn quy mô xử lý & Ngân sách tài nguyên cơ sở:** Cụm k3s đơn nút được thiết kế trong trần tối đa **8 GB RAM toàn nút** (~3 GB cho OS/k3s/PostgreSQL/MinIO/API/Worker, ~4 GB cho SparkApplication driver+executor bao gồm JVM overhead, ~1 GB dự phòng hệ thống chống OOM). Hỗ trợ tối đa **1 SparkApplication chạy tích cực tại một thời điểm**, các lượt chạy tiếp theo xếp hàng trong PostgreSQL. Vertical slice (khoảng 100.000 dòng) làm chuẩn đo kiểm để xác lập baseline hiệu năng.
4. **Quy tắc tính điểm mặc định:** Sử dụng trung bình cộng có trọng số (Weighted Arithmetic Mean). Điểm chất lượng chỉ được công bố (`PUBLISHED`) khi Run hợp lệ và Độ bao phủ (Coverage) $\ge 80\%$.
5. **Thứ tự ưu tiên Quality Gate:** Với Run hợp lệ, đánh giá Cổng Chất lượng theo 6 cấp bậc nghiêm ngặt: (1) `ERROR` (lỗi kỹ thuật `FAILED_TO_MEASURE` trên quy tắc bắt buộc trong Run đã hoàn tất) $\rightarrow$ (2) Critical `FAIL` (quy tắc critical vi phạm) $\rightarrow$ (3) `INSUFFICIENT_EVIDENCE` (Coverage < 80% hoặc thiếu phép đo bắt buộc) $\rightarrow$ (4) `FAIL` (Điểm < 60) $\rightarrow$ (5) `WARN` (60 $\le$ Điểm < 80) $\rightarrow$ (6) `PASS` (Điểm $\ge$ 80). Run lỗi kỹ thuật hệ thống (`FAILED`) không tạo Assessment hay Gate; Assessment `WITHHELD` vẫn được lưu bền vững với `dq_score = null` khi Run đã hoàn tất nhưng không đủ điều kiện công bố điểm.
6. **Định nghĩa SLA End-to-End và Benchmark:** Thời gian xử lý được đo lường End-to-End từ khi API tiếp nhận yêu cầu hợp lệ (`202 Accepted`) đến khi Assessment được tính điểm, ghi nhận bền vững và chính thức công bố (`PUBLISHED`), bao gồm: thời gian chờ hàng đợi (Queue Wait), thời gian khởi tạo Pod Spark (Pod Startup 10–25s), đọc snapshot, tính toán, và ghi nhận kết quả nguyên tử. Các mốc thời gian thiết kế (như mục tiêu $\le 120$s cho 100.000 dòng) là giả thuyết/mục tiêu thiết kế cần đo kiểm thực tế qua Benchmark Test trên môi trường chuẩn 8 GB RAM, không phải cam kết nghiệm thu cứng trước khi đo kiểm.
7. **Năm nhóm quy tắc xác định lõi:** (1) Required/Non-null, (2) Type/Parse, (3) Domain/Range, (4) Uniqueness, (5) Simple Cross-field.
8. **Ranh giới an toàn cho Outlier:** IQR Outlier Detector chạy đơn biến trên cột số, kết quả mang tính cảnh báo (`ADVISORY`), trọng số đóng góp bằng 0 và không làm đổi DQ Score hay phán quyết Quality Gate.
9. **Quản lý Bằng chứng (Two-Tier Evidence Protection):** Bằng chứng dòng lỗi bị giới hạn tối đa 10–50 dòng mẫu (bounded) và che mờ dữ liệu nhạy cảm trước khi ghi CSDL (`EvidenceRedactor`); hiển thị che mờ động theo quyền người dùng (`SensitiveDataMasker`). Thư mục quét tạm thời được dọn dẹp tự động sau lượt chạy.
10. **Bảo toàn Dữ liệu Nguồn và Phân định Rạch ròi Worker – Spark:** Dataset Snapshot trỏ trực tiếp đến các tệp dữ liệu gốc bất biến (hỗ trợ nhiều tệp gốc kèm manifest JSON, tuyệt đối không coalesce/compact làm đổi tệp gốc). Spark chỉ được cấp quyền đọc snapshot (Read-Only) để profiling, validation và scoring; Spark ghi kết quả và evidence vào vùng artifacts riêng. Chỉ Worker điều phối mới có quyền thẩm tra lease fencing và thực hiện giao dịch ghi nguyên tử công bố Assessment vào PostgreSQL 16.
11. **Điều phối bất đồng bộ và Chống ghi đè (Lease Fencing):** API tiếp nhận kiểm thực và đưa vào hàng đợi có kiểm soát trùng lặp (idempotency); Worker nhận lease, duy trì tín hiệu hoạt động (heartbeat), thực thi có kiểm soát số lần thử lại (bounded retry) và công bố nguyên tử. Worker quá hạn lease bị chặn ghi đè kết quả thông qua cơ chế monotonic lease fencing.
12. **Quản trị Tài liệu Đồng bộ:** Toàn bộ 5 chương tài liệu được lưu trữ trực tiếp dưới dạng Markdown trong thư mục `docs/` của kho mã nguồn, được đánh mã băm toàn vẹn và là nguồn sự thật duy nhất (Single Source of Truth) định hướng cho việc triển khai mã nguồn.
13. **Ranh giới An toàn cho Trợ lý LLM và Kho Mẫu Quy tắc:** Hệ thống hỗ trợ Kho Mẫu Quy tắc và Chính sách tính điểm theo Domain; mô-đun LLM Advisory chỉ đóng vai trò trợ lý hỗ trợ sinh cấu hình và phân tích nguyên nhân lỗi, hoàn toàn cách ly dữ liệu thô (chỉ nhận metadata/schema), không có quyền tự động áp dụng cấu hình hay can thiệp vào điểm số và Quality Gate.

---

### 1.13. Quy trình Phê duyệt Cấu hình (Configuration Approval Workflow)

Vòng đời phê duyệt cấu hình áp dụng cho mọi `RulesetRevision` và `ScoringPolicyRevision`, đảm bảo chỉ cấu hình đã được phê duyệt mới được sử dụng trong Evaluation Run:

```
┌──────────┐   submit(Steward)   ┌──────────┐   approve(Owner)   ┌──────────┐
│  DRAFT   │ ─────────────────→  │  DRAFT   │ ──────────────────→ │  ACTIVE  │
│ (Steward │                     │ (chờ     │                      │ (dùng    │
│  soạn)   │                     │  review) │                      │ được cho │
└──────────┘                     └──────────┘                      │  Run)    │
                                      │ reject(Owner)              └────┬─────┘
                                      ↓                                 │ deprecate
                                 DRAFT (ghi                      ┌──────▼─────┐
                                 lý do từ chối)                   │ DEPRECATED │
                                                                  └────────────┘
```

**Trạng thái `RevisionStatus`:**
- `DRAFT`: Cấu hình do Data Steward soạn, chưa được phê duyệt. Không thể gán vào `RunSpec`.
- `ACTIVE`: Cấu hình đã được Data Owner phê duyệt. Sẵn sàng cho Evaluation Run.
- `DEPRECATED`: Cấu hình đã bị thay thế bởi phiên bản mới hơn. Chỉ dùng để tham chiếu lịch sử.

**Quy tắc nghiệp vụ bổ sung:**

- **BR-013:** Ruleset và Scoring Policy phải được Data Owner phê duyệt riêng; `RunSpec` chỉ tham chiếu revision `ACTIVE` và tương thích Snapshot schema.
- **BR-014:** Dù Data Owner và Data Steward là cùng một người trong local prototype, hành động `submit` và `approve` vẫn là hai lệnh riêng với audit timestamp riêng.
- **BR-015:** Dữ liệu nhạy cảm được phân thành 4 nhóm chuẩn hóa: (1) Dữ liệu cá nhân cơ bản, (2) Dữ liệu cá nhân nhạy cảm, (3) Dữ liệu kinh doanh / bí mật nội bộ, (4) Dữ liệu thông thường / phi nhạy cảm; việc phát hiện nhạy cảm là hoạt động gắn nhãn quản trị (Governance Labeling), không tự động coi là lỗi vi phạm chất lượng trừ khi có quy tắc Data Contract cấm rõ ràng.
- **BR-016:** Thực thi cơ chế che mờ hai tầng (Two-Tiered Masking): Toàn bộ mẫu bằng chứng vi phạm lưu trong CSDL metadata phải được che mờ PII trước khi ghi (`EvidenceRedactor`); khi truy vấn qua API/UI, người không liên quan (unprivileged viewer / operator) chỉ được xem số liệu tổng hợp hoặc dữ liệu đã che mờ theo `DataProtectionPolicy`.
- **BR-017:** Điểm DQ Score kỹ thuật cao không có giá trị vượt quyền hay miễn trừ kiểm soát truy cập bảng dữ liệu nguồn trên Lakehouse (Lakehouse IAM/ACLs).
- **BR-018:** Ranh giới Sở hữu Dữ liệu và Cấp quyền Chia sẻ trên Data Marketplace (Marketplace Boundary): Mỗi tài sản, snapshot, ruleset, scoring policy, evaluation run, finding và assessment thuộc quyền sở hữu độc quyền của một Tenant; việc chia sẻ dữ liệu hoặc quyền xem scorecard giữa các bên trên Data Marketplace là hành vi cấp quyền riêng biệt có kiểm soát (Access Grant / Sharing Agreement), tuyệt đối không làm thay đổi ownership và không cho phép truy cập chéo dữ liệu thô, findings hay evidence mẫu.
- **BR-019:** Tính Toàn vẹn Tham chiếu Phân tầng Khóa ghép (Composite Referential Integrity): Mọi liên kết quan hệ phụ thuộc giữa các thực thể con (Run -> Snapshot, Run -> Ruleset, Snapshot -> Asset, Assessment -> Run) bắt buộc phải bảo toàn tính đồng nhất về `tenant_id` thông qua khóa ghép `(tenant_id, id)` ở cấp độ CSDL. Lỗi truyền sai hoặc trộn lẫn ID giữa các tenant phải bị chặn ngay tại tầng ràng buộc CSDL.
- **Lưu ý phạm vi đa tài sản & đa thuê bao:** Hệ thống áp dụng cấu trúc dữ liệu Shared-Schema Multi-Tenancy với khóa ngoại ghép `(tenant_id, id)` và phân lập namespace lưu trữ theo từng tenant, sẵn sàng cho mô hình Data Marketplace.

---

## 2. KẾ HOẠCH HỒ SƠ VÀ CÁC CHƯƠNG TIẾP THEO

| Mã hồ sơ | Tên chương tài liệu | Nội dung trọng tâm | Quan hệ phụ thuộc |
| :--- | :--- | :--- | :--- |
| **AD-001** | **Chương 1: Khảo sát bối cảnh và xác định phạm vi hệ thống** | Bài toán, bối cảnh, 6 chiều DQ, BUC-001..BUC-008, 13 quyết định, quy tắc BR-001..019 | Điểm khởi đầu |
| **AD-002** | **Phân tích Tác nhân & Business Use Cases** | 8 Business Use Cases, stakeholder và actor catalogs | Hỗ trợ Chương 1–2 |
| **AD-003** | **Chương 2: Đặc tả yêu cầu hệ thống (SRS)** | 114 yêu cầu kỹ thuật (27 IF, 64 FR, 23 NFR), 27 DR, 19 BR, 25 AC và ma trận truy vết 2 chiều | Sau Chương 1 và AD-002 |
| **AD-004** | **Chương 3: Phân tích và mô hình hóa hệ thống** | 8 Use Case Specs, Analysis Class Model (Tenant Lớp 0), 10 Sequence Diagrams, 3 State Machines | Sau Chương 2 |
| **AD-009** | **Chương 4: Kiến trúc hệ thống và thiết kế phần mềm** | Kiến trúc Hexagonal, Apache Spark on k3s làm compute engine chuẩn hóa, PostgreSQL 16 durable multi-tenant store, 8 packages, 7 modules | Sau Chương 2, 3 |
| **AD-005** | **Chương 5: Thiết kế dữ liệu và mô hình lớp chi tiết** | Thực thể đa thuê bao, khóa ghép (tenant_id, id), PostgreSQL 16 DDL, RLS, JSON Schemas và canonical hashing | Sau Chương 2, 3, 4 |

---
*(Hết nội dung Chương 1 — Phiên bản 1.7 Review Candidate)*

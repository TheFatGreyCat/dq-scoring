# PROJECT BRIEF — DQ SCORING SYSTEM

**Mã bằng chứng:** EVD-INT-001  
**Mã hồ sơ:** BRIEF-DQ  
**Phiên bản:** 1.2 (Enterprise Centralized Multi-Tenant Baseline)  
**Ngày cập nhật:** 2026-09-23  
**Trạng thái:** Approved Architecture Specification  
**Project Owner / Technical Lead:** `Nguyễn Hoàng Tùng`  
**Requirements Reviewer / Approver:** `Hội đồng Thẩm định Kỹ thuật Doanh nghiệp`  

Tài liệu này xác định tầm nhìn sản phẩm, mô hình triển khai vận hành tập trung, phân định ranh giới đa thuê bao (multi-tenant), luồng tích hợp đầu vào/đầu ra, phạm vi phát hành v1.0, các bất biến kỹ thuật và tiêu chí nghiệm thu sản xuất. Brief là văn kiện pháp lý kỹ thuật và bằng chứng nghiệp vụ cốt lõi `EVD-INT-001` làm kim chỉ nam đồng bộ cho toàn bộ bộ hồ sơ đặc tả (Chương 1 đến Chương 5, INFRASTRUCTURE_DESIGN và AD-012).

---

## 1. TỔNG QUAN DỰ ÁN & MÔ HÌNH VẬN HÀNH (PROJECT OVERVIEW & OPERATING MODEL)

### 1.1. Sản phẩm cần xây dựng & Mô hình Vận hành Nền tảng Tập trung

**DQ Scoring System** là một **Nền tảng Đánh giá & Quản trị Chất lượng Dữ liệu Tập trung Đa Thuê bao (Centrally Operated Shared Multi-Tenant Data Quality Platform)**. Nền tảng được triển khai và vận hành tập trung bởi tổ chức chủ quản, phục vụ nhiều khách hàng / doanh nghiệp đối tác (Tenants) sử dụng chung hạ tầng một cách an toàn và độc lập tuyệt đối:

1. **Quản trị Tập trung Kết quả Đánh giá (Centralized Result Management):** Toàn bộ kết quả đo lường chất lượng, bảng điểm 6 chiều, cổng chất lượng (`Quality Gate`), chỉ số thống kê (`Canonical Metrics`), dữ liệu kiểm toán và mẫu bằng chứng vi phạm đã được khống chế/che mờ (`Bounded & Redacted Evidence`) của mọi khách hàng được lưu trữ, bảo vệ và quản trị tập trung tại cơ sở dữ liệu bền vững PostgreSQL 16 của nền tảng với tính bất biến tuyệt đối (`Immutable Assessment Store`).
2. **Nền tảng Dùng chung nhưng Cách ly Tuyệt đối (Shared Platform with Zero-Trust Multi-Tenancy):** Các khách hàng dùng chung cụm dịch vụ tính toán và lưu trữ, nhưng mọi dữ liệu, cấu hình ruleset, snapshot và bản đánh giá đều bị cô lập nghiêm ngặt qua 3 tầng phòng vệ:
   - *Tầng Lưu trữ Đối tượng:* Tiền tố phân vùng riêng biệt trong Object Storage (`staging/{tenant_id}/...`, `snapshots/{tenant_id}/...`).
   - *Tầng Cơ sở dữ liệu:* Ràng buộc khóa ngoại ghép `(tenant_id, id)` kết hợp cơ chế Row-Level Security (PostgreSQL 16 RLS) cưỡng chế tự động theo phiên làm việc (`app.current_tenant_id`).
   - *Tầng Giao diện & Điều phối:* Ngữ cảnh xác thực đa nhân tố (`AuthContext`), chặn đứng 100% tấn công chiếm quyền đối tượng chéo tổ chức (Anti-BOLA / OWASP API1:2023).
3. **Mô hình Tích hợp Gọn nhẹ & Rõ ràng (Streamlined Ingestion & Consumption Contracts):**
   - **Tích hợp Đầu vào (Input Contract):** Khách hàng tích hợp dữ liệu nguồn vào hệ thống thông qua hai phương thức chuẩn hóa:
     - *Nguồn Tham chiếu Ngoài (External Descriptor):* Cung cấp URI/Descriptor trỏ tới kho lưu trữ chỉ đọc của khách hàng (S3/MinIO bucket hoặc tệp Parquet/Delta) kèm mã băm SHA-256 xác thực toàn vẹn.
     - *Nguồn Snapshot Quản trị bởi Nền tảng (Platform-Managed Snapshot):* Tải tệp nguồn lên bucket staging của nền tảng qua Presigned URL, hệ thống kiểm tra SHA-256 và thăng cấp vào kho snapshot bất biến phục vụ khả năng tái lập (Replayability).
   - **Tích hợp Đầu ra (Output Contract):** Khách hàng khai thác kết quả đánh giá qua hai kênh chính:
     - *Bảng điều khiển Trực quan (Unified Web Dashboard):* Phục vụ người dùng nghiệp vụ và kỹ thuật theo dõi vòng đời lượt chạy (Live Run Monitor), Bảng điểm Scorecard đa chiều, cảnh báo ngoại lệ IQR, và điều tra drill-down bằng chứng lỗi.
     - *Cổng REST API Gateway:* Phục vụ các hệ thống điều phối dữ liệu doanh nghiệp (Airflow, Dagster, ETL pipelines) tự động kích hoạt đánh giá, tra cứu trạng thái và nhận kết quả JSON chuẩn hóa.

### 1.2. Vấn đề thực tế cần giải quyết trong Môi trường Doanh nghiệp

Trong môi trường tích hợp doanh nghiệp và chia sẻ dữ liệu đa bên, việc thiếu một cơ chế đánh giá tập trung, độc lập và minh bạch dẫn đến 5 rủi ro cốt lõi:
1. *Thiếu Tiêu chuẩn Đo lường Thống nhất:* Mỗi bộ phận hoặc đối tác đánh giá chất lượng bằng công cụ rời rạc, không thể so sánh và đối chuẩn chéo giữa các tài sản dữ liệu.
2. *Không Thể Giải thích Nguồn gốc Điểm số:* Điểm chất lượng thường là con số chung chung, không chứng minh được công thức, trọng số và bằng chứng thực tế vi phạm ở cấp độ bản ghi.
3. *Mập mờ giữa Lỗi Dữ liệu và Lỗi Hệ thống:* Khi một quy tắc không thể đo lường (thiếu cột, sai định dạng schema), hệ thống thông thường gán điểm 0 hoặc làm sập đường ống, gây sai lệch nghiêm trọng báo cáo chất lượng.
4. *Nguy cơ Rò rỉ Dữ liệu Nhạy cảm (PII Leakage):* Việc trích xuất mẫu lỗi phục vụ gỡ lỗi thường làm lộ dữ liệu cá nhân, thông tin định danh của khách hàng ra môi trường ghi nhật ký hoặc giao diện người dùng.
5. *Rủi ro Rò rỉ Dữ liệu Chéo Khách hàng (Cross-Tenant Leakage):* Khi vận hành trên nền tảng dùng chung, nguy cơ một khách hàng đọc được siêu dữ liệu, quy tắc nghiệp vụ hoặc mẫu dữ liệu của khách hàng khác là lỗ hổng an ninh mức thảm họa.

Hệ thống DQ Scoring v1.0 giải quyết dứt điểm các rủi ro trên bằng mô hình toán học bất biến, kiến trúc phòng thủ đa tầng và quy trình đánh giá khép kín từ Snapshot đến Immutable Assessment.

### 1.3. Bảng thuật ngữ chuẩn hóa (Ubiquitous Language)

| Thuật ngữ | Định nghĩa trong Nền tảng DQ Scoring |
| :--- | :--- |
| **Tenant** | Khách hàng hoặc không gian tổ chức độc lập trên nền tảng, sở hữu định danh UUID duy nhất và ranh giới bảo mật riêng. |
| **Data Asset** | Tài sản dữ liệu logic thuộc sở hữu của một Tenant (ví dụ: `chicago_taxi_trips`). |
| **Dataset Snapshot** | Phiên bản vật lý cụ thể, bất biến của Data Asset, gắn liền với mã băm toàn vẹn SHA-256 của nội dung tệp. |
| **Canonical Metrics** | Tập chỉ số thống kê nền tảng (row count, null rate, distinct count, min/max, quartiles) quét 1 lần qua Apache Spark Profiling trên k3s. |
| **Quality Rule** | Quy tắc kiểm tra kỳ vọng xác định (deterministic expectation) thuộc 1 trong 6 chiều chất lượng chuẩn DAMA/ISO. |
| **Canonical Quality Result** | Kết quả chuẩn hóa từ Rule hoặc Detector, chứa status, 5 số đếm phân hoạch, metric, config hash và bounded evidence. |
| **Scoring Policy** | Chính sách tính điểm: trọng số quy tắc, trọng số chiều, ngưỡng công bố điểm ($\ge 80\%$) và điều kiện Quality Gate. |
| **Độ bao phủ (Coverage)** | Tỷ lệ trọng số các yêu cầu chất lượng đo được thực tế so với tổng phạm vi kỳ vọng trong `RunSpec`. |
| **Cổng chất lượng (Quality Gate)** | Phán quyết dữ liệu của Assessment: `PASS`, `WARN`, `FAIL`, `INSUFFICIENT_EVIDENCE`; Run lỗi hệ thống không sinh Gate. |
| **Giá trị ngoại lệ (IQR Outlier)**| Giá trị số dị biệt theo phân bố Tukey fences ($[Q1 - 1.5 \cdot IQR, Q3 + 1.5 \cdot IQR]$), mang cờ `ADVISORY`, trọng số 0. |
| **Trạng thái công bố (Publication)**| `PUBLISHED` khi Coverage $\ge 80\%$ và không có required rule lỗi; ngược lại `WITHHELD` (điểm bị giữ lại, không công bố). |
| **Bản đánh giá (Assessment)** | Bản ghi kết quả cuối cùng bất biến (Write-Once Read-Many), gắn mã băm toàn vẹn `assessment_hash` và lưu trữ nguyên tử. |

---

## 2. NGƯỜI DÙNG MỤC TIÊU & PHÂN QUYỀN TRÊN NỀN TẢNG (USER PERSONAS & RBAC)

Hệ thống phân định 4 nhóm tác nhân chính tương tác với nền tảng tập trung:
1. **Khách hàng — Kỹ sư Dữ liệu / Tích hợp (Client Data Engineer - ACT-H-001):** Đăng ký tài sản dữ liệu, quản lý snapshot, tích hợp pipeline tự động qua REST API Gateway (`POST /api/v1/runs`), theo dõi tiến độ và nhận kết quả JSON.
2. **Khách hàng — Quản trị viên Dữ liệu (Client Data Steward & Owner - ACT-H-002, ACT-H-003):** Soạn thảo và phê duyệt Ruleset, Scoring Policy, gán trọng số, giám sát Coverage và thẩm định cảnh báo ngoại lệ IQR.
3. **Khách hàng — Người xem Báo cáo & Lãnh đạo (Client Business Viewer / Consumer - ACT-H-004):** Xem Scorecard đa chiều trên Web Dashboard, đối chuẩn chất lượng dữ liệu, xem mẫu vi phạm đã che mờ động theo quyền (Dynamic Role-based Redaction).
4. **Tổ chức Vận hành Nền tảng — Kỹ sư Vận hành Hạ tầng (Platform SRE / Operator - ACT-H-006):** Giám sát cụm Worker, hàng đợi PostgreSQL, cụm Spark trên k3s và Object Storage; quản trị cấp phát Tenant và backup/restore. Tuyệt đối không có quyền xem trộm dữ liệu thô của khách hàng (Zero-Trust Administrative Principle).

---

## 3. CÁC TÍNH NĂNG VÀ PHẠM VI HỆ THỐNG (FEATURES & SCOPE)

### 3.1. Tính năng Cốt lõi Bắt buộc — Phiên bản 1.0 (P0 Baseline)

| Mã ID | Tên tính năng | Mô tả chức năng & Ranh giới kỹ thuật trong Mô hình Tập trung |
| :--- | :--- | :--- |
| **MF-001** | Unified Application Facade | Cung cấp Python Facade API (`DQEngineFacade`) làm điểm điều phối nghiệp vụ duy nhất; cô lập hoàn toàn quy tắc nghiệp vụ khỏi các presentation adapters. |
| **MF-002** | Tenant Isolation & Access Guard | Cưỡng chế phân lập dữ liệu đa thuê bao qua PostgreSQL 16 RLS, composite keys `(tenant_id, id)` và tiền tố phân quyền Object Storage; ngăn ngừa 100% tấn công BOLA. |
| **MF-003** | REST API Gateway (FastAPI) | Tiếp nhận yêu cầu đánh giá bất đồng bộ (`POST /api/v1/runs`), hỗ trợ Idempotency-Key, kiểm tra AuthContext, tra cứu trạng thái và trả về kết quả chuẩn RFC 9457. |
| **MF-004** | Distributed Worker Daemon | Worker độc lập thực hiện claim lease (`FOR UPDATE SKIP LOCKED`), duy trì heartbeat watchdog, tự động phục hồi khi gặp sự cố và xử lý hàng đợi công bằng giữa các tenant. |
| **MF-005** | Deterministic Profiling & Rule Engine | Quét đơn kỳ (Single-Pass Scan) bằng Apache Spark trên k3s vectorization/pushdown; tính `Canonical Metrics` và thực thi 5 nhóm quy tắc xác định theo 6 chiều chất lượng chuẩn. |
| **MF-006** | IQR Outlier Detector (Advisory) | Phát hiện ngoại lệ đơn biến trên cột số theo Tukey fences ($k=1.5$); gắn cờ `ADVISORY`, trọng số = 0, bảo đảm không làm biến dạng DQ Score và Quality Gate kỹ thuật. |
| **MF-007** | In-Memory Scoring & Quality Gate | Tái chuẩn hóa trọng số các chiều đã đo, xử lý nhóm xung đột (`conflict_group`), tính Coverage và phán quyết Quality Gate theo thứ tự 6 cấp bậc ưu tiên nghiêm ngặt. |
| **MF-008** | Immutable Assessment Store | Đóng gói Assessment nguyên tử kèm 4 mã băm cấu hình và `assessment_hash` (SHA-256); bảo vệ tính bất biến qua triggers và chính sách RLS của PostgreSQL 16. |
| **MF-009** | Two-Tiered Evidence Redaction | Bảo vệ dữ liệu nhạy cảm 2 tầng: Tầng 1 giới hạn 10–50 dòng và che mờ PII tại nguồn trước khi ghi CSDL; Tầng 2 che mờ động theo quyền người gọi khi truy vấn qua API/UI. |
| **MF-010** | Central Web Dashboard (Streamlit) | Giao diện Web hiển thị Scorecard trực quan, tiến độ 5 giai đoạn lượt chạy (Live Run Monitor), và drill-down bằng chứng vi phạm mẫu an toàn. |

### 3.2. Ranh giới An toàn và Bất biến Nghiệp vụ Bắt buộc v1.0

1. **Bảo toàn Tuyệt đối Dữ liệu Nguồn:** Nền tảng hoạt động ở chế độ chỉ đọc (Read-Only) đối với dữ liệu khách hàng; tuyệt đối không thực hiện sửa đổi, làm sạch hoặc ghi đè dữ liệu nguồn.
2. **Ngăn chặn Rò rỉ Dữ liệu Chéo Tenant (Zero Cross-Tenant Leakage):** Tuyệt đối không cho phép bất kỳ truy vấn, API hoặc giao diện nào truy xuất tài nguyên thuộc tenant khác nếu không có `AccessGrant` hợp lệ; áp dụng nguyên tắc từ chối mặc định (Fail-Closed).
3. **Bất biến Mẫu số Không:** Khi một quy tắc không có dòng nào thỏa mãn điều kiện tiên quyết, trả về `NOT_APPLICABLE` hoặc `NOT_MEASURABLE`; tuyệt đối cấm ép mẫu số bằng 0 thành điểm 0 hoặc điểm 100.
4. **Cô lập Tín hiệu Cảnh báo:** Lỗi hoặc tín hiệu ngoại lệ thống kê từ Outlier Detector chỉ mang tính tham vấn, không bao giờ được tự ý trừ điểm kỹ thuật của bộ dữ liệu.
5. **Điều kiện Công bố Điểm Khắt khe:** Điểm số chỉ được `PUBLISHED` khi Run thành công, Độ bao phủ $C_{DQ} \ge 80\%$ và không có quy tắc bắt buộc nào bị lỗi; ngược lại điểm số bị giữ lại (`WITHHELD`).
6. **Vệ sinh Phản hồi & Tệp Xuất (Zero-Trust Leak Prevention):** Phản hồi lỗi API tuân thủ RFC 9457 (không lộ stack trace, SQL query hay đường dẫn hệ thống nội bộ); tệp xuất CSV tự động vô hiệu hóa ký tự công thức (`=`, `+`, `-`, `@`) để chống tấn công CSV Injection.

### 3.3. Ngoài Phạm vi Phát hành v1.0 (Out of Scope / Lộ trình Mở rộng)

- Tự động sửa hoặc làm sạch dữ liệu nguồn (Data Cleansing & Remediation) — Trách nhiệm thuộc hệ thống nguồn của khách hàng.
- Nền tảng vẽ đồ thị dòng dữ liệu chuyên sâu (Data Lineage Graph Engine) và hệ thống tạo vé sự cố (Incident Ticketing).
- Đánh giá dữ liệu luồng thời gian thực dạng streaming (Kafka/Flink Stream Processing).
- Đánh giá dữ liệu phi cấu trúc (Âm thanh, hình ảnh, văn bản tự do chưa gán nhãn).
- AI/LLM tự động thay đổi quy tắc, trọng số hoặc phán quyết Quality Gate không có sự phê duyệt của con người.
- Phân quyền liên đoàn doanh nghiệp qua SSO SAML/OIDC (Được thiết kế sẵn sàng mở rộng, v1.0 sử dụng cơ chế xác thực nội bộ băm Argon2id và Access/Refresh Token).
- Quản trị cụm Spark đa đám mây ngoài k3s (v1.0 chuẩn hóa trên Apache Spark triển khai trên cụm k3s nội bộ thông qua Spark Operator và `IComputeEnginePort`).

---

## 4. LUỒNG SỬ DỤNG VÀ HỢP ĐỒNG TÍCH HỢP CHUẨN (INTEGRATION FLOWS)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 LUỒNG SỬ DỤNG CHUẨN TRONG v1.0                                  │
│                                                                                                 │
│  ┌─────────────────────────┐         ┌─────────────────────────┐         ┌───────────────────┐  │
│  │ 1. Đăng ký Snapshot     │ ──────► │ 2. Khai báo Cấu hình    │ ──────► │ 3. Kích hoạt Run  │  │
│  │    (CSV/Parquet Source) │         │    (Ruleset, Policy)    │         │    (Evaluation)   │  │
│  └─────────────────────────┘         └─────────────────────────┘         └─────────┬─────────┘  │
│                                                                                    │            │
│                                                                                    ▼            │
│  ┌─────────────────────────┐         ┌─────────────────────────┐         ┌───────────────────┐  │
│  │ 6. Xuất Báo cáo         │ ◄────── │ 5. Xem Scorecard &      │ ◄────── │ 4. Đóng gói       │  │
│  │    (JSON/Markdown)      │         │    Drill-down Bằng chứng│         │    Assessment     │  │
│  └─────────────────────────┘         └─────────────────────────┘         └───────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Luồng Tích hợp Tự động qua API (CI/CD & Data Pipeline Integration):**
   - Pipeline của khách hàng gọi `POST /api/v1/runs` kèm JWT Bearer Token và `Idempotency-Key`.
   - Hệ thống phản hồi ngay mã `202 Accepted` kèm `run_id` trong vòng $\le 500$ms.
   - Pipeline thăm dò `GET /api/v1/runs/{run_id}` để theo dõi tiến độ (`QUEUED → RUNNING → SUCCEEDED`).
   - Khi hoàn tất, pipeline truy xuất `GET /api/v1/assessments/{run_id}` để lấy kết luận Quality Gate làm điều kiện cho phép dữ liệu đi tiếp vào Data Warehouse.
2. **Luồng Khai thác Trực quan qua Web Dashboard (Human-in-the-Loop):**
   - Chuyên viên dữ liệu đăng nhập vào Dashboard bằng tài khoản thuộc Tenant của mình.
   - Màn hình Live Run Monitor thể hiện thanh tiến trình 5 giai đoạn của các lượt chạy đang thực thi.
   - Bảng điểm Scorecard hiển thị trực quan 4 thẻ chỉ số chính (DQ Score, Quality Gate, Confidence, Coverage) cùng 6 thanh đo lường kích thước chất lượng.
   - Bảng điều tra drill-down cho phép xem danh sách các bản ghi vi phạm đã được che mờ động các trường PII, phục vụ việc đối soát và khắc phục dữ liệu gốc.

---

## 5. RÀNG BUỘC KỸ THUẬT VÀ HẠ TẦNG SẢN XUẤT (INFRASTRUCTURE & TECHNICAL CONSTRAINTS)

### 5.1. Ràng buộc Công nghệ và Cấu hình Mặc định v1.0

- **Ngôn ngữ & Runtime:** Python 3.13 (quản lý qua `uv`), kiến trúc non-root container (`appuser:10001`).
- **Động cơ Tính toán (Compute Engine):** Apache Spark trên k3s (Spark Operator / `SparkApplication`) thực thi đo lường vector hóa và pushdown SQL, phân tách hoàn toàn giữa Control Plane (FastAPI Gateway + Worker) và Compute Plane (Spark Driver/Executors trên k3s). Worker chịu trách nhiệm gửi và theo dõi `SparkApplication`, xác thực hàng rào lease fencing trước khi tổng hợp điểm và công bố kết quả.
- **Cơ sở Dữ liệu Siêu dữ liệu & Kết quả (Metadata & Result Store):** PostgreSQL 16 phân cụm với connection pooling (`psycopg3`), kích hoạt Row-Level Security (RLS) bắt buộc trên 100% các bảng nghiệp vụ.
- **Lưu trữ Đối tượng Chia sẻ (Shared Object Storage):** Cụm lưu trữ tương thích S3 (MinIO Distributed MNMD / AWS S3) với cấu trúc phân cấp tiền tố tenant rõ ràng; local filesystem adapter hỗ trợ môi trường sandbox/testing cục bộ.
- **Hàng đợi Tác vụ (Task Queue):** Hàng đợi bền vững dựa trên PostgreSQL 16 sử dụng kỹ thuật `FOR UPDATE SKIP LOCKED`, loại bỏ hoàn toàn sự phụ thuộc vào các message broker bên ngoài (Kafka, RabbitMQ, Celery).
- **Ngân sách Tài nguyên Đánh giá Cơ sở:** Khống chế trần tài nguyên toàn nút tối đa **8 GB RAM** trên cụm k3s đơn nút tham chiếu (~3 GB cho OS/k3s/DB/Storage/Worker, ~4 GB cho SparkApplication Driver+Executor bao gồm JVM overhead, ~1 GB dự phòng hệ thống; tối đa 1 Spark run chạy đồng thời, các run sau xếp hàng trong PostgreSQL). Mục tiêu thiết kế End-to-End SLA đo kiểm $\le 120$s trên 100.000 dòng dữ liệu bảng chuẩn (gồm queue wait, pod startup 10–25s, compute và publish), đỉnh RAM Spark $\le 4.0$ GB, dung lượng bằng chứng mẫu $\le 50$ dòng / $\le 500$ KB.

### 5.2. Gói Dữ liệu Kiểm chứng Vertical Slice

Hệ thống sử dụng bộ dữ liệu thực tế từ **City of Chicago Taxi Trips 2023** (Lát cắt tháng 01/2023) với 3 lớp dữ liệu kiểm chứng:
1. **Exploration Dataset:** Dữ liệu mẫu dùng khám phá schema và kiểm thử profiling.
2. **Golden Dataset:** Tập dữ liệu nhỏ có các ca vi phạm biết trước, kèm bảng kết quả kỳ vọng (*Expected Results*) phục vụ kiểm thử tự động 100% đúng đắn.
3. **Benchmark Dataset:** Tập dữ liệu quy mô chuẩn để đo đạc và kiểm chứng ngân sách tài nguyên (Runtime, Peak RAM, Throughput).

---

## 6. TIÊU CHÍ NGHIỆM THU SẢN XUẤT (PRODUCTION ACCEPTANCE GATES)

Hệ thống được coi là sẵn sàng bàn giao và đưa vào vận hành sản xuất khi vượt qua 100% các cổng kiểm chứng sau:

| Mã Cổng | Tên cổng kiểm chứng | Tiêu chí nghiệm thu bắt buộc (Pass Criteria) | Bằng chứng kiểm chứng |
| :--- | :--- | :--- | :--- |
| **GATE-01** | Tính Đúng đắn của Thuật toán Đo lường | 100% ca kiểm thử Golden Cases của 5 nhóm quy tắc và Outlier Tukey fences khớp chính xác kết quả kỳ vọng. | Golden Test Report (AC-004, AC-007, AC-008) |
| **GATE-02** | Bảo toàn Bất biến Toán học & Tính điểm | Mẫu số 0 không thành điểm 0; Outlier advisory có trọng số 0; Quality Gate tuân thủ thứ tự ưu tiên 6 bậc nghiêm ngặt. | Invariant Test Suite (AC-005, AC-009..011) |
| **GATE-03** | Tính Tái lập Tuyệt đối (Determinism) | Chạy lại 10 lần liên tiếp trên cùng Snapshot và cấu hình sinh ra mã băm `assessment_hash` đồng nhất 100%. | Replay Verification (AC-013) |
| **GATE-04** | Cô lập Đa Thuê bao Tuyệt đối (Tenant Isolation) | Kiểm thử thâm nhập BOLA và quét truy vấn chéo tenant: 0 byte rò rỉ dữ liệu hoặc siêu dữ liệu giữa các tenant khác nhau. | Multi-Tenant Penetration Test (AC-016, AC-020) |
| **GATE-05** | Xác thực & Quản lý Phiên An toàn | Thuật toán băm Argon2id; Access Token JWT 15m + Refresh Token UUIDv4 14d; phát hiện và thu hồi toàn bộ khi Refresh Token bị tái sử dụng. | Auth & Security Test (AC-023) |
| **GATE-06** | Phòng vệ Dữ liệu Nhạy cảm & RFC 9457 | 100% trường PII được che mờ tại nguồn; lỗi API chuẩn hóa RFC 9457 (0 stack trace, 0 SQL leak); tệp CSV xuất được vô hiệu hóa công thức. | Data Shielding Test (AC-022, AC-025) |
| **GATE-07** | Phục hồi Sự cố & Hàng đợi Tin cậy | Worker đột tử được watchdog phát hiện trong vòng $\le 30$s, tự động thu hồi lease và phân bổ lại an toàn; xử lý trùng lặp bằng Idempotency-Key. | Chaos & Lease Recovery Test (AC-016, AC-017) |
| **GATE-08** | Quy trình Triển khai, Di trú & Khôi phục | Scripts migration CSDL hai chiều (up/down) hoạt động ổn định; diễn tập khôi phục backup PostgreSQL và MinIO chứng minh RPO $\le 15$m, RTO $\le 30$m. | Disaster Recovery Drill Report |
| **GATE-09** | Khả năng Quan sát & Giám sát Vận hành | Endpoint `/health` phản ánh chính xác trạng thái phụ thuộc (PostgreSQL, MinIO); cấu trúc Structured JSON Logs kèm `tenant_id` và `run_id`. | Observability Audit Report |
| **GATE-10** | Bảo toàn Dữ liệu Nguồn Tuyệt đối | Tệp dữ liệu nguồn của khách hàng duy trì 100% mã băm SHA-256 trước và sau quá trình đánh giá. | Source Integrity Test (AC-015) |


### 6.1. Điều kiện Tiên quyết Triển khai Cần Kiểm chứng (Unverified Preconditions)

Các điều kiện kỹ thuật dưới đây là giả định thiết kế và yêu cầu tiên quyết về hạ tầng, cần được đo kiểm thực tế khi thiết lập môi trường:
1. **Cụm k3s và Spark Operator:** Cụm k3s (phiên bản v1.28+) và Spark Operator CRD cần được kích hoạt, phân bổ namespace cô lập và kiểm chứng độ trễ khởi tạo Pod của Spark Driver/Executor.
2. **Kết nối Object Storage (MinIO S3A):** Kết nối S3A từ Spark Pods đến cụm MinIO nội bộ cần được xác thực thông lượng I/O và tính toàn vẹn chữ ký số qua TLS nội bộ.
3. **Kiểm thử Ngắt mạch & Hàng rào Lease Fencing:** Kịch bản Worker đột tử hoặc SparkApplication chạy quá thời gian lease phải được kiểm chứng không gây ghi đè dữ liệu hoặc xung đột trạng thái (Zombie write prevention).

---

## 7. BIÊN BẢN PHÊ DUYỆT & LỊCH SỬ THAY ĐỔI

| Phiên bản | Ngày cập nhật | Tác giả / Đại diện | Nội dung thay đổi cốt lõi | Quyết định |
| :--- | :--- | :--- | :--- | :--- |
| **v1.0** | 2026-08-27 | Nguyễn Hoàng Tùng | Phê duyệt thiết kế Core Python Engine ban đầu | Approved (Baseline) |
| **v1.1** | 2026-09-08 | Nguyễn Hoàng Tùng | Cập nhật cấu trúc tài liệu theo chuẩn 5 Chương | Reviewed |
| **v1.2** | 2026-09-23 | Nguyễn Hoàng Tùng | Chuẩn hóa mô hình Vận hành Nền tảng Tập trung Đa Thuê bao (Centrally Operated Shared Multi-Tenant Platform), hợp đồng tích hợp API/Dashboard, và 10 Cổng nghiệm thu sản xuất | Approved Specification |
| **v1.3** | 2026-09-24 | Nguyễn Hoàng Tùng | Chuẩn hóa kiến trúc đích k3s đơn nút, ngân sách tối đa 8GB RAM toàn nút (1 Spark run đồng thời), bảo toàn snapshot gốc qua manifest (không compact/coalesce), phân định hợp đồng Worker điều phối - Spark tính toán - Worker công bố, và định nghĩa SLA end-to-end có điều kiện benchmark | **Review Candidate** |

---

## 8. DANH MỤC HỒ SƠ ĐỒNG BỘ TRONG HỆ THỐNG

- [Chương 1: Khảo sát bối cảnh và xác định phạm vi hệ thống (AD-001)](./Chapter_1.md)
- [Chương 2: Đặc tả yêu cầu hệ thống (SRS) (AD-003)](./Chapter_2.md)
- [Chương 3: Phân tích và mô hình hóa hệ thống (AD-004)](./Chapter_3.md)
- [Chương 4: Kiến trúc hệ thống và thiết kế phần mềm (AD-009)](./Chapter_4.md)
- [Chương 5: Thiết kế dữ liệu và mô hình lớp chi tiết (AD-005)](./Chapter_5.md)
- [Đặc tả Hạ tầng Phân tán & Lưu trữ Bền vững](./architecture/INFRASTRUCTURE_DESIGN.md)
- [AD-012: Phân tầng Trải nghiệm & Danh mục Tồn đọng Tính năng](./AD-012_UX_AND_FEATURE_BACKLOG.md)
- [Lý thuyết Toán học & Semantics Tính điểm](./theory/DQ_SCORING_THEORY.md)
- [Hướng dẫn Rà soát và Tái sử dụng Mã nguồn](./engineering/IMPLEMENTATION_REUSE_GUIDE.md)

---
*(Hết nội dung Project Brief — Phiên bản 1.3 Review Candidate)*

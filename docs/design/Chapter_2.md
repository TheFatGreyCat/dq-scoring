# CHƯƠNG 2: ĐẶC TẢ YÊU CẦU HỆ THỐNG (SOFTWARE REQUIREMENTS SPECIFICATION - SRS)

**Hệ thống:** DQ Scoring System  
**Mã hồ sơ:** AD-003-SRS  
**Phiên bản:** 1.7  
**Ngày:** 2026-09-24  
**Trạng thái:** Review Candidate  
**Tiêu chuẩn áp dụng:** ISO/IEC/IEEE 29148:2018 (Edition 2) & Cấu trúc trình bày IEEE 830  

---

## THÔNG TIN VÀ KIỂM SOÁT TÀI LIỆU

**Nguồn nghiệp vụ chính:** `docs/Chapter_1.md` (v1.7 Review Candidate)
**Nguồn phân tích tác nhân:** `docs/AD-002_STAKEHOLDER_AND_BUSINESS_USE_CASES.md` (v1.1 Review Candidate; actor catalog tương thích)
**Nguồn Project Brief & Evidence:** `docs/PROJECT_BRIEF_DQ_SCORING.md` (EVD-INT-001)  
**Nền tảng lý thuyết toán học:** `docs/theory/DQ_SCORING_THEORY.md` (EVD-TH-001)  

### Lịch sử phiên bản và phê duyệt

| Phiên bản | Ngày | Tóm tắt thay đổi | Trạng thái | Tác giả / Người sửa |
| :--- | :--- | :--- | :--- | :--- |
| **0.1** | 2026-08-24 | Khởi tạo SRS từ Chapter 1 v0.1 và AD-002 | Draft | Nguyễn Hoàng Tùng |
| **0.2** | 2026-08-24 | Bổ sung IEEE 29148 governance, thuộc tính requirement và verification matrix | Draft | Nguyễn Hoàng Tùng |
| **0.3** | 2026-08-24 | Chuyển sang form IEEE 830 (Mục 1–6); phân định Interface, FR, NFR, Data Requirements | Draft | Nguyễn Hoàng Tùng |
| **0.4** | 2026-08-24 | Đồng bộ các quyết định về Phase 1 boundary, Dataset Registry, Scoring policy và Invariants | Review Candidate | Nguyễn Hoàng Tùng |
| **0.5** | 2026-08-25 | Chốt local single-workspace prototype, defer IAM/Network, bổ sung candidate vertical slice | Review Candidate | Nguyễn Hoàng Tùng |
| **0.6** | 2026-08-25 | Thu gọn v1.0: cô lập Outlier IQR advisory, bỏ REST API runtime, xác nhận 15 ACs | Review Candidate | Nguyễn Hoàng Tùng |
| **1.0** | 2026-08-27 | Đóng TBD P0 và hoàn thiện ma trận truy vết 2 chiều | **Approved Baseline** | Nguyễn Hoàng Tùng |
| **1.1** | 2026-08-28 | Chuẩn hóa ID 3 chữ số; khôi phục 19 DR; thống nhất Gate, ranh giới lỗi và phê duyệt cấu hình | Review Candidate | Nguyễn Hoàng Tùng |
| **1.2** | 2026-09-04 | Đồng bộ async Evaluation Run trên PostgreSQL: cơ chế lease, retry, hủy bỏ, lũy đẳng và công bố bất biến | Review Candidate | Nguyễn Hoàng Tùng |
| **1.3** | 2026-09-08 | Tích hợp phân tầng yêu cầu UX 3 lớp từ AD-012 | Review Candidate | Nguyễn Hoàng Tùng |
| **1.4** | 2026-09-08 | Chuẩn hóa trạng thái đo lường, khóa bất biến Zero-Default và cách ly Outlier Advisory | Review Candidate | Nguyễn Hoàng Tùng |
| **1.5** | 2026-09-15 | Đồng bộ kiến trúc Lakehouse với Spark; bổ sung yêu cầu Kho Rule tập trung, phân loại dữ liệu nhạy cảm 4 nhóm, che mờ đa tầng và nền tảng Đa thuê bao cho Data Marketplace | Review Candidate | Nguyễn Hoàng Tùng |
| **1.6** | 2026-09-17 | Bổ sung yêu cầu Mẫu Đánh giá theo Domain, API đánh giá hàng loạt (FR-RUN-012) và an toàn LLM Advisory; đồng bộ 6 cấp ưu tiên Quality Gate | Approved Specification | Nguyễn Hoàng Tùng |
| **1.7** | 2026-09-24 | Chuẩn hóa kiến trúc đích k3s đơn nút, ngân sách tối đa 8GB RAM toàn nút (1 Spark run đồng thời), bảo toàn snapshot gốc qua manifest (không compact/coalesce), hợp đồng điều phối Worker - tính toán Spark - công bố Assessment, và định nghĩa SLA end-to-end có điều kiện benchmark | **Review Candidate** | Nguyễn Hoàng Tùng |

### Biên bản phê duyệt Baseline v1.0 (lịch sử)

| Vai trò | Họ và tên | Trách nhiệm | Quyết định | Ngày phê duyệt |
| :--- | :--- | :--- | :--- | :--- |
| **Project Owner / Technical Lead** | Nguyễn Hoàng Tùng | Chịu trách nhiệm toàn bộ nội dung SRS và hiện thực hóa | **Approved** | 2026-08-27 |
| **Requirements Reviewer / Approver** | Mentor / Hội đồng thẩm định | Thẩm định đặc tả kỹ thuật và tiêu chí nghiệm thu | **Approved** | 2026-08-27 |

> Phiên bản 1.7 hiện là **Review Candidate** (đặc tả yêu cầu thiết kế mục tiêu, các chỉ số NFR là ngưỡng thiết kế cần kiểm chứng sau khi lập trình) và chờ vòng thẩm định độc lập.

---

## 1. GIỚI THIỆU (INTRODUCTION)

### 1.1. Mục đích (Purpose)
Tài liệu Đặc tả Yêu cầu Phần mềm (SRS) này xác định đầy đủ các yêu cầu chức năng (FR), yêu cầu phi chức năng (NFR), yêu cầu giao diện (IF), yêu cầu dữ liệu (DR) và các quy tắc nghiệp vụ (BR) của Hệ thống Chấm điểm Chất lượng Dữ liệu (**DQ Scoring System v1.0**).  
Tài liệu là cơ sở kỹ thuật duy nhất phục vụ mô hình hóa UML (Chương 3), thiết kế kiến trúc (Chương 4), thiết kế dữ liệu (Chương 5) và là chuẩn mực nghiệm thu hệ thống.

### 1.2. Quy ước tài liệu (Document Conventions)
- Cấu trúc tài liệu tuân theo tiêu chuẩn **IEEE 830** (6 phần chính); phương pháp luận đặc tả yêu cầu và quản trị chất lượng tuân theo **ISO/IEC/IEEE 29148:2018**.
- Thuật ngữ bắt buộc: **phải** (shall - bắt buộc tuân thủ); **nên/có thể** (should/may - hướng dẫn hoặc khuyến nghị).
- Định danh truy vết tuân theo mẫu `<TYPE>[-<SUBTYPE>]-NNN`: viết hoa, phân tách bằng dấu gạch ngang, số thứ tự đúng 3 chữ số và không dùng hậu tố chữ cái (`a/b`).
  - Nhóm có subtype: `ACT-H-001`, `ACT-S-001`, `EVD-INT-001`, `IF-UI-001`, `FR-RUN-001`, `NFR-COR-001`, `TBD-RESOURCE-001`.
  - Nhóm không có subtype: `AD-001`, `BG-001`, `STK-001`, `BUC-001`, `UC-001`, `SEQ-001`, `CAP-001`, `PKG-001`, `DR-001`, `BR-001`, `AC-001`.
  - Mỗi ID có đúng một định nghĩa; mọi lần xuất hiện khác là tham chiếu tới định nghĩa đó.
  - Các khóa dữ liệu runtime (`snapshot_id`, `run_id`, `assessment_id`, v.v.) vẫn là UUID và không thuộc quy ước ID tài liệu này.
- Mức độ ưu tiên:
  - **P0 (Bắt buộc v1.0):** Thuộc phạm vi phát hành lõi của phiên bản 1.0.
  - **Post-1.0 (Hoãn lại / Deferred):** Được bảo lưu trong kiến trúc, kích hoạt ở các phiên bản sau.

#### 1.2.1. Bảng thuật ngữ và định nghĩa (Glossary)

| Thuật ngữ | Định nghĩa trong DQ Scoring |
| :--- | :--- |
| **Data Asset** | Tài sản dữ liệu logic cần theo dõi vòng đời chất lượng (ví dụ: `chicago_taxi_trips`). |
| **Dataset Snapshot** | Phiên bản dữ liệu vật lý cụ thể, bất biến, gắn liền với mã băm SHA-256 nội dung. |
| **Canonical Metrics** | Tập chỉ số thống kê (row count, null rate, distinct count, min/max, distribution) tính 1 lần qua Profiling. |
| **Quality Rule** | Quy tắc kiểm tra kỳ vọng xác định (deterministic expectation) thuộc 1 trong 6 chiều chất lượng. |
| **Null Policy** | Chính sách xử lý giá trị null/missing trong mẫu số tính điểm (`fail`, `ignore`, `separate`, `not_applicable`). |
| **Scoring Policy** | Chính sách tính điểm: trọng số quy tắc, trọng số chiều, ngưỡng công bố điểm và điều kiện Quality Gate. |
| **Canonical Quality Result** | Kết quả chuẩn hóa từ Rule hoặc Detector, chứa status, counts, metric, config hash và bounded evidence. |
| **Measurement Status** | Trạng thái phép đo được lưu: `MEASURED`, `NOT_APPLICABLE`, `NOT_MEASURABLE`, `INSUFFICIENT_DATA`, `SKIPPED_BY_BUDGET`, `FAILED_TO_MEASURE`; `SKIPPED_BY_BUDGET` được dành cho Post-1.0. |
| **Score Publication Status** | `PUBLISHED` khi Run hợp lệ, không có phép đo score-enabled bắt buộc bị lỗi và Coverage $\ge 80\%$; ngược lại là `WITHHELD`. |
| **Quality Gate** | Kết luận chất lượng của Assessment theo thứ tự ưu tiên 6 cấp bậc của BR-010: `ERROR` (lỗi kỹ thuật `FAILED_TO_MEASURE` trên quy tắc bắt buộc trong Run đã hoàn tất), `FAIL` (vi phạm quy tắc critical hoặc DQ Score < 60), `INSUFFICIENT_EVIDENCE` (thiếu phép đo bắt buộc hoặc Coverage < 80%), `WARN` (60 $\le$ DQ Score < 80), `PASS` (DQ Score $\ge$ 80). Run lỗi kỹ thuật hệ thống kết thúc ở trạng thái `RunStatus.FAILED` và không tạo Assessment hay Gate. |
| **RevisionStatus** | Vòng đời phê duyệt cấu hình: `DRAFT` (Data Steward soạn, chưa phê duyệt — không dùng được cho Run), `ACTIVE` (Data Owner đã phê duyệt — sẵn sàng cho Run), `DEPRECATED` (đã thay thế bởi phiên bản mới). |
| **Bounded Evidence** | Mẫu dữ liệu vi phạm được khống chế số dòng (10–50 dòng) và che mờ thông tin nhạy cảm. |
| **Immutable Assessment** | Bản ghi kết quả đánh giá nguyên tử, không thể chỉnh sửa sau khi công bố. |

### 1.3. Đối tượng độc giả (Intended Audience)
1. **Developer / Implementer:** Hiện thực hóa mã nguồn Core Engine, Data Adapters và Dashboard UI.
2. **Software Architect:** Thiết kế kiến trúc Hexagonal (Ports-and-Adapters) và Package Diagram ở Chương 4.
3. **QA / Tester:** Thiết kế bộ kiểm thử tự động Golden Tests, Boundary Tests và Benchmark Suite.
4. **Project Owner & Mentor:** Đánh giá độ phủ yêu cầu, phê duyệt nghiệm thu đồ án.

### 1.4. Phạm vi Sản phẩm (Product Scope)

#### 1.4.1. Chức năng cốt lõi trong v1.0 (P0)
 - Tiếp nhận và lưu trữ file bảng CSV (UTF-8) / Parquet bất biến vào Dataset Store; đăng ký metadata và SHA-256 qua `SourceAdapter`.
- Profiling tự động toàn bộ snapshot (Full Scan) qua Apache Spark trên k3s tính `Canonical Metrics`.
- Thực thi 5 nhóm quy tắc xác định: (1) Non-null, (2) Type/Parse, (3) Domain/Range, (4) Uniqueness, (5) Cross-field.
- Thực thi IQR Outlier Detector đơn biến trên cột số ở chế độ `ADVISORY` (hệ số $k=1.5$, trọng số = 0).
- Chuẩn hóa kết quả thành `Canonical Quality Results`.
- Tính Rule Score, 6 Dimension Results (score có thể `null`), DQ Score, Coverage và Quality Gate theo Scoring Policy có phiên bản.
- Đóng gói `Immutable Assessment` nguyên tử gắn cứng các mã băm cấu hình.
 - Submit, theo dõi và hủy Evaluation Run qua API/CLI; Worker thực thi bất đồng bộ qua PostgreSQL queue và Dashboard hiển thị lifecycle/Scorecard.

#### 1.4.2. Ngoài phạm vi v1.0 (Deferred / Post-1.0)
- Tự động sửa hoặc xóa dữ liệu nguồn (Cleansing / Remediation).
- Giám sát luồng thời gian thực (Streaming), quản lý Lineage, Incident ticketing.
- AI/LLM tự động sửa điểm, đổi rule hoặc can thiệp Quality Gate.
- Vendor-specific Lakehouse integration, Data Catalog từ xa.
- Quản trị danh tính doanh nghiệp đa cấp độ (Enterprise IAM / SSO Federation / SAML / OIDC nâng cao) và Public REST API phục vụ tích hợp bên thứ ba (hoãn sang Phase 2 theo IF-SRC-006). *Lưu ý quan trọng:* Trong mọi môi trường (kể cả v1.0 và Production), toàn bộ bề mặt giao tiếp (API, CLI, UI, Facade) bắt buộc thực thi xác thực danh tính tạo ngữ cảnh `AuthContext` hợp lệ, đối chiếu ranh giới người thuê (Tenant Boundary Assertion) và ranh giới quyền sở hữu/cấp quyền tài nguyên (Resource-Level Authorization), áp dụng nguyên tắc từ chối mặc định (Fail-Closed) cho mọi yêu cầu.
- Kafka, Celery, RabbitMQ hoặc distributed queue service riêng; PostgreSQL queue là baseline v1.0.
- Tự động trừ điểm từ Outlier / Drift.

### 1.5. Tài liệu tham khảo (References)
- **REF-01:** ISO/IEC/IEEE 29148:2018 (Edition 2) - Requirements Engineering.
- **REF-02:** `docs/Chapter_1.md` (v1.0 Approved Baseline).
- **REF-03:** `docs/AD-002_STAKEHOLDER_AND_BUSINESS_USE_CASES.md` (v1.0).
- **REF-04:** `docs/PROJECT_BRIEF_DQ_SCORING.md` (EVD-INT-001).
- **REF-05:** `docs/theory/DQ_SCORING_THEORY.md` (EVD-TH-001).
- **REF-06:** City of Chicago Taxi Trips 2023 Dataset (EVD-EXT-002).
- **REF-07:** OWASP API Security Top 10 (2023) - API1: Broken Object Level Authorization (BOLA), API5: Broken Function Level Authorization (BFLA) (`https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/`).
- **REF-08:** OWASP Authorization & REST Security Cheat Sheets (`https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html`).
- **REF-09:** PostgreSQL 16 Documentation - Row Security Policies (`https://www.postgresql.org/docs/current/ddl-rowsecurity.html`).
- **REF-10:** NIST SP 800-63B - Digital Identity Guidelines: Authentication and Lifecycle Management (`https://pages.nist.gov/800-63-4/sp800-63b.html`).

---

## 2. MÔ TẢ TỔNG QUAN (OVERALL DESCRIPTION)

### 2.1. Bối cảnh sản phẩm (Product Perspective)

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                                LOCAL ENVIRONMENT                                  │
│                                                                                   │
│  ┌───────────────────────┐                                                        │
│  │   Data Engineer /     │                                                        │
│  │    Local Operator     │                                                        │
│  └───────────┬───────────┘                                                        │
│              │ 1. Upload CSV/Parquet & RunSpec                                    │
│              │ 2. View Scorecard & Drill-down                                     │
│              ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────────────┐  │
│  │                          DQ SCORING SYSTEM v1.0                             │  │
│  │                                                                             │  │
│  │  ┌───────────────────────────────────────────────────────────────────────┐  │  │
│  │  │ Local Dashboard / CLI (Presentation Layer - Streamlit / Rich Console)  │  │  │
│  │  └──────────────────────────────────┬────────────────────────────────────┘  │  │
│  │                                     │ Calls Facade Interface                │  │
│  │                                     ▼                                       │  │
│  │  ┌───────────────────────────────────────────────────────────────────────┐  │  │
│  │  │ Core Scoring Engine (Hexagonal Architecture / Application Facade)     │  │  │
│  │  │  - Profiling Engine (Spark Compute on k3s)                             │  │  │
│  │  │  - Deterministic Rule Engine                                          │  │  │
│  │  │  - IQR Outlier Detector (Advisory)                                    │  │  │
│  │  │  - Score & Gate Aggregator                                            │  │  │
│  │  └──────────────────────────────────┬────────────────────────────────────┘  │  │
│  │                                     │ Reads/Writes                          │  │
│  │                                     ▼                                       │  │
│  │  ┌───────────────────────────────────────────────────────────────────────┐  │  │
│  │  │ Persistence & Storage Layer                                           │  │  │
│  │  │  - Dataset Store: Immutable raw binary files (CSV/Parquet)            │  │  │
│  │  │  - PostgreSQL: durable assets, runs, leases, events, rules, assessments│  │
│  │  └───────────────────────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2. Các chức năng chính (Product Functions)
1. **Quản lý Data Asset và Snapshot:** Lưu trữ tệp bất biến, tính SHA-256, phát hiện schema qua `SourceAdapter` technology-neutral.
2. **Lập hồ sơ dữ liệu (Profiling):** Quét toàn bộ dữ liệu, tính `Canonical Metrics` dùng chung.
3. **Thực thi Kiểm tra Quy tắc (Validation):** Đánh giá 5 nhóm quy tắc, ghi nhận kết quả loại trừ lẫn nhau.
4. **Phát hiện Ngoại lệ (Outlier Detection):** Tính tứ phân vị IQR, gắn cờ giá trị dị biệt ở chế độ advisory.
5. **Chuẩn hóa Kết quả:** Sinh tập hợp `Canonical Quality Results` nhất quán.
6. **Tổng hợp Điểm số và Cổng chất lượng:** Tính Rule Score, Dimension Score, DQ Score, Coverage và Quality Gate.
7. **Điều phối Evaluation Run bất đồng bộ:** API validate/enqueue; Worker claim lease, heartbeat, thực thi và phục hồi job hết lease.
8. **Đóng gói và Trực quan hóa Assessment:** Lưu trữ bản ghi bất biến trong PostgreSQL và hiển thị Scorecard; `WITHHELD` vẫn persisted với `dq_score = null`.

### 2.3. Phân loại người dùng (User Classes and Characteristics)

| Nhóm Actor | Vai trò trong hệ thống | Đặc điểm & Yêu cầu kỹ năng | Tần suất sử dụng |
| :--- | :--- | :--- | :--- |
| **ACT-H-001: Data Engineer / Operator** | Vận hành run, upload dữ liệu, cấu hình pipeline, submit/cancel run | Kỹ sư dữ liệu, thành thạo Python, SQL, cấu trúc dữ liệu bảng | Hàng ngày / Mỗi lượt run |
| **ACT-H-002: Data Owner** | Phê duyệt Ruleset, Critical Rules và Scoring Policy; chịu trách nhiệm cuối về mức chất lượng chấp nhận được | Hiểu sâu nghiệp vụ dữ liệu, ra quyết định chất lượng | Định kỳ / Khi cần phê duyệt cấu hình |
| **ACT-H-003: Data Steward** | Soạn thảo quy tắc, cấu hình null policy, trọng số; submit để Owner phê duyệt; theo dõi Coverage | Hiểu sâu nghiệp vụ dữ liệu, quản trị chất lượng | Định kỳ / Khi đổi cấu hình |
| **ACT-H-004: Dataset Consumer** | Xem Scorecard, kiểm tra độ bao phủ trước khi dùng | Người phân tích dữ liệu, Data Scientist, Business Analyst | Theo nhu cầu truy vấn |
| **ACT-H-006: Workspace / Tenant Administrator** | Quản trị tài khoản thành viên Workspace, phân vai trò RBAC, quản lý kết nối kênh thông báo (Email/Webhook/Slack) và cấu hình chính sách bảo mật nội bộ | Quản trị viên hệ thống / Quản trị viên dữ liệu tổ chức | Định kỳ / Khi thay đổi nhân sự & cấu hình kênh |
| **ACT-S-001: Data Source Provider** | Cung cấp file CSV/Parquet nguồn | Hệ thống lưu trữ tệp tin cục bộ | Tự động / Thủ công |

### 2.4. Môi trường vận hành (Operating Environment)
- **Hình thức triển khai:** Phân tách Control Plane (FastAPI API process + Worker process điều phối) và Compute Plane (Apache Spark thực thi đo lường trên k3s); PostgreSQL 16 là durable runtime store và metadata store duy nhất.
- **Phần cứng tham chiếu cơ sở:** CPU x86-64 / ARM64 (tối thiểu 4 Cores), **Trần tài nguyên toàn nút tối đa 8 GB RAM** cho cụm k3s đơn nút (Single-Node k3s), Ổ cứng SSD trống tối thiểu 20 GB. (Cụm phân tán nhiều nút vật lý 16–32 GB RAM là Profile Mở rộng Doanh nghiệp).
- **Hệ điều hành:** Microsoft Windows 11 (WSL2), Ubuntu Linux 22.04 LTS, macOS 13+ (Ventura).
- **Môi trường thực thi:** Python 3.13 (quản lý gói qua `uv` / Virtualenv), Cụm k3s (v1.28+) với Spark Operator và Apache Spark 3.5+, Streamlit 1.30+.

### 2.5. Ràng buộc thiết kế và cài đặt (Constraints)
- **C-01:** Phần lõi (Core Engine) phải độc lập hoàn toàn với Giao diện Web (Decoupled Core Facade).
- **C-02:** Xử lý dữ liệu bảng và đo lường chất lượng tối ưu hóa bằng Apache Spark trên cụm k3s đơn nút (thông qua Spark Operator / `SparkApplication`), thực thi vectorization và pushdown query trực tiếp trên snapshot nguyên bản.
- **C-03:** Phân tách tuyệt đối giữa Dataset Store (Object Storage / Local FS) và PostgreSQL 16 durable metadata/runtime store.
- **C-04:** Bất biến (Immutability): Snapshot và Assessment sau khi công bố không thể bị sửa đổi; snapshot lưu manifest JSON kiểm soát đường dẫn, kích thước, định dạng và mã băm SHA-256 từng tệp gốc cấu thành.
- **C-05:** Bảo toàn dữ liệu nguồn tuyệt đối: Chỉ đọc (Read-only execution); không sửa đổi, rewrite, xóa hoặc coalesce/compact làm thay đổi cấu trúc tệp dữ liệu gốc.
- **C-06:** Ranh giới Control Plane - Compute Plane: API chỉ tiếp nhận/enqueue; Worker là boundary duy nhất claim lease, đóng băng spec, dispatch và monitor `SparkApplication` trên k3s, đối soát attempt và xác thực lease fencing trước khi thực hiện giao dịch ghi nguyên tử công bố Assessment vào CSDL. Spark chỉ đọc snapshot và ghi metrics/evidence vào vùng artifacts riêng, không trực tiếp ghi Assessment vào CSDL.
- **C-07:** Monotonic lease fencing: Mọi heartbeat, state transition, result write và atomic publication phải được fence bằng `lease_generation`; retry/cancellation/attempt đều phải bounded và audit được.
- **C-08:** Ngân sách tài nguyên & Mức đồng thời cơ sở: Khống chế trần tài nguyên toàn nút $\le 8$ GB RAM (~3 GB OS/k3s/PostgreSQL/MinIO/API/Worker, ~4 GB SparkApplication driver + executor pods bao gồm JVM overhead, ~1 GB dự phòng hệ thống). Trên profile này, hỗ trợ tối đa 1 SparkApplication chạy tích cực tại một thời điểm; các run tiếp theo xếp hàng trong PostgreSQL.

---

## 3. YÊU CẦU GIAO DIỆN NGOÀI (EXTERNAL INTERFACE REQUIREMENTS)

### 3.1. Giao diện Người dùng (User Interfaces - IF-UI)

| ID | Yêu cầu giao diện | Mức ưu tiên | Trạng thái | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **IF-UI-001** | Hệ thống phải cung cấp Dashboard Web cho phép chọn Snapshot, cấu hình RunSpec, submit Run bất đồng bộ và theo dõi lifecycle. | P0 | BASELINED | Demonstration |
| **IF-UI-002** | Dashboard phải hiển thị tổng quan Scorecard: DQ Score, 6 Dimension Scores, Coverage, Score Publication Status, Quality Gate. | P0 | BASELINED | Test (UI) |
| **IF-UI-003** | Dashboard phải cung cấp tính năng Drill-down xem chi tiết từng quy tắc: trạng thái đo lường, mẫu số hợp lệ, số lượng vi phạm và bằng chứng dòng lỗi mẫu (10–50 dòng). | P0 | BASELINED | Test (UI) |
| **IF-UI-004** | Dashboard phải phân biệt trạng thái bằng cả Văn bản (Text) + Biểu tượng (Icon) + Màu sắc nhận diện (hỗ trợ tiếp cận WCAG). | P0 | BASELINED | Inspection |
| **IF-UI-005** | Dashboard phải hiển thị thanh tiến độ thực thi Run theo thời gian thực (Real-time Progress Bar: % hoàn thành, pha xử lý, ước lượng thời gian) qua HTTP Polling (5–10s) ở v1.0 và SSE ở v1.1. | P1 | BASELINED | Test (UI) |
| **IF-UI-006** | Giao diện phải hỗ trợ chế độ màu tối/sáng (Dark/Light Theme Mode), ghi nhớ cấu hình theo người dùng/trình duyệt và tuân thủ WCAG 2.1 AA về tỷ lệ tương phản tối thiểu 4.5:1. | P2 | PLANNED | Inspection |
| **IF-UI-007** | Dashboard phải cung cấp thanh tìm kiếm toàn văn (Full-Text Search) với tính năng gợi ý tự động (Autocomplete) cho Dataset, Run, Rule và Scorecard với độ trễ phản hồi $\le 300$ms. | P1 | PLANNED | Test (UI) |
| **IF-UI-008** | Giao diện phải cung cấp bộ lọc đa tiêu chí linh hoạt (Filter) kết hợp theo thời gian, trạng thái, dải điểm DQ, chiều chất lượng, cho phép lưu bộ lọc yêu thích và nút reset filter. | P1 | BASELINED | Test (UI) |
| **IF-UI-009** | Giao diện phải cung cấp bảng tra cứu lịch sử các lượt chạy (Job History View) với phân trang, hiển thị trạng thái, điểm DQ, số vi phạm, và thời lượng thực thi; hỗ trợ xuất danh sách ra CSV. | P0 | BASELINED | Demonstration |
| **IF-UI-010** | Hệ thống phải hỗ trợ sinh liên kết chia sẻ Scorecard an toàn (Share Dashboard Link) kèm mã token xác thực chỉ đọc (Read-only Token) có thời hạn (TTL) hoặc mã nhúng iframe cho Confluence/Notion. | P2 | DEFERRED | Contract Test |
| **IF-UI-011** | Giao diện phải tích hợp biểu mẫu phản hồi và báo lỗi (Feedback / Bug Report Widget) tự động đính kèm ngữ cảnh kỹ thuật (`run_id`, `snapshot_id`, stacktrace) gửi về hệ thống tiếp nhận sự cố. | P3 | PLANNED | Demonstration |
| **IF-UI-012** | Hệ thống phải cung cấp hướng dẫn tương tác từng bước (Interactive Tour Guide) cho người dùng mới qua các quy trình đăng ký asset, soạn thảo policy và đọc báo cáo; hỗ trợ lưu trạng thái đã xem. | P3 | PLANNED | Demonstration |
| **IF-UI-013** | Dashboard phải cung cấp ma trận nhiệt tương tác (Interactive Heatmap Matrix) trực quan hóa phân bố điểm chất lượng theo Bảng $\times$ Cột $\times$ 6 Chiều chất lượng, hỗ trợ click để drill-down. | P2 | PLANNED | Test (UI) |
| **IF-UI-014** | Dashboard phải cung cấp biểu đồ xu hướng chất lượng chuỗi thời gian (Data Quality Trend Chart) thể hiện biến thiên điểm DQ và từng chiều chất lượng; cho phép xuất biểu đồ ảnh hoặc tệp số liệu CSV. | P1 | PLANNED | Test (UI) |
| **IF-UI-015** | Trình xem bằng chứng vi phạm (Sample Error Viewer) phải hỗ trợ phân trang dòng lỗi và cung cấp nút tải xuống danh sách mẫu vi phạm (10–50 dòng) định dạng CSV đã qua che mờ PII (Redacted CSV). | P0 | BASELINED | Test (UI) |
| **IF-UI-016** | Giao diện phải cho phép người dùng ghim tối đa 20 tập dữ liệu yêu thích (Favorite Datasets) lên vị trí đầu trang chủ Dashboard để theo dõi nhanh và nhận cảnh báo ưu tiên. | P3 | PLANNED | Test (UI) |

### 3.2. Giao diện Phần mềm & Dữ liệu nguồn (Software Interfaces - IF-SRC)

| ID | Giao diện phần mềm | Mức ưu tiên | Trạng thái | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **IF-SRC-001** | Hệ thống phải tiếp nhận tệp dữ liệu nguồn bảng định dạng CSV (UTF-8, có dòng header) và Apache Parquet. | P0 | BASELINED | Integration Test |
| **IF-SRC-002** | Hệ thống phải lưu trữ tệp nhị phân trong Dataset Store và lưu metadata, source descriptor, mã băm SHA-256 trong PostgreSQL durable store. | P0 | BASELINED | Storage Test |
| **IF-SRC-003** | Hệ thống phải cung cấp typed `SourceAdapter` technology-neutral cho CSV/Parquet; vendor-specific Lakehouse adapter không thuộc baseline v1.0. | P0 | BASELINED | Contract Test |
| **IF-SRC-004** | API process phải cung cấp command/query boundary để submit, đọc trạng thái, đọc events và cancel Run; Worker process không bị gọi qua internal HTTP. | P0 | BASELINED | Contract Test |
| **IF-SRC-005** | Hệ thống phải cung cấp đầu nối tích hợp công cụ BI (Tableau, PowerBI, Looker) và dịch vụ xuất báo cáo định kỳ (Scheduled Export) qua cấu trúc bảng dẹt chuẩn hóa (Flattened Schema). | P1 | DEFERRED | Contract Test |
| **IF-SRC-006** | API process phải cung cấp giao diện RESTful công khai (Public REST API) chuẩn OpenAPI 3.1 cho phép truy vấn điểm DQ, lịch sử chạy và danh sách lỗi có phân trang (Pagination) và giới hạn tần suất (Rate Limiting). | P1 | DEFERRED | Contract Test |
| **IF-EXT-001** | Vendor-specific Lakehouse integration và Data Catalog từ xa được hoãn lại sau v1.0. | Post-1.0 | DEFERRED | Inspection |

### 3.3. Giao diện Truyền thông & Dòng lệnh (Communications & CLI Interfaces - IF-COM / IF-CLI)

| ID | Giao diện truyền thông & Dòng lệnh | Mức ưu tiên | Trạng thái | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **IF-COM-001** | API và Worker phải trao đổi qua PostgreSQL durable state, không phụ thuộc internal HTTP; API có thể expose HTTP boundary cho client. | P0 | BASELINED | Integration Test |
| **IF-COM-002** | TLS, Reverse Proxy và Firewall Allowlist áp dụng theo deployment; không được dùng localhost-only assumption trong contracts. | P0 | BASELINED | Security Inspection |
| **IF-CLI-001** | Hệ thống phải cung cấp giao diện dòng lệnh (CLI Interface) hỗ trợ đầy đủ các lệnh đăng ký asset, submit run, track progress, xuất báo cáo và đối soát mã băm bất biến. | P0 | BASELINED | CLI Test |
| **IF-CLI-002** | CLI phải hỗ trợ chế độ thực thi không đầu (Headless CI/CD Mode) với các tham số ngưỡng `--fail-under=<score>`, `--require-gate=<gate>`, trả về mã thoát phi không (Exit Code: 1 cho WARN, 2 cho FAIL) để chặn build tự động. | P1 | BASELINED | Automation Test |

---

## 4. YÊU CẦU CHỨC NĂNG (FUNCTIONAL REQUIREMENTS)

### 4.1. Phân hệ Quản lý Data Asset và Snapshot (FR-ASSET)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-ASSET-001** | Hệ thống phải cho phép đăng ký Data Asset với định danh logic, tên hiển thị, nguồn gốc và định dạng. | P0 | BASELINED | Asset được lưu trong metadata store; thiếu tên bị từ chối (Test). |
| **FR-ASSET-002** | Hệ thống phải tạo Dataset Snapshot bất biến gắn với Data Asset, gán Snapshot ID và sinh manifest JSON liệt kê đường dẫn, kích thước, định dạng và mã băm SHA-256 từng tệp (hỗ trợ tập dữ liệu đơn tệp hoặc nhiều tệp gốc - multi-file raw snapshot); tính mã băm tổng thể manifest SHA-256. Tuyệt đối không compact/coalesce hay chuyển đổi định dạng tệp gốc trước khi đánh giá. | P0 | BASELINED | Snapshot và manifest lưu thành công; kiểm tra mã băm SHA-256 khớp 100% từng tệp vật lý (Test). |
| **FR-ASSET-003** | Hệ thống phải tự động phát hiện schema (tên cột, kiểu dữ liệu inferred) và ghi nhận vào Snapshot metadata. | P0 | BASELINED | Trích xuất đúng danh sách cột và kiểu dữ liệu trên Chicago Taxi dataset (Test). |
| **FR-ASSET-004** | Hệ thống phải bảo đảm tính chỉ đọc (Read-only) tuyệt đối trên toàn bộ các tệp nguồn cấu thành snapshot; Spark và Worker không được phép ghi đè, xóa hoặc thay đổi bất kỳ byte nào của các tệp nguồn. | P0 | BASELINED | Tệp nguồn giữ nguyên 100% mã băm SHA-256 trước và sau quá trình đánh giá (Test). |

### 4.2. Phân hệ Lập hồ sơ dữ liệu (Profiling Engine - FR-PROF)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-PROF-001** | Hệ thống phải lập Profiling Plan tối ưu hóa, chỉ tính các chỉ số cần thiết cho Ruleset và Outlier Config. | P0 | BASELINED | Plan không tính các metric dư thừa ngoài phạm vi đánh giá (Inspection). |
| **FR-PROF-002** | Hệ thống phải tính toán các chỉ số thống kê cơ bản: row count, null count, distinct count, min/max, numeric quartiles. | P0 | BASELINED | Các chỉ số thống kê khớp 100% kết quả tính độc lập trên golden fixture (Test). |
| **FR-PROF-003** | Toàn bộ các quy tắc và bộ phát hiện trong cùng một Run phải tái sử dụng chung tập `Canonical Metrics`. | P0 | BASELINED | Snapshot chỉ được quét 1 lần duy nhất trong quá trình Profiling (Test). |
| **FR-PROF-004** | Mỗi Canonical Metric phải lưu rõ Snapshot ID, tên cột, phương pháp đo và thời điểm tạo. | P0 | BASELINED | Truy vết đầy đủ nguồn gốc của từng metric trong audit record (Test). |
| **FR-PROF-005** | Phiên bản 1.0 phải thực hiện quét toàn bộ (Full Scan) trên Snapshot; chế độ Sampling hoãn lại sau v1.0. | P0 | BASELINED | Run metadata ghi rõ `scan_mode = FULL` (Test). |

### 4.3. Phân hệ Quản trị Quy tắc và Cấu hình (Governance - FR-GOV)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-GOV-001** | Hệ thống phải lưu trữ Ruleset, Scoring Policy và Outlier Config dưới dạng cấu hình có phiên bản và mã băm. | P0 | BASELINED | Cùng mã băm cấu hình luôn trả về nội dung quy tắc đồng nhất (Test). |
| **FR-GOV-002** | Mỗi quy tắc phải khai báo: Rule ID, Tên, Chiều chất lượng (Dimension), Cột mục tiêu, Tham số, Null Policy, Trọng số và Mức nghiêm trọng (`critical`/`standard`). | P0 | BASELINED | Cấu hình thiếu tham số bắt buộc bị từ chối trước khi chạy (Test). |
| **FR-GOV-003** | Hệ thống phải hỗ trợ đầy đủ 4 chính sách Null Policy: `fail`, `ignore`, `separate`, `not_applicable`. | P0 | BASELINED | Golden tests chứng minh mẫu số và outcome thay đổi chính xác theo null policy (Test). |
| **FR-GOV-004** | Thay đổi bất kỳ thông số nào trong Ruleset hoặc Scoring Policy phải tự động sinh ra mã băm cấu hình mới. | P0 | BASELINED | Tính bất biến của phiên bản cấu hình được bảo toàn (Test). |
| **FR-GOV-005** | Hệ thống phải cho phép Data Steward tạo `RulesetRevision` / `ScoringPolicyRevision` ở trạng thái `DRAFT`; cấu hình `DRAFT` không thể gán vào `RunSpec`. | P0 | BASELINED | Thử gán revision DRAFT vào RunSpec → hệ thống từ chối với lỗi `CONFIGURATION_NOT_APPROVED` (Test). |
| **FR-GOV-006** | Phê duyệt Ruleset và Scoring Policy là thao tác riêng sau submit; chỉ revision `ACTIVE` được `RunSpec` tham chiếu. Mặc định người tạo/submit không tự duyệt. Ngoại lệ: `WORKSPACE_ADMIN` trong tenant hiện tại được tự duyệt ruleset/policy `PENDING_APPROVAL` với lý do bắt buộc 1–500 ký tự sau trim và audit nguyên tử; không áp dụng template hoặc privacy. | P0 | BASELINED | Non-admin tự duyệt bị 403; Admin thiếu lý do bị 422; lỗi audit rollback cả approval/supersession; cả hai cấu hình ACTIVE mới được tạo Run và Quality Gate không đổi (Test). |
| **FR-GOV-007** | Hệ thống phải ghi nhận `actor_id` và `timestamp` riêng biệt cho hành động `submit` (Data Steward) và `approve` (Data Owner) trong audit trail. | P0 | BASELINED | Bản ghi audit chứa đủ submitted_by, submitted_at, approved_by, approved_at (Test). |
| **FR-GOV-011** | Hệ thống phải cung cấp **Kho Rule Tập Trung (Centralized Rule Catalog)** quản lý các bản mẫu quy tắc chuẩn hóa (`RuleCatalogTemplate`) cho phép tái sử dụng khi tạo mới quy tắc kiểm tra chất lượng. | P0 | BASELINED | Cho phép tra cứu mẫu quy tắc chuẩn, kế thừa schema tham số và Null Policy mặc định (Test). |
| **FR-GOV-012** | Hệ thống phải quản lý tập trung danh mục Quy tắc Phân loại Dữ liệu Nhạy cảm (`ClassificationRule`) và Chính sách Che mờ Dữ liệu (`DataProtectionPolicy`), tách bạch với quy tắc chất lượng dữ liệu kỹ thuật. | P0 | BASELINED | Phân định rõ ràng 3 phân hệ cấu hình độc lập trên PostgreSQL với vòng đời phê duyệt riêng (Test). |
| **FR-GOV-013** | Hệ thống phải cung cấp thư viện **Mẫu Bộ Quy tắc Đánh giá (`RulesetTemplate`)** chuẩn hóa theo từng Domain nghiệp vụ (Tài chính, Bán lẻ, Y tế, Vận tải/Logistics), loại dữ liệu (Bảng chiều, Sự kiện giao dịch, Master Data) và mục đích sử dụng. Bản mẫu định nghĩa sẵn danh sách rule types, mức độ nghiêm trọng (`critical`/`standard`), trọng số quy tắc, tham số chuẩn và ánh xạ cột logic; khi áp dụng sẽ nhân bản thành `RulesetRevision` ở trạng thái `DRAFT` thuộc tenant để tùy biến và phê duyệt độc lập. | P0 | BASELINED | Áp dụng template tạo đúng Ruleset DRAFT theo tenant, kế thừa trọn vẹn quy tắc và lưu vết `derived_from_template_id` (Test). |
| **FR-GOV-014** | Hệ thống phải cung cấp thư viện **Mẫu Chính sách Tính điểm (`ScoringPolicyTemplate`)** tương thích với từng Domain và mục đích sử dụng. Bản mẫu định nghĩa sẵn bộ trọng số 6 chiều ($W_d$), các ngưỡng phân loại Quality Gate (`pass_min`, `warn_min`), và ngưỡng bao phủ công bố `publication_threshold` (mặc định chuẩn `0.80`); khi áp dụng sẽ nhân bản thành `ScoringPolicyRevision` ở trạng thái `DRAFT` thuộc tenant để tùy biến và phê duyệt độc lập. | P0 | BASELINED | Áp dụng template tạo đúng Scoring Policy DRAFT theo tenant, kế thừa trọng số/ngưỡng và lưu vết `derived_from_template_id` (Test). |

### 4.4. Phân hệ Quản lý Lượt Đánh giá (Evaluation Run - FR-RUN)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-RUN-001** | Hệ thống phải tiếp nhận yêu cầu chạy (`RunSpec`) gồm: Snapshot ID, Ruleset, Scoring Policy, Outlier Config, idempotency key và tham số `priority` (tùy chọn, mặc định 5=Normal; 1=Interactive cho on-demand tức thì; 10=Batch cho lịch định kỳ). | P0 | BASELINED | API tạo đúng một Run ID và trả trạng thái `QUEUED`; request lặp lại trả cùng Run (Test). |
| **FR-RUN-002** | Hệ thống phải kiểm tra Snapshot tồn tại, schema tương thích và cả Ruleset lẫn Policy đều `ACTIVE` trước khi enqueue. | P0 | BASELINED | Thiếu Snapshot, lệch schema hoặc cấu hình chưa ACTIVE bị từ chối sớm (Test). |
| **FR-RUN-003** | Hệ thống phải đóng băng toàn bộ cấu hình đầu vào, gồm Outlier Config và `outlier_config_hash`, trong RunSpec snapshot trước khi enqueue. | P0 | BASELINED | Mọi sửa đổi cấu hình ngoài luồng không làm ảnh hưởng Run đang chạy (Test). |
| **FR-RUN-004** | Quản lý trạng thái durable của Run qua `QUEUED`, `LEASED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`; cancellation được audit và chỉ cho phép ở trạng thái hợp lệ. | P0 | BASELINED | State transition bất hợp lệ bị từ chối; Worker chỉ chạy sau khi claim lease (Test). |
| **FR-RUN-005** | Phân tách rạch ròi giữa lỗi thực thi kỹ thuật và lỗi chất lượng dữ liệu. Lỗi đọc Snapshot, DB, Profiling hoặc Scoring cốt lõi làm Run `FAILED`; không tạo Assessment. | P0 | BASELINED | Lỗi kỹ thuật ghi `EXECUTION_ERROR`, không tạo vi phạm dữ liệu giả hay Assessment không hoàn chỉnh (Test). |
| **FR-RUN-006** | Công bố Assessment nguyên tử (Atomic Publication): chỉ publish một lần khi Worker còn lease hợp lệ; kết quả bị fencing không được ghi. | P0 | BASELINED | Result rows, Assessment, event và `SUCCEEDED` commit cùng transaction (Test). |
| **FR-RUN-007** | Worker phải heartbeat trong lease, khôi phục Run hết lease bằng generation mới và fence mọi heartbeat/write/publish của Worker cũ. | P0 | BASELINED | Crash/recovery không mất job và Worker cũ không thể ghi đè (Fault Test). |
| **FR-RUN-008** | Hệ thống phải hỗ trợ cancellation có kiểm soát; Worker dừng tại cancellation checkpoint và không công bố Assessment. | P0 | BASELINED | Cancel trước claim hoặc trong execution tạo audit event và không có Assessment mới (Test). |
| **FR-RUN-009** | Retry chỉ áp dụng cho lỗi kỹ thuật retryable với số attempt và backoff bounded; không retry sau khi source read không còn replayable. | P0 | BASELINED | Retry matrix và attempt cap được thực thi, lỗi non-retryable kết thúc `FAILED` (Test). |
| **FR-RUN-010** | Hệ thống phải lưu vết toàn bộ lịch sử các lượt chạy (Job Execution History) gồm timestamp bắt đầu/kết thúc, thời lượng, trạng thái hoàn tất, điểm DQ Score và tổng số vi phạm; cho phép truy vấn lọc và xuất lịch sử. | P0 | BASELINED | API trả về danh sách lịch sử đầy đủ và phân trang chính xác từ `evaluation_runs` (Test). |
| **FR-RUN-011** | Hệ thống phải hỗ trợ cơ chế đánh giá chất lượng **bất đồng bộ kích hoạt sau khi snapshot commit trên Lakehouse**; API tiếp nhận bất đồng bộ (non-blocking) qua hàng đợi bền vững PostgreSQL 16; Worker điều phối tính toán bằng cách gửi và theo dõi `SparkApplication` trên cụm k3s, trả về kết quả đo lường phân hoạch trước khi Worker thực hiện chấm điểm và công bố nguyên tử. | P0 | BASELINED | Pipeline tiếp nhận nhận ngay Run ID với trạng thái `QUEUED`, Worker xử lý nền và công bố Assessment nguyên tử cùng giao dịch (Integration Test). |
| **FR-RUN-012** | Hệ thống phải cung cấp giao diện lập trình tiếp nhận đánh giá hàng loạt đa tài sản (`POST /api/v1/runs/batch`) [Thiết kế Mở rộng]; phân tách payload thành các `EvaluationRun` độc lập theo từng tài sản và tenant, trả về danh sách `run_id` tương ứng; lỗi kiểm thực của một tài sản không làm gián đoạn việc tiếp nhận các tài sản hợp lệ khác. | P1 | EXTENSION | API trả về mã HTTP 202 Accepted và mảng danh sách Run ID độc lập cho các asset hợp lệ (Test). |

### 4.5. Phân hệ Kiểm tra Quy tắc Xác định (Rule Engine - FR-VAL)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-VAL-001** | Rule Engine phải thực thi từng quy tắc trên đúng Snapshot và phạm vi cột được khai báo. | P0 | BASELINED | Kết quả kiểm tra phản ánh chính xác dữ liệu thực tế của cột mục tiêu (Test). |
| **FR-VAL-002** | Hỗ trợ 5 nhóm quy tắc xác định lõi: (1) Non-null, (2) Type/Parse, (3) Domain/Range, (4) Uniqueness, (5) Cross-field. | P0 | BASELINED | Đạt 100% Golden Test Cases cho 5 nhóm quy tắc trên Chicago Taxi data (Test). |
| **FR-VAL-003** | Phân loại kết quả từng bản ghi thành các tập loại trừ lẫn nhau: `passed`, `failed`, `missing`, `miscast`, `not_applicable`. | P0 | BASELINED | Invariant: $passed + failed + missing + miscast + not\_applicable = total\_observed$ (Test). |
| **FR-VAL-004** | Trạng thái đo lường (Measurement Status) của từng quy tắc phải được xác định độc lập: `MEASURED`, `NOT_APPLICABLE`, `NOT_MEASURABLE`, `FAILED_TO_MEASURE`. | P0 | BASELINED | Xác định đúng trạng thái cho từng quy tắc trong mọi kịch bản biên (Test). |
| **FR-VAL-005** | Trường hợp mẫu số bằng 0 (Zero Denominator) phải trả về `NOT_APPLICABLE` hoặc `NOT_MEASURABLE`, không gán điểm 0 hoặc 100. | P0 | BASELINED | Không phát sinh Rule Score khi mẫu số bằng 0 (Test). |
| **FR-VAL-006** | Chuẩn hóa kết quả quy tắc thành `Canonical Quality Result` gồm đầy đủ metadata, counts, metrics, config hash và bounded evidence. | P0 | BASELINED | Khớp 100% Canonical Schema Specification (Contract Test). |

### 4.6. Phân hệ Phát hiện Ngoại lệ Thống kê (IQR Outlier Detector - FR-DET)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-DET-001** | Hệ thống phải cung cấp bộ phát hiện ngoại lệ IQR đơn biến trên các cột số với hệ số $k=1.5$ cấu hình được. | P0 | BASELINED | Tính đúng tứ phân vị $Q1, Q3, IQR$ và ranh giới $[Q1-1.5 \cdot IQR, Q3+1.5 \cdot IQR]$ (Test). |
| **FR-DET-002** | Kết quả Outlier phải ghi rõ: ranh giới dưới/trên, số lượng bản ghi dị biệt, tỷ lệ dị biệt và danh sách dòng mẫu. | P0 | BASELINED | Khớp kết quả kỳ vọng trên tập dữ liệu Golden Outlier Fixture (Test). |
| **FR-DET-003** | Xử lý an toàn các trường hợp biên: toàn bộ cột là null, dữ liệu < 4 bản ghi, hoặc $IQR = 0$ phải trả `NOT_MEASURABLE` với lý do rõ ràng. | P0 | BASELINED | Đạt 100% boundary cases, không gây crash hệ thống (Test). |
| **FR-DET-004** | Chuẩn hóa kết quả Outlier thành `Canonical Quality Result` ở chế độ cảnh báo (`ADVISORY`). | P0 | BASELINED | Tín hiệu mang cờ `is_advisory = True` và `contribution_weight = 0` (Test). |
| **FR-DET-005** | Tín hiệu Outlier trong v1.0 tuyệt đối không làm thay đổi DQ Score hoặc trạng thái Quality Gate. | P0 | BASELINED | DQ Score và Gate giữ nguyên khi có hoặc không có Outlier Signal (Test). |
| **FR-DET-006** | Lỗi Outlier Detector phải sinh `CanonicalQualityResult(status=FAILED_TO_MEASURE, is_advisory=true, contribution_weight=0)` cho từng cột cấu hình; không làm giảm Coverage score-enabled hoặc cản trở Assessment. | P0 | BASELINED | Khi Outlier lỗi, Rule Results, DQ Score và Assessment vẫn được công bố bình thường (Fault Test). |
| **FR-DET-007** | Mở rộng phát hiện ngoại lệ bằng các mô hình máy học đa biến (Isolation Forest, One-Class SVM) hoặc so sánh baseline lịch sử (Drift Detection) được xếp vào lộ trình sau v1.0 và luôn giữ nguyên tắc chỉ đóng vai trò cảnh báo (`ADVISORY`, trọng số 0). | P2 | DEFERRED | Inspection |

### 4.7. Phân hệ Tính Điểm và Cổng Chất lượng (Score Engine - FR-SCORE)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-SCORE-001** | Score Engine chỉ được đọc dữ liệu từ `Canonical Quality Results` và `Scoring Policy`, không quét lại dữ liệu nguồn. | P0 | BASELINED | Phân tách hoàn toàn tầng tính điểm và tầng đọc dữ liệu (Architecture Test). |
| **FR-SCORE-002** | Tính Rule Score bằng tỷ lệ số bản ghi đạt trên số bản ghi đủ điều kiện theo Null Policy bao hàm Miscast: $Score_{rule} = \frac{Passed}{Passed + Failed + Miscast + Missing_{penalized}} \times 100$ (với $Missing_{penalized} = Missing$ khi Null Policy là `fail`, và $= 0$ khi thuộc `{'ignore', 'separate', 'not_applicable'}`; khi mẫu số bằng 0, điểm là `null` với trạng thái `NOT_APPLICABLE` hoặc `NOT_MEASURABLE`, tuyệt đối không ép về 0 hay 100). | P0 | BASELINED | Đạt 100% ca kiểm thử công thức toán học và zero denominator (Test). |
| **FR-SCORE-003** | Tạo đúng 6 Dimension Results. Chiều có rule hợp lệ là `MEASURED`; policy xác nhận không áp dụng là `NOT_APPLICABLE`; policy yêu cầu nhưng thiếu metadata/reference/SLA là `NOT_MEASURABLE` với score `null`. | P0 | BASELINED | Không dimension nào bị ép thành điểm 0 khi không đo được (Test). |
| **FR-SCORE-004** | Tính DQ Score theo trung bình có trọng số và tái chuẩn hóa denominator trên các dimension `MEASURED`; công bố Coverage riêng. | P0 | BASELINED | DQ Score nằm trong $[0,100]$ và không che giấu dimension thiếu bằng chứng (Property Test). |
| **FR-SCORE-005** | Tính Coverage bằng tổng trọng số rule score-enabled đã đo trên tổng trọng số rule policy kỳ vọng; `NOT_APPLICABLE` đã được policy xác nhận bị loại khỏi denominator, còn `NOT_MEASURABLE` và `FAILED_TO_MEASURE` làm giảm Coverage. | P0 | BASELINED | Coverage độc lập với DQ Score và không bị ảnh hưởng bởi Outlier advisory trọng số 0 (Test). |
| **FR-SCORE-006** | Chỉ `PUBLISHED` khi Run hợp lệ (`run_status == 'SUCCEEDED'`), không có bất kỳ phép đo bắt buộc nào (cả score-enabled lẫn gate-only) bị lỗi kỹ thuật `FAILED_TO_MEASURE` (tức Quality Gate không bị `ERROR`), không có bất kỳ phép đo bắt buộc nào (cả score-enabled lẫn gate-only) không đo được (`NOT_MEASURABLE`, `INSUFFICIENT_DATA`, `SKIPPED_BY_BUDGET`), tất cả chiều bắt buộc đều có ít nhất một quy tắc được đo lường thành công và Coverage $\ge 80\%$; ngược lại là `WITHHELD` với `dq_score = null`. | P0 | BASELINED | Coverage thấp hoặc required measurement lỗi/thiếu đều giữ lại DQ Score (Test). |
| **FR-SCORE-007** | Với Run hoàn tất (không sập hạ tầng), đánh giá Quality Gate trong bộ nhớ theo đúng thứ tự ưu tiên 6 cấp bậc của BR-010: (1) `ERROR` khi có bất kỳ phép đo bắt buộc nào (`is_required = True`, bao gồm cả score-enabled lẫn gate-only) bị `FAILED_TO_MEASURE`, (2) Critical `FAIL` khi có quy tắc critical bị vi phạm (theo Zero-Tolerance hoặc theo ngưỡng riêng), (3) `INSUFFICIENT_EVIDENCE` khi thiếu phép đo bắt buộc hoặc Coverage < 80%, (4) `FAIL` khi DQ Score < 60, (5) `WARN` khi 60 $\le$ DQ Score < 80, (6) `PASS` khi DQ Score $\ge$ 80. Run `FAILED` do sự cố hệ thống không có Assessment hay Gate. | P0 | BASELINED | Đạt 100% Golden Test Cases về Gate Precedence (Test). |
| **FR-SCORE-008** | Quy tắc `critical` bị vi phạm buộc Quality Gate về `FAIL` bất kể DQ Score tổng hợp đạt mức nào. | P0 | BASELINED | Điểm 95 nhưng có critical rule vi phạm thì Gate vẫn là `FAIL` (Test). |
| **FR-SCORE-009** | Confidence Status trong phiên bản v1.0 full scan luôn ghi nhận là `NOT_APPLICABLE` (không tạo số giả). | P0 | BASELINED | Assessment không chứa trường số Confidence giả lập (Test). |

### 4.8. Phân hệ Quản lý và Công bố Báo cáo (Assessment - FR-ASM)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-ASM-001** | Mỗi Run hoàn tất measurement thành công (`SUCCEEDED`) phải persist đúng một `Immutable Assessment`; Assessment `WITHHELD` vẫn được lưu với `dq_score = null`. | P0 | BASELINED | Bản ghi Assessment mang tính bất biến và được lưu trong PostgreSQL (Test). |
| **FR-ASM-002** | Assessment phải chứa DQ Score, đúng 6 Dimension Results, Coverage, Publication Status, Quality Gate, hash Snapshot/Ruleset/Policy/Outlier Config, `assessment_hash` và Bounded Evidence. | P0 | BASELINED | Kiểm tra đầy đủ các trường theo schema quy định (Contract Test). |
| **FR-ASM-003** | Bằng chứng vi phạm (Evidence) phải được khống chế số dòng (10–50 dòng) và che mờ dữ liệu nhạy cảm (Redaction). | P0 | BASELINED | Không tràn bộ nhớ và không làm lộ dữ liệu nhạy cảm (Security Test). |
| **FR-ASM-004** | Tệp dữ liệu quét tạm thời và artifacts trong quá trình Spark execution phải được tự động dọn dẹp sau khi Run kết thúc. | P0 | BASELINED | Thư mục tạm thời và staging artifacts sạch sẽ sau mỗi lượt chạy (Storage Test). |
| **FR-ASM-005** | Hệ thống phải hỗ trợ xuất báo cáo kết quả đánh giá ra các định dạng chuẩn hóa: JSON Canonical (đầy đủ cấu trúc), HTML tĩnh độc lập (standalone kèm CSS inline), CSV/Excel bảng số liệu và schema mở rộng cho công cụ BI (Tableau, PowerBI). | P1 | BASELINED | Tệp xuất bảo đảm tính toàn vẹn và đối soát khớp 100% bản ghi Assessment gốc (Contract Test). |

### 4.9. Phân hệ Lập lịch và Tự động hóa (Scheduling & Automation - FR-SCHED)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-SCHED-001** | Hệ thống phải hỗ trợ thiết lập lịch chạy đánh giá tự động định kỳ (Hàng giờ, hàng ngày, hàng tuần) theo biểu thức Cron cho từng cặp Snapshot/Ruleset. | P2 | DEFERRED | Kích hoạt đúng lịch biểu và sinh `RunSpec` hợp lệ đưa vào durable queue (Integration Test). |
| **FR-SCHED-002** | Hệ thống phải cung cấp cơ chế bù lịch (Missed Run Catch-up) và kiểm soát số lần retry tối đa khi job lập lịch bị gián đoạn do sự cố hạ tầng. | P2 | DEFERRED | Không sinh job trùng lặp và tự động phục hồi lịch sau sự cố (Fault Test). |

### 4.10. Phân hệ Cộng tác và Khuyến nghị Chất lượng (Collaboration & Remediation - FR-COLLAB / FR-RECOM / FR-ROOT)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-COLLAB-001** | Hệ thống phải cho phép người dùng đính kèm ghi chú, giải trình ngữ cảnh (Annotations / Comments) và gắn thẻ thành viên thảo luận trên từng quy tắc, bảng dữ liệu hoặc kết quả đánh giá. | P2 | DEFERRED | Bản ghi annotation lưu trữ liên kết khóa ngoại và hiển thị đúng ngữ cảnh (Integration Test). |
| **FR-RECOM-001** | Hệ thống phải tự động phân tích vi phạm và đề xuất khuyến nghị khắc phục chất lượng dữ liệu (Actionable Remediation Recommendations) kèm đoạn mã mẫu SQL / Python tương ứng. | P2 | DEFERRED | Khuyến nghị mang tính chất tư vấn (Advisory) và khớp logic vi phạm đo lường (Inspection). |
| **FR-ROOT-001** | Hệ thống phải hỗ trợ đối soát tương quan và gợi ý nguyên nhân gốc (Root Cause Suggestion) gây suy giảm chất lượng dựa trên lịch sử thay đổi schema và metadata pipeline. | P3 | DEFERRED | Đưa ra cảnh báo ngữ cảnh hỗ trợ điều tra sự cố (Inspection). |

### 4.11. Phân hệ Quản trị Danh tính, Xác thực và Tài khoản (Identity, Authentication & Account Management - FR-AUTH)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-AUTH-001** | Đăng ký Người dùng & Khởi tạo Workspace: Cho phép người dùng đăng ký tài khoản (email, họ tên, mật khẩu), tự động tạo Workspace/Tenant mới (với vai trò `WORKSPACE_ADMIN`) hoặc tiếp nhận lời mời tham gia Workspace hiện có qua mã mời (Invitation Token). | P0 | BASELINED | Tạo tài khoản, khởi tạo tenant và cấp phát vai trò quản trị viên hợp lệ (Integration Test). |
| **FR-AUTH-002** | Xác thực & Cấp phát Token Phiên: Xác thực thông tin đăng nhập (email + mật khẩu) bằng thuật toán băm Argon2id (RFC 9106); cấp phát cặp Access Token (JWT, TTL ngắn 15–30 phút, chứa `user_id`, `tenant_id`, `roles`, `scopes`) và Refresh Token (Opaque Token UUIDv4, TTL dài 7–14 ngày, lưu hash SHA-256 trong CSDL). | P0 | BASELINED | Token JWT ký chuẩn RS256/EdDSA, claims đầy đủ, từ chối mật khẩu sai (Security Test). |
| **FR-AUTH-003** | Xoay vòng & Phát hiện Tái sử dụng Refresh Token (Refresh Token Rotation): Mỗi lần cấp lại Access Token mới, hệ thống tự động xoay vòng Refresh Token (hủy token cũ, cấp token mới); nếu phát hiện Refresh Token cũ bị gửi lại (Token Reuse), lập tức thu hồi toàn bộ phiên làm việc của người dùng. | P0 | BASELINED | Hủy token cũ sau khi dùng, thu hồi toàn bộ session khi phát hiện reuse (Security Test). |
| **FR-AUTH-004** | Khóa Tài khoản Tạm thời & Chống Brute-Force: Tự động khóa tài khoản tạm thời 15 phút sau 5 lần đăng nhập thất bại liên tiếp; áp dụng giới hạn tần suất (Rate Limiting qua Token Bucket) theo IP và theo tài khoản đăng nhập. | P0 | BASELINED | Chặn request thứ 6 trong 15 phút và kích hoạt rate limit (Security Test). |
| **FR-AUTH-005** | Đăng xuất & Hủy Phiên Tức thì: Cho phép người dùng đăng xuất phiên hiện tại hoặc đăng xuất toàn bộ thiết bị (Revoke All Sessions); vô hiệu hóa Refresh Token trong CSDL ngay lập tức; không cho phép tái sử dụng phiên đã đăng xuất. | P0 | BASELINED | Refresh token bị thu hồi, Access token bị từ chối sau TTL (Integration Test). |
| **FR-AUTH-006** | Đặt lại Mật khẩu An toàn (Self-Service Password Reset): Cung cấp luồng đặt lại mật khẩu qua email với mã Token một lần (Single-use Token) ký mã hóa có thời hạn sống $\le 15$ phút; không làm lộ trạng thái tồn tại của tài khoản cho người ngoài. | P1 | BASELINED | Token một lần hết hạn sau 15 phút, mật khẩu mới cập nhật thành công (Functional Test). |
| **FR-AUTH-007** | Mời Thành viên & Phân quyền Workspace (Workspace Invitation & RBAC): Cho phép `WORKSPACE_ADMIN` gửi thư mời qua email và gán trước một trong 4 vai trò nghiệp vụ (`DATA_STEWARD`, `DATA_OWNER`, `DATA_ENGINEER`, `BUSINESS_VIEWER`); người được mời kích hoạt tài khoản qua Token liên kết có hạn sống 48 giờ. | P0 | BASELINED | Thư mời được ghi nhận, gán đúng tenant và vai trò sau khi kích hoạt (Integration Test). |
| **FR-AUTH-008** | Quản lý Khóa API Cá nhân (Personal API Key Management): Cho phép người dùng sinh API Key định danh kèm phạm vi quyền (`scopes`) và thời hạn sống phục vụ tích hợp CI/CD hoặc gọi tự động; khóa bí mật chỉ hiển thị 1 lần lúc tạo và lưu mã băm an toàn trong CSDL. | P1 | BASELINED | API Key xác thực thành công qua header Bearer, kiểm tra scope chính xác (Security Test). |

### 4.12. Phân hệ Thông báo Đa kênh, Cảnh báo Sự kiện và Webhook (Notification, Alerting & Webhooks - FR-NOTIF)

| ID | Yêu cầu chức năng | Pri | Status | Tiêu chí nghiệm thu & Phương pháp |
| :--- | :--- | :--- | :--- | :--- |
| **FR-NOTIF-001** | Cấu hình Kênh Thông báo Đa kênh (Multi-Channel Notification Configuration): Cho phép `WORKSPACE_ADMIN` khai báo, kiểm thử kết nối và quản lý các kênh thông báo thuộc Workspace: Email (SMTP), Webhook HTTP/HTTPS, Slack Incoming Webhook, Microsoft Teams Webhook. | P1 | BASELINED | Lưu trữ cấu hình kênh mã hóa bí mật, kiểm thử ping kênh thành công (Integration Test). |
| **FR-NOTIF-002** | Đăng ký Nhận Cảnh báo theo Sự kiện & Mức độ Nghiêm trọng (Event & Severity Subscriptions): Cho phép thành viên hoặc nhóm vai trò đăng ký nhận thông báo theo loại sự kiện (`RUN_FAILED`, `QUALITY_GATE_FAIL`, `POLICY_SUBMITTED_FOR_APPROVAL`, `PII_DETECTED_WARNING`) và ngưỡng nghiêm trọng tối thiểu (`INFO`, `WARN`, `CRITICAL`). | P1 | BASELINED | Định tuyến đúng thông báo tới các tài khoản đã đăng ký sự kiện tương ứng (Event Test). |
| **FR-NOTIF-003** | Định tuyến & Phân phối Cảnh báo Bất đồng bộ (Async Alert Dispatching): Worker đẩy sự kiện vào bảng Outbox CSDL ngay tại checkpoint hoàn tất; tác vụ Dispatcher nền đọc outbox và gửi thông báo bất đồng bộ, không làm nghẽn tiến trình tính điểm cốt lõi. | P1 | BASELINED | Độ trễ dispatch $\le 60$ giây; tiến trình worker không bị ảnh hưởng bởi kênh ngoại vi (Perf Test). |
| **FR-NOTIF-004** | Ký số Xác thực Webhook (HMAC-SHA256 Signed Webhook Payload): Toàn bộ thông báo Webhook gửi ra ngoài bắt buộc được ký bằng mã băm HMAC-SHA256 với secret của kênh (`X-DQ-Signature: sha256=...`) kèm timestamp (`X-DQ-Timestamp`), bảo đảm tính toàn vẹn và chống tấn công phát lại (Replay Attack). | P1 | BASELINED | Chữ ký khớp payload và secret; từ chối request có timestamp chênh lệch $> 300$ giây (Security Test). |
| **FR-NOTIF-005** | Phòng vệ SSRF cho Webhook (SSRF Protection & Safe Outbound Dispatch): Hệ thống kiểm tra và chặn đứng tuyệt đối mọi Webhook URL trỏ đến dải địa chỉ nội bộ, IP loopback (`127.0.0.1`, `localhost`), dải mạng riêng tư (RFC 1918) hoặc IP dịch vụ siêu dữ liệu đám mây (`169.254.169.254`); áp dụng DNS Pinning ngăn ngừa tấn công DNS Rebinding. | P0 | BASELINED | Chặn 100% URL nội bộ và metadata cloud ngay trước khi kết nối (Security Test). |
| **FR-NOTIF-006** | Bản tin Tóm tắt Định kỳ (Scheduled Email Quality Digest): Tự động tổng hợp số liệu chất lượng định kỳ (tuần/tháng) của các Data Asset trong Workspace (top suy giảm điểm, top vi phạm, tỷ lệ bao phủ) và gửi bản tin email cho các thành viên đăng ký. | P2 | DEFERRED | Phát đúng lịch biểu Cron và tổng hợp số liệu chính xác (Integration Test). |

---

## 5. YÊU CẦU PHI CHỨC NĂNG (NON-FUNCTIONAL REQUIREMENTS)

### 5.1. Hiệu năng và Ngân sách Tài nguyên (Performance - NFR-PERF)

| ID | Yêu cầu phi chức năng | Ngưỡng mục tiêu (Target Budget) | Status | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **NFR-PERF-001** | Thời gian thực thi toàn luồng End-to-End SLA (tính từ API tiếp nhận `202 Accepted` / `QUEUED` đến khi hoàn tất và `PUBLISHED` trên API/Dashboard, bao gồm thời gian chờ hàng đợi, khởi tạo Pod Spark 10–25s, đọc dữ liệu, tính toán Profiling + Validation + Outlier, và công bố nguyên tử) trên tập dữ liệu Vertical Slice (~100.000 dòng). | Mục tiêu thiết kế $\le 120$ giây trên môi trường tham chiếu k3s đơn nút 8 GB RAM (chạy đơn lẻ, không kẹt hàng đợi) | TARGET_BENCHMARK | Benchmark Test (Đo kiểm thực nghiệm) |
| **NFR-PERF-002** | Đỉnh dung lượng bộ nhớ RAM của tác vụ tính toán Spark (`SparkApplication` Peak Memory RAM bao gồm Driver pod + Executor pod + JVM memory overhead). | $\le 4.0$ GB RAM (hoặc $\le 3.5$ GiB); đỉnh bộ nhớ toàn nút $\le 8.0$ GB RAM | TARGET_BENCHMARK | Resource Profiling (cAdvisor / kubectl top) |
| **NFR-PERF-003** | Dung lượng đĩa tạm (Temporary Disk Spill) trong quá trình xử lý Spark pod trên k3s. | $\le 1$ GB / pod | TARGET_BENCHMARK | Disk Monitoring |
| **NFR-PERF-004** | Thời gian tải và hiển thị Scorecard trên Local Dashboard từ Assessment Store đã lưu. | $\le 1.0$ giây | TARGET_BENCHMARK | UI Benchmark |
| **NFR-PERF-005** | Thời gian phản hồi tác vụ lập hồ sơ dữ liệu theo yêu cầu (On-Demand Profiling) cho đơn cột trên tập dữ liệu 100.000 dòng. | $\le 15.0$ giây (bao gồm khởi tạo pod Spark nếu chưa cache) | TARGET_BENCHMARK | Benchmark Test |
| **NFR-PERF-006** | Thời gian tiếp nhận và claim trong hàng đợi (Queue Claim Latency) cho lượt chạy **Interactive** (priority=1) khi tài nguyên rảnh (không có Spark run khác đang chiếm slot): tính từ khi API nhận `RunSpec` đến khi Worker claim lease (`LEASED`). | Mục tiêu thiết kế $\le 2.5$ giây khi tài nguyên rảnh (gồm NOTIFY wakeup ~50ms + claim SQL ~100ms); khi slot Spark đang bận, các run sau xếp hàng chờ tuần tự | TARGET_BENCHMARK | End-to-End Latency Test |

### 5.2. An toàn và Tính toàn vẹn (Safety & Data Integrity - NFR-SAFE)

| ID | Yêu cầu an toàn | Ngưỡng mục tiêu | Status | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **NFR-SAFE-001** | Bảo toàn dữ liệu nguồn: Tuyệt đối không thực hiện bất kỳ thao tác ghi, cập nhật hoặc xóa trên tệp nguồn. | 100% bất biến (Mã băm SHA-256 không đổi) | BASELINED | File Hash Verification |
| **NFR-SAFE-002** | Tính nguyên tử của Assessment: Không bao giờ công bố bản đánh giá chưa hoàn thành hoặc bị lỗi nửa chừng. | 0 Assessment không hoàn chỉnh khi Run `FAILED` | BASELINED | Fault Injection Test |
| **NFR-SAFE-003** | Cách ly lỗi: Lỗi hệ thống hoặc crash detector không được làm sai lệch kết quả chất lượng của các quy tắc khác. | 100% cách ly lỗi | BASELINED | Fault Injection Test |
| **NFR-SAFE-004** | Giới hạn tài nguyên và cách ly sandbox cho Chế độ Khách (Guest Mode): kích thước tệp upload tối đa $\le 10$ MB và giới hạn tài nguyên Spark driver/executor pod $\le 1$ CPU, $\le 1$ GB RAM. | 100% cách ly tài nguyên | DEFERRED | Resource Monitoring |

### 5.3. Bảo mật và Quyền riêng tư (Security & Privacy - NFR-SEC)

| ID | Yêu cầu bảo mật | Ngưỡng mục tiêu | Status | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **NFR-SEC-001** | Che mờ bằng chứng (Evidence Redaction): Dữ liệu dòng lỗi hiển thị trên UI phải được che mờ các trường nhạy cảm/định danh. | 100% trường nhạy cảm được che mờ | BASELINED | Security Inspection |
| **NFR-SEC-002** | Không lưu trữ mật khẩu, khóa bí mật hoặc thông tin xác thực trong mã nguồn, log hoặc kết quả đánh giá. | 0 Credential leak | BASELINED | Static Code Analysis |
| **NFR-SEC-003** | Quản trị Danh tính & Phân quyền Cấp Tài nguyên (Resource-Level Authorization & Anti-BOLA): Hoãn lại hệ thống phân quyền liên đoàn doanh nghiệp (Dynamic RBAC Engine, IdP Federation SAML/OIDC) sau v1.0. Ở baseline v1.0, hệ thống bắt buộc thực thi xác thực danh tính có cấu trúc (`AuthContext` gồm `user_id`, `tenant_id`, `roles`, `scopes`), kiểm soát ranh giới người thuê (Tenant Isolation) ở cấp độ CSDL/API/Storage và phân quyền cấp tài nguyên (Resource-Level Access Guard): người dùng chỉ được thao tác trên tài nguyên do mình sở hữu (`owner_id`), được chia sẻ hợp lệ (`AccessGrant`), hoặc qua vai trò quản trị; áp dụng nguyên tắc từ chối mặc định (Fail-Closed) cho mọi giao diện (API, CLI, UI, Facade) theo OWASP API1:2023 (BOLA) và API5:2023 (BFLA). | 100% Fail-Closed, Resource-Bound & Anti-BOLA | BASELINED (v1.0 Core Authorization) / DEFERRED (Enterprise SSO) | Security Contract & BOLA Test |
| **NFR-SEC-004** | Tự động thu hồi và xóa dữ liệu tạm của Chế độ Khách (Guest Mode Sandbox) sau thời gian sống TTL 30–60 phút mà không phụ thuộc phiên duyệt. | 100% tệp tạm được dọn sạch sau TTL | DEFERRED | Storage Test |
| **NFR-SEC-005** | Nhận diện & Phân loại dữ liệu nhạy cảm: Hệ thống phải tự động quét nhận diện các trường chứa PII/nhạy cảm và phân thành 4 nhóm (Cá nhân cơ bản, Cá nhân nhạy cảm, Bí mật kinh doanh, Dữ liệu tiêu chuẩn). | 100% phát hiện khớp theo Classification Rules | BASELINED | Profiling & Security Test |
| **NFR-SEC-006** | Cơ chế Che mờ Đa tầng (Two-Tiered Masking): Che mờ tĩnh PII trước khi lưu trữ bằng chứng lỗi vào PostgreSQL; đồng thời thực thi che mờ động (Dynamic Role-Based Masking) theo vai trò khi truy vấn qua API/UI để bảo vệ dữ liệu trước người không liên quan. | 0 PII thô bị lộ lọt ra CSDL metadata hoặc người không có thẩm quyền | BASELINED | RBAC Masking Test |
| **NFR-SEC-007** | An toàn Nguồn Tệp & Ngăn chặn Thoát Thư mục (Source Sandboxing & Path Traversal Prevention): Mọi đường dẫn tệp cục bộ (`LOCAL_FILE`) phải được chuẩn hóa và giới hạn trong thư mục cho phép (Storage Root Allowlist), chặn đứng `..` và symlink trỏ ra ngoài; mọi object key (`OBJECT_FILE`) phải bị ràng buộc nghiêm ngặt trong prefix thuộc quyền sở hữu của tenant (`snapshots/{tenant_id}/...`) và bucket hợp lệ. | 100% từ chối truy cập ngoài ranh giới cho phép | BASELINED | Path Traversal & Fuzzing Test |
| **NFR-SEC-008** | Xác thực Ranh giới Tenant (Tenant Boundary Assertion): Header `X-Tenant-ID` chỉ đóng vai trò khai báo phạm vi yêu cầu (Requested Scope), bắt buộc phải được đối chiếu và xác thực khớp với claims/danh tính trong Auth Context (JWT / API Key). Tuyệt đối cấm tin cậy trực tiếp `X-Tenant-ID` chưa qua xác thực. | 0 Cross-tenant data leak | BASELINED | Multi-tenant Security Test |
| **NFR-SEC-009** | Vệ sinh Bằng chứng & Nhật ký Kiểm toán (Audit & Evidence Sanitization): Dữ liệu dòng lỗi (evidence), bảng điểm (scorecards), gói kiểm toán (audit packages) và log hệ thống tuyệt đối không chứa credentials, API keys, dữ liệu thô chưa che mờ (Unmasked PII) hoặc stacktrace lộ cấu trúc máy chủ nội bộ. | 0 Credential & 0 Unmasked PII leak | BASELINED | Security Inspection & Log Audit |
| **NFR-SEC-010** | Tách biệt Trạng thái Tính toán và Phạm vi Công bố (Assessment State vs Visibility Scope): Trạng thái kỹ thuật `PublicationStatus.PUBLISHED` chỉ biểu thị kết quả đạt điều kiện tính toán ($C_{DQ} \ge 80\%$, không lỗi bắt buộc). Quyền truy cập vào kết quả này chịu sự chi phối độc lập của `VisibilityScope` (`PRIVATE`, `WORKSPACE`, `PUBLIC_READ`). Chế độ công khai hoặc chia sẻ bên thứ ba chỉ cung cấp bản chiếu an toàn (`PublicScorecardProjection`) với danh sách trường cho phép (Allowlist); tuyệt đối không để lộ dữ liệu thô (raw rows), bằng chứng lỗi (evidence), findings chi tiết hoặc đường dẫn nội bộ. | 0 Byte raw/evidence leak trong Public Projection | BASELINED | Information Disclosure & Projection Test |
| **NFR-SEC-011** | Triệt tiêu Rò rỉ Cấu trúc & Metadata (Schema & Structural Metadata Shielding): Tên cột, tên bảng, kiểu dữ liệu và định nghĩa schema nội bộ thuộc về phạm vi sở hữu riêng của Tenant. Đối với các bản chiếu công khai (`PublicScorecardProjection`) hoặc người dùng vãng lai, hệ thống loại bỏ hoàn toàn danh mục tên cột/thuộc tính nhạy cảm, chỉ trả về các chỉ số tổng hợp cấp Dataset/Dimension; ngăn ngừa việc suy đoán bí mật kinh doanh qua metadata. | 0 Cột nhạy cảm/nội bộ rò rỉ ra ngoài ranh giới cho phép | BASELINED | Schema Leakage Test |
| **NFR-SEC-012** | Vệ sinh Lỗi Kỹ thuật Chuẩn hóa & Chống Dấu vân tay Máy chủ (RFC 7807/9457 Error Sanitization & Anti-Fingerprinting): Toàn bộ phản hồi lỗi API bắt buộc tuân thủ chuẩn RFC 9457 Problem Details; tuyệt đối không trả về stack trace, SQL query, đường dẫn tệp máy chủ nội bộ hoặc phiên bản phần mềm (`Spark`, `Python`, `FastAPI`); loại bỏ toàn bộ HTTP response header nhận diện công nghệ (`Server`, `X-Powered-By`). | 0 Stacktrace/Internal Path/Software Banner leak | BASELINED | Error Fuzzing & Header Audit |
| **NFR-SEC-013** | Phòng chống Tấn công Suy diễn Thống kê từ Dữ liệu Tổng hợp (Statistical Inference & Small Sample Suppression): Trong các báo cáo phân tích hồ sơ dữ liệu (Profiling Summary), nếu kích thước tập dữ liệu hoặc phân nhóm nhỏ hơn ngưỡng an toàn $K < 5$ ($K$-Anonymity), hệ thống tự động ẩn hoặc làm mờ các giá trị cực trị (Min, Max, Outlier values) nhằm triệt tiêu nguy cơ tái lập danh tính hoặc thuộc tính nhạy cảm từ các chỉ số thống kê tổng hợp. | 100% cực trị được ẩn khi $N < 5$ | BASELINED | Statistical Privacy Test |
| **NFR-SEC-014** | Phòng chống Tấn công Tiêm Công thức qua Tệp Xuất (CSV / Excel Formula Injection Sanitization): Khi kết xuất báo cáo, bảng điểm hoặc mẫu lỗi vi phạm ra định dạng CSV/Excel, 100% các trường văn bản bắt đầu bằng các ký tự điều khiển hoặc công thức (`=`, `+`, `-`, `@`, `\t`, `\r`) bắt buộc phải được tiền tố bằng dấu nháy đơn (`'`) để ngăn chặn việc thực thi mã macro độc hại khi người dùng mở tệp bằng các phần mềm bảng tính. | 100% ký tự công thức được escape an toàn | BASELINED | CSV Injection Security Test |
| **NFR-SEC-015** | Phòng vệ Kênh Webhook Ngoại vi & Chống Tấn công Phát lại / SSRF (Webhook Defense & Replay Protection): 100% yêu cầu Webhook phát ra ngoại vi phải được ký số HMAC-SHA256 kèm timestamp có hiệu lực $\le 300$ giây; kiểm tra ranh giới mạng chặn đứng toàn bộ địa chỉ nội bộ, loopback (RFC 1122), dải private (RFC 1918) và endpoint cloud metadata (`169.254.169.254`); áp dụng DNS Pinning ngăn ngừa DNS Rebinding. | 0 SSRF request thoát ra mạng nội bộ | BASELINED | Outbound SSRF & Replay Test |

### 5.4. Tính đúng đắn và Khả năng Tái lập (Correctness & Reproducibility - NFR-COR)

| ID | Yêu cầu chất lượng | Ngưỡng mục tiêu | Status | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **NFR-COR-001** | Tính tái lập: cùng Snapshot, Ruleset, Scoring Policy và Outlier Config luôn sinh cùng kết quả, Gate và `assessment_hash`. | 100% khớp kết quả qua 10 lượt Replay | BASELINED | Replay Test Suite |
| **NFR-COR-002** | Bảo toàn miền giá trị: Rule Score, Dimension Score và DQ Score luôn nằm trong đoạn $[0, 100]$ hoặc mang giá trị null hợp lệ. | 100% giá trị hợp lệ | BASELINED | Property-based Test |
| **NFR-COR-003** | Xử lý mẫu số 0: Trường hợp không có bản ghi đủ điều kiện đo tuyệt đối không sinh ra điểm 0 hoặc điểm 100 tùy tiện. | 100% tuân thủ Semantics | BASELINED | Boundary Test Suite |

### 5.5. Yêu cầu Thông báo và Tích hợp CI/CD (Notification & Integration - NFR-NOTIF / NFR-INT)

| ID | Yêu cầu thông báo & Tích hợp | Ngưỡng mục tiêu | Status | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **NFR-NOTIF-001** | Độ trễ gửi cảnh báo sự kiện (Alert Latency) qua Webhook/Email khi lượt chạy bị `FAILED` hoặc điểm DQ dưới ngưỡng quy định. | $\le 60$ giây sau khi commit | BASELINED | Integration Test |
| **NFR-NOTIF-002** | Hỗ trợ phân cấp mức độ cảnh báo (Critical, Warning, Info) định tuyến đến đúng nhóm quản trị dữ liệu hoặc kênh Slack/Teams tương ứng. | 100% định tuyến chính xác | BASELINED | Test (Event) |
| **NFR-NOTIF-003** | Định kỳ tổng hợp và phát bản tin email digest tóm tắt chất lượng tuần/tháng cho các bên liên quan. | Phát đúng lịch biểu | DEFERRED | Integration Test |
| **NFR-INT-001** | Khả năng vận hành độc lập không đầu (Headless Operation) trong môi trường Docker Container phục vụ tích hợp CI/CD pipelines. | Hoàn toàn tương thích CI container | BASELINED | Container Test |

### 5.6. An toàn, Riêng tư và Cách ly Trợ lý AI (AI Advisory Safety & Isolation - NFR-AI)

| ID | Yêu cầu an toàn AI | Ngưỡng mục tiêu | Status | Phương pháp kiểm chứng |
| :--- | :--- | :--- | :--- | :--- |
| **NFR-AI-001** | **Cách ly & An toàn Trợ lý Cố vấn AI (LLM Advisory Safety & Isolation):**<br/>1. **Không lộ dữ liệu thô (Zero Raw Data Exposure):** Hệ thống tuyệt đối không gửi bản ghi dữ liệu thô, mẫu vi phạm (evidence records) hoặc thông tin kết nối/chứng thực sang LLM; chỉ gửi schema và các chỉ số thống kê tổng hợp (`CanonicalMetric`).<br/>2. **Khử khuẩn PII (PII Sanitization):** Các giá trị phân phối min/max trên các cột nhạy cảm/PII phải được khử khuẩn hoặc che mờ trước khi đưa vào ngữ cảnh LLM.<br/>3. **Ranh giới Cố vấn Đọc (Read-Only Advisory):** Mọi đề xuất từ AI (gợi ý template, draft rule, narrative report) chỉ mang tính tham vấn, phải gán nhãn `source = 'AI_ADVISORY'` và lưu audit trail. LLM tuyệt đối không tự sửa điểm số, không tự đổi rule `ACTIVE`, không can thiệp Quality Gate.<br/>4. **Tự chủ & Khả năng suy thoái (Fault Isolation):** Core Scoring Engine chạy hoàn toàn độc lập với LLM; sự cố, timeout hoặc lỗi cú pháp từ LLM không làm gián đoạn pipeline tính điểm. | 0 byte raw data/evidence lộ lọt sang LLM;<br/>100% Core Scoring độc lập;<br/>100% đề xuất AI gắn nhãn `source = 'AI_ADVISORY'`. | BASELINED | Privacy Audit & Fault Injection Test |

---

## 6. YÊU CẦU DỮ LIỆU, QUY TẮC NGHIỆP VỤ VÀ MA TRẬN TRUY VẾT

### 6.1. Danh mục 27 Yêu cầu Dữ liệu (Data Requirements - DR)

| ID | Yêu cầu dữ liệu bắt buộc | Nguồn kiểm chứng |
| :--- | :--- | :--- |
| **DR-001** | `DataAsset` có UUID, `tenant_id`, tên logic (duy nhất trong phạm vi tenant), provenance, định dạng và thời điểm tạo UTC. | Data dictionary + DDL |
| **DR-002** | `DatasetSnapshot` tham chiếu Asset, lưu đường dẫn chỉ đọc, SHA-256 duy nhất, schema, kích thước và thời điểm chụp UTC. | DDL + hash test |
| **DR-003** | `CanonicalMetric` tham chiếu Snapshot và lưu cột, tên metric, giá trị/payload, phương pháp và thời điểm tính. | Contract test |
| **DR-004** | `RulesetRevision` có UUID, version, canonical config hash, trạng thái và audit submit/approve. | DDL + approval test |
| **DR-005** | `QualityRule` tham chiếu Ruleset và lưu dimension, target, type, parameters, Null Policy, weight và severity. | Schema validation |
| **DR-006** | `ScoringPolicyRevision` có UUID, version, canonical config hash, dimension weights, publication threshold, gate rules và audit submit/approve. | DDL + approval test |
| **DR-007** | `EvaluationRun` tham chiếu Snapshot/Ruleset/Policy, có `tenant_id`, đóng băng RunSpec/Outlier Config/hash và lưu state async, `priority` (1=Interactive/5=Normal/10=Batch), attempt, lease, heartbeat, cancellation, idempotency cùng lỗi kỹ thuật. | Run contract test |
| **DR-008** | `CanonicalQualityResult` lưu provenance, measurement status, score/advisory flag, bounded evidence và đầy đủ năm count partition. | JSON/DDL contract test |
| **DR-009** | `ImmutableAssessment` tham chiếu một Run `SUCCEEDED` duy nhất và lưu score nullable, coverage, publication status, Gate, config hashes, `assessment_hash`, thời điểm công bố. `WITHHELD` vẫn được persist như Assessment hoàn tất và bắt buộc có `dq_score = null`. | Atomic publication test |
| **DR-010** | Mỗi Assessment có đúng sáu `DimensionResult`, duy nhất theo `(assessment_id, dimension)`, với score nullable và counts rule hợp lệ. | DDL constraint test |
| **DR-011** | Bounded Evidence chỉ lưu trong `evidence_payload` của durable result store hoặc artifact reference, tối đa 50 dòng mỗi result và tổng tối đa 500 KB mỗi Assessment, đã redacted trước khi ghi. | Security/storage test |
| **DR-012** | Mọi hash dùng JSON canonical UTF-8, `sort_keys=true`, separators không khoảng trắng và không chứa timestamp runtime ngoài contract. | Canonical hash test |
| **DR-013** | Mọi timestamp lưu UTC theo RFC 3339 và kết thúc bằng `Z`. | Schema/format test |
| **DR-014** | Snapshot và graph Assessment đã công bố là append-only; PostgreSQL trigger/privilege boundary từ chối `UPDATE/DELETE`. | PostgreSQL immutability test |
| **DR-015** | Khóa ngoại lịch sử dùng `RESTRICT`; xóa cấu hình không được làm mất provenance của kết quả đã công bố. | Referential integrity test |
| **DR-016** | Mọi result bảo toàn `passed + failed + missing + miscast + not_applicable = total_observed`. | CHECK constraint test |
| **DR-017** | Tất cả khóa định danh runtime dùng UUID; ID tài liệu không được dùng làm khóa dữ liệu. | Contract inspection |
| **DR-018** | Assessment, Dimension Results, Canonical Results, publication event và Run `SUCCEEDED` được ghi trong một PostgreSQL transaction; lỗi giữa chừng không để lại bản công bố cục bộ. | Fault injection test |
| **DR-019** | Schema evolution giữ dữ liệu lịch sử đọc được và phải có kiểm thử upgrade/downgrade trước release. | Migration test |
| **DR-020** | `SensitiveDataFinding` lưu vết kết quả nhận diện trường dữ liệu nhạy cảm (snapshot_id, run_id, column_name, category, confidence_score, status, detected_at). | DDL + finding test |
| **DR-021** | `RuleCatalogTemplate` lưu bản mẫu quy tắc chuẩn hóa có thể tái sử dụng trong Kho Rule tập trung (template_code, name, rule_type, parameter_schema, default_null_policy, default_dimension, is_advisory_default). | DDL + catalog test |
| **DR-022** | `ClassificationRule` lưu quy tắc nhận diện PII/nhạy cảm (rule_name, target_category, pattern_type, pattern_regex, confidence_threshold, priority). | DDL + regex test |
| **DR-023** | `DataProtectionPolicy` lưu chính sách che mờ dữ liệu theo vai trò người dùng (asset_id, target_category, user_role, masking_strategy, masking_parameters). | DDL + masking test |
| **DR-024** | Mọi tài sản (`DataAsset`), snapshot, ruleset, scoring policy, protection policy, run, finding, evidence và assessment thuộc sở hữu độc quyền của một Tenant (`tenant_id NOT NULL REFERENCES tenants`). Khóa ngoại ghép ở tầng CSDL ngăn chặn tuyệt đối việc tham chiếu chéo giữa các tenant. | DDL composite FK test |
| **DR-025** | Tên tài sản `asset_name`, phiên bản cấu hình và `idempotency_key` có phạm vi duy nhất theo từng tenant (`UNIQUE (tenant_id, ...)`). Mã băm `config_hash` không áp đặt unique toàn cục để cho phép các tenant độc lập sở hữu cùng định nghĩa quy tắc/chính sách mà không xung đột. | Tenant isolation test |
| **DR-026** | `RulesetTemplate` lưu bản mẫu bộ quy tắc đánh giá chuẩn hóa theo Domain, Data Type và Mục đích sử dụng (template_code, name, domain, data_type, target_use_case, description, rules_payload, is_system_template, tenant_id). | DDL + template test |
| **DR-027** | `ScoringPolicyTemplate` lưu bản mẫu chính sách tính điểm tương thích (template_code, name, domain, target_use_case, dimension_weights, publication_threshold, gate_rules, is_system_template, tenant_id). | DDL + template test |

---

### 6.2. Danh mục 17 Quy tắc Nghiệp vụ (Business Rules - BR)

- **BR-001:** DQ Score chỉ phản ánh mức độ tuân thủ kỹ thuật của Snapshot đối với Scoring Policy cụ thể, không đại diện cho giá trị thương mại hay uy tín nhà cung cấp.
- **BR-002:** DQ Score, 6 Dimension Results, Coverage, Publication Status và Quality Gate phải được công bố độc lập ở các trường riêng biệt.
- **BR-003:** Trạng thái `NOT_MEASURABLE`, `NOT_APPLICABLE`, `FAILED_TO_MEASURE` hoặc mẫu số bằng 0 không được coi là điểm 0 hoặc điểm 100; trường `computed_score` bắt buộc phải là `null`.
- **BR-004:** Chiều Accuracy trong v1.0 được đo dưới dạng *Accuracy Proxy* (tính hợp lý nội tại); đo Accuracy thực tế qua Ground Truth thuộc Post-1.0.
- **BR-005:** Quy tắc được đánh dấu `critical` khi bị vi phạm sẽ buộc Quality Gate chuyển sang `FAIL` bất kể điểm trung bình.
- **BR-006:** Tín hiệu Outlier IQR trong v1.0 là `ADVISORY`, mang `source_kind = 'OUTLIER'`, cờ `is_advisory = TRUE` và trọng số đóng góp `contribution_weight = 0`; tuyệt đối không làm suy giảm điểm DQ Score, không làm giảm Dimension Scores và không kích hoạt Quality Gate `FAIL` hoặc `WARN`.
- **BR-007:** Phân định rõ ràng bốn trạng thái đo lường (`MeasurementStatus`): (1) `MEASURED`: quy tắc đo thành công có mẫu số hợp lệ; (2) `NOT_APPLICABLE`: quy tắc không thỏa mãn điều kiện áp dụng trên tập dữ liệu này, bị loại khỏi mẫu số Dimension và Coverage, `score = null`; (3) `NOT_MEASURABLE`: quy tắc được policy yêu cầu nhưng thiếu metadata/cột tham chiếu/SLA, tính vào mẫu số Coverage làm giảm Coverage, `score = null`; (4) `FAILED_TO_MEASURE`: lỗi kỹ thuật thực thi Spark SQL / SparkApplication, khoanh vùng ở `CanonicalQualityResult` và kích hoạt Quality Gate `ERROR`.
- **BR-008:** So sánh chất lượng giữa hai lần đánh giá chỉ có giá trị khi cùng Snapshot schema, Ruleset và Scoring Policy tương đương.
- **BR-009:** DQ Score chỉ được công bố (`PUBLISHED`) khi Run hợp lệ và Độ bao phủ (Coverage) $\ge 80\%$.
- **BR-010:** Với Run `SUCCEEDED`, thứ tự ưu tiên Quality Gate (Gate Precedence) tuân thủ nghiêm ngặt 6 cấp bậc: (1) `ERROR` (nếu có lỗi kỹ thuật `FAILED_TO_MEASURE` trên quy tắc bắt buộc) $\succ$ (2) Critical `FAIL` (có quy tắc critical bị vi phạm) $\succ$ (3) `INSUFFICIENT_EVIDENCE` (Coverage < 80% hoặc thiếu phép đo bắt buộc) $\succ$ (4) `FAIL` (DQ Score < 60) $\succ$ (5) `WARN` (60 $\le$ DQ Score < 80) $\succ$ (6) `PASS` (DQ Score $\ge$ 80). Run `FAILED` hoặc `CANCELLED` không tạo Gate.
- **BR-011:** Phiên bản 1.0 chỉ thực hiện Full Scan trên snapshot; không tự ý kích hoạt chế độ lấy mẫu (Sampling).
- **BR-012:** Lỗi Outlier Detector sinh advisory `FAILED_TO_MEASURE` trọng số 0, không làm gián đoạn Rule Engine, Score Engine hoặc làm giảm Coverage score-enabled.
- **BR-013:** Ruleset và Scoring Policy phải được Data Owner phê duyệt riêng; `RunSpec` chỉ tham chiếu revision `ACTIVE` và tương thích Snapshot schema.
- **BR-014:** Dù Data Owner và Data Steward là cùng một người trong local prototype, hành động `submit` và `approve` vẫn là hai lệnh riêng với audit timestamp riêng.
- **BR-015:** Dữ liệu nhạy cảm được phân thành 4 nhóm chuẩn hóa: (1) Dữ liệu cá nhân cơ bản, (2) Dữ liệu cá nhân nhạy cảm, (3) Dữ liệu kinh doanh / bí mật nội bộ, (4) Dữ liệu thông thường / phi nhạy cảm; việc phát hiện nhạy cảm là hoạt động gắn nhãn quản trị (Governance Labeling), không tự động coi là lỗi vi phạm chất lượng trừ khi có quy tắc Data Contract cấm rõ ràng.
- **BR-016:** Thực thi cơ chế che mờ hai tầng (Two-Tiered Masking): Toàn bộ mẫu bằng chứng vi phạm lưu trong CSDL metadata phải được che mờ PII trước khi ghi (`EvidenceRedactor`); khi truy vấn qua API/UI, người không liên quan (unprivileged viewer / operator) chỉ được xem số liệu tổng hợp hoặc dữ liệu đã che mờ theo `DataProtectionPolicy`.
- **BR-017:** Điểm DQ Score kỹ thuật cao không có giá trị vượt quyền hay miễn trừ kiểm soát truy cập bảng dữ liệu nguồn trên Lakehouse (Lakehouse IAM/ACLs).
- **BR-018:** Ranh giới Sở hữu Dữ liệu và Cấp quyền Chia sẻ trên Data Marketplace (Marketplace Boundary): Mỗi tài sản, snapshot, ruleset, scoring policy, evaluation run, finding và assessment thuộc quyền sở hữu độc quyền của một Tenant; việc chia sẻ dữ liệu hoặc quyền xem scorecard giữa các bên mua bán trên Data Marketplace là hành vi cấp quyền riêng biệt có kiểm soát (Access Grant / Sharing Agreement), tuyệt đối không làm thay đổi ownership của dữ liệu và không cho phép truy cập chéo dữ liệu thô, findings hay evidence mẫu.
- **BR-019:** Tính Toàn vẹn Tham chiếu Phân tầng Khóa ghép (Composite Referential Integrity): Mọi liên kết quan hệ phụ thuộc giữa các thực thể con (Run -> Snapshot, Run -> Ruleset, Snapshot -> Asset, Assessment -> Run) bắt buộc phải bảo toàn tính đồng nhất về `tenant_id` thông qua khóa ghép `(tenant_id, id)` ở cấp độ CSDL. Lỗi truyền sai hoặc trộn lẫn ID giữa các tenant phải bị chặn ngay tại tầng ràng buộc CSDL, không phụ thuộc duy nhất vào logic lọc tại tầng ứng dụng.
- **BR-020:** Ranh giới Sở hữu Cấp Người dùng và Chống BOLA Nội bộ (Intra-Tenant Resource Ownership & Anti-BOLA): Toàn bộ tài nguyên nghiệp vụ (Asset, Snapshot, Ruleset, Policy, Run, Assessment) đều gắn liền với `tenant_id` và `owner_user_id` / `created_by`. Người dùng trong cùng một tenant mặc định không có quyền xem hay thao tác trên tài nguyên riêng tư của người dùng khác trừ khi được cấp quyền tường minh qua `AccessGrant` hoặc sở hữu vai trò quản trị `WORKSPACE_ADMIN`. Mọi hành động can thiệp (hủy Run, sửa Ruleset, xem Evidence) bắt buộc kiểm tra thẩm quyền trên từng đối tượng (Object-Level Authorization theo OWASP API1:2023).
- **BR-021:** Tách biệt Trạng thái Đánh giá và Phạm vi Hiển thị Công bố (Publication Status vs Visibility Grant): `PublicationStatus.PUBLISHED` chỉ xác nhận tính toàn vẹn kỹ thuật của kết quả đánh giá ($C_{DQ} \ge 80\%$, không lỗi phép đo bắt buộc). Quyền truy cập vào kết quả này chịu sự chi phối độc lập của chính sách phân quyền và phạm vi hiển thị (`VisibilityScope`: `PRIVATE`, `WORKSPACE`, `PUBLIC_READ`). Truy cập công khai hoặc chia sẻ đối tác chỉ nhận bản chiếu an toàn (`PublicScorecardProjection`), tuyệt đối che giấu hoặc loại bỏ: dữ liệu thô (raw data), mẫu bằng chứng lỗi (evidence), phát hiện dữ liệu nhạy cảm (PII findings), đường dẫn tệp hạ tầng và cấu hình nội bộ.
- **BR-022:** Xác thực Không Tiết lộ Trạng thái & Triệt tiêu Tấn công Kênh phụ Thời gian (State-Agnostic Authentication & Timing Attack Neutralization): Mọi thông báo lỗi đăng nhập, xác thực hoặc đặt lại mật khẩu không bao giờ tiết lộ sự tồn tại của tài khoản trong hệ thống (thông báo thống nhất: `"Invalid email or password"`). Nếu email không tồn tại, hệ thống vẫn thực thi một phép tính băm mật khẩu giả lập có thời gian tương đương (Constant-Time Dummy Argon2id Execution) trước khi trả về `401 Unauthorized`, nhằm triệt tiêu chênh lệch thời gian phản hồi (Timing Attack Oracle) ngăn chặn tin tặc rà quét danh sách tài khoản hợp lệ.
- **BR-023:** Bảo vệ Tuyệt đối Chống Tiêm Công thức trong Báo cáo Xuất Dữ liệu (Spreadsheet Formula Injection Prevention): Toàn bộ dữ liệu trích xuất ra định dạng CSV/Excel từ bảng điểm, quy tắc, bằng chứng hoặc metadata bắt buộc phải đi qua bộ lọc `FormulaSanitizer`. Mọi chuỗi văn bản bắt đầu bằng ký tự công thức (`=`, `+`, `-`, `@`, `\t`, `\r`) đều được tự động vô hiệu hóa bằng dấu tiền tố an toàn `'` trước khi ghi vào luồng stream xuất, ngăn ngừa rủi ro thực thi lệnh ngoại vi trên máy trạm người dùng.
- **BR-024:** Quy tắc Ranh giới Mạng Ngoại vi & Bảo mật Giao vận Webhook (Safe Outbound Webhook & Network Boundary Isolation): Endpoint Webhook chỉ được phép sử dụng giao thức HTTPS hợp lệ; cấm tuyệt đối cấu hình URL trỏ vào các dải địa chỉ IP riêng tư (RFC 1918), loopback (RFC 1122), link-local hoặc endpoint siêu dữ liệu máy chủ đám mây (`169.254.169.254`). Khóa bí mật ký số HMAC của webhook phải được lưu trữ mã hóa và không bao giờ xuất hiện trong log hoặc response API.
- **BR-025:** Tính Nhất quán Ngữ nghĩa Quy tắc (Rule Semantic Consistency & Mutual Exclusion): Cấm tuyệt đối cấu hình đồng thời `is_required = TRUE` và `is_advisory = TRUE` (hoặc `source = 'AI_ADVISORY'`) trên cùng một quy tắc. Quy tắc mang tính tư vấn/ngoại lệ cảnh báo (Advisory / Outlier) luôn có trọng số $w_r = 0$ và không bắt buộc; quy tắc bắt buộc (`is_required = TRUE`) phải là quy tắc kỹ thuật xác định (Deterministic Rule). Mọi yêu cầu tạo hoặc duyệt quy tắc vi phạm tổ hợp này đều bị từ chối ngay tại tầng kiểm thực dữ liệu (Fail-fast Validation Error) và cưỡng chế bằng ràng buộc toàn vẹn CSDL.

---

### 6.3. Tiêu chí Nghiệm thu Hệ thống (System Acceptance Criteria - AC)

| Mã AC | Tình huống kiểm thử nghiệm thu | Kết quả kỳ vọng bắt buộc | Nhóm yêu cầu kiểm chứng |
| :--- | :--- | :--- | :--- |
| **AC-001** | Đăng ký Data Asset và Snapshot từ file CSV/Parquet mẫu. | Tạo Snapshot bất biến, trích xuất schema đúng, tính mã băm SHA-256 khớp tệp nguồn. | FR-ASSET-001..004 |
| **AC-002** | Thực hiện Profiling tự động trên Snapshot bằng Apache Spark trên k3s. | Sinh tập Canonical Metrics chính xác 100% so với kết quả tính toán đối chuẩn độc lập. | FR-PROF-001..005 |
| **AC-003** | Submit rồi phê duyệt riêng Ruleset và Scoring Policy; ngoại lệ Admin được thực hiện rõ ràng, không tự động. | RunSpec từ chối revision DRAFT; chấp nhận khi cả hai ACTIVE. Audit có actor/tenant/revision, submit/approve và cờ self-approval/lý do; lỗi audit rollback. Non-admin và template giữ phê duyệt độc lập; tự duyệt không thay điểm/gate/privacy. | FR-GOV-001..007, BR-013..014 |
| **AC-004** | Chạy 5 nhóm quy tắc xác định trên tập dữ liệu Golden. | Năm partition count khớp expected data và tổng đúng `total_observed`. | FR-VAL-001..003, DR-016 |
| **AC-005** | Kiểm thử quy tắc có mẫu số bằng 0 (Zero Denominator). | Trả về trạng thái `NOT_APPLICABLE` (loại khỏi mẫu số) hoặc `NOT_MEASURABLE` (tính vào mẫu số Coverage làm giảm Coverage), `computed_score` bắt buộc là `null`, tuyệt đối không tạo điểm 0 hoặc điểm 100. | FR-VAL-005, NFR-COR-003 |
| **AC-006** | Mô phỏng sự cố kỹ thuật cốt lõi (lỗi SQL, DB hoặc hỏng file). | Run `FAILED`, ghi `EXECUTION_ERROR` và không công bố Assessment. | FR-RUN-004..006, NFR-SAFE-002 |
| **AC-007** | Thực thi IQR Outlier Detector trên cột số có giá trị dị biệt. | Phát hiện chính xác các điểm ngoại lệ, tính đúng tứ phân vị; tín hiệu mang `is_advisory = True` và `contribution_weight = 0`, tuyệt đối không làm thay đổi DQ Score hay Quality Gate. | FR-DET-001..005 |
| **AC-008** | Gây lỗi thực thi trong Outlier Detector. | Sinh advisory `FAILED_TO_MEASURE`; Rule Results, DQ Score, Coverage score-enabled và Assessment vẫn được công bố. | FR-DET-006, BR-012 |
| **AC-009** | Tính toán tổng hợp điểm số và Coverage khi có dimension không đo được. | Có đúng 6 Dimension Results; score dimension thiếu bằng chứng là `null`, DQ Score tái chuẩn hóa và Coverage vẫn phản ánh khoảng trống. | FR-SCORE-001..005, DR-010 |
| **AC-010** | Thiếu độ bao phủ (Coverage < 80%) hoặc lỗi phép đo bắt buộc. | DQ Score mang trạng thái `WITHHELD` (`dq_score = null`); Quality Gate là `INSUFFICIENT_EVIDENCE` (hoặc `ERROR` nếu có phép đo bắt buộc bị `FAILED_TO_MEASURE` theo BR-010); nếu đồng thời có vi phạm quy tắc critical thì Gate ưu tiên trả về `FAIL` theo thứ tự Gate Precedence. | FR-SCORE-006..007, BR-009..010 |
| **AC-011** | Đánh giá trường hợp Vi phạm quy tắc sống còn (`critical`). | Quality Gate chuyển sang `FAIL` ngay cả khi DQ Score tổng hợp đạt 90+ điểm, hoặc khi kết hợp đồng thời với Coverage < 80% (Critical `FAIL` ưu tiên cao hơn `INSUFFICIENT_EVIDENCE` theo BR-010). | FR-SCORE-008, BR-005, BR-010 |
| **AC-012** | Trực quan hóa kết quả trên Local Dashboard. | Hiển thị đầy đủ Scorecard, 6 chiều chất lượng, cảnh báo Outlier và dòng lỗi mẫu được che mờ. | IF-UI-001..004, FR-ASM-003 |
| **AC-013** | Kiểm tra tính tái lập (Reproducibility Replay). | Chạy lại 10 lần cùng Snapshot, Ruleset, Policy và Outlier Config cho ra cùng `assessment_hash`, điểm số và Gate. | NFR-COR-001, DR-012 |
| **AC-014** | Đo đạc hiệu năng Benchmark trên môi trường tham chiếu k3s đơn nút 8 GB RAM. | Thời gian chạy End-to-End SLA mục tiêu $\le 120$s, đỉnh RAM Spark $\le 4.0$GB (đỉnh toàn nút $\le 8.0$GB), Đĩa tạm $\le 1.0$GB trên Vertical Slice 100.000 dòng; ghi nhận kết quả thực nghiệm vào Báo cáo Benchmark. | NFR-PERF-001..003 |
| **AC-015** | Bảo toàn tính toàn vẹn của tệp dữ liệu nguồn. | Tệp CSV/Parquet nguồn không bị sửa đổi bất kỳ byte nào sau toàn bộ các lượt kiểm thử. | FR-ASSET-004, NFR-SAFE-001 |
| **AC-016** | Kiểm thử Độc lập Không gian Tên và Idempotency Đa Thuê bao (Multi-Tenant Namespace & Idempotency). | Hai tenant khác nhau đăng ký tài sản cùng `asset_name`, áp dụng `config_hash` giống nhau và dùng cùng `idempotency_key` hoàn toàn độc lập, không xung đột hay ghi đè; CSDL từ chối liên kết chéo `(tenant_id, snapshot_id)` giữa Tenant A và Tenant B. | DR-024, DR-025, BR-018, BR-019 |
| **AC-017** | Tương thích Vận hành Đơn Thuê bao với Nền tảng Đa Thuê bao (Default Tenant Backward Compatibility). | Môi trường v1.0 tự động nạp Tenant Context mặc định (`00000000-0000-0000-0000-000000000001`), toàn bộ API, worker và pipeline chạy bình thường mà không cần cấu hình phức tạp; toàn bộ dữ liệu ghi nhận đều gắn `tenant_id` chuẩn bị sẵn sàng cho Data Marketplace. | DR-024, AC-001..015 |
| **AC-018** | Áp dụng Assessment Template và Phê duyệt Độc lập (Template Cloning & Independent Approval). | Áp dụng Assessment Template nhân bản thành đúng hai bản ghi DRAFT riêng biệt (`RulesetRevision` và `ScoringPolicyRevision`) thuộc sở hữu của tenant; kế thừa toàn bộ tham số, lưu vết `derived_from_template_id`; kiểm thực chặn ruleset chứa nhóm xung đột không có đúng một quy tắc chính (`Theory §10`); yêu cầu Data Owner phê duyệt độc lập (`approve_ruleset`, `approve_policy`) trước khi đưa vào `RunSpec`. | FR-GOV-013, FR-GOV-014, DR-026, DR-027 |
| **AC-019** | Kiểm soát Ranh giới An toàn và Gắn nhãn Provenance của Trợ lý AI (AI Advisory Safety & Provenance). | LLM chỉ nhận aggregated schema và metrics; 0 byte raw data hoặc evidence bị rò rỉ; mọi cấu hình/báo cáo do AI gợi ý mang nhãn `source = 'AI_ADVISORY'` và ở trạng thái DRAFT/tham vấn; Core Scoring Engine hoạt động hoàn toàn chính xác khi tắt hoặc ngắt kết nối LLM. | NFR-AI-001 |
| **AC-020** | Kiểm soát Truy cập Cấp Đối tượng Nội bộ Tenant (Intra-Tenant Anti-BOLA). | Hai người dùng User A và User B cùng thuộc Tenant 1; User B gửi request đọc/sửa Ruleset DRAFT hoặc hủy Evaluation Run của User A mà không có `AccessGrant` $\rightarrow$ hệ thống từ chối an toàn với mã `403 Forbidden` / `404 Not Found`; không rò rỉ dữ liệu hoặc trạng thái của User A cho User B. | NFR-SEC-003, BR-020 |
| **AC-021** | Toàn vẹn Ngữ cảnh Xác thực và Thu hồi Quyền Tức thì (Context Integrity & Immediate Revocation). | Client truyền header `X-Tenant-ID` hoặc body `owner_id` giả mạo không khớp với claims trong token $\rightarrow$ hệ thống từ chối ngay lập tức (`403 Forbidden`); khi một `AccessGrant` bị thu hồi hoặc hết hạn, các lượt truy vấn tiếp theo lập tức bị từ chối, không bị vượt qua do bộ đệm phiên hay connection pooling. | NFR-SEC-003, NFR-SEC-008, BR-020 |
| **AC-022** | Bảo đảm An toàn Bản chiếu Công bố Công khai (Public Scorecard Projection Sanitization). | Truy xuất Scorecard đã được công bố ở chế độ chia sẻ / public; API chỉ trả về `PublicScorecardProjection` gồm điểm DQ Score, 6 Dimension Scores, Quality Gate, Coverage, Timestamp và tóm tắt thống kê; xác minh 0 byte raw data, 0 byte evidence, 0 PII findings và không có thông tin hạ tầng nội bộ bị rò rỉ. | NFR-SEC-010, BR-021 |
| **AC-023** | Xác thực Đăng ký, Đăng nhập & Vòng đời Token (Authentication & Token Lifecycle). | Đăng ký tài khoản mới $\rightarrow$ tạo User & Tenant thành công, băm mật khẩu bằng Argon2id; đăng nhập cấp phát Access Token (JWT 15m) và Refresh Token (UUIDv4 14d); xoay vòng Refresh Token thành công; khi gửi lại Refresh Token cũ đã bị xoay vòng $\rightarrow$ hệ thống phát hiện Token Reuse và lập tức thu hồi toàn bộ phiên hoạt động của user; đăng nhập sai 5 lần liên tiếp $\rightarrow$ tài khoản bị khóa tạm thời 15 phút. | FR-AUTH-001..008, NFR-SEC-003, BR-022 |
| **AC-024** | Phân phối Cảnh báo Đa kênh & Bảo mật Webhook HMAC-SHA256 (Notification & Webhook Security). | Cấu hình kênh Webhook và Email; worker hoàn tất run với kết quả Quality Gate `FAIL` $\rightarrow$ hệ thống ghi sự kiện vào outbox và dispatch webhook thành công trong vòng $\le 60$ giây; webhook payload được ký số HMAC-SHA256 kèm timestamp chuẩn xác; kiểm thử cấu hình Webhook URL trỏ đến `http://169.254.169.254` hoặc `http://127.0.0.1:5432` $\rightarrow$ hệ thống chặn đứng với mã lỗi an toàn `SSRF_TARGET_BLOCKED`. | FR-NOTIF-001..005, NFR-NOTIF-001..002, NFR-SEC-015, BR-024 |
| **AC-025** | Triệt tiêu Rò rỉ Metadata, Lỗi Kỹ thuật RFC 9457 & Tiêm Công thức CSV (Data Leakage & Formula Injection Shielding). | Gửi request gây lỗi hệ thống $\rightarrow$ API trả về cấu trúc lỗi chuẩn RFC 9457 Problem Details, 0 byte stack trace, 0 SQL query, 0 server file path, response headers không chứa banner công nghệ (`Server`, `X-Powered-By`); xuất báo cáo CSV có trường bắt đầu bằng `=`, `+`, `-`, `@` $\rightarrow$ 100% trường được tự động thêm tiền tố `'`; xem thống kê phân tích với tập dữ liệu $N < 5$ dòng $\rightarrow$ các giá trị cực trị Min, Max được ẩn/làm mờ an toàn. | NFR-SEC-011..014, BR-022, BR-023 |

---

### 6.4. Ma trận Truy vết Yêu cầu 2 chiều (Bidirectional Traceability Matrix)

| Mục tiêu nghiệp vụ | Business Use Case | Nhóm Yêu cầu Chức năng, Giao diện & Dữ liệu | Tiêu chí Nghiệm thu |
| :--- | :--- | :--- | :--- |
| **BG-001: Chuẩn hóa đánh giá** | BUC-001, BUC-002, BUC-003, BUC-004 | FR-ASSET-001..004, FR-GOV-001..007, FR-GOV-011..014, FR-RUN-001..012, IF-SRC-001..006 | AC-001, AC-003, AC-013, AC-016, AC-018 |
| **BG-002: Tự động hóa quy trình** | BUC-004, BUC-005 | FR-PROF-001..005, FR-RUN-001..012, FR-SCHED-001..002, FR-NOTIF-001..006, NFR-PERF-001..005, NFR-NOTIF-001..003, NFR-INT-001 | AC-002, AC-014, AC-024 |
| **BG-003: Ra quyết định sử dụng** | BUC-005, BUC-006 | FR-SCORE-001..009, FR-ASM-001..005, IF-UI-001..016, IF-CLI-001..002, NFR-SEC-010 | AC-009, AC-010, AC-011, AC-012, AC-022 |
| **BG-004: Truy vết bằng chứng** | BUC-001, BUC-004, BUC-005, BUC-006, BUC-008 | FR-ASM-001..005, FR-COLLAB-001, FR-ROOT-001, FR-AUTH-001..008, NFR-COR-001, NFR-AI-001, NFR-SEC-003, NFR-SEC-011..015, DR-001..027, BR-022..024 | AC-012, AC-013, AC-015, AC-016, AC-019, AC-020, AC-021, AC-023, AC-025 |
| **BG-005: Phân biệt lỗi rạch ròi** | BUC-002, BUC-004, BUC-005, BUC-007 | FR-VAL-004..006, FR-RUN-005, FR-SCORE-007, FR-RECOM-001 | AC-005, AC-006, AC-010 |
| **BG-006: Đa mô hình Hybrid** | BUC-004, BUC-007 | FR-VAL-001..003, FR-DET-001..007 | AC-004, AC-007, AC-008 |
| **BG-007: Trực quan hóa Scorecard**| BUC-006, BUC-008 | IF-UI-001..016, FR-ASM-001..005, FR-COLLAB-001 | AC-012 |
| **BG-008: Đảm bảo tính tái lập** | BUC-001, BUC-002, BUC-003, BUC-004, BUC-008 | NFR-COR-001..003, FR-GOV-001..007, FR-RUN-003, NFR-SAFE-001..004 | AC-013, AC-015, AC-017 |

---

### 6.5. Danh mục Đóng toàn bộ Quyết định TBD (Closed TBD Registry)

Tất cả các vấn đề kỹ thuật TBD đều đã được giải quyết và chốt cứng cho Baseline v1.0:

| Mã TBD | Nội dung vấn đề kỹ thuật | Quyết định Baseline được phê duyệt chính thức | Trạng thái |
| :--- | :--- | :--- | :--- |
| **TBD-APPROVER-001** | Danh tính người chịu trách nhiệm và phê duyệt | Project Owner: Nguyễn Hoàng Tùng; Approver: Mentor / Hội đồng thẩm định | **CLOSED** |
| **TBD-VSLICE-001** | Tập dữ liệu, ruleset và cấu hình Vertical Slice | Sử dụng Chicago Taxi Trips 2023 (Lát cắt tháng 01/2023), 5 nhóm rule xác định, IQR $k=1.5$ | **CLOSED** |
| **TBD-RESOURCE-001** | Ngân sách tài nguyên thực thi đơn nút | Trần tài nguyên toàn nút k3s $\le 8$ GB RAM (1 Spark run đồng thời; peak RAM Spark $\le 4.0$ GB), Temporary Disk $\le 1$ GB/pod; mục tiêu End-to-End SLA đo kiểm $\le 120$s cho 100.000 dòng | **CLOSED** |
| **TBD-SCORE-001** | Chính sách tính điểm, ngưỡng công bố và Quality Gate | Weighted Arithmetic Mean; công bố khi Coverage $\ge 80\%$; Gate Precedence theo BR-010 | **CLOSED** |
| **TBD-COMM-001** | Cấu hình bảo mật mạng phân tán và triển khai Server | TLS, Reverse Proxy và Firewall Allowlist phụ thuộc deployment; API/Worker trao đổi qua PostgreSQL, không có localhost-only contract | **CLOSED** |

---
*(Hết nội dung Chương 2 — Phiên bản 1.7 Review Candidate)*

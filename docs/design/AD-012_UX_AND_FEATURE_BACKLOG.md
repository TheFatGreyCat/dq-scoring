# AD-012: HỒ SƠ QUẢN TRỊ TRẢI NGHIỆM NGƯỜI DÙNG VÀ DANH MỤC TÍNH NĂNG MỞ RỘNG (UX & FEATURE BACKLOG)

**Mã hồ sơ:** AD-012-UX-BACKLOG  
**Phiên bản:** 1.9 (Template Hierarchy & DDL Enum Aligned)  
**Ngày phát hành:** 2026-09-22  
**Tác giả:** Nguyễn Hoàng Tùng (Project Owner / Lead Developer)  
**Tình trạng:** Khóa Baseline Roadmap v1.9, UI/UX Interaction Specifications, 3-Tier Template Hierarchy & DDL Enum Alignment, Local Mode & Architecture Decision Records (MECE Partition, Circuit Breaker, REST Gateway)  

---

## THÔNG TIN VÀ KIỂM SOÁT TÀI LIỆU

### Lịch sử phiên bản và phê duyệt

| Phiên bản | Ngày | Tóm tắt nội dung thay đổi | Tình trạng | Người thực hiện |
| :--- | :--- | :--- | :--- | :--- |
| **1.0** | 2026-09-08 | Khởi tạo hồ sơ quản trị danh mục 27 tính năng trải nghiệm người dùng (UX) và mở rộng tính năng; phân bổ 3 lớp kiến trúc (SRS Chapter 2, Modeling Chapter 3, Roadmap Backlog AD-012) | **Approved Baseline** | Nguyễn Hoàng Tùng |
| **1.7** | 2026-09-22 | Bổ sung Chương 4 & 5: Đặc tả toàn diện UI/UX v1.7 gồm lựa chọn Template/Guide/Rule/Config, vòng đời 6 trạng thái (`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `WITHHELD`), thanh tiến độ 5 giai đoạn, phân tách 4 trụ cột chất lượng (Score, Coverage, Gate, Evidence), giải thích ngữ nghĩa `WITHHELD`, bảng chẩn đoán lỗi ("Why did this fail?") kèm PII-masking, so sánh Run đối chuẩn (Current vs Previous), chế độ Local 1-Click an toàn, và phân tầng Persona (Business vs Engineer/Auditor). | **Approved Baseline** | Nguyễn Hoàng Tùng |
| **1.8** | 2026-09-22 | Tái cấu trúc Mục 6 theo chuẩn Architectural Decision Record (ADR) với đầy đủ 3 quyết định thiết kế cốt lõi: (1) Thứ bậc ưu tiên phân hoạch MECE (Strict Cascading Precedence), (2) Cơ chế ngắt mạch điểm số (Circuit Breaker Score Cap chống bẫy trung bình), và (3) Kiến trúc phân tách REST Gateway phi trạng thái (FastAPI + Decoupled UI). Bổ sung phân tích bối cảnh, phương án loại bỏ, bất biến toán học, đặc tả API và ma trận truy vết kiểm chứng (verification evidence). | **Approved Baseline** | Nguyễn Hoàng Tùng |
| **1.9** | 2026-09-22 | Đồng bộ hóa toàn diện hệ thống Mẫu (Templates) theo kiến trúc 3 tầng kỹ thuật (`RuleCatalogTemplate`, `RulesetTemplate`, `ScoringPolicyTemplate`) và Gói Đánh giá UI trọn gói (Assessment Template); chuẩn hóa 5 miền chuẩn theo DDL enum (`FINANCE`, `RETAIL`, `HEALTHCARE`, `TRANSPORTATION`, `GENERAL`); phân định Master Data là `data_type` thay vì domain; bổ sung `AssessmentTemplateDTO`, `RuleCatalogTemplateDTO` và schema đặc tả `sample_templates.json` vào Mục 5; làm rõ REST endpoint `GET /api/templates` và ma trận truy vết. | **Approved Baseline** | Nguyễn Hoàng Tùng |

---

## 1. TỔNG QUAN VÀ CHIẾN LƯỢC PHÂN TẦNG TÍNH NĂNG (3-TIER ARCHITECTURE)

Hồ sơ `AD-012` đóng vai trò là cầu nối giữa **Đặc tả Yêu cầu Kỹ thuật (SRS - Chapter 2)**, **Mô hình hóa Hành vi Hệ thống (UML - Chapter 3)** và **Lộ trình Phát triển Sản phẩm (Product Roadmap)**.

Nhằm bảo đảm tính tinh gọn, đúng chuẩn kỹ thuật của hồ sơ phần mềm chuyên nghiệp (Robert C. Martin Clean Architecture, Alistair Cockburn Use Case Guidelines, IEEE 29148 SRS):
1. **Lớp 1 — Yêu cầu Hệ thống (System Requirements trong Chapter 2):** Các tính năng liên quan đến chất lượng phần mềm, hiệu năng, an toàn hoặc giao diện người dùng được chuẩn hóa thành các mã yêu cầu kỹ thuật đo lường được (`NFR`, `IF`, `FR`).
2. **Lớp 2 — Mô hình hóa Nghiệp vụ (System Modeling trong Chapter 3):** Giữ nguyên vẹn 8 Use Cases cốt lõi của Baseline v1.0. Các tính năng mở rộng được tích hợp dưới dạng điểm mở rộng (`<<extend>>`), hậu điều kiện (Postconditions) hoặc quy định giao diện, tránh làm loãng hoặc phá vỡ các biểu đồ UML.
3. **Lớp 3 — Hồ sơ Quản trị Tính năng (Product Feature Backlog trong AD-012):** Toàn bộ 27 tính năng cải thiện trải nghiệm người dùng được lập danh mục chi tiết với đầy đủ các thuộc tính: Phân loại, Độ ưu tiên (Priority), Ước lượng độ phức tạp (Effort), Sự phụ thuộc kỹ thuật (Dependencies), Phân tích rủi ro & giải pháp kiến trúc, cùng Pha mục tiêu phát hành.

### Định nghĩa các bậc ưu tiên và kích thước nỗ lực (Effort)
- **Độ ưu tiên (Priority):**
  - `P0 (Core / Mandatory)`: Bắt buộc phải có trong Baseline v1.0 để đáp ứng bài toán lõi DQ Scoring.
  - `P1 (High / Essential Enhancements)`: Cần thiết cho trải nghiệm người dùng sản phẩm thực tế (Target: v1.0 / v1.1).
  - `P2 (Medium / Value-Add Features)`: Tính năng mở rộng nâng cấp giá trị vận hành và tự động hóa (Target: Phase 2 Enterprise).
  - `P3 (Low / Future Exploratory)`: Tính năng thử nghiệm nâng cao hoặc phụ trợ ngoài phạm vi gần (Target: Phase 3 Advanced).
- **Quy mô nỗ lực (Effort T-Shirt Size):**
  - `S (Small)`: $\le 1$–2 ngày công lập trình, thay đổi cục bộ ở frontend hoặc cấu hình.
  - `M (Medium)`: 3–5 ngày công, cần thêm API endpoint, điều chỉnh schema CSDL hoặc tích hợp thư viện mới.
  - `L (Large)`: 1–2 tuần công, đòi hỏi thiết kế engine mới, xử lý phân tán hoặc thay đổi kiến trúc pipeline.
  - `XL (Extra-Large)`: $> 2$ tuần công, tích hợp sâu với các nền tảng bên ngoài (Git, CI/CD, ML training pipelines).

---


## 2. BẢNG DANH MỤC TOÀN DIỆN 27 TÍNH NĂNG TRẢI NGHIỆM NGƯỜI DÙNG

| STT | Mã Yêu cầu (Ch. 2 / Ch. 3) | Tên Tính Năng | Phân Loại Nghiệp Vụ | Mô Tả Nghiệp Vụ & Giá Trị UX | Giải Pháp Kỹ Thuật Khuyến Nghị | Pri | Effort | Phụ Thuộc (Dependencies) | Pha Phát Hành |
|:---:|:---|:---|:---|:---|:---|:---:|:---:|:---|:---:|
| **1** | `NFR-NOTIF-001`, `NFR-NOTIF-002`, `UC-005 (Post)` | Thông báo Đa kênh (Notification) | Notification & Event Alert | Gửi cảnh báo tức thời khi job hoàn tất, thất bại hoặc DQ Score dưới ngưỡng qua Email, Slack, Microsoft Teams. | Event hook tại worker completion checkpoint; dispatch qua hàng đợi nền hoặc webhook client; cấu hình alert policy theo user/channel. | P1 | M | Event publisher trong `evaluation_runs`, SMTP/Webhook credentials | Phase 2 |
| **2** | `IF-UI-005`, `UC-005 (Flow)` | Thanh Tiến độ Thời gian thực (Real-time Progress Bar) | Progress Tracking & Feedback | Hiển thị % hoàn thành, pha xử lý hiện tại (Profiling, Rule Validation, Outlier, Scoring) và ước lượng thời gian còn lại. | Giai đoạn v1.0: Interval Polling (5–10s) vào endpoint `/runs/{id}/status`; Giai đoạn v1.1: Server-Sent Events (SSE) stream event từ PostgreSQL listen/notify. | P1 | S (Poll) / M (SSE) | Bảng `run_events`, WebSocket / SSE runtime adapter | v1.0 (Poll) / v1.1 (SSE) |
| **3** | `FR-SCHED-001`, `FR-SCHED-002`, `UC-009` | Lập Lịch Đánh giá Tự động (Auto Run Schedule) | Automation & Scheduling | Thiết lập lịch chạy định kỳ (Hàng giờ, hàng ngày, hàng tuần) theo biểu thức Cron; tự động retry khi lỗi và có tùy chọn chạy bù. | Tích hợp module scheduler nội bộ (APScheduler / PostgreSQL `pg_cron`) sinh `RunSpec` theo lịch đưa vào durable queue. | P2 | M | Durable Queue PostgreSQL 16, Cron parser | Phase 2 |
| **4** | `FR-RUN-007`, `FR-RUN-010`, `IF-UI-009` | Lịch sử Lượt chạy & Audit Log (Job History) | Audit & Observability | Xem danh sách toàn bộ các lượt chạy: thời gian, trạng thái, DQ Score, số lỗi, thời lượng; hỗ trợ lọc và xuất CSV lịch sử. | Truy vấn trực tiếp từ bảng `evaluation_runs`, `run_attempts`, `run_events`; bảng giao diện phân trang phía server (server-side pagination). | P0 | S | PostgreSQL Schema v1.0 (đã sẵn sàng) | v1.0 |
| **5** | `IF-UI-010`, `UC-007 (Extend)` | Chia sẻ Bảng điều khiển (Share Dashboard) | Collaboration & Reporting | Tạo liên kết chia sẻ Scorecard kèm token bí mật (Read-Only) hoặc mã nhúng iframe cho Confluence / Notion. | Sinh Signed URL / Share Token có thời hạn TTL (`expires_at`); API endpoint công khai kiểm tra chữ ký HMAC trước khi render read-only scorecard. | P2 | M | Token generator, RBAC Service | Phase 2 |
| **6** | `FR-GOV-008`, `UC-003 (Flow)` | Ngưỡng Cảnh báo Cá nhân hóa (Custom Threshold) | Quality Governance | Người dùng tự thiết lập ngưỡng cảnh báo riêng cho từng chiều chất lượng hoặc từng quy tắc, độc lập với policy mặc định. | Mở rộng schema `scoring_policies` cho phép override thresholds theo workspace / user profile; hệ thống đánh giá gate cá nhân song song gate hệ thống. | P2 | S | Scoring Policy Engine | Phase 2 |
| **7** | `FR-GOV-011`, `FR-GOV-013`, `FR-GOV-014`, `UC-003`, `DR-021`, `DR-026`, `DR-027`, `AC-018` | Thư viện Mẫu Đánh giá & Quy tắc Chuẩn hóa (Assessment & Rule Template Library) | Ruleset Authoring & Reuse | Cung cấp sẵn các gói bản mẫu đánh giá theo ngành (`RulesetTemplate` + `ScoringPolicyTemplate`) và kho mẫu quy tắc nguyên tử (`RuleCatalogTemplate`) tái sử dụng; hỗ trợ nhân bản thành DRAFT revision thuộc tenant và lưu vết `derived_from_template_id`. | Quản lý tập trung trên PostgreSQL qua các bảng `ruleset_templates`, `scoring_policy_templates`, `rule_catalog_templates`; UI cho phép 1-click import hoặc nhân bản DRAFT để tùy biến độc lập. | P0 / P1 | M | Ruleset & Policy Specification JSON Schemas | v1.0 / v1.1 |
| **8** | `IF-UI-006` | Giao diện Tối / Sáng (Dark / Light Theme Mode) | User Experience & Accessibility | Tùy biến theme giao diện tối hoặc sáng, tự động theo cài đặt hệ điều hành hoặc chuyển đổi thủ công; tuân thủ WCAG 2.1 AA. | Sử dụng CSS variables / Tailwind dark class; lưu preference vào `localStorage` hoặc user profile; kiểm tra độ tương phản màu tối thiểu 4.5:1. | P2 | S | Frontend framework (Tailwind CSS / UI components) | v1.1 |
| **9** | `FR-ASM-005`, `IF-SRC-005`, `UC-008` | Xuất Báo cáo Đa định dạng & Kết nối BI (Export & Integration) | Data Integration & Export | Xuất kết quả đánh giá ra CSV, Excel, PDF, JSON Canonical; hỗ trợ webhook và schema chuẩn để nạp trực tiếp vào Tableau / PowerBI. | Tích hợp thư viện sinh tệp (OpenPyXL, WeasyPrint/Puppeteer); mở rộng `AssessmentExportService` hỗ trợ định dạng bảng dẹt (flattened tabular view). | P1 | M | `ImmutableAssessment` JSON Schema, Export Service | v1.0 (JSON/HTML) / Phase 2 (Excel/BI) |
| **10** | `NFR-SAFE-004`, `NFR-SEC-004` | Chế độ Khách Dùng thử (Guest Mode Sandbox) | Trial & Onboarding | Cho phép người dùng trải nghiệm đánh giá nhanh không cần đăng nhập: tải file mẫu $\le 10$MB, chạy 1 lần, tự hủy sau 30–60 phút. | Sandbox cách ly thư mục tạm; áp dụng hạn mức tài nguyên nghiêm ngặt (RAM $\le 512$MB); cron worker định kỳ quét xóa dữ liệu tạm sau TTL. | P3 | M | Spark compact in-memory, Cleanup worker | Phase 2 |
| **11** | `FR-RECOM-001`, `UC-007 (Tab)` | Khuyến nghị Cải thiện Dữ liệu (Actionable Recommendations) | Data Remediation Advisory | Dựa trên kết quả đo lường, tự động đưa ra khuyến nghị sửa lỗi (ví dụ: regex formatting, fill null, drop duplicates) kèm script mẫu SQL/Python. | Bộ phân tích heuristic luật sinh dựa trên loại vi phạm và đặc trưng cột (từ Profiling Metrics); sinh snippet code xử lý mẫu có thể copy. | P2 | L | Profiling Metrics, Rule Results | Phase 2 |
| **12** | `IF-UI-011` | Phản hồi & Báo lỗi Gắn ngữ cảnh (Feedback & Bug Report) | Support & Developer Relations | Widget "Báo lỗi" / "Góp ý" gắn kèm context tự động (snapshot_id, run_id, error trace, client environment) gửi về hệ thống issue tracker. | Modal popup thu thập phản hồi; tự động đính kèm metadata hệ thống; chuyển tiếp ticket qua GitHub Issues API / Jira Webhook. | P3 | S | Webhook client, Ticket Tracker API | v1.1 |
| **13** | `IF-UI-012` | Hướng dẫn Sử dụng Tương tác (Interactive Tour Guide) | User Onboarding | Hướng dẫn tương tác từng bước (walkthrough) cho người dùng mới qua các màn hình: Đăng ký Asset $\rightarrow$ Tạo Policy $\rightarrow$ Chạy Run $\rightarrow$ Đọc Scorecard. | Tích hợp thư viện walkthrough nhẹ (Intro.js hoặc Shepherd.js); lưu trạng thái `tour_completed = true` vào profile/localStorage để không lặp lại. | P3 | S | Frontend walkthrough library | v1.1 |
| **14** | `IF-UI-007`, `UC-007` | Tìm kiếm Toàn văn có Gợi ý (Full-text Search & Autocomplete) | Search & Discovery | Tìm kiếm nhanh Dataset, Run, Rule hoặc kết quả đánh giá theo tên, tag, owner; gợi ý kết quả tức thì (autocomplete) khi gõ. | Tận dụng PostgreSQL Full-Text Search (`tsvector` + `tsquery`) kèm extension `pg_trgm` cho tìm kiếm mờ; debounce input phía client 300ms. | P1 | M | PostgreSQL 16 Full-Text Index | v1.1 |

| **15** | `IF-UI-008`, `UC-007` | Bộ lọc Đa tiêu chí Nâng cao (Advanced Multi-Criteria Filter) | Filtering & Navigation | Lọc kết quả đánh giá và danh sách lượt chạy theo khoảng thời gian, trạng thái, khoảng điểm DQ (min-max), chiều chất lượng, owner, tag. | Query builder hỗ trợ kết hợp điều kiện `AND`/`OR`; lưu preset bộ lọc yêu thích của người dùng; nút "Reset Filter" đưa về mặc định. | P1 | S | API query parameters, frontend filter state | v1.0 |
| **16** | `IF-UI-013`, `UC-007` | Ma trận Nhiệt Chất lượng (Interactive Heatmap) | Visualization & Analytics | Ma trận màu (Xanh/Vàng/Đỏ) thể hiện trực quan mức độ đạt chất lượng phân bố theo Bảng $\times$ Cột $\times$ 6 Chiều chất lượng; nhấp ô để drill-down. | Vẽ biểu đồ lưới ma trận bằng D3.js hoặc SVG tương tác nhẹ; tối ưu hóa virtualization khi số lượng cột vượt quá 50 cột. | P2 | M | Frontend charting library (D3.js / Plotly) | v1.1 |
| **17** | `IF-UI-014`, `UC-007` | Biểu đồ Xu hướng Chất lượng (Data Quality Trend Chart) | Historical Analytics | Biểu đồ đường thể hiện biến thiên DQ Score và 6 Dimension Scores qua các chuỗi thời gian (ngày/tuần/tháng); hỗ trợ xuất ảnh hoặc CSV. | Tổng hợp lịch sử `evaluation_runs` và `dimension_results` theo trục thời gian; render bằng Chart.js/ECharts; cho phép bật tắt các chiều. | P1 | M | Aggregation Query trên PostgreSQL 16 | Phase 2 |
| **18** | `IF-UI-003`, `IF-UI-015`, `UC-007` | Trình Xem & Tải Mẫu Lỗi (Sample Error Viewer & Export) | Drill-down & Debugging | Xem trước 10–50 bản ghi lỗi vi phạm thực tế kèm che mờ dữ liệu nhạy cảm; cung cấp nút tải toàn bộ mẫu lỗi ra tệp CSV để chuyển giao fix. | API streaming trích xuất Bounded Evidence đã được `EvidenceRedactor` xử lý; định dạng bảng động kèm nút "Download Sample CSV". | P0 | S | `EvidenceRedactor`, Bounded Evidence schema | v1.0 |
| **19** | `FR-ROOT-001` | Gợi ý Nguyên nhân Gốc Vi phạm (Root Cause Suggestion) | Advanced Diagnostics | Tự động đối soát và gợi ý nguyên nhân suy giảm chất lượng (ví dụ: schema thay đổi sau đợt deploy ETL, dữ liệu nguồn bị lệch múi giờ). | Phân tích tương quan giữa schema diff, timestamp vi phạm và metadata thay đổi hạ tầng; đưa ra cảnh báo ngữ cảnh (Advisory context). | P3 | XL | Git/CI metadata connector, Schema History Store | Phase 3 |
| **20** | `FR-COLLAB-001`, `UC-007 (Extend)` | Ghi chú & Thảo luận Cộng tác (Comment & Annotation) | Collaboration | Cho phép người dùng gắn ghi chú vào từng quy tắc, bảng hoặc lượt chạy (ví dụ: "Đang chờ team A sửa hệ thống nguồn"); hỗ trợ mention @user. | Bảng dữ liệu `annotations` liên kết khóa ngoại với `assessment_id` hoặc `rule_id`; gửi thông báo nội bộ khi có mention. | P2 | M | CSDL PostgreSQL (bảng annotations), Notification | Phase 2 |
| **21** | `FR-GOV-010`, `UC-011` | Quy trình Phê duyệt Đa cấp (Approval Workflow) | Enterprise Governance | Quy trình phê duyệt qua các cấp thẩm quyền (Steward kiểm tra $\rightarrow$ Owner thẩm định $\rightarrow$ Manager phê duyệt) trước khi công bố Scorecard ra ngoài. | Máy trạng thái phê duyệt (`DRAFT → PENDING_REVIEW → APPROVED → PUBLISHED`); ghi nhận chữ ký số hoặc audit trail kèm lý do từ chối. | P2 | M | State Machine, User Role RBAC | Phase 2 |

| **22** | `IF-CLI-002`, `NFR-INT-001`, `UC-010` | Cổng Kiểm soát CI/CD (CI/CD Quality Gate) | DevOps / MLOps Automation | Kích hoạt kiểm tra DQ trong pipeline CI/CD (GitHub Actions, GitLab CI); trả mã thoát (Exit Code) khác 0 để chặn build nếu Gate là `FAIL`. | CLI runner hỗ trợ chế độ headless với các cờ lệnh `--fail-under=80`, `--require-gate=PASS`, `--exit-code`; xuất kết quả dạng tệp `junit.xml` hoặc `summary.json`. | P1 | S (CLI) / M (Action) | CLI Command Engine, Exit Code handler | v1.0 (CLI) / v1.1 (Action) |
| **23** | `IF-SRC-006` | Truy vấn REST API Công khai (Public REST API Query) | API Integration | Cho phép các ứng dụng bên thứ ba truy vấn điểm DQ, lịch sử chạy, và danh sách vi phạm qua API chuẩn RESTful kèm phân trang và rate-limit. | FastAPI endpoints chuẩn OpenAPI 3.1; cơ chế xác thực API Key / Bearer Token; phân trang chuẩn Cursor hoặc Offset/Limit; rate limit qua Token Bucket. | P1 | M | FastAPI routing, API Key Authentication | Phase 2 |
| **24** | `IF-UI-016`, `UC-007` | Ghim Tập dữ liệu Yêu thích (Favorite Datasets) | Personalization | Đánh dấu sao các dataset quan trọng để đưa lên vị trí ưu tiên trên trang chủ Dashboard; nhận cảnh báo ưu tiên khi có thay đổi. | Lưu danh sách `favorite_dataset_ids` theo tài khoản người dùng hoặc lưu tại `localStorage` trình duyệt trong phiên bản máy đơn. | P3 | S | LocalStorage / User Profile Service | v1.1 |
| **25** | `NFR-NOTIF-003` | Bản tin Tóm tắt Định kỳ (Scheduled Email Digest) | Reporting & Engagement | Định kỳ hàng tuần hoặc hàng tháng gửi email tóm tắt điểm DQ, top 5 dataset suy giảm mạnh nhất, và top quy tắc vi phạm nhiều nhất. | Dịch vụ nền chạy theo lịch tổng hợp số liệu lịch sử; sinh nội dung HTML email chuẩn hiển thị trên mọi thiết bị; gửi qua SMTP. | P2 | M | Module Scheduler (STT 3) + Notification (STT 1) | Phase 2 |
| **26** | `FR-PROF-006`, `NFR-PERF-005`, `UC-002` | Lập Hồ sơ Dữ liệu Theo yêu cầu (Data Profiling On-demand) | Interactive Exploration | Chạy thống kê mô tả (min/max, null%, distinct, distribution) cho bất kỳ cột nào chỉ với 1 click từ giao diện khám phá dữ liệu. | Tái sử dụng trực tiếp `SnapshotProfiler` của Spark; thực thi truy vấn thống kê đơn cột bất đồng bộ không cần chạy full ruleset. | P0 | S | `SnapshotProfiler` (Engine cốt lõi đã có) | v1.0 |
| **27** | `FR-DET-007`, `UC-006 (Roadmap)` | Mở rộng Phát hiện Ngoại lệ ML (ML / Multivariate Outlier) | Advanced Analytics | Mở rộng năng lực phát hiện giá trị bất thường bằng mô hình học máy (Isolation Forest, One-Class SVM) hoặc so sánh với baseline lịch sử. | Tích hợp thư viện Scikit-learn; chạy ngoại lệ đa biến trong container worker riêng; kết quả giữ nguyên vai trò Cảnh báo (`ADVISORY`, trọng số 0). | P2 | L | Python ML dependencies (scikit-learn), Baseline Store | Phase 2 / 3 |
| **28** | `FR-AUTH-001..006`, `UC-012`, `AC-023` | Quản trị Danh tính, Xác thực & Vòng đời Token (Authentication & Session Management) | Identity & Access Management | Đăng ký tài khoản, đăng nhập băm Argon2id, cấp phát cặp Access Token (JWT 15m) + Refresh Token (UUIDv4 14d), xoay vòng và thu hồi phiên, triệt tiêu tấn công dò quét thời gian (Constant-time Dummy Execution). | Bảng `users`, `user_sessions`, Argon2id Hasher, JWT Handler. | P0 | M | PostgreSQL 16 Schema, Argon2id library | v1.0 |
| **29** | `FR-AUTH-007`, `UC-013`, `AC-020` | Mời Thành viên & Phân quyền Workspace (Workspace Member Management & RBAC) | Workspace Administration | Quản trị viên gửi thư mời thành viên vào Workspace qua email; gán vai trò (`DATA_STEWARD`, `DATA_OWNER`, `DATA_ENGINEER`, `BUSINESS_VIEWER`); người nhận kích hoạt qua Token có hạn 48h. | Bảng `tenant_memberships`, `user_invitations`, SMTP Dispatcher. | P0 | S | PostgreSQL Schema, AuthContext | v1.0 |
| **30** | `NFR-SEC-011..015`, `BR-022..024`, `AC-025` | Phòng vệ Chống Rò rỉ Dữ liệu Toàn diện & RFC 9457 (Zero-Trust Data Leak Prevention) | Security & Privacy Shielding | Vệ sinh lỗi chuẩn hóa RFC 9457 (0 stack trace, 0 SQL query, 0 file path); gỡ bỏ header công nghệ; tự động vô hiệu hóa ký tự công thức trong tệp xuất CSV/Excel (CSV Formula Sanitizer); ẩn giá trị cực trị khi mẫu $N < 5$. | `RFC9457ErrorSanitizer`, `FormulaSanitizer`, `SSRFProtectionValidator`. | P0 | S | FastAPI Exception Handlers, Export Service | v1.0 |


---


## 3. PHÂN TÍCH RỦI RO KỸ THUẬT VÀ GIẢI PHÁP KIẾN TRÚC ĐẶC BIỆT

### 3.1. Rủi ro DoS / Cạn kiệt Bộ nhớ đối với Chế độ Khách (Guest Mode - STT 10)
- **Rủi ro:** Người dùng vãng lai liên tục tải lên các tệp dữ liệu lớn (hàng trăm megabytes) hoặc kích hoạt hàng loạt job đồng thời làm tràn RAM, đầy ổ đĩa tạm hoặc cạn kiệt tài nguyên xử lý Spark worker.
- **Ranh giới Phát hành & Điều kiện Bật:** Guest Mode là tính năng P3 thuộc Phase 2 và hoãn lại sau baseline v1.0. Trong môi trường sản xuất (Production), tính năng này tuyệt đối **không được kích hoạt** khi chưa hoàn tất kiểm thử tự động cho toàn bộ 3 biện pháp phòng vệ bên dưới.
- **Giải pháp Kiến trúc:**
  1. *Ngưỡng chặn cứng (Strict Guard):* Giới hạn kích thước tệp upload cho Guest Mode tối đa $\le 10$ MB (tương đương $\approx 100.000$ dòng CSV).
  2. *Cách ly Bộ nhớ (Memory Capping):* Spark process của lượt chạy Guest bị giới hạn `spark.driver.memory = '512m'`.
  3. *Tự hủy có kiểm soát (TTL Cleanup Daemon):* Tệp dữ liệu và thư mục tạm được đánh dấu `is_guest = true`, thiết lập thời gian sống (TTL) 30–60 phút. Tiến trình quét nền tự động thu hồi tài nguyên sau khi hết hạn mà không phụ thuộc vào hành động đóng trình duyệt của người dùng.

### 3.2. Cân đối Tải Hạ tầng cho Thanh Tiến độ Thời gian thực (Real-time Progress Bar - STT 2)
- **Rủi ro:** Hàng trăm client gửi HTTP Polling liên tục (chu kỳ 1–2 giây) vào API Server sẽ gây quá tải CPU, nghẽn kết nối cơ sở dữ liệu PostgreSQL và làm giảm thông lượng của các worker chính.
- **Giải pháp Kiến trúc:**
  1. *Pha 1 (Baseline v1.0):* Áp dụng **Throttled Polling**: Client chỉ được phép thăm dò định kỳ mỗi **5 đến 10 giây**. API Server trả về trạng thái từ bộ nhớ đệm (cached state) hoặc bảng trạng thái nhẹ, không kích hoạt truy vấn aggregate nặng.
  2. *Pha 2 (v1.1 Enhancement):* Chuyển đổi sang giao thức **Server-Sent Events (SSE)** một chiều. Worker chỉ gửi bản tin tiến độ khi có sự kiện chuyển tiếp giai đoạn (`PROFILING_COMPLETED`, `RULES_EVALUATED`, `OUTLIER_DETECTED`), giảm $90\%$ lưu lượng mạng không cần thiết so với HTTP polling.

### 3.3. Cơ chế Khắc phục và Vượt qua Cổng CI/CD (CI/CD Quality Gate Bypass Governance - STT 22)
- **Rủi ro:** Khi dữ liệu thực tế đang trong quá trình di trú hoặc thử nghiệm (Migration phase), việc cổng CI/CD chặn đứng hoàn toàn pipeline sẽ gây tê liệt quy trình phát hành phần mềm của doanh nghiệp.
- **Giải pháp Kiến trúc:**
  1. Hỗ trợ tham số `--allow-failure-with-reason="Lý do cụ thể"` hoặc biến môi trường `DQ_GATE_ALLOW_BYPASS=true`.
  2. Toàn bộ hành vi bypass bắt buộc phải được ghi nhật ký (Audit Log) lưu trữ vĩnh viễn trong CSDL kèm danh tính người thực hiện và lý do giải trình, bảo đảm tính minh bạch khi hậu kiểm tuân thủ (Compliance Audit).

### 3.4. Ranh giới Đơn biến vs Đa biến trong Phát hiện Ngoại lệ (Outlier Scope - STT 27)
- **Rủi ro:** Nhầm lẫn giữa ngoại lệ đơn biến cục bộ trong cùng một cột dữ liệu với bất thường đa biến (Multivariate anomaly) hoặc trôi dạt dữ liệu theo thời gian (Data Drift) so với baseline lịch sử.
- **Giải pháp Kiến trúc:**
  1. Khóa cứng phân định rạch ròi: Baseline v1.0 chỉ tập trung giải quyết triệt để **IQR đơn biến trên cột số** trong phạm vi nội tại của snapshot (`EVD-INT-001`, `Chapter_1.md`).
  2. Các mô hình máy học phức tạp (Isolation Forest) và kiểm định trôi dạt dữ liệu so với baseline lịch sử (Kolmogorov-Smirnov Test, Population Stability Index - PSI) được xếp vào lộ trình Phase 2/3 và luôn giữ nguyên tắc: **Chỉ mang tính chất khuyến nghị (Advisory), không trực tiếp trừ điểm chất lượng kỹ thuật**.

### 3.5. Điều kiện Tiên quyết An ninh Mạng cho Cổng API Công khai (Public REST API Exposure Gate - STT 23)
- **Rủi ro:** Khi mở API công khai ra mạng bên ngoài cho các hệ thống bên thứ ba truy vấn mà không có kiểm soát truy cập và phòng vệ lạm dụng, hệ thống đối mặt với nguy cơ brute-force, rò rỉ dữ liệu chéo tổ chức (Cross-Tenant Data Leakage), và cạn kiệt tài nguyên xử lý do truy vấn quét lớn.
- **Giải pháp Kiến trúc & Điều kiện Nghiệm thu:**
  1. *Xác thực Danh tính Bắt buộc (Mandatory Authentication):* Tuyệt đối không mở endpoint công khai không danh tính ngoại trừ probe kiểm tra sức khỏe `/health`. Mọi request phải kèm API Key hoặc Bearer JWT được mã hóa mạnh.
  2. *Cưỡng chế Ranh giới Tenant (Strict Tenant Scope Enforcement):* Khóa truy vấn tự động theo `token.claims.tenant_id`. Chặn đứng tuyệt đối việc client truyền `X-Tenant-ID` giả mạo.
  3. *Giới hạn Tần suất & Quản lý Thông lượng (Rate Limiting & Token Bucket):* Áp dụng Rate Limiting phân cấp theo tenant (ví dụ: tối đa 60 requests/phút cho tier cơ bản) tại lớp Ingress / Reverse Proxy để ngăn ngừa tấn công từ chối dịch vụ.
  4. *Phân trang Bắt buộc (Enforced Pagination):* Giới hạn `limit` tối đa $\le 100$ bản ghi cho các API liệt kê (scorecards, run history, rules); cấm truy vấn không giới hạn số lượng (unbounded queries).
  5. *Vệ sinh Dữ liệu & Che mờ PII (Response Sanitization):* Toàn bộ API response trả về danh sách lỗi (evidence) bắt buộc phải qua bộ lọc che mờ PII (Two-Tiered Masking) tương ứng với vai trò của API token.

### 3.6. Điều kiện Nghiệm thu An toàn Cho Tính năng Chia sẻ Bảng điều khiển (Share Dashboard Security Gate - STT 5)
- **Rủi ro:** Khi tạo liên kết chia sẻ Scorecard ra bên ngoài (hoặc nhúng vào Confluence/Notion qua iframe), nếu áp dụng cơ chế xác thực lỏng lẻo hoặc truyền trực tiếp ID, hệ thống đối mặt với nguy cơ BOLA/IDOR (OWASP API1), rò rỉ dữ liệu cá nhân nhạy cảm (PII Leakage) và rò rỉ cấu trúc tệp máy chủ nội bộ.
- **Ràng buộc Bắt buộc & Điều kiện Nghiệm thu:**
  1. *Token Ký số Xác thực (Cryptographically Signed Share Token):* Mọi liên kết chia sẻ bắt buộc sử dụng Share Token được ký HMAC-SHA256 (hoặc Ed25519) có thời hạn sống (TTL tối đa 30 ngày) và gắn cứng định danh `(tenant_id, assessment_id)`.
  2. *Điều kiện Trạng thái Đánh giá (Assessment Publication Precondition):* Chỉ những bản đánh giá mang trạng thái `publication_status == 'PUBLISHED'` mới được phép kích hoạt tính năng chia sẻ. Mọi Assessment đang chạy (`QUEUED`, `RUNNING`) hoặc bị giữ lại (`WITHHELD`) đều bị từ chối chia sẻ.
  3. *Chiếu Dữ liệu Công khai An toàn (Sanitized Public Projection):* Khi truy cập qua Share Token, hệ thống chỉ trả về DTO chuyên biệt `PublicScorecardProjectionDTO` theo nguyên tắc Allowlist nghiêm ngặt: Tên tài sản, Snapshot ID, điểm DQ Score, 6 Dimension Scores, Quality Gate, Coverage Ratio, Assessment Hash và Published Timestamp.
  4. *Cam kết Zero-Leak (Zero Raw & Zero Evidence):* Tuyệt đối không bao gồm mẫu dòng lỗi vi phạm (`evidence_payload`), không bao gồm thẻ phát hiện dữ liệu nhạy cảm (`SensitiveDataFinding`), không chứa cấu hình rule chi tiết và không chứa đường dẫn tệp nội bộ.
  5. *Cơ chế Thu hồi Quyền Tức thì (Immediate Revocation Enforcement):* Khi người quản trị thực hiện thu hồi link chia sẻ (cập nhật `revoked_at` trong bảng `access_grants`), mọi request tiếp theo dùng token đó bắt buộc phải bị từ chối ngay lập tức (`403 Forbidden` hoặc `404 Not Found`), không bị lọt qua cache hay connection state cũ.
  6. *Giới hạn Tần suất (Rate Limiting):* Áp dụng ngưỡng rate limiting riêng biệt cho public share endpoints (tối đa 30 requests/phút trên mỗi địa chỉ IP) nhằm ngăn ngừa tấn công scraping hoặc DoS.

---


## 4. MA TRẬN TRUY VẾT HAI CHIỀU VỚI TÀI LIỆU CHÍNH (TRACEABILITY MATRIX)

Bảng ma trận truy vết đối chiếu toàn bộ 27 tính năng với các điều khoản trong **Chapter 2 (SRS)** và **Chapter 3 (System Modeling)**, kèm liên kết rõ ràng tới các packages kiến trúc trong **Chapter 4** và các bảng/schema CSDL trong **Chapter 5** nhằm đảm bảo tính nhất quán end-to-end:

| STT | Tên Tính Năng | Chương 2 (SRS) | Chương 3 (Modeling) | Chương 4 (Architecture) | Chương 5 (Database & Schema) |
|:---:|:---|:---|:---|:---|:---|
| **1** | Notification | `NFR-NOTIF-001`, `NFR-NOTIF-002` | `UC-005 (Postcondition)` | Event Dispatcher Adapter | Bảng `run_events` |
| **2** | Progress Bar | `IF-UI-005` | `UC-005 (Interaction Flow)` | Web Presentation Layer | Bảng `run_events` |
| **3** | Auto Run Schedule | `FR-SCHED-001`, `FR-SCHED-002` | `UC-009 (Phase 2 Roadmap)` | Scheduler Daemon Module | Bảng `evaluation_schedules` (Phase 2) |
| **4** | Job History | `FR-RUN-007`, `FR-RUN-010`, `IF-UI-009` | `UC-005`, `UC-007` | PostgreSQL State Repository | Bảng `evaluation_runs`, `run_attempts` |
| **5** | Share Dashboard | `IF-UI-010` | `UC-007 (<<extend>>)` | Auth & Access Port | Bảng `dashboard_shares` (Phase 2) |
| **6** | Custom Threshold | `FR-GOV-008` | `UC-003 (Flow)` | Scoring Domain Engine | Bảng `scoring_policies` |
| **7** | Assessment & Rule Library | `FR-GOV-011`, `FR-GOV-013`, `FR-GOV-014` | `UC-003 (Flow)` | Rule Catalog & Template Repository | Bảng `ruleset_templates`, `scoring_policy_templates`, `rule_catalog_templates` |
| **8** | Dark Theme | `IF-UI-006` | Presentation Attribute | Web Frontend UI Client | LocalStorage / Settings |
| **9** | Export & BI | `FR-ASM-005`, `IF-SRC-005` | `UC-008 (Export)` | Export Service Port | Schema `ImmutableAssessment` |
| **10** | Guest Mode | `NFR-SAFE-004`, `NFR-SEC-004` | `UC-001`, `UC-005 (Guest)` | Sandboxed Runner Adapter | Ephemeral In-Memory Storage |
| **11** | Recommendations | `FR-RECOM-001` | `UC-007 (Advisory Tab)` | Remediation Recommendation Service | Heuristic Rule Templates |
| **12** | Feedback / Bug | `IF-UI-011` | Support Utility | Feedback Webhook Adapter | External Issue Tracker |
| **13** | Tour Guide | `IF-UI-012` | Onboarding Flow | Web Presentation Layer | Client LocalStorage |
| **14** | Search & Auto | `IF-UI-007` | `UC-007 (Discovery Flow)` | Search Indexing Service | PostgreSQL `tsvector` Index |
| **15** | Multi Filter | `IF-UI-008` | `UC-007 (Control Flow)` | Query Builder Adapter | PostgreSQL Filter Clauses |
| **16** | Heatmap | `IF-UI-013` | `UC-007 (Visualization)` | Visualization Engine | Dimension Results Aggregator |
| **17** | Trend Chart | `IF-UI-014` | `UC-007 (Trend Flow)` | Time-Series Query Adapter | Historical Assessment Store |
| **18** | Sample Viewer | `IF-UI-003`, `IF-UI-015` | `UC-007 (Drill-down Flow)` | Bounded Evidence Redactor | Bounded Evidence Schema |
| **19** | Root Cause | `FR-ROOT-001` | Post-1.0 Diagnostics | Metadata Correlation Engine | Pipeline Audit Store |
| **20** | Annotation | `FR-COLLAB-001` | `UC-007 (<<extend>>)` | Collaboration Service | Bảng `annotations` (Phase 2) |
| **21** | Approval Workflow | `FR-GOV-010` | `UC-011 (Phase 2 Roadmap)` | Governance State Machine | Bảng `policy_approvals`, `run_approvals` |
| **22** | CI/CD Gate | `IF-CLI-002`, `NFR-INT-001` | `UC-010 (Phase 2 Roadmap)` | Headless CLI Application | Terminal Exit Codes & Summary JSON |
| **23** | REST API Query | `IF-SRC-006` | `CAP-009 (Post-1.0)` | Public FastAPI Adapter | OpenAPI 3.1 Contract Endpoints |
| **24** | Favorite Datasets | `IF-UI-016` | `UC-007 (Dashboard Home)` | User Preference Port | LocalStorage / User Profile |
| **25** | Email Digest | `NFR-NOTIF-003` | `UC-008`, `UC-009` | Mail Digest Dispatcher | Template Mailer Service |
| **26** | On-demand Profiling | `FR-PROF-006`, `NFR-PERF-005` | `UC-002 (Standalone Mode)` | Spark Snapshot Profiler | Profiling Plan & Canonical Metrics |
| **27** | ML Outlier | `FR-DET-007` | `UC-006 (ML Extension)` | ML Scikit-Learn Detector | Model Artifacts & Advisory Signals |


---

## 4. ĐẶC TẢ GIAO DIỆN NGƯỜI DÙNG VÀ LUỒNG TƯƠNG TÁC v1.7 (USER INTERFACE SPECIFICATIONS & INTERACTION FLOWS)

Nhằm hiện thực hóa trọn vẹn các yêu cầu nghiệp vụ và kỹ thuật trong SRS (Chương 2), Mô hình hóa (Chương 3) và Kiến trúc Đa thuê bao (Chương 4 & 5), phần này đặc tả chi tiết giao diện người dùng v1.7 của DQ Scoring, tối ưu cho cả môi trường phát triển cục bộ (Local Mode) lẫn môi trường vận hành đám mây doanh nghiệp (Enterprise Cloud).

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ DQ SCORING STUDIO v1.7 — [Persona: 🟢 Nghiệp vụ (Business) | 🔧 Kỹ sư & Kiểm toán (Auditor)]     │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [1. Config & Templates] │ [2. Run Lifecycle] │ [3. 4-Pillars Scorecard] │ [4. Diagnostics]       │
│ - Template Selector     │ - 6 Trạng thái     │ - DQ Score (or WITHHELD) │ - "Why did this fail?" │
│ - Interactive Guide     │ - 5-Stage Stepper  │ - Coverage (C_DQ)        │ - 5-Partition Identity │
│ - Inline Rule & Weights │ - Lease & Time     │ - Quality Gate (6 tiers) │ - Masked PII Evidence  │
│ - 1-Click Local Run     │ - SLA & Cancel     │ - Evidence Summary       │ - Drift & Compare Runs │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 4.1. Phân tầng Persona: Người dùng Nghiệp vụ vs Kỹ sư & Kiểm toán (Persona Adaptive Architecture)

Giao diện áp dụng nguyên tắc **Tiết lộ Tiến bộ (Progressive Disclosure)** thông qua nút chuyển đổi Persona tại thanh điều hướng trung tâm:

```
[ Chế độ Xem: (•) 🟢 Người dùng Nghiệp vụ (Business User)   ( ) 🔧 Kỹ sư & Kiểm toán (Auditor/Engineer) ]
```

1. **Chế độ Người dùng Nghiệp vụ (Business User - Mặc định):**
   - **Tối giản độ nhiễu kỹ thuật:** Tuyệt đối ẩn các định danh kỹ thuật dài dòng (UUID v4, Lease Token, Fused SQL Statement, Worker Process ID, SHA-256 Hashes, Exception Tracebacks).
   - **Tập trung vào giá trị nghiệp vụ:** Hiển thị điểm số phần trăm, nhãn cổng chất lượng trực quan bằng màu sắc (`PASS`, `WARN`, `FAIL`), số lượng bản ghi vi phạm thực tế, tỷ lệ lỗi và hướng dẫn khắc phục cụ thể bằng ngôn ngữ tự nhiên.
   - **Hành động rõ ràng:** Tải báo cáo tóm lược PDF/Excel, kích hoạt lại đánh giá, gửi yêu cầu phản hồi.

2. **Chế độ Kỹ sư & Kiểm toán viên (Engineer / Auditor):**
   - **Tính minh bạch và đơn định tuyệt đối (DDIA):** Mở rộng các bảng kiểm toán chuyên sâu, hiển thị `run_id`, `assessment_id`, `tenant_id`, `lease_owner`, `priority`, số lần thử lại (`attempt_count`), thời lượng từng giai đoạn (ms).
   - **Mã băm bất biến (Cryptographic Verification):** Hiển thị toàn bộ chuỗi băm SHA-256 cấu thành: `assessment_hash`, `ruleset_hash`, `policy_hash`, `snapshot_sha256`.
   - **Trình đọc câu lệnh tối ưu (SQL Pushdown Inspector):** Cho phép xem định dạng tô màu cú pháp (Syntax Highlighted) của câu lệnh Fused Single-Pass SQL CTE do `SqlQueryBuilder` sinh ra để đẩy xuống Apache Spark trên k3s.
   - **Xuất trọn gói gói kiểm toán (Audit Bundle):** Nút tải tệp `assessment_audit_package.json` có ký mã băm hoàn chỉnh để phục vụ kiểm toán độc lập bên thứ ba.

---

### 4.2. Khung Khởi động Nhanh Chế độ Cục bộ (Zero-Friction Local Mode & 1-Click Run)

Nhằm triệt tiêu rào cản thiết lập ban đầu (Zero-Friction Onboarding), giao diện cung cấp khu vực **Quick Start Local Playground** ngay đầu trang:

* **Thiết lập mặc định an toàn (Safe Local Defaults):**
  * `Tenant`: `tenant-local-dev` (Không gian Sandbox độc lập, không ảnh hưởng dữ liệu khác).
  * `Dataset Snapshot`: `sample_ecommerce_orders.parquet` (Bộ dữ liệu thương mại điện tử mẫu gồm 10.000 bản ghi, tích hợp sẵn các ca vi phạm điển hình: email sai định dạng RFC-5322, số lượng âm, mã khách hàng thiếu).
  * `Ruleset`: `E-Commerce Customer & Orders Standard Ruleset` (7 quy tắc bao phủ 4 chiều chất lượng: Completeness, Validity, Uniqueness, Timeliness).
  * `Scoring Policy`: `Balanced Enterprise Policy` (Trọng số: Completeness 30%, Validity 30%, Uniqueness 20%, Timeliness 20%; Ngưỡng Gate: Pass $\ge 90.0$, Warn $\ge 80.0$).
  * `Execution Priority`: `INTERACTIVE` (Priority = 1, mục tiêu SLA phản hồi $\le 2.5\text{ giây}$).
* **Nút bấm hành động duy nhất:** Nút lớn `🚀 Chạy Đánh giá Ngay (One-Click Quick Run)` — tự động tải dữ liệu mẫu, thiết lập tham số, gửi lệnh `enqueue_run()` và chuyển tức thì sang màn hình Giám sát Vòng đời mà không cần nhập liệu thủ công.


---

### 4.3. Quản trị Mẫu (Templates), Hướng dẫn (Guide), Quy tắc & Cấu hình Đánh giá

Giao diện cung cấp màn hình **Evaluation Studio / Configurator** cho phép người dùng tùy biến linh hoạt nhưng được kiểm soát chặt chẽ:

1. **Bộ chọn Mẫu Đánh giá theo Miền (Domain Template Selector):**
   - Trình bày dạng danh thiếp tương tác (Card Grid) tương ứng chuẩn xác với 5 miền nghiệp vụ trong định nghĩa CSDL PostgreSQL (`domain IN ('FINANCE', 'RETAIL', 'HEALTHCARE', 'TRANSPORTATION', 'GENERAL')`), kèm biểu tượng đặc trưng, số lượng quy tắc và các chiều chất lượng đo lường:
     - 🏦 **Banking & Financial Transactions (`domain = 'FINANCE'`):** Kiểm tra số tài khoản IBAN/Napas, số dư $\ge 0$, dấu thời gian giao dịch không vượt quá thời gian hiện tại, kiểm tra trùng lặp mã giao dịch (`data_type = 'TRANSACTION'`).
     - 🛒 **E-Commerce & Retail (`domain = 'RETAIL'`):** Kiểm tra tính toàn vẹn đơn hàng, khóa ngoại khách hàng, định dạng email chuẩn RFC-5322, giá tiền không âm, trạng thái đơn hàng hợp lệ (`data_type = 'TRANSACTION'` hoặc `'DIMENSION'`).
     - 🏥 **Healthcare & Clinical Records (`domain = 'HEALTHCARE'`):** Kiểm tra mã định danh bệnh nhân, phạm vi chỉ số y tế hợp lý (nhịp tim, huyết áp), độ phủ dữ liệu bắt buộc, kiểm tra nhạy cảm PII nghiêm ngặt (`data_type = 'DIMENSION'`).
     - 🚚 **Logistics & Fleet Operations (`domain = 'TRANSPORTATION'`):** Kiểm tra mã vận đơn hợp lệ, trọng tải phương tiện $\ge 0$, tọa độ GPS trong phạm vi địa lý cho phép, mốc thời gian nhận - giao hàng hợp lý (`data_type = 'EVENT'`).
     - ⚙️ **General Purpose & Master Data (`domain = 'GENERAL'`):** Kiểm tra tính duy nhất khóa chính (CCCD/Mã KH/SĐT), chuẩn hóa định dạng văn bản, phát hiện bản ghi trùng lặp (`data_type = 'MASTER_DATA'`), hoặc khởi tạo danh sách rỗng để chuyên viên tự do định nghĩa (`data_type = 'DIMENSION'`).

2. **Phân tầng Kiến trúc Mẫu (3-Tier Template Hierarchy) và Ánh xạ Thực thể Miền:**
   - Nhằm bảo đảm tính đồng bộ tuyệt đối giữa giao diện người dùng và tầng kỹ thuật CSDL (`Chapter_2` FR-GOV-011..014, DR-021, DR-026..027; `Chapter_5` Schema DDL), hệ thống phân tách rõ ràng 3 tầng bản mẫu kỹ thuật và 1 gói trải nghiệm:
     - **Rule Template (`RuleCatalogTemplate`, `FR-GOV-011`, `DR-021`):** Mẫu quy tắc nguyên tử trong Kho Rule tập trung. Định nghĩa cấu trúc kiểm tra đơn lẻ (`rule_type`, schema tham số, `default_null_policy`, `default_dimension`, `is_advisory_default`). Trả lời: *"Một phép kiểm tra cụ thể được định nghĩa ra sao?"*
     - **Ruleset Template (`RulesetTemplate`, `FR-GOV-013`, `DR-026`):** Bản mẫu danh mục tập hợp nhiều quy tắc cho một đối tượng/ngữ cảnh dữ liệu (`template_code`, `domain`, `data_type`, `target_use_case`, danh sách rule types, mức độ nghiêm trọng `CRITICAL`/`STANDARD`, trọng số $w_r$, tham số mặc định). Trả lời: *"Bộ dữ liệu này cần được kiểm tra những khía cạnh nào?"*
     - **Scoring Policy Template (`ScoringPolicyTemplate`, `FR-GOV-014`, `DR-027`):** Bản mẫu chính sách tính toán và phân loại cổng chất lượng (`template_code`, `domain`, `target_use_case`, bộ trọng số 6 chiều $W_d$, ngưỡng Gate `pass_min`, `warn_min`, `publication_threshold`). Trả lời: *"Kết quả kiểm tra kỹ thuật được tổng hợp thành điểm số và kết luận nghiệp vụ như thế nào?"*
     - **Gói Đánh giá Trọn gói (Assessment Template - UI Experience Package):** Ở cấp độ trải nghiệm người dùng, hệ thống cung cấp gói giải pháp hoàn chỉnh gồm **Ruleset Template + Scoring Policy Template tương thích đi kèm**. Khi người dùng chọn một thẻ Domain trên giao diện, hệ thống tự động nhân bản thành đúng hai bản ghi `RulesetRevision` và `ScoringPolicyRevision` ở trạng thái `DRAFT` thuộc sở hữu độc quyền của Tenant, kế thừa trọn vẹn tham số và lưu vết `derived_from_template_id` theo đúng bất biến kiểm thử `AC-018`.

   | Thẻ UI (Card Label) | Domain Enum (DDL) | Data Type (`data_type`) | Mã Mẫu Ruleset (`template_code`) | Mã Mẫu Policy (`template_code`) | Trọng số Chiều Tiêu biểu ($W_d$) | Ngưỡng Gate Mặc định |
   | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
   | **Banking & Finance** | `FINANCE` | `TRANSACTION` | `RST_FIN_TRANSACTION_V1` | `POL_FIN_REGULATORY_STRICT_V1` | V: 30%, C: 25%, U: 20%, I: 15%, T: 10% | Pass: $\ge 90.0$, Warn: $\ge 75.0$ |
   | **E-Commerce & Retail** | `RETAIL` | `TRANSACTION` | `RST_RET_ORDER_LIFECYCLE_V1` | `POL_RET_BALANCED_OPERATIONAL_V1` | C: 30%, V: 25%, I: 20%, U: 15%, T: 10% | Pass: $\ge 85.0$, Warn: $\ge 70.0$ |
   | **Healthcare & Clinical** | `HEALTHCARE` | `DIMENSION` | `RST_HLT_PATIENT_RECORDS_V1` | `POL_HLT_CLINICAL_SAFETY_V1` | V: 35%, C: 30%, U: 20%, I: 10%, T: 5% | Pass: $\ge 95.0$, Warn: $\ge 85.0$ |
   | **Logistics & Fleet** | `TRANSPORTATION` | `EVENT` | `RST_TRN_WAYBILL_TRACKING_V1` | `POL_TRN_DISPATCH_REALTIME_V1` | T: 35%, V: 25%, C: 20%, I: 10%, U: 10% | Pass: $\ge 80.0$, Warn: $\ge 65.0$ |
   | **Master Data (MDM)** | `GENERAL` | `MASTER_DATA` | `RST_GEN_MDM_GOLDEN_RECORD_V1` | `POL_GEN_MDM_UNIQUENESS_HIGH_V1` | U: 40%, V: 25%, C: 20%, I: 15%, T: 0% | Pass: $\ge 90.0$, Warn: $\ge 80.0$ |
   | **Custom Blank** | `GENERAL` | `DIMENSION` | `RST_GEN_BLANK_CUSTOM_V1` | `POL_GEN_DEFAULT_EQUAL_WEIGHT_V1` | C: 17%, V: 17%, U: 17%, I: 17%, T: 16%, K: 16% | Pass: $\ge 80.0$, Warn: $\ge 70.0$ |

3. **Trợ lý Hướng dẫn Tương tác (Interactive Guide & Field Tooltips):**
   - Hộp trợ giúp trực quan giải thích bằng thuật ngữ rõ ràng, tránh ngôn từ mơ hồ:
     - *Nhóm Xung đột (Conflict Group) là gì?* Giải thích: "Khi 2 quy tắc cùng kiểm tra 1 trường (ví dụ `is_valid_email` và `email_domain_allowed`), chỉ quy tắc chính (`primary_scoring_rule=true`) mới trừ điểm chất lượng nếu sai, quy tắc phụ chỉ ghi nhận bằng chứng vi phạm, chống trừ điểm 2 lần."
     - *Chính sách Dữ liệu Trống (Null Policy) là gì?* Giải thích: "Xác định xem các dòng bị khuyết dữ liệu có được tính vào mẫu số để đánh giá tính hợp lệ hay không (`EXCLUDE_FROM_EVALUATION` vs `FAIL_IMMEDIATELY`)."
     - *Ngoại lệ Thống kê (Advisory Outlier):* Giải thích: "Phát hiện giá trị bất thường qua IQR chỉ mang tính chất cảnh báo, trọng số bằng 0, không bao giờ làm tụt điểm kỹ thuật DQ Score."

4. **Bảng Tinh chỉnh Quy tắc Trực quan (Rule & Policy Fine-Tuner):**
   - **Bộ lọc & Tìm kiếm:** Lọc tức thời theo chiều chất lượng (*Completeness, Validity, Uniqueness, Timeliness, Consistency, Integrity*), theo cột mục tiêu, hoặc theo mức độ nghiêm trọng.
   - **Cơ chế điều khiển trên từng dòng (Inline Controls):**
     - Switch Bật/Tắt quy tắc (`Active / Inactive`).
     - Slider điều chỉnh ngưỡng vi phạm cho phép (ví dụ: `Tỷ lệ lỗi chấp nhận ≤ 0.5%`).
     - Badge chọn mức độ nghiêm trọng: `CRITICAL` (ảnh hưởng trực tiếp Quality Gate), `HIGH`, `MEDIUM`, `LOW`.
   - **Bộ Tái cân bằng Trọng số Chiều (Dimension Weight Rebalancer):**
     - Thanh trượt động cho từng chiều chất lượng.
     - Đồ thị thanh / vòng tròn thể hiện phân bổ trọng số với cơ chế tự động chuẩn hóa: Tổng trọng số các chiều có quy tắc đo lường luôn bằng đúng 100.0%.


---

### 4.4. Giám sát Trực quan Vòng đời Lượt chạy & Tiến độ 5 Giai đoạn

Màn hình **Live Run Monitor** thể hiện trực quan vòng đời lượt chạy đánh giá theo máy trạng thái chuẩn trong CSDL (`evaluation_runs`):

#### a. Trạng thái Vòng đời Toàn cục (6 Lifecycle States)
* 🟡 `QUEUED`: Lượt chạy đang nằm trong hàng đợi PostgreSQL. Hiển thị: Mức ưu tiên (*Interactive / Normal / Batch*), vị trí trong hàng đợi, thời gian đã chờ (ví dụ: `0.3s / 2.5s SLA`). Cho phép hủy bằng nút `Hủy lượt chạy`.
* 🔵 `RUNNING`: Worker đã nhận lease (lease token hợp lệ, heartbeat định kỳ mỗi 5s). Hiển thị: `Worker Lease ID`, thời gian chạy thực tế, mức chiếm dụng bộ nhớ tạm. Cho phép hủy bằng nút `Hủy lượt chạy`.
* 🟢 `SUCCEEDED`: Lượt chạy hoàn tất xuất sắc, bản đánh giá đã được tạo bền vững và công bố điểm số thành công (`status = PUBLISHED`).
* 🟣 `WITHHELD`: **Bản đánh giá đã hoàn tất thành công nhưng Điểm số bị giữ lại**. Không có lỗi sập hệ thống; bản ghi đánh giá vẫn bất biến và hợp lệ cho mục đích kiểm toán.
* 🔴 `FAILED`: Sự cố kỹ thuật nghiêm trọng (Lỗi I/O, tràn bộ nhớ, mất kết nối CSDL, crash tiến trình Spark driver/executor).
* ⚪ `CANCELLED`: Lượt chạy bị hủy chủ động bởi người dùng hoặc hệ thống thu hồi do hết hạn lease.

#### b. Thanh Tiến độ 5 Giai đoạn Tuyến tính (5-Stage Linear Stepper)

```
[ (✓) 1. Snapshot Check ] ──> [ (✓) 2. Profiling ] ──> [ (●) 3. Validation ] ──> [ ( ) 4. Scoring ] ──> [ ( ) 5. Publication ]
       120ms (Done)                  450ms (Done)              In Progress (1.2s)          Pending                 Pending
```

1. **Giai đoạn 1 — Snapshot Check:**
   - Xác thực sự tồn tại của tệp dữ liệu nguồn (Parquet / Delta / CSV).
   - Kiểm tra SHA-256 mã băm tệp nguồn, bảo đảm tính bất biến (Immutable Source Protection).
   - Xác thực schema các cột mục tiêu so với định nghĩa trong Ruleset.
2. **Giai đoạn 2 — Profiling:**
   - Thu thập thống kê tổng quan: Tổng số dòng (`row_count`), số lượng cột.
   - Thống kê phân bố giá trị rỗng (Null count/ratio) và số lượng giá trị phân biệt (Distinct counts).
   - Kích hoạt cơ chế quét và gắn nhãn phân loại dữ liệu nhạy cảm PII (`SensitiveDataFinding`).
3. **Giai đoạn 3 — Validation (Single-Pass Execution):**
   - Biên dịch ruleset thành một câu lệnh SQL Fused duy nhất (`SqlQueryBuilder.build_fused_single_pass_query`).
   - Đẩy truy vấn xuống Apache Spark thực thi chỉ với một lần quét dữ liệu (Single-Pass Scan).
   - Thu thập 5 số đếm phân hoạch (`passed`, `failed`, `missing`, `miscast`, `not_applicable`) kiểu `BIGINT`.
   - Trích xuất mẫu dòng vi phạm có che mờ tại nguồn (`LIMIT 50`, `EvidenceRedactor`).
4. **Giai đoạn 4 — Scoring & Quality Gate:**
   - Thực thi thuật toán tính điểm hoàn toàn trong bộ nhớ Python (Engine-Agnostic In-Memory Scoring).
   - Áp dụng triệt tiêu trùng lặp theo `conflict_group` và chuẩn hóa trọng số các chiều.
   - Đánh giá Cổng chất lượng 6 bậc nghiêm ngặt (`QualityGatePrecedence`).
5. **Giai đoạn 5 — Publication & Cleanup:**
   - Mở giao dịch PostgreSQL nguyên tử (Atomic ACID Transaction).
   - Tạo mã băm toàn vẹn `assessment_hash` (SHA-256).
   - Lưu trữ đồng thời vào các bảng: `evaluation_results`, `dimension_results`, `immutable_assessments`.
   - Đổi trạng thái lượt chạy sang `SUCCEEDED` (hoặc `WITHHELD`) và giải phóng hoàn toàn thư mục tạm `.tmp/`.


---

### 4.5. Phân tách 4 Trụ cột Đo lường & Giải thích Ngữ nghĩa Trạng thái WITHHELD

Giao diện **Tuyệt đối không gộp chung** các chiều đo lường vào một trạng thái chất lượng mơ hồ. Thay vào đó, 4 thẻ chỉ số chính được bố trí tách bạch trên hàng ngang đầu tiên của Bảng điểm:

```
┌───────────────────────────┐ ┌───────────────────────────┐ ┌───────────────────────────┐ ┌───────────────────────────┐
│     1. ĐIỂM SỐ (SCORE)    │ │   2. ĐỘ BAO PHỦ (COVERAGE)  │ │   3. CỔNG CHẤT LƯỢNG (GATE) │ │     4. BẰNG CHỨNG LỖI     │
│           94.2%           │ │           96.8%             │ │          ⚠️ WARN          │ │        38 Vi phạm         │
│  Xu hướng: +2.4%          │ │  31 / 32 Thuộc tính đo lường│ │  Không có lỗi Critical     │ │  50 Dòng mẫu che mờ PII   │
│  Completeness: 98.5%      │ │  1 Cột không có quy tắc     │ │  Điểm dưới ngưỡng Pass(95)│ │  Dung lượng: 18.4 KB      │
│  Validity:     91.2%      │ │  Coverage DQ: 96.8%         │ │  Bậc 5 trong chuỗi ưu tiên│ │  Zero byte rò rỉ PII thô  │
└───────────────────────────┘ └───────────────────────────┘ └───────────────────────────┘ └───────────────────────────┘
```

#### Ngữ nghĩa Thấu cảm và Minh bạch cho Trạng thái `WITHHELD`

Khi kết quả đánh giá mang trạng thái `WITHHELD`, giao diện hiển thị thẻ cảnh báo màu tím/indigo đặc trưng, bảo đảm người dùng không nhầm lẫn với lỗi hỏng hệ thống:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 🟣 ĐIỂM SỐ CHẤT LƯỢNG TẠM THỜI KHÔNG KHẢ DỤNG (SCORE WITHHELD)                                    │
│                                                                                                  │
│ ℹ️ Lý giải nghiệp vụ: Bản đánh giá chất lượng này đã được thực thi hoàn tất và ghi nhận bất biến │
│ vào kho lưu trữ kiểm toán. Tuy nhiên, hệ thống KHÔNG THỂ CÔNG BỐ ĐIỂM DQ SCORE vì:               │
│ • Lý do: Phép đo bắt buộc trên quy tắc cốt lõi không có dữ liệu hợp lệ để đo lường (Mẫu số = 0)  │
│          hoặc Độ bao phủ đo lường hiện tại (72.5%) thấp hơn ngưỡng tin cậy tối thiểu (80.0%).     │
│ • Cam kết kỹ thuật: Đây KHÔNG PHẢI lỗi sập hệ thống (Crash/System Failure). Toàn bộ dữ liệu vi   │
│   phạm và bằng chứng đã được ghi nhận đầy đủ phục vụ rà soát nguyên nhân gốc rễ.                  │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 4.6. Chẩn đoán Chi tiết Vi phạm theo Quy tắc ("Why Did This Fail?" Diagnostic Panels)

Mỗi quy tắc phát sinh lỗi vi phạm được hiển thị dưới dạng một thẻ chẩn đoán chuyên sâu (Accordion Card), cho phép chuyên viên nghiệp vụ và kỹ sư nắm rõ lý do và hành động ngay lập tức:

1. **Thanh tiêu đề Quy tắc:**
   - Mã quy tắc: `RULE-VAL-EMAIL-01` | Tên nghiệp vụ: `Kiểm tra tính hợp lệ định dạng Email Khách hàng`
   - Chiều chất lượng: `Validity` | Cột dữ liệu: `customer_email`
   - Nhãn mức độ nghiêm trọng: `[CRITICAL]` (Màu đỏ viền nổi)
   - Trọng số đóng góp: `Weight = 0.30`

2. **Bảng Phân rã Bất biến 5 Phân hoạch (5-Partition Identity Check):**
   Tuân thủ nghiêm ngặt bất biến toán học DDIA: $\text{passed} + \text{failed} + \text{missing} + \text{miscast} + \text{not\_applicable} = \text{total\_observed}$
   - 🟢 `Passed`: **9.962** dòng (99.62%)
   - 🔴 `Failed`: **38** dòng (0.38%)
   - ⚪ `Missing`: **0** dòng (0.00%)
   - ⚪ `Miscast`: **0** dòng (0.00%)
   - ⚪ `Not Applicable`: **0** dòng (0.00%)
   - **Tổng quan sát:** **10.000** dòng

3. **Lý giải Nguyên nhân Gốc rễ bằng Ngôn ngữ Tự nhiên (Why did this fail?):**
   - *"Giá trị trong cột 'customer_email' không khớp biểu thức chính quy chuẩn RFC-5322 (thiếu ký tự '@', thiếu tên miền cấp cao '.com/.vn', hoặc chứa khoảng trắng thừa ở cuối chuỗi)."*

4. **Khung Bằng chứng Mẫu đã Che mờ PII (Sample Evidence Viewer):**
   - Hiển thị bảng 10–50 dòng vi phạm thực tế đã được che mờ động an toàn tại tầng Compute (`nguy***@gmail.com`, `098***765`).
   - Cột gây lỗi được bôi đỏ nhạt và hiển thị chi tiết giá trị vi phạm.
   - Nút hành động: `📥 Tải Mẫu Vi phạm (CSV / JSON)`.

5. **Khuyến nghị Khắc phục Nghiệp vụ (Remediation Advice):**
   - *"Kiểm tra dịch vụ tiếp nhận đơn hàng phía Web Frontend; bổ sung bộ lọc `trim()` khoảng trắng trước khi nạp dữ liệu vào bảng cơ sở dữ liệu."*


---

### 4.7. So sánh Đánh giá Đa phiên bản (Dataset/Run Comparison View)

Cho phép người dùng thực hiện đối soát chất lượng giữa Lượt chạy Hiện tại (Current Assessment) và Lượt chạy Liền kề trước đó (Baseline Run):

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ SO SÁNH ĐỐI CHUẨN: Lượt chạy hiện tại (#Run-108)  vs.  Lượt chạy trước (#Run-104 - Baseline)      │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Δ Điểm DQ Score:      +2.4%  (91.8% ──> 94.2%  ▲ Tăng trưởng tích cực)                          │
│ Δ Độ Bao phủ:          0.0%  (96.8% ──> 96.8%  — Ổn định)                                        │
│ Dịch chuyển Gate:     WARN  ──> PASS          (Nâng bậc thành công)                              │
│ Bản ghi vi phạm:      -15 bản ghi vi phạm      (Giảm từ 53 xuống 38 vi phạm)                     │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ BIẾN ĐỘNG QUY TẮC (RULE DRIFT ANALYSIS):                                                         │
│ 🟢 Đã khắc phục (Fixed):      `RULE-COMP-PHONE-02` (Vi phạm 0 dòng, trước đó 15 dòng)            │
│ 🔴 Phát sinh lỗi mới (Drift): Không có quy tắc nào bị hồi quy lỗi                               │
│ 🟡 Cải thiện một phần:       `RULE-VAL-EMAIL-01`  (Giảm từ 38 xuống 23 lỗi)                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

* **Biểu đồ Đối sánh 6 Chiều (Comparative Dimension Chart):**
  Hiển thị trực quan biểu đồ cột kép so sánh từng chiều giữa Baseline (Cột xám viền đứt) và Current (Cột xanh dương đậm).

---

### 4.8. Bảng Điều khiển Kiểm toán Kỹ thuật (Engineering Audit Panel & Signed Export)

Chỉ hiển thị khi chuyển sang Persona **Kỹ sư & Kiểm toán viên**:

1. **Khối Khóa Runtime & Thực thi:**
   - `Run ID`: `9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d`
   - `Assessment ID`: `f47ac10b-58cc-4372-a567-0e02b2c3d479`
   - `Tenant ID`: `tenant-local-dev`
   - `Lease Owner`: `worker-node-01-pid-4912`
   - `Execution Priority`: `1 (Interactive, SLA <= 2.5s)`
   - `Execution Time`: `1,842 ms` (Queue: 120ms, Compute: 1,480ms, Publication: 242ms)

2. **Khối Băm Toàn vẹn Mã hóa (Cryptographic Immutability Hashes):**
   - `Assessment Hash (SHA-256)`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
   - `Ruleset Hash (SHA-256)`: `d2d2d2d2...`
   - `Scoring Policy Hash (SHA-256)`: `a1a1a1a1...`
   - `Source Data Hash (SHA-256)`: `7f83b165...`

3. **Trình xem Truy vấn Tối ưu (Fused SQL Query Inspector):**
   - Cung cấp khung xem câu lệnh SQL gộp Single-Pass CTE thực tế đã được Spark thực thi, chứng minh tính minh bạch của số liệu.

4. **Nút Xuất Gói Kiểm toán Toàn vẹn (1-Click Signed Audit Package):**
   - Nút: `📥 Tải Gói Kiểm toán Đầy đủ (Signed JSON Bundle)`.
   - Gói tải về chứa trọn vẹn: Toàn bộ thông số cấu hình, kết quả số đếm 5 phân hoạch, chuỗi băm bảo chứng, không chứa dữ liệu PII thô của khách hàng.


---

## 5. ĐẶC TẢ THÀNH PHẦN TẦNG TRÌNH DIỄN (`PKG-007`) VÀ HỢP ĐỒNG DỮ LIỆU UI

### 5.1. Cấu trúc Module Tầng Trình diễn (`src/dq_scoring/presentation/`)

Tuân thủ kiến trúc phân tầng trong Chương 4 và nguyên lý Clean Code:

```
src/dq_scoring/presentation/
├── __init__.py
├── app.py                      # Streamlit Application Entrypoint & Navigation Shell
├── state.py                    # Session State Management & Local Storage Handlers
├── components/                 # Các khối UI độc lập tái sử dụng (Atomic Components)
│   ├── __init__.py
│   ├── persona_bar.py          # Thanh chuyển đổi Persona (Business vs Auditor)
│   ├── lifecycle_stepper.py    # Thanh tiến độ 5 giai đoạn & hiển thị 6 trạng thái vòng đời
│   ├── pillar_cards.py         # 4 Thẻ trụ cột: Score, Coverage, Quality Gate, Evidence
│   ├── withheld_banner.py      # Thẻ giải thích ngữ nghĩa tường minh khi trạng thái WITHHELD
│   ├── diagnostic_card.py      # Khung "Why did this fail?" kèm bảng phân rã 5 phân hoạch
│   ├── comparison_table.py     # Bảng đối sánh Current vs Previous Run & Rule Drift
│   └── audit_drawer.py         # Ngăn kéo kiểm toán kỹ sư (Hashes, SQL Viewer, JSON Export)
├── views/                      # Các trang màn hình chính (Page Controllers)
│   ├── __init__.py
│   ├── config_studio.py        # Tab 1: Chọn Template, Hướng dẫn, Quy tắc, Cấu hình, 1-Click Run
│   ├── live_monitor.py         # Tab 2: Giám sát Vòng đời Lượt chạy thời gian thực
│   ├── scorecard_view.py       # Tab 3: Bảng điểm 4 Trụ cột & Chi tiết Đánh giá
│   └── comparison_view.py      # Tab 4: So sánh đa phiên bản & Phân tích Xu hướng
└── samples/                    # Dữ liệu & Mẫu quy tắc phục vụ Chế độ Local Playground
    ├── sample_orders.parquet   # Bộ dữ liệu mẫu 10.000 dòng có sẵn vi phạm kiểm thử
    └── sample_templates.json   # Danh mục mẫu đánh giá tiêu chuẩn theo ngành (mảng JSON chứa các bản ghi AssessmentTemplateDTO đồng bộ DDL Chapter 5)
```

### 5.2. Ánh xạ Hợp đồng Dữ liệu DTO (UI Data Contracts)

Các view trong `PKG-007` chỉ tương tác với tầng Facade (`PKG-004`) và REST Gateway thông qua các DTO bất biến, không bao giờ truy vấn trực tiếp CSDL:

* `AssessmentTemplateDTO`: Bản ghi mẫu đánh giá trọn gói phục vụ Domain Template Selector trên UI; chứa `template_id` (UUID), `template_code` (String, ví dụ `RST_FIN_TRANSACTION_V1`), `name` (String), `domain` (Enum `FINANCE`, `RETAIL`, `HEALTHCARE`, `TRANSPORTATION`, `GENERAL`), `data_type` (Enum `TRANSACTION`, `DIMENSION`, `MASTER_DATA`, `EVENT`), `target_use_case` (String), `description` (String), `ruleset_template` (chi tiết danh sách quy tắc, mức độ nghiêm trọng `CRITICAL`/`STANDARD`, trọng số quy tắc $w_r$, tham số chuẩn), `scoring_policy_template` (chi tiết bộ trọng số 6 chiều $W_d$, ngưỡng Gate `pass_min`, `warn_min`, `publication_threshold`), và `is_system_template` (Boolean).
* `RuleCatalogTemplateDTO`: Bản ghi mẫu quy tắc nguyên tử phục vụ tra cứu trong Kho Rule tập trung; chứa `template_id` (UUID), `template_code` (String), `name` (String), `rule_type` (`NON_NULL`, `TYPE_PARSE`, `DOMAIN_RANGE`, `UNIQUENESS`, `CROSS_FIELD`), `default_dimension` (Dimension Enum), `parameter_schema` (JSON Schema), `default_null_policy` (`EXCLUDE_FROM_EVALUATION`, `FAIL_IMMEDIATELY`), `is_advisory_default` (Boolean).
* `RunStatusDTO`: Chứa `run_id`, `status` (`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `WITHHELD`), `stage_name`, `elapsed_ms`, `queue_position`.
* `ScorecardDTO`: Chứa `assessment_id`, `dq_score`, `coverage_percentage`, `quality_gate_status`, `is_withheld`, `withheld_reason`, danh sách `DimensionScoreDTO`.
* `RuleDiagnosticDTO`: Chứa `rule_name`, `dimension`, `column_name`, `severity`, `passed_count`, `failed_count`, `missing_count`, `miscast_count`, `not_applicable_count`, `sample_violations` (đã che mờ PII), `remediation_advice`.
* `AssessmentComparisonDTO`: Chứa `current_score`, `baseline_score`, `delta_score`, `delta_coverage`, `gate_transition`, danh sách quy tắc `fixed_rules`, `regressed_rules`, `unchanged_rules`.
* `AuditPackageDTO`: Chứa toàn bộ cây dữ liệu JSON có chữ ký băm phục vụ xuất kiểm toán.


---

## 6. HỒ SƠ QUYẾT ĐỊNH THIẾT KẾ KIẾN TRÚC (ARCHITECTURAL DECISION RECORDS — ADR)

Nhằm đảm bảo tính minh bạch, khả năng tái lập (reproducibility) và tính đơn định (determinism) tuyệt đối theo chuẩn Martin Kleppmann (DDIA) và Robert C. Martin (Clean Architecture), phần này ghi nhận 3 quyết định kiến trúc cốt lõi định hình tầng phân hoạch dữ liệu, logic ngắt mạch an toàn và cổng giao tiếp dịch vụ của hệ thống DQ Scoring.

---

### 6.1. ADR-012-1: Thứ bậc Ưu tiên Phân hoạch Tuyệt đối (Strict MECE Cascading Partition Priority)

#### a. Bối cảnh và Vấn đề Kỹ thuật (Context & Problem Statement)
Trong quá trình lượng hóa chất lượng dữ liệu ở cấp độ phần tử (cell-level data observation), một ô dữ liệu có thể đồng thời kích hoạt nhiều trạng thái tiêu cực:
- Vừa mang giá trị thiếu (e.g. `NULL` hoặc chuỗi rỗng `""`),
- Vừa không thể ép kiểu sang kiểu dữ liệu mục tiêu (e.g. `TRY_CAST` trả về `NULL`),
- Vừa không thỏa mãn biểu thức logic nghiệp vụ (e.g. `order_amount > 0`).

Nếu không có một quy tắc phân định rõ ràng và đơn định, hệ thống sẽ gặp các vấn đề nghiêm trọng:
1. **Chồng lấn phân hoạch (Partition Overlap Ambiguity):** Một bản ghi bị đếm trùng lặp ở nhiều phân loại lỗi khác nhau, làm méo mó mẫu số tính điểm.
2. **Vi phạm Bất biến Toàn vẹn Phân hoạch (DDIA Total Observed Invariant):** Phá vỡ đẳng thức bảo toàn không gian mẫu:
   $$\text{passed} + \text{failed} + \text{missing} + \text{miscast} + \text{not\_applicable} = \text{total\_observed}$$
3. **Chi phí I/O đa lượt (Multi-Pass Query Inefficiency):** Nếu thực thi từng quy tắc kiểm tra qua các câu truy vấn SQL riêng biệt, hệ thống phải quét bảng (table scan) nhiều lần, gây suy giảm hiệu năng nghiêm trọng trên các tập dữ liệu hàng chục triệu dòng.

#### b. Quyết định Thiết kế (Decision)
Hệ thống thiết lập một **Thứ bậc Ưu tiên Tuyến tính 5 Cấp độ Tuyệt đối (Strict 5-Tier Early-Exit Cascade)** mang tính MECE (Mutually Exclusive, Collectively Exhaustive):

$$\text{not\_applicable} \;\succ\; \text{missing} \;\succ\; \text{miscast} \;\succ\; \text{failed} \;\succ\; \text{passed}$$

Quy trình phân loại cho từng phần tử quan sát diễn ra tuần tự với cơ chế thoát sớm (early exit):
1. **Cấp 1 — `not_applicable` (Ưu tiên cao nhất):**
   - *Điều kiện:* Dòng dữ liệu không thỏa mãn vị ngữ bộ lọc tiền đề (`row_filter_predicate`).
   - *Hành vi:* Gán vào `not_applicable`, ngắt toàn bộ các kiểm tra phía sau. Dòng này không tham gia đánh giá quy tắc.
2. **Cấp 2 — `missing`:**
   - *Điều kiện:* Dữ liệu thuộc diện áp dụng nhưng mang giá trị khuyết (`IS NULL`, chuỗi rỗng `""`, hoặc nằm trong Sentinel Tokens: `'N/A'`, `'\N'`, `'null'`).
   - *Hành vi:* Gán vào `missing`. Cell thiếu không thể kiểm tra kiểu dữ liệu hay quy tắc logic.
3. **Cấp 3 — `miscast`:**
   - *Điều kiện:* Dữ liệu áp dụng, có mặt, nhưng ép kiểu an toàn `TRY_CAST(col AS target_type)` trả về `NULL`.
   - *Hành vi:* Gán vào `miscast` (lỗi cú pháp kiểu). Cell sai kiểu không đưa vào so sánh nghiệp vụ.
4. **Cấp 4 — `failed`:**
   - *Điều kiện:* Dữ liệu áp dụng, có mặt, đúng kiểu, nhưng vi phạm biểu thức logic (`business_rule_sql`).
   - *Hành vi:* Gán vào `failed` (vi phạm nghiệp vụ).
5. **Cấp 5 — `passed`:**
   - *Điều kiện:* Dữ liệu thỏa mãn đồng thời toàn bộ các điều kiện trên.
   - *Hành vi:* Gán vào `passed`.

Toàn bộ quy trình này được đẩy xuống Spark Engine dưới dạng **Fused Single-Pass Vectorized Pushdown SQL** sử dụng mệnh đề `COUNT(*) FILTER (WHERE ...)` bảo đảm tính toán $O(1)$ lượt quét duy nhất.

#### c. Các Phương án đã Xem xét và Loại bỏ (Alternatives Considered & Rejected)
- **Phương án A — Gán Đa Nhãn (Multi-Label Tagging):** Cho phép một dòng nhận đồng thời nhiều nhãn (`missing=true`, `failed=true`).  
  *Lý do loại bỏ:* Làm mất tính MECE, vi phạm đẳng thức tổng quan sát, khiến tổng hợp điểm số các chiều trở nên nhập nhằng.
- **Phương án B — Truy vấn Độc lập Từng Phân hoạch (Multi-pass Queries):** Thực hiện 5 câu truy vấn riêng biệt cho 5 trạng thái.  
  *Lý do loại bỏ:* Chi phí quét bảng tăng gấp 5 lần, tiềm ẩn nguy cơ sai lệch giữa các lần quét nếu dữ liệu biến động.
- **Phương án C — Đặt `failed` trước `missing`:** Kiểm tra logic nghiệp vụ trước khi kiểm tra dữ liệu thiếu.  
  *Lý do loại bỏ:* Trong SQL ba giá trị, so sánh biểu thức logic trên `NULL` luôn trả về `UNKNOWN`/`NULL`, dễ gán nhầm dòng thiếu thành vi phạm logic.

#### d. Bằng chứng Triển khai & Kiểm chứng (Implementation Evidence & Verification)
- **Logic Phân loại Đơn định:** Module `dq_scoring.presentation.partition_hierarchy`:
  - Enum `PartitionCategory(StrEnum)`: `{NOT_APPLICABLE, MISSING, MISCAST, FAILED, PASSED}`.
  - Tuple bất biến `PARTITION_PRECEDENCE`.
  - Hàm phân loại: `classify_cell_partition(*, is_applicable, is_missing, can_cast, passes_rule) -> PartitionCategory`.
- **Trình sinh SQL Đơn lượt (Single-Pass SQL Generator):**
  - Class `SinglePassSQLGenerator.generate_partition_counts_query(...)`: Tự động sinh biểu thức SQL CTE tương thích Spark với 5 mệnh đề `FILTER (WHERE ...)` loại trừ lẫn nhau.
- **REST API Endpoints:** `POST /api/partition/classify` và `POST /api/partition/sql`.
- **Bộ Kiểm thử Đơn vị (Unit Test Suite):**
  - Tệp `tests/unit/presentation/test_partition_hierarchy.py` (7 tests đạt 100% pass):
    - `test_partition_precedence_order`: Bất biến thứ tự ưu tiên của tuple.
    - `test_precedence_level_1_not_applicable` đến `test_precedence_level_5_passed`: Kiểm chứng độc lập 5 nhánh ưu tiên.
    - `test_mece_single_pass_sql_generator`: Kiểm chứng cấu trúc câu lệnh Spark SQL pushdown.
  - Tệp `tests/unit/presentation/test_api.py`: Kiểm chứng phân loại và sinh SQL qua HTTP endpoints.

#### e. Hệ quả & Đánh đổi (Tradeoffs & Mitigations)
- **Đánh đổi:** Biểu thức SQL pushdown dài hơn do phải mang các điều kiện phủ định tích lũy (`NOT missing_clause`, `TRY_CAST IS NOT NULL`).
- **Biện pháp:** Trình sinh SQL tự động đóng gói toàn bộ logic này, người dùng chỉ cần định nghĩa vị ngữ nghiệp vụ đơn giản.

---

### 6.2. ADR-012-2: Cơ chế Ngắt Mạch Điểm Số (Circuit Breaker Score Cap — Chống Bẫy Trung Bình)

#### a. Bối cảnh và Vấn đề Kỹ thuật (Context & Problem Statement)
Trong các hệ thống đo lường chất lượng dữ liệu truyền thống áp dụng mô hình Điểm trung bình có trọng số (Weighted Average Scoring):
- Nếu một tập dữ liệu có 20 quy tắc phụ (định dạng, độ dài, chính tả) đạt điểm tuyệt đối 100%, nhưng chỉ duy nhất 1 quy tắc bất biến sống còn (Critical Invariant — ví dụ: khóa chính trùng lặp, số dư tài khoản âm, trường mã định danh khách hàng bị rỗng 100%) bị vi phạm, điểm trung bình tổng hợp vẫn có thể đạt mức **95.0% – 97.0%**.
- **Hiện tượng "Bẫy Trung Bình" (The Averaging Trap):** Điểm số trung bình che giấu hoàn toàn rủi ro thảm họa dữ liệu, tạo ra "cảm giác an toàn giả tạo" cho doanh nghiệp, khiến dữ liệu độc hại vẫn được cấp phép nạp vào kho dữ liệu báo cáo tài chính hoặc mô hình AI production.

#### b. Quyết định Thiết kế (Decision)
Hệ thống thiết lập **Cơ chế Ngắt Mạch Điểm Số Phi Tuyến (Non-Linear Circuit Breaker Score Cap)**:

$$S_{final} = \begin{cases} 
S_{weighted}, & \text{nếu } \forall r \in R_{critical}, \; \text{failed}_r = 0 \;\land\; \text{pass\_rate}_r \ge \theta_{critical} \\
\min(S_{weighted}, 49.0), & \text{nếu } \exists r \in R_{critical}, \; \text{failed}_r > 0 \;\lor\; \text{pass\_rate}_r < \theta_{critical}
\end{cases}$$

Trong đó:
- $R_{critical}$: Tập hợp các quy tắc có mức độ nghiêm trọng `RuleSeverity.CRITICAL`.
- $\theta_{critical}$: Ngưỡng tỷ lệ đạt tối thiểu của quy tắc sống còn (mặc định $95.0\%$ hoặc $100\%$ đối với zero-tolerance rules).
- Hằng số trần `CIRCUIT_BREAKER_SCORE_CAP = 49.0%`: Mức điểm trần tương ứng với xếp hạng kém nhất (Grade F), tước bỏ hoàn toàn khả năng đạt cổng chấp nhận.

Khi cơ chế Circuit Breaker được kích hoạt:
1. **Áp trần điểm số tức thì:** Điểm chất lượng tổng thể bị áp trần ở mức $\le 49.0\%$. Nếu điểm ban đầu đã thấp hơn 49.0%, giữ nguyên điểm thấp hơn thông qua hàm $\min(S_{weighted}, 49.0)$.
2. **Kích hoạt Cổng Chất lượng Cưỡng bức:** Trạng thái Quality Gate lập tức bị nâng lên cấp độ nghiêm trọng **`QualityGateStatus.CRITICAL_FAIL`**, ghi đè toàn bộ các điều kiện điểm số thông thường.
3. **Bảo tồn Dữ liệu Kiểm toán:** Ghi nhận cờ `circuit_breaker_triggered = True`, lưu vết đồng thời cả `uncapped_dq_score` (điểm số chưa áp trần) và lý do ngắt mạch chi tiết (`gate_trigger_reason`) vào bảng điểm `ScorecardDTO`.

#### c. Các Phương án đã Xem xét và Loại bỏ (Alternatives Considered & Rejected)
- **Phương án A — Thổi phồng Trọng số (Weight Inflation, e.g. weight=1000):** Tăng trọng số quy tắc critical lên cực lớn trong công thức trung bình.  
  *Lý do loại bỏ:* Làm phá vỡ tính chuẩn hóa tổng trọng số các chiều (luôn bằng 100%), gây khó khăn trong phân bổ ngân sách trọng số và vẫn không đảm bảo tuyệt đối chặn được điểm số nếu tập quy tắc con quá nhiều.
- **Phương án B — Hủy ngang Lượt chạy (Hard Abort / FAILED):** Đánh dấu toàn bộ lượt chạy là `FAILED` khi phát hiện lỗi critical.  
  *Lý do loại bỏ:* Vi phạm nguyên tắc khả quan sát (DDIA Observability). Người dùng cần báo cáo chi tiết về nguyên nhân lỗi và bằng chứng vi phạm chứ không phải một thông báo lỗi sập hệ thống.
- **Phương án C — Ép điểm về 0.0%:** Gán điểm số về 0 tuyệt đối.  
  *Lý do loại bỏ:* Dễ gây nhầm lẫn với trạng thái chưa đánh giá hoặc lỗi kỹ thuật. Mức trần 49.0% định vị chính xác phân loại Grade F (Fail) trong thang điểm giáo dục và tiêu chuẩn chất lượng.

#### d. Bằng chứng Triển khai & Kiểm chứng (Implementation Evidence & Verification)
- **Logic Đánh giá Ngắt mạch:** Hàm `evaluate_circuit_breaker` trong module `dq_scoring.presentation.partition_hierarchy`:
  - Trả về cấu trúc bất biến `CircuitBreakerResult(NamedTuple)` gồm: `final_dq_score`, `circuit_breaker_triggered`, `uncapped_dq_score`, `gate_status`, `gate_trigger_reason`, `critical_violations_count`.
- **Mô hình Dữ liệu Bất biến:** `ScorecardDTO` trong `dq_scoring.presentation.models`:
  - Quản trị độc lập 4 trụ cột đánh giá: Trụ cột 1 (DQ Score kèm Circuit Breaker), Trụ cột 2 (Coverage), Trụ cột 3 (Quality Gate), Trụ cột 4 (Evidence).
- **REST API Endpoint:** `GET /api/assessments/{run_id}?circuit_breaker=true` trả về payload tích hợp trạng thái ngắt mạch.
- **Bộ Kiểm thử Đơn vị & Giao diện (Unit Test Suite):**
  - Tệp `tests/unit/presentation/test_circuit_breaker.py` (5 tests đạt 100% pass):
    - `test_circuit_breaker_not_triggered_when_all_critical_pass`: Xác nhận không can thiệp điểm số khi quy tắc critical đạt chuẩn.
    - `test_circuit_breaker_triggered_by_critical_rule_failure`: Xác minh điểm số 98.5% bị ép chuẩn xác xuống 49.0% khi có vi phạm critical.
    - `test_circuit_breaker_respects_lower_uncapped_score`: Xác nhận nếu điểm ban đầu là 35.0%, hệ thống giữ nguyên 35.0% chứ không nâng lên 49.0%.
    - `test_circuit_breaker_ignores_non_critical_severity`: Xác nhận lỗi ở quy tắc HIGH/MEDIUM/LOW không kích hoạt ngắt mạch điểm số.
    - `test_pillar_cards_renders_circuit_breaker_state`: Kiểm chứng UI component hiển thị huy hiệu cảnh báo và nhãn `CRITICAL FAIL`.
  - Tệp `tests/unit/presentation/test_api.py::test_api_get_scorecard_circuit_breaker`.

#### e. Hệ quả & Đánh đổi (Tradeoffs & Mitigations)
- **Đánh đổi:** Người dùng nghiệp vụ có thể bất ngờ khi thấy điểm số tụt dốc phi tuyến từ 98% xuống 49%.
- **Biện pháp:** Giao diện người dùng hiển thị trực quan thông điệp giải thích minh bạch: *"Cơ chế ngắt mạch đã kích hoạt do Quy tắc Sống còn bị vi phạm — Điểm số chưa trần: 98.5%, Điểm áp trần: 49.0% (Grade F)"*, kèm liên kết trực tiếp tới bản ghi lỗi trong bảng chẩn đoán vi phạm.

---

### 6.3. ADR-012-3: Kiến trúc Phân Tách REST Gateway & Tối Ưu Hóa Giao Diện Người Dùng

#### a. Bối cảnh và Vấn đề Kỹ thuật (Context & Problem Statement)
Các giải pháp giao diện phân tích dữ liệu nguyên khối (như Streamlit) thường gặp phải các hạn chế cấu trúc:
- **Duy trì Trạng thái qua WebSocket (Stateful WebSocket Connections):** Mỗi phiên làm việc của người dùng chiếm dụng bộ nhớ RAM liên tục trên máy chủ backend. Khi số lượng người dùng đồng thời tăng, nguy cơ cạn kiệt bộ nhớ (OOM) rất cao.
- **Cơ chế Chạy lại Toàn bộ Script (Full-Script Rerun):** Mỗi tương tác bấm nút hoặc chọn dropdown kích hoạt chạy lại toàn bộ script Python từ đầu đến cuối, gây lãng phí chu kỳ CPU và tăng độ trễ giao diện.
- **Không có Giao tiếp Lập trình (Lack of Programmatic Interface):** Không cung cấp cổng API REST chuẩn hóa để các công cụ bên ngoài (Airflow, Dagster, GitLab CI/CD, CronJobs) có thể gọi đánh giá và đối soát chất lượng dữ liệu tự động.

#### b. Quyết định Thiết kế (Decision)
Hệ thống áp dụng mô hình **Kiến trúc Phân tách Tầng Trình diễn (Decoupled Presentation Architecture)**:
1. **FastAPI REST API Gateway (`dq_scoring.presentation.api`):**
   - Hoàn toàn phi trạng thái (Stateless), tuân thủ 100% chuẩn đặc tả OpenAPI 3.1.
   - Triển khai theo mẫu thiết kế Application Factory (`create_app()`), tích hợp CORS Middleware cho phép mở rộng linh hoạt.
   - Sẵn sàng mở rộng ngang (Horizontal Pod Autoscaling - HPA) trong môi trường container Kubernetes mà không lo ngại đồng bộ trạng thái phiên.
2. **Giao diện Web Phản ứng Nhanh Tự chủ (Decoupled Reactive SPA):**
   - Được phục vụ trực tiếp tại root `/` và `/ui` dưới dạng mã nguồn tĩnh tự chủ (Single-file SPA).
   - Sử dụng Alpine.js cho reactivity tại client và Tailwind CSS cho giao diện thích ứng, không cần cài đặt Node.js hay build step phức tạp trên máy chủ vận hành.
   - Giao tiếp 100% qua các API endpoints phi trạng thái, đưa mức tiêu tốn RAM máy chủ cho mỗi phiên người dùng về xấp xỉ 0 MB.

#### c. Các Phương án đã Xem xét và Loại bỏ (Alternatives Considered & Rejected)
- **Phương án A — Duy trì Thuần túy Streamlit:**  
  *Lý do loại bỏ:* Tiêu tốn bộ nhớ phiên, khó tích hợp CI/CD tự động và không thể mở rộng ngang hiệu quả trong cụm microservices.
- **Phương án B — Xây dựng Frontend Độc lập bằng Next.js/React:**  
  *Lý do loại bỏ:* Theo nguyên lý Ponytail / YAGNI, việc thêm dự án Next.js yêu cầu quản lý môi trường Node.js riêng, pipeline Docker đa tầng phức tạp và chi phí bảo trì vượt quá yêu cầu tinh gọn của giai đoạn hiện tại. Phương án Alpine.js nhúng tĩnh đáp ứng hoàn hảo tính phản xạ (reactivity) mà vẫn giữ toàn bộ ứng dụng trong một package Python duy nhất.

#### d. Bằng chứng Triển khai & Kiểm chứng (Implementation Evidence & Verification)
- **Cấu hình Gateway:** `dq_scoring.presentation.api.app` (hàm `create_app() -> FastAPI`).
- **Danh mục 10 Endpoints REST Chuẩn hóa (`dq_scoring.presentation.api.routes`):**
  1. `GET /api/health`: Kiểm tra sức khỏe dịch vụ và thông tin phiên bản.
  2. `GET /api/templates`: Truy xuất danh mục mẫu đánh giá trọn gói theo ngành (`List[AssessmentTemplateDTO]`) phục vụ Domain Template Selector trên UI. (Các mẫu quy tắc nguyên tử trong Kho Rule được truy xuất riêng qua `GET /api/catalog/rules`).
  3. `POST /api/runs`: Tiếp nhận yêu cầu đánh giá mới vào hàng đợi (HTTP 202 ACCEPTED).
  4. `GET /api/runs/{run_id}/status`: Giám sát trạng thái 6 vòng đời và tiến độ 5 giai đoạn.
  5. `GET /api/assessments/{run_id}`: Bảng điểm 4 trụ cột kèm Circuit Breaker và WITHHELD.
  6. `GET /api/assessments/{run_id}/diagnostics`: Bảng chẩn đoán chi tiết vi phạm và dòng che mờ PII.
  7. `GET /api/assessments/{run_id}/audit`: Dữ liệu kiểm toán kỹ thuật (chuỗi băm SHA-256, Fused SQL).
  8. `GET /api/runs/{run_id}/comparison`: Dữ liệu đối chuẩn đa phiên bản và Rule Drift.
  9. `POST /api/partition/classify`: Kiểm thử phân loại MECE 5 cấp.
  10. `POST /api/partition/sql`: Sinh câu lệnh Spark Single-Pass SQL pushdown.
- **Bộ Kiểm thử Đơn vị & Tích hợp (Unit & Integration Test Suite):**
  - Tệp `tests/unit/presentation/test_api.py` (13 tests đạt 100% pass với Starlette `TestClient`):
    - `test_api_health_check`: Kiểm tra HTTP 200 và nội dung JSON.
    - `test_api_list_templates`: Xác thực nạp danh mục mẫu đánh giá trọn gói (`AssessmentTemplateDTO`) với các trường `template_code`, `domain` khớp chuẩn DDL enum (`FINANCE`, `RETAIL`, `HEALTHCARE`, `TRANSPORTATION`, `GENERAL`), `ruleset_template` và `scoring_policy_template`.
    - `test_api_submit_run`: Kiểm tra tiếp nhận lượt chạy trả về mã 202 và `run_id`.
    - `test_api_get_run_status`: Kiểm tra cấu trúc 5 giai đoạn thực thi.
    - `test_api_get_scorecard`: Kiểm tra cấu trúc 4 trụ cột chất lượng.
    - `test_api_get_scorecard_circuit_breaker`: Kiểm tra điểm số áp trần 49.0% và cổng CRITICAL_FAIL qua API.
    - `test_api_get_scorecard_withheld`: Kiểm tra trạng thái giữ lại điểm khi thiếu dữ liệu.
    - `test_api_get_diagnostics`, `test_api_get_audit`, `test_api_get_comparison`: Kiểm tra các endpoint chẩn đoán và kiểm toán.
    - `test_api_partition_classification_endpoint`, `test_api_partition_sql_endpoint`: Kiểm chứng API phân hoạch MECE.
    - `test_api_serves_web_ui`: Kiểm tra trả về giao diện HTML responsive tại `/` và `/ui`.

#### e. Hệ quả & Đánh đổi (Tradeoffs & Mitigations)
- **Đánh đổi:** Cần duy trì sự đồng bộ giữa schema DTO của Pydantic trên backend và payload hiển thị trên UI.
- **Biện pháp:** Tận dụng tài liệu OpenAPI 3.1 tự động tại `/docs`, cho phép tự động sinh TypeScript SDK/DTOs khi có nhu cầu nâng cấp lên giao diện React chuyên biệt trong tương lai.

---

### 6.4. Ma trận Truy vết Thiết kế Kiến trúc (Architecture Traceability & Verification Matrix)

Bảng tổng hợp đối chiếu ba quyết định kiến trúc với các yêu cầu kỹ thuật, mô hình hóa nghiệp vụ, mã nguồn triển khai và bộ kiểm thử tự động:

| Mã Quyết định | Vấn đề Giải quyết | Tiêu chuẩn / Invariant | Artifact Logic Triển khai | Artifact Kiểm thử Tự động | Giao diện API Phục vụ |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AD-012-D1** | Chồng lấn phân loại dòng dữ liệu; vi phạm đẳng thức phân hoạch | $\sum_{i=1}^5 C_i = N_{total}$; thứ tự 5 cấp ưu tiên tuyến tính | `dq_scoring.presentation.partition_hierarchy.classify_cell_partition`, `SinglePassSQLGenerator` | `tests/unit/presentation/test_partition_hierarchy.py` (7 tests) | `POST /api/partition/classify`, `POST /api/partition/sql` |
| **AD-012-D2** | Bẫy trung bình (Averaging Trap); che giấu vi phạm bất biến sống còn | Điểm tối đa $\le 49.0\%$ (Grade F); Quality Gate = `CRITICAL_FAIL` | `dq_scoring.presentation.partition_hierarchy.evaluate_circuit_breaker`, `ScorecardDTO` | `tests/unit/presentation/test_circuit_breaker.py` (5 tests) | `GET /api/assessments/{id}?circuit_breaker=true` |
| **AD-012-D3** | Bộ nhớ WebSocket stateful; không thể mở rộng ngang; thiếu REST API | Kiến trúc phi trạng thái (Stateless); Single-Pass SPA; OpenAPI 3.1 | `dq_scoring.presentation.api.app.create_app`, `api_router` | `tests/unit/presentation/test_api.py` (13 tests) | 10 REST endpoints tại `/api/*` và Web UI tại `/`, `/ui` |

---

### 6.5. Ma trận Kiểm thử An ninh Phân quyền và Bảo vệ Dữ liệu (OWASP & NIST Security Test Matrix)

Nhằm đảm bảo hệ thống triệt tiêu hoàn toàn các rủi ro bảo mật thuộc danh mục **OWASP API Security Top 10 (2023)** và tuân thủ nguyên tắc quản lý vòng đời xác thực **NIST SP 800-63B**, bảng ma trận dưới đây đặc tả các kịch bản kiểm thử an ninh bắt buộc (Automated Security Test Suite) được tích hợp vào CI pipeline:

| Mã Kiểm Thử | Tình huống Tấn công / Vi phạm Giả định | Chuẩn Đối chiếu | Cơ chế Phòng vệ (Defense Mechanism) | Kết quả Kỳ vọng (Assertion / Expected Outcome) | Artifact Kiểm thử |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SEC-TEST-01** | **Intra-Tenant BOLA (User A vs User B cùng Tenant):** User B dùng JWT hợp lệ gửi request đọc/sửa Ruleset DRAFT hoặc hủy Evaluation Run do User A tạo. | OWASP API1:2023 (BOLA) | Facade `Authorizer`: Kiểm tra `created_by == auth.user_id` và bảng `access_grants`. | Trả về `403 Forbidden` (hoặc `404 Not Found`); không lộ bất kỳ metadata hay trạng thái nào của User A. | `tests/security/test_intra_tenant_bola.py` |
| **SEC-TEST-02** | **Cross-Tenant Boundary Bypass:** Tenant B gửi request kèm ID của Snapshot, Ruleset hoặc Run thuộc Tenant A. | OWASP API1:2023, DDIA Ch. 11 | Khóa ngoại ghép `(tenant_id, id)` + PostgreSQL RLS + Facade Tenant Assertion. | Trả về `404 Not Found` (không để lộ sự tồn tại); câu lệnh DB trả về 0 row do RLS 3VL. | `tests/security/test_tenant_isolation.py` |
| **SEC-TEST-03** | **Context & Identity Spoofing:** Request truyền header `X-Tenant-ID` hoặc body `owner_id` khác với thông tin đã ký trong JWT claim. | NIST SP 800-63B, OWASP API2 | API Middleware: Đối chiếu `token.claims.tenant_id == X-Tenant-ID`; gắn cứng `actor_id = auth.user_id`. | Trả về ngay mã `403 Forbidden` (Fail-Closed) trước khi chuyển tiếp vào Facade hoặc CSDL. | `tests/security/test_auth_spoofing.py` |
| **SEC-TEST-04** | **Immediate Revocation & Session Cleanliness:** Thu hồi `access_grant` (gán `revoked_at`); gửi request tiếp theo trên cùng connection pool. | NIST SP 800-63B §7, OWASP API5 | Không lưu cache quyền trạng thái; CSDL thực thi `DISCARD ALL` khi checkin pool; Facade kiểm tra `revoked_at IS NULL`. | Yêu cầu tiếp theo bị từ chối `403 Forbidden` ngay lập tức; 0 request lọt qua do connection pool dirty. | `tests/security/test_grant_revocation.py` |
| **SEC-TEST-05** | **Public Scorecard Sanitization Leak Check:** Gọi `GET /api/v1/public/scorecards/{id}` với Share Token hợp lệ hoặc công khai. | OWASP API3:2023 (Broken Object Property Level Auth) | DTO Allowlist `PublicScorecardProjectionDTO`: Chỉ trả về điểm số tổng hợp, 6 chiều, gate, coverage, hash. | 0 byte dữ liệu thô (raw rows), 0 byte bằng chứng lỗi (evidence), 0 PII findings và không lộ đường dẫn tệp hạ tầng. | `tests/security/test_public_projection.py` |
| **SEC-TEST-06** | **Segregation of Duties (BFLA):** Data Steward (`submitted_by`) cố gắng tự phê duyệt (`approved_by`) chính sách hoặc ruleset của chính mình. | OWASP API5:2023 (BFLA) | Facade Policy Guard: Bắt buộc `caller.roles` chứa `DATA_OWNER` VÀ `auth.user_id != resource.submitted_by`. | Trả về `403 Forbidden` (Self-Approval Denied); ghi nhận cố gắng vi phạm vào Audit Trail. | `tests/security/test_bfla_segregation.py` |
| **SEC-TEST-07** | **Password Timing Attack & User Enumeration:** Gửi 100 requests đăng nhập với email tồn tại và 100 requests với email không tồn tại; đo độ trễ mạng/CPU. | NIST SP 800-63B, OWASP API2 | Dummy Argon2id execution trên tài khoản không tồn tại (`BR-022`); thông báo lỗi đồng nhất. | Độ lệch chuẩn độ trễ $|\Delta t| < 15\text{ms}$; không phân biệt được email tồn tại hay không; 0 enumeration leak. | `tests/security/test_timing_attacks.py` |
| **SEC-TEST-08** | **Spreadsheet Formula Injection Sanitization:** Tạo dữ liệu kiểm thử có giá trị chuỗi bắt đầu bằng `=`, `+`, `-`, `@`, `\t`, `\r` rồi xuất báo cáo CSV/Excel. | OWASP Injection Prevention, CWE-1236 | `FormulaSanitizer` tiền tố dấu nháy đơn `'` trên toàn bộ các chuỗi có nguy cơ thực thi macro. | 100% ô văn bản được vô hiệu hóa công thức an toàn; không kích hoạt lệnh ngoại vi khi mở bảng tính. | `tests/security/test_formula_injection.py` |
| **SEC-TEST-09** | **Outbound Webhook SSRF & Private IP Shielding:** Khai báo Webhook URL trỏ tới `http://169.254.169.254/latest/meta-data/`, `http://127.0.0.1:5432`, `http://10.0.0.1`. | OWASP API7:2023 (SSRF), CWE-918 | `SSRFProtectionValidator` thực thi DNS Pinning và chặn dải IP loopback, private RFC 1918, cloud metadata. | Trả về lỗi `400 Bad Request / SSRF_TARGET_BLOCKED`; 0 gói tin HTTP nào được gửi ra hạ tầng nội bộ. | `tests/security/test_webhook_ssrf.py` |
| **SEC-TEST-10** | **Webhook HMAC-SHA256 Signature & Replay Protection:** Kiểm tra tính toàn vẹn và mốc thời gian của webhook request phát ra ngoại vi. | OWASP API8:2023, RFC 2104 | Header `X-DQ-Signature` (HMAC-SHA256) và `X-DQ-Timestamp`; từ chối request có timestamp chênh lệch $> 300$ giây. | Chữ ký khớp payload và secret; yêu cầu quá hạn hoặc chữ ký sai bị từ chối ngay lập tức. | `tests/security/test_webhook_signature.py` |
| **SEC-TEST-11** | **RFC 9457 Problem Details & Server Anti-Fingerprinting:** Kích hoạt các tình huống lỗi SQL cú pháp, tràn bộ nhớ hoặc ngoại lệ Python. | OWASP API3, CWE-209 | `RFC9457ErrorSanitizer` lọc toàn bộ stack trace; middleware xóa header `Server` và `X-Powered-By`. | Response body chuẩn RFC 9457; 0 stack trace, 0 SQL query, 0 file path máy chủ; headers không lộ tech stack. | `tests/security/test_error_sanitization.py` |
| **SEC-TEST-12** | **Small Cohort / Statistical Inference Suppression ($K < 5$):** Chạy profiling trên tập dữ liệu hoặc phân nhóm nhỏ có số dòng $N < 5$. | Differential Privacy, $K$-Anonymity | Bộ lọc thống kê tự động ẩn hoặc làm mờ các giá trị cực trị (Min, Max, Outliers) khi $N < 5$. | 100% giá trị cực trị được ẩn hoặc hiển thị `"< 5"`; ngăn chặn suy đoán danh tính cá nhân từ số liệu tổng hợp. | `tests/security/test_statistical_privacy.py` |


---
*(Hết nội dung hồ sơ AD-012 — Phiên bản 2.0 Security & Multi-Tenant Authorization Hardened)*


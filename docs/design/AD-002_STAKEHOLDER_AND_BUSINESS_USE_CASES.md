# AD-002 — PHÂN TÍCH TÁC NHÂN VÀ NHU CẦU NGHIỆP VỤ (STAKEHOLDER & BUSINESS USE CASES)

**Đề tài:** Chấm điểm Chất lượng dữ liệu (DQ Scoring System)  
**Mã hồ sơ:** AD-002-BUC  
**Phiên bản:** 1.2  
**Ngày:** 2026-09-04  
**Trạng thái:** Review Candidate  
**Nguồn chuẩn:** `docs/Chapter_1.md` (v1.2 Review Candidate), `docs/Chapter_2.md` (SRS v1.2 Review Candidate)  

## THÔNG TIN VÀ KIỂM SOÁT TÀI LIỆU

### Lịch sử phiên bản và phê duyệt

| Phiên bản | Ngày | Tóm tắt thay đổi | Trạng thái | Tác giả / Người sửa |
| :--- | :--- | :--- | :--- | :--- |
| **1.0** | 2026-08-27 | Khởi tạo phân tích tác nhân và Business Use Cases; phê duyệt Baseline v1.0 | **Approved Baseline** | Nguyễn Hoàng Tùng |
| **1.1** | 2026-08-28 | Tách vai trò Data Owner và Data Steward; tách BUC-002 và BUC-003; bổ sung quy tắc phân định Draft/Approve | Review Candidate | Nguyễn Hoàng Tùng |
| **1.2** | 2026-09-04 | Chuẩn hóa danh mục 8 BUC khớp 8 System UC; bổ sung ma trận ánh xạ BUC-to-UC và đồng bộ vòng đời async với PostgreSQL 16 | Review Candidate | Nguyễn Hoàng Tùng |

---

## 1. Mục đích và Quy ước

Hồ sơ này hoàn tất phân tích tác nhân và nhu cầu nghiệp vụ cho hệ thống DQ Scoring v1.1: xác định stakeholder, actor, mục tiêu nghiệp vụ, quyền quyết định và 8 Business Use Cases cốt lõi (BUC-001 đến BUC-008).

| Ký hiệu | Ý nghĩa |
| :--- | :--- |
| `[XÁC NHẬN]` | Đã có căn cứ trực tiếp và được phê duyệt trong Chapter 1 và Chapter 2 (SRS) |
| `[THAM CHIẾU]` | Phù hợp với khung chuẩn quốc tế (DAMA DMBOK2 / ISO/IEC 25012) |
| `[POST-1.0]` | Phạm vi mở rộng cho các phiên bản tiếp theo |

---

## 2. Mục tiêu Nghiệp vụ (Business Goals)

| Mã | Mục tiêu | Chỉ dấu thành công ở mức nghiệp vụ | Nguồn |
| :--- | :--- | :--- | :--- |
| **BG-001** | Chuẩn hóa cách đánh giá chất lượng giữa các dataset | Mỗi assessment sử dụng cùng canonical contract và policy có phiên bản đóng băng. | `[XÁC NHẬN]` C1.7, C2 (BR-001..012) |
| **BG-002** | Giảm thời gian tổng hợp và tự động hóa đánh giá | Người dùng nhận scorecard từ một evaluation run tự động thay vì ghép kết quả rời rạc. | `[XÁC NHẬN]` C1.7.1, C2 (FR-PROF) |
| **BG-003** | Giúp người dùng quyết định sử dụng dataset có kiểm soát | Scorecard công bố đồng thời DQ Score, Dimension Scores, Coverage, Quality Gate và Giới hạn. | `[XÁC NHẬN]` C1.1, C2 (FR-SCORE) |
| **BG-004** | Truy vết được kết luận tới bằng chứng cụ thể | Điểm số truy được tới snapshot, rule/detector hash, metric và bounded evidence. | `[XÁC NHẬN]` C1.7, C2 (FR-ASM, DR) |
| **BG-005** | Phân biệt lỗi dữ liệu với thiếu bằng chứng và lỗi hệ thống | Measurement status và execution error status được công bố tách biệt hoàn toàn. | `[XÁC NHẬN]` C1.5, C2 (FR-VAL-004, FR-RUN-005) |
| **BG-006** | Phát hiện lỗi đã biết và dấu hiệu bất thường thống kê | Rule results và advisory outlier IQR signals cùng chuẩn hóa theo Canonical Result Contract. | `[XÁC NHẬN]` C1.6, C2 (FR-DET, FR-VAL) |
| **BG-007** | Trực quan hóa và công bố kết quả cho người dùng | Scorecard trực quan hóa trên Local Dashboard và đóng gói Immutable Assessment Record. | `[XÁC NHẬN]` C1.7, C2 (IF-UI, FR-ASM) |
| **BG-008** | Đảm bảo tính tái lập (Reproducibility) qua thời gian | Cùng snapshot và cấu hình băm luôn tạo ra cùng kết quả đánh giá 100%. | `[XÁC NHẬN]` C1.7, C2 (NFR-COR-001) |

---

## 3. Ma trận Stakeholders

| Mã | Stakeholder | Nhu cầu chính | Quyết định / Trách nhiệm | Thông tin cần nhận | Mức ảnh hưởng |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **STK-001** | Dataset Consumer | Biết dataset có phù hợp với mục đích trước khi sử dụng | Đọc Scorecard và chấp nhận rủi ro sử dụng dữ liệu | Scorecard, Coverage, Quality Gate, Bounded Evidence | Cao |
| **STK-002** | Data Owner | Xác định yêu cầu và mức chất lượng chấp nhận | Phê duyệt Ruleset, Critical Rules và Scoring Policy | Gate failures, Dimension breakdown, Trend | Rất cao |
| **STK-003** | Data Steward | Quản trị quy tắc và chính sách chất lượng | Thiết lập Ruleset, Null Policy, trọng số và Baseline | Configuration hashes, Audit, Coverage, Unresolved results | Rất cao |
| **STK-004** | Domain Expert | Xác nhận tính đúng đắn theo nghiệp vụ | Thẩm định các tín hiệu ngoại lệ (Outlier) và độ lệch | Failed rules, Outlier evidence, Anomalies | Cao |
| **STK-005** | Data Engineer | Cung cấp snapshot và vận hành evaluation pipeline | Đăng ký dataset, tạo snapshot, kích hoạt run và giám sát lỗi | Run status, Execution error, Storage impact | Rất cao |
| **STK-006** | Catalog Administrator | Tích hợp scorecard vào Data Catalog | Quản lý mapping asset và metadata | API contract, Publication result, Version hashes | Trung bình (`[POST-1.0]`) |
| **STK-007** | Security / Governance | Bảo vệ dữ liệu và bảo mật thông tin | Kiểm soát an toàn dữ liệu, che mờ (redaction) và kiểm toán | Access audit, Evidence redaction, Retention | Cao |
| **STK-008** | Project Owner / Mentor | Định hướng kỹ thuật và nghiệm thu sản phẩm | Phê duyệt baseline tài liệu và kết quả kiểm chứng | Toàn bộ hồ sơ 5 chương, Golden Test Reports | Tối cao |

---

## 4. Danh mục Tác nhân (Actor Catalog)

### 4.1. Tác nhân Con người (Human Actors)

| Mã Actor | Tác nhân | Tương tác chính trong v1.0 | Ghi chú |
| :--- | :--- | :--- | :--- |
| **ACT-H-001** | Data Engineer / Operator | Đăng ký snapshot, cấu hình `RunSpec`, submit run bất đồng bộ, theo dõi tiến trình và hủy run | Tác nhân vận hành cốt lõi |
| **ACT-H-002** | Data Owner | Phê duyệt Ruleset, Critical Rules và Scoring Policy; chịu trách nhiệm cuối (Accountable) về mức chất lượng chấp nhận được | Tác nhân phê duyệt cốt lõi |
| **ACT-H-003** | Data Steward | Soạn thảo Ruleset, cấu hình Null Policy, gán trọng số; submit cấu hình DRAFT để Data Owner phê duyệt; theo dõi Coverage và Unresolved Results | Tác nhân cấu hình cốt lõi |
| **ACT-H-004** | Dataset Consumer | Xem Scorecard, kiểm tra Coverage và drill-down bằng chứng dòng lỗi | Persona tham chiếu / Read-only |
| **ACT-H-005** | Domain Expert | Xem xét và thẩm định các tín hiệu ngoại lệ IQR advisory | Tác nhân tư vấn chuyên môn |

*(Lưu ý về phân định vai trò ACT-H-001): ACT-H-001 đại diện cho vai trò vận hành hệ thống; trong thực tế triển khai tổ chức, Data Engineer và Operator có thể là hai cá nhân khác nhau nhưng trong phạm vi phiên bản v1.0 (Standalone CLI / Local Worker) họ có cùng tập quyền submit run, cancel run, xuất báo cáo và đăng ký asset. Quan hệ kế thừa và phân định trách nhiệm chi tiết giữa hai vai trò được mô hình hóa tại Mục 1.1.1 Chapter 3.*

### 4.2. Tác nhân Hệ thống ngoài (External System Actors)

| Mã Actor | Tác nhân | Dữ liệu trao đổi | Trạng thái v1.0 |
| :--- | :--- | :--- | :--- |
| **ACT-S-001** | Data Source Provider / Local File System | Cung cấp tệp CSV/Parquet nguồn và lưu trữ snapshot nhị phân | `[XÁC NHẬN]` Cốt lõi v1.0 |
| **ACT-S-002** | Data Catalog / External Registry | Nhận scorecard và liên kết asset metadata | `[POST-1.0]` Lộ trình mở rộng |
| **ACT-S-003** | Identity and Access Management (IAM) | Xác thực và phân quyền đa người dùng phân tán | `[POST-1.0]` Lộ trình mở rộng |

<!-- *(Lưu ý: DQ Scoring System là đối tượng được xây dựng, không tự đóng vai trò Actor của chính nó).* -->

---

## 5. Ma trận Stakeholder – Mục tiêu Nghiệp vụ

| Stakeholder | BG-001 | BG-002 | BG-003 | BG-004 | BG-005 | BG-006 | BG-007 | BG-008 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **STK-001 Dataset Consumer** | I | I | P | P | P | I | P | P |
| **STK-002 Data Owner** | A | P | A | P | A | P | I | A |
| **STK-003 Data Steward** | R | R | R | R | R | R | R | R |
| **STK-004 Domain Expert** | C | I | C | C | C | R | I | C |
| **STK-005 Data Engineer** | C | R | I | R | R | C | C | R |
| **STK-006 Catalog Administrator** | I | I | I | I | I | I | R | I |
| **STK-007 Security / Governance** | C | I | C | A | A | C | C | C |
| **STK-008 Project Owner / Mentor** | A | A | A | A | A | A | A | A |

*Ký hiệu:* `R` (Responsible - Chịu trách nhiệm thực hiện); `A` (Accountable - Phê duyệt cuối cùng); `P` (Participant - Trực tiếp hưởng lợi/sử dụng); `C` (Consulted - Tham vấn); `I` (Informed - Được thông báo).

---

## 6. Danh mục 8 Trường hợp Sử dụng Nghiệp vụ (Business Use Cases)

Bảng tổng hợp danh mục 8 Business Use Cases và định nghĩa 1 câu chuẩn hóa:

| Mã BUC | Tên Trường hợp Sử dụng Nghiệp vụ | Tác nhân chính | Tóm tắt mục tiêu (1 câu chuẩn hóa) |
| :--- | :--- | :--- | :--- |
| **BUC-001** | Đăng ký Data Asset và Khởi tạo Snapshot | ACT-H-001 Data Engineer / Operator | Tiếp nhận tệp bảng CSV/Parquet, tính mã băm SHA-256 nội dung, tự động trích xuất schema và lưu trữ snapshot bất biến vào Dataset Store cùng metadata vào PostgreSQL 16. |
| **BUC-002** | Soạn thảo Ruleset và Scoring Policy (Draft) | ACT-H-003 Data Steward | Khai báo danh mục quy tắc chất lượng, Null Policy, trọng số và điều kiện Quality Gate dưới dạng bản thảo revision có mã băm cấu hình ở trạng thái DRAFT chờ phê duyệt. |
| **BUC-003** | Phê duyệt Ruleset và Scoring Policy (Approve) | ACT-H-002 Data Owner | Xem xét, thẩm định và phê duyệt độc lập RulesetRevision và ScoringPolicyRevision để kích hoạt trạng thái ACTIVE sẵn sàng cho các lượt đánh giá. |
| **BUC-004** | Khởi tạo và Thực thi Lượt Đánh giá Bất đồng bộ | ACT-H-001 Data Engineer / Operator | Đệ trình yêu cầu đánh giá qua API/CLI, quản lý vòng đời bất đồng bộ qua hàng đợi PostgreSQL 16, điều phối worker xử lý profiling, validation, outlier và công bố kết quả nguyên tử. |
| **BUC-005** | Tổng hợp Điểm số và Đánh giá Cổng Chất lượng | Hệ thống (Tự động trong BUC-004) | Tự động tính toán điểm quy tắc, tổng hợp 6 chiều chất lượng, chuẩn hóa DQ Score, tính Coverage và xác định trạng thái Quality Gate theo thứ tự ưu tiên nghiêm ngặt. |
| **BUC-006** | Xem Scorecard và Drill-down Bằng chứng | ACT-H-004 Dataset Consumer | Truy vấn và trực quan hóa kết quả đánh giá đã công bố, kiểm tra DQ Score, 6 chiều chất lượng, Coverage, Quality Gate và phân tích mẫu dữ liệu vi phạm đã che mờ thông tin nhạy cảm. |
| **BUC-007** | Xem và Thẩm định Tín hiệu Ngoại lệ IQR (Advisory) | ACT-H-005 Domain Expert | Kiểm tra và thẩm định chuyên môn các tín hiệu phân phối dị biệt thống kê do thuật toán Tukey IQR phát hiện mà không ảnh hưởng trực tiếp đến điểm DQ kỹ thuật. |
| **BUC-008** | Xuất Báo cáo Đánh giá (Assessment Export) | ACT-H-001 Data Engineer / Operator | Trích xuất toàn bộ kết quả đánh giá bất biến, bảng điểm số, chỉ số chi tiết và mã băm kiểm toán ra các định dạng chuẩn hóa (JSON/Markdown) phục vụ lưu trữ và tích hợp. |

---

### BUC-001 — Đăng ký Data Asset và Khởi tạo Snapshot

- **Mục tiêu:** BG-001, BG-004.
- **Tác nhân chính:** ACT-H-001 Data Engineer / Operator.
- **Tác nhân hỗ trợ:** ACT-S-001 Data Source Provider.
- **Tiền điều kiện:** Tệp dữ liệu CSV (UTF-8) hoặc Apache Parquet có sẵn trên máy cục bộ; metadata tài sản dữ liệu được cung cấp.
- **Kích hoạt:** Operator yêu cầu đăng ký một dataset hoặc snapshot mới.
- **Đầu vào:** Tệp nhị phân dữ liệu, tên tài sản dữ liệu (`asset_name`), nguồn gốc (`provenance_url`), định dạng.
- **Luồng thành công:**
  1. Hệ thống kiểm tra tính toàn vẹn cấu trúc bảng (header, format).
  2. Hệ thống tính mã băm SHA-256 nội dung tệp.
  3. Hệ thống tự động phát hiện schema thông qua PyArrow/Spark (tên cột, kiểu dữ liệu inferred, tổng số dòng).
  4. Hệ thống sao chép tệp vào Dataset Store bất biến.
  5. Hệ thống ghi nhận bản ghi `DataAsset` và `DatasetSnapshot` vào PostgreSQL 16 Metadata Store và trả về `snapshot_id`.
- **Ngoại lệ:** Tệp hỏng, định dạng không hỗ trợ, tệp rỗng $\rightarrow$ báo lỗi `INVALID_PAYLOAD_FORMAT`, không ghi dữ liệu không hợp lệ.
- **Kết quả:** Snapshot bất biến sẵn sàng cho profiling và evaluation; dữ liệu nguồn giữ nguyên 100% (Read-only).

### BUC-002 — Soạn thảo Ruleset và Scoring Policy (Draft)

- **Mục tiêu:** BG-001, BG-003, BG-005.
- **Tác nhân chính:** ACT-H-003 Data Steward.
- **Tiền điều kiện:** Data Asset đã tồn tại; schema các cột mục tiêu đã được định danh.
- **Đầu vào:** Danh sách quy tắc thuộc 5 nhóm lõi, Null Policy, trọng số, mức độ nghiêm trọng (`critical`/`standard`), trọng số 6 chiều, ngưỡng công bố điểm ($\ge 80\%$) và điều kiện Quality Gate.
- **Luồng thành công:** Hệ thống kiểm tra tính hợp lệ cú pháp, sinh mã băm SHA-256 cấu hình chuẩn hóa tạm thời, lưu trữ `RulesetRevision` và `ScoringPolicyRevision` vào PostgreSQL 16 ở trạng thái `DRAFT`.
- **Ngoại lệ:** Sai kiểu dữ liệu, thiếu tham số bắt buộc, tổng trọng số không hợp lệ $\rightarrow$ báo lỗi `INVALID_CONFIGURATION_SYNTAX`.
- **Kết quả:** Phiên bản cấu hình ở trạng thái `DRAFT`, chưa thể gán vào Evaluation Run, chờ phê duyệt.

### BUC-003 — Phê duyệt Ruleset và Scoring Policy (Approve)

- **Mục tiêu:** BG-001, BG-003, BG-008.
- **Tác nhân chính:** ACT-H-002 Data Owner.
- **Tác nhân hỗ trợ:** ACT-H-003 Data Steward (cung cấp ngữ cảnh khi cần).
- **Tiền điều kiện:** Tồn tại `RulesetRevision` / `ScoringPolicyRevision` ở trạng thái `DRAFT`.
- **Đầu vào:** `ruleset_id` và `policy_id` của hai revision cần phê duyệt.
- **Luồng thành công:** Data Owner xem xét từng Draft rồi gọi riêng `approve_ruleset(ruleset_id, owner_id)` và `approve_policy(policy_id, owner_id)`; hệ thống chuyển từng revision sang `ACTIVE` và ghi `submitted_by`, `submitted_at`, `approved_by`, `approved_at` vào PostgreSQL 16.
- **Luồng ngoại lệ:** Owner từ chối → trạng thái vẫn là `DRAFT`, hệ thống ghi nhận lý do từ chối.
- **Kết quả:** Phiên bản cấu hình ở trạng thái `ACTIVE`, sẵn sàng gắn vào Evaluation Run.

### BUC-004 — Khởi tạo và Thực thi Lượt Đánh giá Bất đồng bộ (Async Evaluation Run Pipeline)

- **Mục tiêu:** BG-001, BG-002, BG-004, BG-005, BG-006, BG-008.
- **Tác nhân chính:** ACT-H-001 Data Engineer / Operator.
- **Tiền điều kiện:** Snapshot hợp lệ; Ruleset và Scoring Policy đều `ACTIVE` và tương thích schema.
- **Đầu vào:** `RunSpec` chứa các định danh snapshot, ruleset, scoring policy, cấu hình IQR Outlier và idempotency key.
- **Luồng thành công:**
  1. API validate request, kiểm tra idempotency, persist `EvaluationRun` với trạng thái ban đầu `QUEUED` trong PostgreSQL 16 và trả về `run_id`.
  2. Worker tiến hành claim run qua cơ chế lease, nhận `lease_generation`, cập nhật trạng thái `LEASED → RUNNING`, bắt đầu heartbeat định kỳ.
  3. Worker gọi profiling tự động (tương ứng UC-002) qua Spark pushdown trên k3s sinh tập `Canonical Metrics` dùng chung.
  4. Worker thực thi song song Rule Engine (5 nhóm quy tắc xác định) và IQR Outlier Detector (chế độ `ADVISORY`, tương ứng UC-006) thông qua Spark SQL pushdown trên k3s.
  5. Chuẩn hóa toàn bộ kết quả thành tập `Canonical Quality Results`.
  6. Thực thi quy trình tổng hợp điểm số và cổng chất lượng nội bộ (tương ứng BUC-005 / SEQ-007): tạo đúng 6 Dimension Results, tính DQ Score trên các chiều `MEASURED`, tính Coverage độc lập và xác định Quality Gate theo thứ tự ưu tiên nghiêm ngặt.
  7. Worker thực hiện giao dịch ghi nguyên tử (Atomic Publication) vào PostgreSQL 16: lưu trữ toàn bộ Results, Dimension Results, `Immutable Assessment` kèm `assessment_hash`, ghi nhận run events và chuyển trạng thái run sang `SUCCEEDED` (có fencing bảo vệ bởi `lease_generation`).
- **Ngoại lệ:** 
  - *Lỗi kỹ thuật / I/O / Compute Engine:* Thực hiện retry có giới hạn (bounded retry); nếu hết retry ngân sách, chuyển `FAILED` kèm mã lỗi `EXECUTION_ERROR`, không công bố Assessment không hoàn chỉnh.
  - *Yêu cầu hủy (Cancellation):* Ghi nhận checkpoint, chuyển trạng thái sang `CANCELLED`, giải phóng tài nguyên.
- **Kết quả:** Bản ghi `Immutable Assessment` bất biến được công bố hoàn tất trong PostgreSQL 16; client có thể truy vấn trạng thái và kết quả.

### BUC-005 — Tổng hợp Điểm số và Đánh giá Cổng Chất lượng (Scoring & Gate Capability)

*(Lưu ý về kiến trúc: BUC-005 là năng lực tính toán và đánh giá nội bộ của hệ thống, được hiện thực hóa dưới dạng tuần tự SEQ-007 trong phạm vi thực thi của UC-005. BUC-005 không có actor con người tương tác trực tiếp mà đóng vai trò cốt lõi trong quy trình hoàn tất một Evaluation Run).*

- **Mục tiêu:** BG-001, BG-003, BG-005.
- **Tác nhân chính:** Hệ thống (Tự động thực thi trong BUC-004 / UC-005 qua `ScoreAggregator`).
- **Tiền điều kiện:** Toàn bộ Canonical Quality Results của lượt chạy đã hoàn tất và được chuẩn hóa.
- **Đầu vào:** Canonical Quality Results và Scoring Policy (đã đóng băng hash).
- **Luồng thành công:**
  1. Tính Rule Score theo Null Policy trên mẫu số hợp lệ (non-zero denominator).
  2. Tạo đúng 6 Dimension Results: phân loại `MEASURED`, policy-approved `NOT_APPLICABLE`, hoặc `NOT_MEASURABLE` với score `null`.
  3. Tái chuẩn hóa DQ Score trên các chiều đã đo (`MEASURED`) và tính Coverage độc lập.
  4. Xác định điều kiện công bố: Chỉ `PUBLISHED` khi Coverage $\ge 80\%$ và không có required score-enabled measurement lỗi; ngược lại đánh dấu `WITHHELD` với `dq_score = null`.
  5. Đánh giá Quality Gate theo thứ tự ưu tiên nghiêm ngặt (BR-010): (1) `ERROR` (nếu có lỗi kỹ thuật `FAILED_TO_MEASURE` trên quy tắc bắt buộc) $\succ$ (2) Critical `FAIL` (có quy tắc critical bị vi phạm) $\succ$ (3) `INSUFFICIENT_EVIDENCE` (thiếu phép đo bắt buộc hoặc Coverage < 80%) $\succ$ (4) `FAIL` ($<60$) $\succ$ (5) `WARN` ($[60, 80)$) $\succ$ (6) `PASS` ($\ge 80$).
- **Kết quả:** Bộ 6 Dimension Results, DQ Score, Coverage và Quality Gate chuẩn xác về mặt toán học và bất biến.

### BUC-006 — Xem Scorecard và Drill-down Bằng chứng

- **Mục tiêu:** BG-003, BG-004, BG-007.
- **Tác nhân chính:** ACT-H-004 Dataset Consumer, ACT-H-001 Data Engineer / Operator, ACT-H-002 Data Owner.
- **Tiền điều kiện:** Assessment đã được công bố trong PostgreSQL 16 Metadata Store.
- **Đầu vào:** `assessment_id` hoặc chọn Snapshot trên Dashboard / CLI.
- **Luồng thành công:**
  1. Giao diện tải Assessment nguyên vẹn từ PostgreSQL 16 mà không tính toán lại.
  2. Hiển thị bảng Scorecard: DQ Score, 6 Dimension Results (score có thể `null`), Coverage và Quality Gate.
  3. Cho phép người dùng nhấp xem chi tiết từng chiều và drill-down vào quy tắc vi phạm / tín hiệu outlier để xem mẫu số, số lượng lỗi và danh sách 10–50 dòng mẫu vi phạm đã che mờ thông tin nhạy cảm (Bounded Evidence $\le 500$ KB).
- **Kết quả:** Người dùng hiểu rõ chất lượng dữ liệu, độ bao phủ và nguyên nhân điểm giảm.

### BUC-007 — Xem và Thẩm định Tín hiệu Ngoại lệ IQR (Advisory)

- **Mục tiêu:** BG-005, BG-006.
- **Tác nhân chính:** ACT-H-005 Domain Expert, ACT-H-003 Data Steward.
- **Tiền điều kiện:** Lượt chạy đã sinh tín hiệu IQR Outlier trên các cột số mục tiêu.
- **Đầu vào:** Tín hiệu Outlier Result, ranh giới Tukey ($Q1 \pm 1.5 \cdot IQR$), số lượng và tỷ lệ dị biệt.
- **Luồng thành công:**
  1. Người dùng xem các điểm dị biệt trên Dashboard.
  2. Đọc các dòng dữ liệu mẫu ngoại lệ để thẩm định bản chất nghiệp vụ.
  3. Ghi nhận cảnh báo mà không làm sai lệch DQ Score kỹ thuật của hệ thống.
- **Kết quả:** Cung cấp thông tin cảnh báo phân phối bổ trợ cho người dùng.

### BUC-008 — Xuất Báo cáo Đánh giá (Assessment Export)

- **Mục tiêu:** BG-004, BG-007, BG-008.
- **Tác nhân chính:** ACT-H-001 Data Engineer / Operator.
- **Tiền điều kiện:** Assessment đã công bố trong PostgreSQL 16.
- **Đầu vào:** Yêu cầu xuất báo cáo kèm định dạng (JSON Canonical / Markdown Summary).
- **Luồng thành công:** Hệ thống xuất toàn bộ dữ liệu Assessment bất biến kèm mã băm SHA-256 cấu hình và tóm tắt 6 chiều chất lượng.
- **Kết quả:** Tệp báo cáo đánh giá phục vụ lưu trữ, kiểm toán hoặc tích hợp pipeline downstream.

---

## 7. Ma trận Ánh xạ Nghiệp vụ – Hệ thống (BUC-to-UC Mapping Matrix)

Để đảm bảo tính nhất quán tuyệt đối giữa phân tích nhu cầu nghiệp vụ (Business Analysis) và mô hình hóa chức năng hệ thống (System Modeling trong `docs/Chapter_3.md`), ma trận dưới đây xác lập quan hệ ánh xạ và cơ chế thực thi giữa 8 BUC và 8 UC hệ thống:

| Mã BUC | Tên Business Use Case | Mã UC tương ứng | Tên System Use Case | Vai trò và Cơ chế Thực thi |
| :--- | :--- | :--- | :--- | :--- |
| **BUC-001** | Đăng ký Data Asset và Khởi tạo Snapshot | **UC-001** | Đăng ký Data Asset | Ánh xạ trực tiếp 1-1; tiếp nhận file, hash SHA-256, trích xuất schema qua PyArrow/Spark, persist vào Dataset Store và PostgreSQL 16. |
| **BUC-002** | Soạn thảo Ruleset và Scoring Policy (Draft) | **UC-003** | Soạn thảo Ruleset & Scoring Policy (Draft) | Ánh xạ trực tiếp 1-1; Data Steward nhập cấu hình, validate cú pháp, lưu revision DRAFT kèm config hash vào PostgreSQL 16. |
| **BUC-003** | Phê duyệt Ruleset và Scoring Policy (Approve) | **UC-004** | Phê duyệt Ruleset & Scoring Policy (Approve) | Ánh xạ trực tiếp 1-1; Data Owner thẩm định và kích hoạt ACTIVE qua 2 thao tác độc lập kèm audit log vào PostgreSQL 16. |
| **BUC-004** | Khởi tạo và Thực thi Lượt Đánh giá Bất đồng bộ | **UC-005** | Khởi tạo và Thực thi Lượt Đánh giá Bất đồng bộ | Ánh xạ trực tiếp 1-1; bao hàm vòng đời async (`QUEUED → LEASED → RUNNING → SUCCEEDED/FAILED/CANCELLED`), worker lease, `<<include>>` UC-002 (Profiling), `<<include>>` UC-006 (IQR Outlier), tích hợp năng lực BUC-005 (SEQ-007) và atomic publication (SEQ-008). |
| **BUC-005** | Tổng hợp Điểm số và Đánh giá Cổng Chất lượng | **UC-005** (Thành phần nội bộ) | Khởi tạo và Thực thi Lượt Đánh giá Bất đồng bộ (SEQ-007) | Không có UC độc lập riêng vì BUC-005 là bước tính toán nội bộ (`SEQ-007`) nằm trọn vẹn trong luồng thực thi của UC-005 (`ScoreAggregator`). |
| — | Lập hồ sơ dữ liệu (Profiling) | **UC-002** | Lập hồ sơ dữ liệu (Profiling) | Năng lực hệ thống được `UC-005` gọi tự động qua quan hệ `<<include>>` để tính toán `CanonicalMetric` dùng chung. |
| **BUC-007** | Xem và Thẩm định Tín hiệu Ngoại lệ IQR (Advisory) | **UC-006** & **UC-007** | Phát hiện Ngoại lệ IQR (Advisory) & Xem Scorecard | Thuật toán phát hiện dị biệt là **UC-006** (được `UC-005` include); giao diện trực quan hóa và thẩm định tín hiệu là một phần của **UC-007**. |
| **BUC-006** | Xem Scorecard và Drill-down Bằng chứng | **UC-007** | Xem Scorecard & Drill-down Bằng chứng | Ánh xạ trực tiếp 1-1; tải Assessment bất biến từ PostgreSQL 16 hiển thị scorecard và drill-down bounded evidence. |
| **BUC-008** | Xuất Báo cáo Đánh giá (Assessment Export) | **UC-008** | Xuất Báo cáo Đánh giá (Export) | Ánh xạ trực tiếp 1-1; kết xuất báo cáo định dạng JSON canonical hoặc Markdown từ Assessment đã công bố. |

---

## 8. Ranh giới Tác nhân và Quyền hạn v1.0

1. **Phân tách trách nhiệm:** Data Engineer vận hành pipeline; Data Owner phê duyệt cấu hình chất lượng; Data Steward soạn thảo cấu hình; Consumer đọc kết quả.
2. **Quyền chỉ đọc dữ liệu nguồn:** Tuyệt đối không có tác nhân hoặc tiến trình nào được phép sửa đổi tệp dữ liệu nguồn.
3. **Tính bất biến của cấu hình:** Mọi thay đổi trong Ruleset hoặc Policy đều sinh ra mã băm phiên bản mới.
4. **Cách ly cảnh báo thống kê:** Domain Expert xem xét Outlier mang tính tư vấn (`ADVISORY`), không tự động trừ điểm tùy tiện khi chưa có calibration evidence.
5. **Ranh giới công bố điểm:** DQ Score chỉ `PUBLISHED` khi Coverage $\ge 80\%$ và không có required score-enabled measurement lỗi.
6. **Phân tách Draft/Approve:** Data Steward không có quyền tự kích hoạt (activate) Ruleset/Policy do chính mình soạn; mọi cấu hình phải qua Data Owner phê duyệt trước khi chuyển sang trạng thái `ACTIVE` và được phép gán vào `RunSpec`.

---

## 9. Ma trận Truy vết Mục tiêu – Use Cases (Traceability Matrix)

| Mục tiêu nghiệp vụ (Business Goal) | Trường hợp sử dụng tương ứng (BUC) |
| :--- | :--- |
| **BG-001: Chuẩn hóa cách đánh giá** | BUC-001, BUC-002, BUC-003, BUC-004, BUC-005 |
| **BG-002: Giảm thời gian / Tự động hóa** | BUC-004 |
| **BG-003: Ra quyết định sử dụng có kiểm soát**| BUC-002, BUC-003, BUC-005, BUC-006 |
| **BG-004: Truy vết kết luận tới bằng chứng** | BUC-001, BUC-004, BUC-005, BUC-006, BUC-008 |
| **BG-005: Phân biệt lỗi rạch ròi** | BUC-002, BUC-004, BUC-005, BUC-007 |
| **BG-006: Đa mô hình Hybrid** | BUC-004, BUC-007 |
| **BG-007: Trực quan hóa và công bố** | BUC-006, BUC-008 |
| **BG-008: Đảm bảo tính tái lập** | BUC-001, BUC-002, BUC-003, BUC-004, BUC-008 |

---

## 10. Tình trạng Đóng các Quyết định Mở (Closed TBDs)

| Mã TBD | Nội dung | Quyết định Baseline v1.0 | Trạng thái |
| :--- | :--- | :--- | :--- |
| **TBD-ROLE-001** | Ma trận quyền chi tiết cho từng actor | Phân tách 4 roles trong Single-node Prototype; RBAC Server chuyển sang Post-1.0 | **CLOSED** |
| **TBD-APPROVAL-001** | Quy trình phê duyệt rule, policy, baseline | Data Steward submit; Data Owner phê duyệt Ruleset và Policy bằng hai lệnh riêng, có audit timestamps | **CLOSED** |
| **TBD-CATALOG-001** | Tích hợp Data Catalog bên ngoài | Hoãn lại sau v1.0 (`[POST-1.0]`); v1.0 xuất JSON/HTML export | **CLOSED (DEFERRED)** |
| **TBD-IAM-001** | Định danh và phân quyền mạng phân tán | Hoãn lại sau v1.0 (`[POST-1.0]`); v1.0 chạy local loopback | **CLOSED (DEFERRED)** |
| **TBD-VSLICE-001** | Dataset và cấu hình Vertical Slice | City of Chicago Taxi Trips (Tháng 01/2023), 5 nhóm rule xác định, IQR $k=1.5$ | **CLOSED** |

---
*(Hết nội dung AD-002 — Phiên bản 1.2 Review Candidate)*

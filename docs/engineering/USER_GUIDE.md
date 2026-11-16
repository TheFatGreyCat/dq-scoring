# HƯỚNG DẪN SỬ DỤNG VÀ THAO TÁC HỆ THỐNG (SYSTEM USER & OPERATION GUIDE)

**Mã tài liệu:** ENG-USER-01  
**Phiên bản:** 1.0  
**Ngày ban hành:** 2026-10-01  
**Trạng thái:** Official User Manual — Cẩm nang hướng dẫn sử dụng và luồng thao tác toàn trình  
**Tài liệu tham chiếu:** `docs/theory/DQ_SCORING_THEORY.md`, `docs/Chapter_2.md`, `docs/Chapter_3.md`, `docs/engineering/DEPLOYMENT_GUIDE.md`

---

## 1. MÔ HÌNH THỰC THỂ & PHÂN QUYỀN TRUY CẬP (RBAC & CONCEPTS)

Hệ thống chấm điểm chất lượng dữ liệu xác định (`dq-scoring`) quản lý dữ liệu theo mô hình đa thuê bao cô lập (`Multi-Tenant Isolation`) với các thực thể cốt lõi:

```text
  ┌──────────────┐
  │    Tenant    │
  └──────┬───────┘
         │ 1:N
  ┌──────┴───────┐        1:N        ┌───────────────────┐
  │  Data Asset  ├──────────────────►│ Dataset Snapshot  │ (Bất biến / Read-Only)
  └──────┬───────┘                   └─────────┬─────────┘
         │ 1:N                                 │
  ┌──────┴───────┐        1:N                  │
  │   Ruleset    ├──────────────┐              │
  └──────────────┘              ▼              ▼
                        ┌───────────────────────────────┐
  ┌──────────────┐      │        Evaluation Run         │ (Hàng đợi phi khóa / Outbox)
  │Scoring Policy├─────►│  (Pushdown Single-Pass Spark) │
  └──────────────┘ 1:N  └──────────────┬────────────────┘
                                       │ 1:1
                                       ▼
                        ┌───────────────────────────────┐
                        │     Quality Assessment        │ (Scorecard, 6 Dims, Evidence)
                        └───────────────────────────────┘
```

### 1.1. Ma trận Phân quyền Vai trò (Role-Based Access Control - RBAC)

| Quyền hạn / Thao tác | `WORKSPACE_ADMIN` | `DATA_OWNER` | `DATA_STEWARD` | `DATA_ANALYST` | `AUDITOR` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Quản trị User & Tenant | Toàn quyền | Không | Không | Không | Không |
| Tạo Data Asset & Snapshot | Có | Có | Có | Có | Không |
| Soạn thảo Ruleset / Policy (Draft) | Có | Có | Có | Có | Không |
| **Gửi duyệt (Submit for Approval)** | Có | Có | Có | Không | Không |
| **Phê duyệt độc lập (4-Eyes Approval)**| Có (khác creator)| Có (khác creator)| Có (khác creator)| Không | Không |
| Kích hoạt Đánh giá (Trigger Run) | Có | Có | Có | Có | Không |
| Xem Báo cáo Chi tiết & Bằng chứng | Có | Có | Có | Có | Có |
| Xem Bản chiếu Công khai (Public View)| Có | Có | Có | Có | Có |

> **Kiểm soát 4-Eyes (AC-003):** Mặc định cần người phê duyệt độc lập. Ngoại lệ chỉ dành cho `WORKSPACE_ADMIN` trong workspace hiện tại: tự duyệt Ruleset/Policy ở trạng thái `PENDING_APPROVAL` bằng thao tác **Tự phê duyệt**, nhập lý do bắt buộc (1–500 ký tự sau khi loại khoảng trắng đầu/cuối). Phê duyệt, thay thế phiên bản ACTIVE và audit được ghi trong cùng giao dịch; lỗi ghi audit làm rollback. `DATA_OWNER`/`DATA_STEWARD` vẫn không được tự duyệt; template không có ngoại lệ. Ngoại lệ không duyệt run/assessment, không thay điểm hoặc Quality Gate và không bỏ qua privacy.

### Theo dõi job và Operations

- **Job của tôi** (`/my-jobs`): danh sách evaluation run do tài khoản hiện tại gửi; scope được lọc ở server. Link trực tiếp, timeline và Spark observation dùng cùng quyền sở hữu. Chỉ Admin được xem scope workspace; không xem xuyên tenant.
- Danh sách tự cập nhật khi có job active; lỗi mạng giữ lần quan sát thành công gần nhất, không biến job thành FAILED. Refresh chỉ đọc lại trạng thái. Timeline phân trang bằng cursor gắn với run, không chứa raw log/payload hoặc stack trace.
- Chi tiết tách trạng thái request khỏi Spark observation theo attempt/lease. `UNKNOWN` là chưa có quan sát, `STALE` là quan sát cũ, `ENDED` là attempt đã kết thúc; job Spark được hiển thị là lần quan sát cuối, không phải bảo đảm trạng thái hiện tại. Không suy ra phần trăm tiến độ. Application/job-group chỉ hiện cho Admin trong scope workspace.
- **Operations**: evaluation requests có bộ lọc trạng thái/người gửi và liên kết chi tiết; DB/storage/Spark/advisory gateway có nguồn và thời điểm quan sát. Gateway OFF không phải DOWN; configured nhưng chưa probe là UNKNOWN. Import/privacy giữ trang và state machine riêng; bảng evaluation requests không tuyên bố bao phủ các loại request đó.
- Spark telemetry lưu trong `run_events`, tối đa 500 quan sát/attempt, 20 jobs/quan sát; API trả tối đa 10 attempts. Telemetry không xuất hiện như log timeline thông thường; áp dụng retention `janitor_prune_run_events` hiện có.


---

## 2. LUỒNG THAO TÁC TOÀN TRÌNH QUA REST API (END-TO-END WORKFLOW)

Tất cả các lệnh tương tác dưới đây có thể thực hiện thông qua `curl`, PowerShell `Invoke-RestMethod`, hoặc Swagger UI tại `http://localhost:8000/docs`.

### Bước 1: Đăng nhập & Xác thực JWT Token

```bash
# Đăng nhập bằng tài khoản Quản trị / Data Steward
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice.steward@example.com",
    "password": "StrongPassword123!",
    "tenant_id": "<tenant_id>"
  }'
```

**Phản hồi thành công (HTTP 200 OK):**
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 1800,
  "refresh_token": "Zk3x9Qw2...opaque-token"
}
```
*Lưu ý: `refresh_token` là chuỗi mờ (opaque), không phải JWT. Nhập sai mật khẩu 5 lần liên tiếp sẽ khóa tài khoản trong 15 phút; khi đó API trả HTTP 423 kèm `reason`, `max_failed_attempts`, `locked_until`, `retry_after_seconds` và header `Retry-After`.*

*Lưu ý: Đính kèm token vào mọi request tiếp theo qua Header `Authorization: Bearer <access_token>`.*

---

### Bước 2: Đăng ký Tài sản Dữ liệu & Dataset Snapshot

```bash
# 1. Đăng ký Data Asset (ví dụ: chicago_taxi_trips)
curl -X POST "http://localhost:8000/api/v1/assets" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "chicago_taxi_trips"
  }'

# 2. Đăng ký Snapshot dữ liệu bất biến (Dataset Snapshot)
curl -X POST "http://localhost:8000/api/v1/snapshots" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "<asset_id>",
    "source_kind": "LOCAL_FILE",
    "source_descriptor": {
      "path": "data/fixtures/chicago_taxi/chicago_taxi_golden_5k.csv",
      "format": "CSV"
    },
    "schema_definition": {
      "columns": ["trip_id", "taxi_id", "trip_start_timestamp", "trip_end_timestamp", "trip_seconds", "trip_miles", "pickup_census_tract", "dropoff_census_tract", "pickup_community_area", "dropoff_community_area", "fare", "tips", "tolls", "extras", "trip_total", "payment_type", "company", "pickup_centroid_latitude", "pickup_centroid_longitude", "pickup_centroid_location", "dropoff_centroid_latitude", "dropoff_centroid_longitude", "dropoff_centroid_location"]
    },
    "total_rows": 5000,
    "total_columns": 23
  }'
```

---

### Bước 3: Cấu hình Bộ quy tắc Chất lượng & Phê duyệt 4-Eyes (Ruleset Workflow)

Quy trình phê duyệt thực thi theo chu trình 3 trạng thái: `DRAFT` $\rightarrow$ `PENDING_APPROVAL` $\rightarrow$ `ACTIVE`.

```bash
# 1. Soạn thảo Ruleset (Tài khoản Alice)
curl -X POST "http://localhost:8000/api/v1/rulesets" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "<asset_id>",
    "name": "Taxi Quality Ruleset v1",
    "rules": [
      {
        "rule_code": "R_COMP_01",
        "dimension": "Completeness",
        "rule_type": "NON_NULL",
        "parameters": {"column": "trip_id"},
        "is_required": true,
        "is_critical": true,
        "acceptance_threshold": 95.0
      },
      {
        "rule_code": "R_VAL_01",
        "dimension": "Validity",
        "rule_type": "DOMAIN_RANGE",
        "parameters": {"column": "fare", "min_value": 0.0},
        "is_required": true
      }
    ]
  }'

# 2. Gửi duyệt (Alice Submit)
curl -X POST "http://localhost:8000/api/v1/rulesets/<ruleset_id>/submit" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Ready for production review"}'

# 3. Phê duyệt độc lập (Tài khoản Bob - Data Owner / Admin phê duyệt)
curl -X POST "http://localhost:8000/api/v1/rulesets/<ruleset_id>/approve" \
  -H "Authorization: Bearer $BOB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approval_notes": "Approved for M5 deployment"}'
```

---

### Bước 4: Cấu hình Chính sách Chấm điểm & Phê duyệt 4-Eyes (Policy Workflow)

```bash
# 1. Soạn thảo Scoring Policy (Alice)
curl -X POST "http://localhost:8000/api/v1/policies" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production Scoring Policy 2026",
    "gate_fail_threshold": 60.0,
    "gate_warn_threshold": 80.0,
    "min_coverage_threshold": 0.80,
    "critical_acceptance_threshold": 95.0,
    "dimension_weights": {
      "Completeness": 0.35,
      "Validity": 0.35,
      "Uniqueness": 0.30
    }
  }'

# 2. Gửi duyệt & Phê duyệt bởi người thứ hai (Bob)
curl -X POST "http://localhost:8000/api/v1/policies/<policy_id>/submit" \
  -H "Authorization: Bearer $ALICE_TOKEN"

curl -X POST "http://localhost:8000/api/v1/policies/<policy_id>/approve" \
  -H "Authorization: Bearer $BOB_TOKEN"
```

---

### Bước 5: Kích hoạt Lượt Đánh giá (Trigger Evaluation Run)

Tác vụ đánh giá được đưa vào hàng đợi xử lý bất đồng bộ, hỗ trợ khóa chống trùng lặp (`idempotency_key`):

```bash
curl -X POST "http://localhost:8000/api/v1/runs" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "snapshot_id": "<snapshot_id>",
    "ruleset_id": "<ruleset_id>",
    "policy_id": "<policy_id>",
    "execution_profile": "standard",
    "idempotency_key": "eval-taxi-2026-10-01-001"
  }'
```

**Phản hồi (HTTP 202 Accepted):**
```json
{
  "run_id": "r1000000-0000-0000-0000-000000000001",
  "tenant_id": "a0000000-0000-0000-0000-000000000001",
  "snapshot_id": "<snapshot_id>",
  "ruleset_id": "<ruleset_id>",
  "policy_id": "<policy_id>",
  "status": "QUEUED",
  "created_at": "2026-10-01T08:00:00Z"
}
```

---

### Bước 6: Thăm dò Trạng thái Xử lý (Polling Run Status)

Ứng dụng UI/Client thực hiện polling nhẹ nhàng theo chu kỳ 5–10s:

```bash
curl -X GET "http://localhost:8000/api/v1/runs/<run_id>/status" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**Khi xử lý thành công (Status: SUCCEEDED):**
```json
{
  "run_id": "r1000000-0000-0000-0000-000000000001",
  "status": "SUCCEEDED",
  "error_message": null,
  "assessment_id": "e1000000-0000-0000-0000-000000000001",
  "updated_at": "2026-10-01T08:00:05Z"
}
```

---

### Bước 7: Truy xuất Báo cáo Kết quả (Scorecard vs Public View)

#### 1. Bản chiếu Đầy đủ Nội bộ (Detailed Assessment)

```bash
curl -X GET "http://localhost:8000/api/v1/assessments/<assessment_id>" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Bao gồm: `dq_score`, `quality_gate` (`PASS`/`WARN`/`FAIL`/`ERROR`), `publication_status` (`PUBLISHED`/`WITHHELD`), `assessment_hash`, điểm 6 chiều dữ liệu, và danh sách vi phạm đã che mờ PII (tối đa 50 dòng).

#### 2. Bản chiếu Công khai Chống Rò rỉ (Public Zero-Leak Projection - AC-022)

```bash
curl -X GET "http://localhost:8000/api/v1/assessments/<assessment_id>/public"
```

*Không yêu cầu Header xác thực; 100% metadata nội bộ, cấu hình quy tắc, đường dẫn tệp và mẫu vi phạm bị triệt tiêu hoàn toàn.*

---

## 3. GIAO DIỆN BẢNG ĐIỀU KHIỂN TRỰC QUAN (STREAMLIT DASHBOARD UI)

Module trực quan hóa được triển khai tại `src/dq_scoring/presentation/ui/dashboard.py` cung cấp các thành phần giao diện phục vụ giám sát và phân tích:

### 3.1. Các Khối Hiển thị Trọng yếu (Dashboard Components)

1. **Thẻ Điểm Tổng thể (Scorecard Metric Summary):**
   - Hiển thị Điểm chất lượng tổng thể (`DQ Score`) từ 0.00 đến 100.00.
   - Nhãn Cổng chất lượng (`Quality Gate Badge`) với chỉ báo màu sắc chuẩn mực:
     - 🟢 `PASS` (Điểm $\ge 80.0$)
     - 🟡 `WARN` ($60.0 \le$ Điểm $< 80.0$)
     - 🔴 `FAIL` (Điểm $< 60.0$ hoặc vi phạm Critical Rule)
     - ⛔ `ERROR` (Lỗi kỹ thuật đo lường trên quy tắc bắt buộc)
     - ⚪ `INSUFFICIENT_EVIDENCE` (Độ bao phủ $< 80\%$ hoặc thiếu dữ liệu đo)

2. **Ma trận Phân tích 6 Chiều Dữ liệu (6 Dimension Breakdown):**
   - Biểu đồ và bảng tiến độ cho: `Completeness`, `Validity`, `Uniqueness`, `Consistency`, `Timeliness`, `Accuracy`.

3. **Phân phối Bất biến Phân vùng MECE (MECE Partition Percentage Distribution):**
   - Tỷ lệ phần trăm trực quan của 5 trạng thái bản ghi:
     $$\text{passed} + \text{failed} + \text{missing} + \text{miscast} + \text{not\_applicable} = \text{total\_observed}$$

4. **Khu vực Soi Bằng chứng Vi phạm (PII-Redacted Evidence Drill-Down):**
   - Hiển thị bảng mẫu vi phạm (khống chế $\le 50$ dòng, dung lượng $\le 500$ KB).
   - Tự động che mờ 4 họ thông tin nhạy cảm: Email, Số điện thoại, Mã định danh/SSN, Số thẻ thanh toán.

### 3.2. Khởi chạy Giao diện Dashboard (Streamlit)

```powershell
# Khởi chạy giao diện Streamlit Dashboard
uv run streamlit run src/dq_scoring/presentation/ui/dashboard.py --server.port 8501
```

Truy cập giao diện tại: `http://localhost:8501`.

---

## 4. CẨM NANG GIẢI NGHĨA TOÁN HỌC & BẤT BIẾN ĐO LƯỜNG

Khi phân tích kết quả đánh giá, người dùng cần nắm vững các nguyên tắc toán học cốt lõi:

1. **Bảo toàn Số lượng Quan sát (MECE Identity):**
   Mọi dòng dữ liệu thuộc tập quan sát luôn rơi vào đúng một trong năm trạng thái loại trừ lẫn nhau, không bao giờ mất mát hoặc đếm trùng.

2. **Xử lý Mẫu số Bằng 0 (Zero Denominator Semantics):**
   - Khi không có dòng nào thỏa điều kiện lọc: Trả về trạng thái `NOT_APPLICABLE` (không tính vào mẫu số bao phủ).
   - Khi thiếu bảng tham chiếu hoặc siêu dữ liệu: Trả về `NOT_MEASURABLE` (tính vào mẫu số và kéo giảm độ bao phủ `coverage`).
   - Tuyệt đối không bao giờ ép điểm về 0.0 hay 100.0 khi mẫu số bằng 0.

3. **Thứ tự Ưu tiên 6 Cấp bậc Cổng Chất lượng (Gate Precedence):**
   $$\text{ERROR} \succ \text{Critical FAIL} \succ \text{INSUFFICIENT\_EVIDENCE} \succ \text{FAIL} \succ \text{WARN} \succ \text{PASS}$$

4. **Cô lập Tín hiệu Ngoại lệ (IQR Advisory Isolation):**
   Quy tắc phát hiện điểm ngoại lệ (Outlier IQR) mang tính chất cố vấn nghiệp vụ (`is_advisory = true`, trọng số đóng góp = 0.0), không làm suy giảm điểm DQ Score kỹ thuật hay kích hoạt cổng FAIL.

5. **Điều kiện Xuất bản Điểm số (Publication Criteria):**
   Báo cáo chỉ đạt trạng thái `PUBLISHED` khi: Đợt chạy thành công, Cổng chất lượng khác `ERROR`, Độ bao phủ $\ge 80\%$, và không có phép đo bắt buộc nào bị bỏ sót. Ngược lại, điểm số sẽ bị `WITHHELD` (`dq_score = null`).


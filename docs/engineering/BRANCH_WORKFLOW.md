# QUY CHUẨN QUẢN TRỊ NHÁNH GIT (GIT BRANCHING & RELEASE WORKFLOW)

**Dự án:** DQ Scoring System  
**Phiên bản tài liệu:** 1.0  
**Ngày ban hành:** 2026-09-25  
**Quy chuẩn nền tảng:** GitFlow, Trunk-Based Integration, Conventional Commits 1.0  

---

## 1. MỤC ĐÍCH & NGUYÊN TẮC CỐT LÕI

Hệ thống DQ Scoring là nền tảng tính toán chất lượng dữ liệu với các bất biến toán học và yêu cầu độ tin cậy phân tán nghiêm ngặt (DDIA). Để bảo đảm tính ổn định của mã nguồn runtime, tài liệu này quy chuẩn hóa mô hình phân nhánh (Branching Model) nhằm:
1. **Bảo vệ nhánh Release/Master:** Nhánh `master` luôn phản ánh trạng thái đã phát hành, được kiểm định đầy đủ và có thể triển khai sản xuất ngay lập tức.
2. **Tích hợp liên tục trên Develop:** Nhánh `develop` là trung tâm tích hợp toàn bộ các tính năng, bộ chuyển đổi hạ tầng (adapters) và tài liệu trong quá trình phát triển các Milestone.
3. **Phân lập tính năng nguyên tử:** Mọi cải tiến hoặc sửa lỗi được phát triển trên các nhánh nhánh độc lập (`feat/*`, `fix/*`), trải qua kiểm thử tự động trước khi tích hợp.

---

## 2. CẤU TRÚC PHÂN NHÁNH CHUẨN HÓA (BRANCH TAXONOMY)

```text
  origin/master (Production / Releases)
      │
      ├── [Tag v1.0-m1] (Milestone 1 Baseline: 8f1b4ae)
      │
      └── [PR / Release Merge] ◄────────────────────────┐
                                                       │
  develop (Active Development & Integration Trunk)     │
      │                                                │
      ├── feat/m1-sandbox-and-fixtures                 │
      ├── feat/m2-postgres-adapters                    │
      ├── feat/m3-spark-pushdown                       │
      │                                                │
      └── release/v1.0-m1-validation ──────────────────┘
```

### 2.1. Nhánh Chính (Long-Lived Branches)

| Tên Nhánh | Mục Đích & Vai Trò | Quy Tắc Bảo Vệ & Giới Hạn |
| :--- | :--- | :--- |
| **`master`** | Nhánh sản xuất / phát hành chính thức (Release Trunk). Luôn đồng bộ với `origin/master`. | **Protected:** Nghiêm cấm commit trực tiếp. Chỉ nhận mã nguồn thông qua Pull Request hoặc merge từ nhánh `release/*` hoặc `hotfix/*` sau khi nghiệm thu toàn diện. |
| **`develop`** | Nhánh tích hợp phát triển chính (Main Integration Branch). Tập hợp mã nguồn cho milestone tiếp theo. | **Always Green:** Mọi commit/merge vào `develop` bắt buộc phải vượt qua 100% test suite (`uv run pytest`) và 0 lỗi linter (`uv run ruff check .`). |

### 2.2. Nhánh Ngắn Hạn (Short-Lived Supporting Branches)

| Tiền Tố Nhánh | Nhánh Xuất Phát | Nhánh Đích (Merge) | Trường Hợp Sử Dụng |
| :--- | :--- | :--- | :--- |
| **`feat/<tên-tính-năng>`** | `develop` | `develop` | Phát triển nhiệm vụ hoặc tính năng mới (ví dụ: `feat/m2-postgres-store`, `feat/m3-spark-operator`). |
| **`fix/<tên-lỗi>`** | `develop` | `develop` | Sửa lỗi phát hiện trong quá trình phát triển hoặc kiểm thử tích hợp. |
| **`release/<phiên-bản>`** | `develop` | `master` & `develop` | Đóng gói nghiệm thu milestone, hoàn thiện tài liệu, đóng băng tính năng trước khi gắn tag lên `master`. |
| **`hotfix/<tên-sửa-gấp>`**| `master` | `master` & `develop` | Xử lý khẩn cấp lỗi nghiêm trọng trên môi trường production/release baseline. |

---

## 3. QUY TRÌNH PHÁT TRIỂN & CHU TRÌNH ĐÓNG GÓI MILESTONE

### 3.1. Chu trình Phát triển Tính năng (Feature Workflow)
1. Tạo nhánh tính năng từ `develop`:
   ```powershell
   git checkout develop
   git pull origin develop
   git checkout -b feat/m2-postgres-adapter
   ```
2. Thực hiện sửa đổi và tuân thủ Pre-Commit Checklist theo `commit_guide.md`:
   ```powershell
   uv run ruff check .
   uv run pytest
   git commit -m "feat(adapters): implement PostgresAssessmentStoreAdapter with lease fencing"
   ```
3. Merge vào `develop` (hoặc tạo PR trên remote):
   ```powershell
   git checkout develop
   git merge --no-ff feat/m2-postgres-adapter
   ```

### 3.2. Chu trình Nghiệm thu và Phát hành Milestone (Milestone Release)
1. Khi hoàn thành toàn bộ các nhiệm vụ trong Milestone (ví dụ: Mốc 1 hoàn thành T1.1–T1.3 và Báo cáo nghiệm thu):
2. Đóng gói trên `release/v1.0-m1`:
   - Chạy toàn bộ test suites và đối soát báo cáo nghiệm thu.
   - Thẩm định working tree sạch sẽ, không có secret và không sót file rác.
3. Hợp nhất vào `master` và gắn thẻ phiên bản (Git Tag):
   ```powershell
   git checkout master
   git merge --no-ff release/v1.0-m1
   git tag -a v1.0-m1 -m "release: Milestone 1 - Sandbox, Chicago Taxi Fixtures & Test Oracle"
   ```
4. Đồng bộ ngược lại vào `develop` (nếu có cập nhật tài liệu phát sinh trong nhánh release).

---

## 4. QUY TẮC BẢO TOÀN LỊCH SỬ GIT (GIT INTEGRITY INVARIANTS)

1. **Tuyệt đối không force push lên nhánh chung:** Không sử dụng `git push --force` trên `master` hoặc `develop` khi đã chia sẻ với remote.
2. **Phục hồi trunk cục bộ an toàn:** Khi nhánh cục bộ `master` bị trôi commit chưa chia sẻ (unpushed commits), toàn bộ commit phát triển phải được chuyển giao sang `develop` trước khi đưa `master` cục bộ về đúng `origin/master`.
3. **Commit nguyên tử (Atomic Commits):** Mỗi commit mang đúng một mục đích, có thông điệp tường minh theo chuẩn Conventional Commits (`commit_guide.md`).

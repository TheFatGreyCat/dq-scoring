# HƯỚNG DẪN KỸ THUẬT TRIỂN KHAI VÀ TÁI CẤU TRÚC MÃ NGUỒN (ENGINEERING & IMPLEMENTATION REUSE GUIDE)

**Mã tài liệu:** ENG-REUSE-01  
**Phiên bản:** 1.3  
**Ngày:** 2026-09-24  
**Trạng thái:** Target Implementation Specification — Bộ tiêu chí định hướng triển khai mã nguồn, kiểm soát chất lượng và nghiệm thu thực nghiệm  
**Tài liệu tham chiếu:** `AGENTS.md`, `GEMINI.md`, `docs/Chapter_1.md` đến `docs/Chapter_5.md`, `docs/theory/DQ_SCORING_THEORY.md`  

---

## 1. MỤC ĐÍCH VÀ NGUYÊN TẮC CỐT LÕI

Tài liệu này là cẩm nang kỹ thuật bắt buộc dành cho kỹ sư phần mềm và AI Coding Agents (Gemini, Codex, Claude) khi thiết kế, triển khai mới và di trú mã nguồn sang Core Engine sản phẩm (`dq_scoring`).

> **Lưu ý về Hiện trạng Kho mã nguồn:** Dự án đã hoàn thành toàn diện Giai đoạn 1 (Phase 1: Pure Domain Core, Ports, Orchestration Services và In-Memory Adapters) và Giai đoạn 2 (Phase 2: PostgreSQL 16 Persistence with RLS, Outbox Queue with Lease Generation, PySpark Single-Pass SQL Pushdown, FastAPI REST Gateway with Argon2id/JWT Auth, Two-Tier PII Redaction và Webhook Security) cùng Milestone 5 Hardening với 108 unit tests đạt 100% pass (bao gồm trọn bộ Golden Matrix G1–G19). Toàn bộ cấu trúc thư mục `src/dq_scoring` và `tests/` đang vận hành chuẩn Clean Architecture. Mọi logic mở rộng tiếp theo đều phải tuân thủ nghiêm ngặt cấu trúc và quy chuẩn này.

### Các Nguyên tắc Bất biến (Invariants)
1. **Ports-and-Adapters Isolation (Clean Architecture):** Phân tách tuyệt đối 4 tầng: Domain (`core`), Application (`services`), Contract (`ports`), Infrastructure (`adapters`), và Delivery (`presentation`). Phụ thuộc chỉ đi theo một chiều hướng tâm (inward dependency).
2. **Semantics First:** Tính đúng đắn của phép đo, null policy, trọng số, coverage và quality gate phải tuân thủ 100% đặc tả tại `Chapter_2.md` và `DQ_SCORING_THEORY.md`.
3. **Apache Spark on k3s Pushdown Engine:** Tận dụng Apache Spark trên k3s làm compute engine chuẩn hóa duy nhất cho Profiling và Validation trên file bảng (CSV/Parquet); triệt để áp dụng cơ chế vectorized pushdown, loại bỏ việc nạp toàn phần dữ liệu vào bộ nhớ heap Python hoặc Great Expectations runtime.
4. **Bảo toàn Dữ liệu Nguồn Tuyệt đối:** Tuyệt đối không can thiệp sửa đổi, coalesce hay compact làm biến đổi dữ liệu nguồn; snapshot đa tệp được quản lý thông qua canonical `manifest.json`.
5. **Đơn định và Tái lập (Determinism & Reproducibility):** Cùng một cặp `(DatasetSnapshot, RunSpec)` chạy $N$ lần luôn cho ra kết quả `Assessment` và mã băm `assessment_hash` đồng nhất $100\%$.

---

## 2. QUY CHUẨN KỸ THUẬT TRIỂN KHAI & KIỂM SOÁT CHẤT LƯỢNG MÃ NGUỒN

### 2.1. Giới hạn Kích thước Tệp & Hàm (File & Function Sizing Budget)
- **Kích thước Hàm (Function Granularity):**
  - Lý tưởng: **5 – 20 dòng code**, tối đa không vượt quá **30 dòng**.
  - Áp dụng nguyên tắc Single Level of Abstraction (SLAP): Mỗi hàm chỉ thực hiện một mức độ trừu tượng duy nhất.
  - Tối đa 2 tham số vị trí; nếu cần $\ge 3$ tham số, bắt buộc gom vào Typed Dataclass hoặc Pydantic BaseModel.
  - Tuyệt đối không sử dụng `flag argument` (tham số boolean điều khiển rẽ nhánh `if/else` lớn trong hàm).
- **Kích thước Tệp (File Sizing Budget):**
  - Lý tưởng: **50 – 250 dòng code**.
  - Trần cứng tối đa: **$\le 400$ dòng code**. Bất kỳ file nào vượt quá 300 dòng đều phải được xem xét phân rã thành các sub-module mạch lạc.
  - Áp dụng nguyên tắc Đơn nhiệm cấp Tệp (Single Responsibility Principle per File): Một file chỉ giải quyết một nhóm trách nhiệm gắn kết chặt chẽ.
  - **Nghiêm cấm "File rác tổng hợp":** Tuyệt đối không tạo các file như `utils.py`, `helpers.py`, `misc.py`, `common.py`. Mọi tiện ích phải có tên định danh rõ miền trách nhiệm (ví dụ: `hash_utils.py`, `time_utils.py`, `redaction_utils.py`).

### 2.2. Phân rã Module Chuẩn (Clean Architecture Seams)
Mã nguồn được tổ chức phân tầng rõ ràng giữa phần đã hoàn thiện (Phase 1) và phân hệ mục tiêu (Phase 2):
```text
src/dq_scoring/
├── core/                  # Pure Domain [Phase 1 - Đã hoàn thiện]: Entities, Value Objects, Pure Formulas
│                          # (TUYỆT ĐỐI KHÔNG import Spark, SQLAlchemy, FastAPI, Requests)
├── ports/                 # Abstract Interfaces [Phase 1 - Đã hoàn thiện]: IComputeEnginePort, IAssessmentStorePort, IQueuePort
├── services/              # Application Use Cases [Phase 1 - Đã hoàn thiện]: orchestrator, score_aggregator, validation_service, replay_runner
├── adapters/              # Infrastructure Implementations:
│   ├── (In-Memory)        # In-Memory adapters phục vụ unit testing & replay verification [Phase 1 - Đã hoàn thiện]
│   ├── compute/           # Spark on k3s pushdown query builder & executor [Phase 2 - Kế hoạch mục tiêu]
│   ├── db/                # PostgreSQL 16 repositories with Row Level Security (RLS) [Phase 2 - Kế hoạch mục tiêu]
│   ├── storage/           # MinIO / S3 client [Phase 2 - Kế hoạch mục tiêu]
│   └── queue/             # PostgreSQL 16 FOR UPDATE SKIP LOCKED job queue [Phase 2 - Kế hoạch mục tiêu]
├── presentation/          # Delivery [Phase 2 - Kế hoạch mục tiêu]: api/ (FastAPI), cli/ (Typer), ui/ (Streamlit)
└── common/                # Tiện ích độc lập nghiệp vụ: hash_utils.py [Phase 1 - Đã hoàn thiện], redaction/time [Phase 2]
```

### 2.3. Nguyên tắc YAGNI & Lazy Senior Developer (Ponytail Principle)
- Không xây dựng các tính năng, interface, abstract factory hoặc framework dự phòng cho tương lai chưa được yêu cầu trong 25 Tiêu chí Nghiệm thu (AC-001 đến AC-025).
- Thang ưu tiên trước khi viết mã: YAGNI $\rightarrow$ Reuse helper có sẵn $\rightarrow$ Standard Library $\rightarrow$ Installed Dependencies $\rightarrow$ Viết số dòng mã tối thiểu.
- Đánh dấu các đơn giản hóa có chủ đích bằng ghi chú `# ponytail: <lý do và hướng mở rộng>`.

### 2.4. Quy chuẩn Chống Hardcode & Magic Numbers
- **Không hardcode giá trị nghiệp vụ:** Các ngưỡng điểm (như `80.0`, `60.0`, `0.80`), trọng số, timeout, số lần retry và chính sách null policy phải được truyền vào qua đối tượng cấu hình (`ScoringPolicy`, `QualityRule`, `RunSpec`).
- **Hằng số Kỹ thuật Chuẩn hóa:** Những hằng số kỹ thuật nội bộ bất biến (như `MAX_SAMPLE_ROWS = 50`, `MAX_EVIDENCE_BYTES = 512_000`, `UTC_TIMESTAMP_FORMAT`) phải được khai báo dạng `SCREAMING_SNAKE_CASE` ở cấp module kèm docstring giải thích căn cứ kỹ thuật.
- **Tuyệt đối cấm Magic Numbers:** Không sử dụng các con số không rõ nguồn gốc trong các biểu thức tính toán hoặc lọc dữ liệu (ví dụ: `if len(x) > 50`, `score < 60`).

### 2.5. Quy trình Chống Sửa Chắp vá (Anti-Spaghetti Patching Protocol)
Khi phát hiện lỗi hoặc unit test bị fail, kỹ sư và AI Agent bắt buộc tuân thủ quy trình 5 bước theo đúng thứ tự:
1. **Lần vết Nguyên nhân gốc (Trace Root Cause):** Lần vết ngược luồng dữ liệu lên upstream để xác định nơi phát sinh lỗi gốc. Nghiêm cấm đặt `if special_case:` tạm bợ ở tầng downstream để lách test case.
2. **Đối soát Invariants:** Kiểm tra lại công thức và bất biến tại `DQ_SCORING_THEORY.md`. Nghiêm cấm sửa assertion của test nếu không có căn cứ từ đặc tả lý thuyết.
3. **Viết Test Tái hiện trước (Reproducing Test First):** Viết unit/regression test chứng minh lỗi tồn tại (test đỏ) trước khi chỉnh sửa mã nguồn.
4. **Sửa Tận gốc (Fix at Source):** Thực hiện thay đổi tối thiểu, thanh lịch và chuẩn xác tại đúng nguồn khởi phát để chuyển test đỏ thành xanh.
5. **Rà soát Diff Sạch (Self-Diff Review):** Tự đọc lại toàn bộ diff, loại bỏ biến thừa, mã chết và log debug trước khi hoàn thành.

### 2.6. Chính sách Bảo mật Biến môi trường, Bí mật và Dữ liệu Nhạy cảm
- **Không bao giờ commit `.env`:** Tệp `.env` chỉ dùng ở máy trạm cá nhân, luôn bị chặn bởi `.gitignore`.
- **Duy trì `.env.example`:** Mọi biến môi trường mới phải được khai báo vào `.env.example` kèm giá trị giả định an toàn và chú thích rõ ràng.
- **Fail-Fast Configuration:** Khởi động hệ thống thông qua `Pydantic Settings` có kiểm thực chặt chẽ; thiếu biến bảo mật bắt buộc phải raise exception dừng ngay lập tức, không fallback âm thầm về mật khẩu mặc định rỗng.
- **Bảo mật Lỗi & Dữ liệu (Zero Secret/PII Leakage):**
  - Tuân thủ chuẩn RFC 9457: Phản hồi lỗi API không được để lộ chuỗi kết nối, tên bảng, mật khẩu hay stack trace nội bộ.
  - Bằng chứng vi phạm chất lượng dữ liệu phải được giới hạn tối đa 50 dòng và che mờ PII 2 tầng trước khi lưu kho hoặc trả về client.

---

## 3. MA TRẬN PHÂN LOẠI TÁI SỬ DỤNG (REUSE CLASSIFICATION MATRIX)

> **Lộ trình Chuyển đổi & Tái sử dụng:** Bảng ma trận dưới đây định hình lộ trình chuyển đổi và hiện thực hóa mục tiêu (Target TO-BE) cho Giai đoạn 2 (đặc biệt là Spark Pushdown, Postgres Persistence và API). Logic tính toán điểm cốt lõi (`score_aggregator`, `rule_scoring`, `quality_gate`) đã được hiện thực hóa và kiểm chứng đơn định tại `src/dq_scoring/core/` và `src/dq_scoring/services/`.

| Mã thành phần | Module nguồn (AS-IS) | Đánh giá kỹ thuật | Quyết định xử lý | Module đích (Target Package TO-BE) |
| :--- | :--- | :--- | :--- | :--- |
| **COMP-01** | Rule Execution SQL Logic | Thuật toán kiểm tra 5 nhóm quy tắc xác định hoạt động tối ưu qua pushdown trên Spark. | **Adopt (Tái sử dụng có tinh chỉnh)** | `dq_scoring.adapters.compute.sql_query_builder` |
| **COMP-02** | Profiling Aggregations | Câu lệnh SQL tính row count, nulls, distincts, min/max, quartiles. | **Adopt (Tái sử dụng có tinh chỉnh)** | `dq_scoring.services.profiling_service` |
| **COMP-03** | IQR Outlier Detection | Thuật toán tính Tukey fences ($Q1 \pm 1.5 \cdot IQR$). | **Adopt (Chuyển sang Advisory)** | `dq_scoring.services.outlier_service` |
| **COMP-04** | Weighted Score Engine | Công thức tính Rule Score, Dimension Score, DQ Score và Quality Gate. | **Adopt (Chuẩn hóa Invariants)** | `dq_scoring.services.score_aggregator` |
| **COMP-05** | Evidence Redaction | Logic cắt giới hạn 10–50 dòng và che mờ PII nhạy cảm. | **Adopt (Chuẩn hóa Utils)** | `dq_scoring.common.evidence_redactor` |
| **COMP-06** | Great Expectations Wrapper | Quá nhiều lớp trừu tượng, nặng nề, khó kiểm soát SQL sinh ra. | **Reject (Loại bỏ hoàn toàn)** | Thay thế bằng Spark Pushdown Direct Compute |
| **COMP-07** | Celery / Redis Task Queue | Dư thừa broker ngoài, làm tăng độ phức tạp vận hành | **Reject/Replace** | Thay thế bằng hàng đợi bền vững PostgreSQL 16 `FOR UPDATE SKIP LOCKED` (`dq_scoring.adapters.queue`) |
| **COMP-08** | Legacy In-Memory IAM | Mô hình cũ thiếu bảo mật tenant và ranh giới RLS | **Adopt with Overhaul** | Thiết kế lại thành Multi-tenant AuthContext với Argon2id + JWT + PostgreSQL 16 RLS (`dq_scoring.presentation.api.auth`) |

---

## 4. HƯỚNG DẪN TRIỂN KHAI CHI TIẾT THEO PHÂN HỆ

> **Phân định Hiện trạng vs Kế hoạch:** Phân hệ 4.1 (Spark Pushdown), 4.4 (Evidence Redaction utils hoàn chỉnh), và các adapter bên ngoài của 4.5 (Postgres RLS, MinIO) là tài liệu hướng dẫn kỹ thuật cho Giai đoạn 2. Phân hệ 4.2 (Validation Service), 4.3 (Score Aggregator & Quality Gate) và luồng điều phối cơ bản của 4.5 đã hoàn thành phần lõi miền trong Phase 1.

### 4.1. Phân hệ Profiling và Compute (`dq_scoring.adapters.compute`)
- **Yêu cầu:** Single-pass aggregation trên Apache Spark Pushdown.
- **Quy tắc:**
  - Tuyệt đối không nạp toàn bộ dữ liệu bảng vào bộ nhớ heap Python để tính toán thống kê.
  - Sử dụng trực tiếp SQL / pushdown `SELECT COUNT(*), COUNT(col), MIN(col), MAX(col), percentile_approx(col, array(0.25, 0.5, 0.75))...`.
  - Khống chế tài nguyên Spark trong ngân sách 4 GB RAM (`driver + executor`) trên nút đơn k3s 8 GB RAM; tối đa 1 run chạy đồng thời.
  - Đóng gói kết quả đầu ra thành tập hợp `CanonicalMetric` bất biến.

### 4.2. Phân hệ Kiểm tra Quy tắc (`dq_scoring.services.validation_service`)
- **Yêu cầu:** Đánh giá 5 nhóm quy tắc xác định: Non-null, Type/Parse, Domain/Range, Uniqueness, Cross-field.
- **Quy tắc:**
  - Phân loại kết quả của mỗi bản ghi thành các tập loại trừ lẫn nhau: `passed`, `failed`, `missing`, `miscast`, `not_applicable`.
  - Bảo toàn Invariant: $\sum \text{counts} = \text{total\_observed}$.
  - Sinh `CanonicalQualityResult` thống nhất cấu trúc cho mỗi quy tắc.

### 4.3. Phân hệ Tính Điểm & Cổng Chất lượng (`dq_scoring.services.score_aggregator`)
- **Yêu cầu:** Áp dụng đúng công thức toán học và thứ tự ưu tiên Quality Gate được cấu hình theo `ScoringPolicy`.
- **Quy tắc:**
  - Rule Score: Áp dụng nghiêm ngặt theo `null_policy` (`fail`, `ignore`, `separate`, `not_applicable`).
  - Mẫu số bằng 0 hoặc không đo được trả về `NOT_APPLICABLE` / `NOT_MEASURABLE`, không gán điểm 0.
  - Tín hiệu Outlier IQR gán cờ `is_advisory = True`, trọng số bằng 0, không làm đổi DQ Score/Gate.
  - Thứ tự ưu tiên Quality Gate: `ERROR` $\succ$ Critical `FAIL` $\succ$ `INSUFFICIENT_EVIDENCE` (Coverage < threshold) $\succ$ `FAIL` $\succ$ `WARN` $\succ$ `PASS`.

### 4.4. Phân hệ Quản lý & Che mờ Bằng chứng (`dq_scoring.common.evidence_redactor`)
- **Yêu cầu:** Bảo mật và an toàn bộ nhớ.
- **Quy tắc:**
  - Khống chế danh sách dòng vi phạm mẫu từ 10 đến tối đa 50 dòng (`LIMIT 50`).
  - Giới hạn dung lượng payload bằng chứng $\le 500\text{ KB}$.
  - Tự động quét và che mờ dữ liệu nhạy cảm (email, số điện thoại, định danh).
  - Tự động dọn dẹp các tệp tạm scratchpad trong `.tmp/` sau khi kết thúc lượt chạy.

### 4.5. Phân hệ Lưu trữ Bất biến & Điều phối (`dq_scoring.adapters.db`, `dq_scoring.services.evaluation_orchestrator`)
- **Yêu cầu:** Append-only assessment, quản trị snapshot đa tệp qua `manifest.json`.
- **Quy tắc:**
  - Không coalesce hay compact tệp gốc của snapshot.
  - Điều phối lượt chạy qua cơ chế Worker Lease và hàng đợi PostgreSQL 16 `FOR UPDATE SKIP LOCKED`.
  - Công bố kết quả đánh giá nguyên tử (Atomic Publication) trong một transaction duy nhất.

---

## 5. MẪU THAM CHIẾU HIỆN THỰC HÓA BẤT BIẾN TOÁN HỌC & CỔNG CHẤT LƯỢNG (REFERENCE PATTERNS)

Nhằm loại bỏ hoàn toàn các "Bẫy Tử huyệt" (Trap Inventory) đã được chỉ ra trong Báo cáo Deep Research Audit, mã nguồn triển khai trong `dq_scoring` Core Engine phải tuân thủ nghiêm ngặt các mẫu tham chiếu chuẩn mực dưới đây:

### 5.1. Đánh giá Cổng Chất lượng 6 Cấp bậc Phụ thuộc Chính sách (Policy-Driven Quality Gate)

```python
from enum import Enum
from typing import List, Optional, Set
from pydantic import BaseModel, Field


class QualityGateStatus(str, Enum):
    ERROR = "ERROR"
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    WARN = "WARN"
    PASS = "PASS"


class QualityRuleResult(BaseModel):
    rule_id: str
    dimension: str
    measurement_status: str  # MEASURED, NOT_APPLICABLE, NOT_MEASURABLE, FAILED_TO_MEASURE, INSUFFICIENT_DATA, SKIPPED_BY_BUDGET
    is_critical: bool = False
    is_advisory: bool = False
    is_required: bool = (
        False  # Bắt buộc phải đo thành công; FAILED_TO_MEASURE kích hoạt Gate ERROR
    )
    gate_enabled: bool = True  # Cho phép rule tham gia quyết định Quality Gate
    score_enabled: bool = True  # Cho phép rule đóng góp điểm vào Dimension Score
    conflict_group: Optional[str] = (
        None  # Nhóm quy tắc xung đột / đo cùng hiện tượng (Theory §10)
    )
    is_primary_scoring_rule: bool = (
        True  # Quy tắc chính trong nhóm xung đột đóng góp điểm vào R_d^m
    )
    contribution_weight: float = 1.0  # Trọng số hiệu dụng w_r
    acceptance_threshold: Optional[float] = (
        None  # Ngưỡng chấp nhận t_r; None kích hoạt Zero-Tolerance
    )
    confidence: Optional[float] = (
        None  # None trong v1.0 full scan (NOT_APPLICABLE per FR-SCORE-009)
    )
    computed_score: Optional[float] = None
    violations_count: int = (
        0  # failed + miscast + missing_penalized dùng cho nhánh Zero-Tolerance
    )


class ScoringPolicy(BaseModel):
    """
    Chính sách tính điểm và ngưỡng cổng chất lượng được cấu hình theo Tenant/Dataset.
    Tuyệt đối KHÔNG hardcode các giá trị này vào hàm nghiệp vụ!
    """

    publication_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    warn_min: float = Field(default=60.0, ge=0.0, le=100.0)
    pass_min: float = Field(default=80.0, ge=0.0, le=100.0)
    min_critical_confidence: float = Field(default=0.80, ge=0.0, le=1.0)

    @property
    def coverage_threshold(self) -> float:
        """Alias tương thích cho publication_threshold."""
        return self.publication_threshold

    @property
    def gate_fail_threshold(self) -> float:
        """Ngưỡng phân định FAIL và WARN (tương đương warn_min)."""
        return self.warn_min

    @property
    def gate_warn_threshold(self) -> float:
        """Ngưỡng phân định WARN và PASS (tương đương pass_min)."""
        return self.pass_min


class GateEvaluationInput(BaseModel):
    """Gói tham số đầu vào cho hàm đánh giá Quality Gate (tuân thủ quy tắc <= 2 params & SLAP)."""

    rule_results: List[QualityRuleResult]
    dq_score: Optional[float]
    coverage_ratio: Optional[float] = None
    policy: ScoringPolicy
    required_dimensions: Set[str] = Field(default_factory=set)


def _is_critical_violated(rule: QualityRuleResult, min_conf: float) -> bool:
    """Kiểm tra vi phạm quy tắc critical theo 2 nhánh: Zero-Tolerance hoặc Ngưỡng chấp nhận riêng."""
    if (
        not rule.is_critical
        or not rule.gate_enabled
        or rule.is_advisory
        or rule.measurement_status != "MEASURED"
    ):
        return False
    # Trong v1.0 full scan, confidence là None (NOT_APPLICABLE per FR-SCORE-009) nên không bị chặn
    if rule.confidence is not None and rule.confidence < min_conf:
        return False
    if rule.acceptance_threshold is not None:
        return (
            rule.computed_score is not None
            and rule.computed_score < rule.acceptance_threshold
        )
    return rule.violations_count > 0


def evaluate_quality_gate(inp: GateEvaluationInput) -> QualityGateStatus:
    """
    Đánh giá Quality Gate theo đúng thứ tự ưu tiên 6 cấp bậc dựa trên ScoringPolicy (BR-010):
    ERROR > Critical FAIL > INSUFFICIENT_EVIDENCE > FAIL > WARN > PASS.
    """
    # 1. Bẫy lỗi kỹ thuật: có bất kỳ quy tắc bắt buộc nào (cả score-enabled lẫn gate-only)
    # bị lỗi thực thi kỹ thuật FAILED_TO_MEASURE trong Run đã hoàn tất -> ERROR (BR-010, BR-025)
    if any(
        r.is_required and r.measurement_status == "FAILED_TO_MEASURE"
        for r in inp.rule_results
    ):
        return QualityGateStatus.ERROR

    # 2. Quy tắc sống còn (Critical Rule) bị vi phạm (Zero-Tolerance hoặc Ngưỡng riêng)
    if any(
        _is_critical_violated(r, inp.policy.min_critical_confidence)
        for r in inp.rule_results
    ):
        return QualityGateStatus.FAIL

    # 3. Bằng chứng không đủ: Coverage < threshold, thiếu phép đo bắt buộc, hoặc thiếu chiều bắt buộc
    has_unmeasured_required = any(
        r.is_required
        and r.measurement_status
        in ("NOT_MEASURABLE", "INSUFFICIENT_DATA", "SKIPPED_BY_BUDGET")
        for r in inp.rule_results
    )
    # Chiều được coi là đã đo hợp lệ khi có ít nhất 1 quy tắc thuộc R_d^m:
    # MEASURED, score_enabled, không phải advisory, là primary scoring rule, và có computed_score hợp lệ (Theory §10, §11)
    measured_dims = {
        r.dimension
        for r in inp.rule_results
        if r.measurement_status == "MEASURED"
        and r.score_enabled
        and not r.is_advisory
        and r.is_primary_scoring_rule
        and r.computed_score is not None
    }
    missing_required_dim = bool(inp.required_dimensions - measured_dims)

    is_coverage_insufficient = (
        inp.coverage_ratio is None or inp.coverage_ratio < inp.policy.coverage_threshold
    )
    if (
        is_coverage_insufficient
        or inp.dq_score is None
        or has_unmeasured_required
        or missing_required_dim
    ):
        return QualityGateStatus.INSUFFICIENT_EVIDENCE

    # 4. Ngưỡng điểm thất bại: DQ Score < policy.gate_fail_threshold (warn_min)
    if inp.dq_score < inp.policy.gate_fail_threshold:
        return QualityGateStatus.FAIL

    # 5. Ngưỡng điểm cảnh báo: gate_fail_threshold <= DQ Score < policy.gate_warn_threshold (pass_min)
    if inp.dq_score < inp.policy.gate_warn_threshold:
        return QualityGateStatus.WARN

    # 6. Đạt tiêu chuẩn chất lượng: DQ Score >= policy.gate_warn_threshold (pass_min)
    return QualityGateStatus.PASS
```

### 5.2. Guard Clauses Xử lý Mẫu số Không & Trạng thái Đo lường

> **Lưu ý triển khai về `zero_denominator_status`:** Mẫu tham chiếu dưới đây khuyến nghị caller truyền tường minh `zero_denominator_status` (`"NOT_APPLICABLE"` hoặc `"NOT_MEASURABLE"`) khi gọi hàm để phản ánh đúng ngữ cảnh đo lường. Trong triển khai nền tảng hiện tại (`src/dq_scoring/core/rule_scoring.py`), trường này có giá trị mặc định là `MeasurementStatus.NOT_MEASURABLE.value` nhằm đảm bảo tính tương thích với các caller hiện có (`validation_service.py`). Khi gọi `compute_rule_score`, caller nên chủ động truyền giá trị mong muốn thay vì phụ thuộc ngầm vào default.

```python
class RuleCounts(BaseModel):
    passed: int = 0
    failed: int = 0
    missing: int = 0
    miscast: int = 0


class RuleScoringInput(BaseModel):
    counts: RuleCounts
    null_policy: str = "fail"
    # zero_denominator_status bắt buộc truyền tường minh: "NOT_APPLICABLE" hoặc "NOT_MEASURABLE".
    # Tuyệt đối KHÔNG gán default ngầm để ngăn ngừa việc vô tình che giấu dữ liệu khuyết thiếu!
    zero_denominator_status: str
    is_applicable: bool = True
    has_required_metadata: bool = True


def compute_rule_score(inp: RuleScoringInput) -> tuple[str, Optional[float]]:
    """
    Tính Rule Score theo Null Policy kèm Guard Clauses ngăn ngừa Zero Default Trap.
    Tuân thủ phân hoạch phân loại loại trừ lẫn nhau:
      total_observed = passed + failed + missing + miscast + not_applicable.
    Mẫu số n_r theo DQ_SCORING_THEORY.md:
      - 'fail': n_r = passed + failed + miscast + missing
      - 'ignore' / 'separate' / 'not_applicable': n_r = passed + failed + miscast
    Trả về: (measurement_status, computed_score)
    """
    # Guard 1: Quy tắc không áp dụng cho cấu hình / schema dữ liệu này
    if not inp.is_applicable:
        return "NOT_APPLICABLE", None

    # Guard 2: Quy tắc thiếu metadata tham chiếu hoặc cột cần thiết để đo
    if not inp.has_required_metadata:
        return "NOT_MEASURABLE", None

    c = inp.counts
    if inp.null_policy == "fail":
        denominator = c.passed + c.failed + c.miscast + c.missing
    elif inp.null_policy in ("ignore", "separate", "not_applicable"):
        denominator = c.passed + c.failed + c.miscast
    else:
        raise ValueError(f"Unsupported null policy: {inp.null_policy}")

    # Guard 3: Xử lý mẫu số bằng 0 (Zero Denominator Trap)
    # Tuyệt đối KHÔNG trả về 0.0 hoặc 100.0 khi mẫu số bằng 0!
    # zero_denominator_status do caller truyền tường minh:
    # "NOT_APPLICABLE" (nếu ngoài predicate / không áp dụng, loại khỏi coverage)
    # hoặc "NOT_MEASURABLE" (nếu thiếu dữ liệu quan sát / metadata, tính vào mẫu số coverage làm giảm coverage)
    if denominator == 0:
        return inp.zero_denominator_status, None

    score = (c.passed / denominator) * 100.0
    # Giữ nguyên độ chính xác số thực (float) nội bộ theo DQ_SCORING_THEORY §17;
    # Không làm tròn sớm tại đây (chỉ làm tròn khi serialize/persist bản đánh giá).
    return "MEASURED", score
```

### 5.3. Mẫu Cô lập Outlier Advisory (Outlier Advisory Isolation)

```python
class OutlierResultInput(BaseModel):
    column_name: str
    total_evaluated: int
    iqr: float = 0.0
    outlier_count: int = 0
    is_all_null: bool = False


def build_outlier_advisory_result(inp: OutlierResultInput) -> QualityRuleResult:
    """
    Chuẩn hóa kết quả IQR Outlier Detector thành Canonical Quality Result (FR-DET-003..005).
    Xử lý an toàn boundary cases: toàn bộ null, dữ liệu < 4 bản ghi, hoặc IQR = 0 trả NOT_MEASURABLE.
    Bảo đảm: is_advisory = True, contribution_weight = 0.0 (không phạt điểm DQ).
    """
    is_valid_measurement = (
        not inp.is_all_null and inp.total_evaluated >= 4 and inp.iqr > 0.0
    )
    status = "MEASURED" if is_valid_measurement else "NOT_MEASURABLE"

    return QualityRuleResult(
        rule_id=f"outlier_iqr_{inp.column_name}",
        dimension="ACCURACY",  # Phân loại theo Accuracy Proxy
        measurement_status=status,
        is_critical=False,
        is_advisory=True,  # Đánh dấu tín hiệu khuyến nghị
        is_required=False,
        gate_enabled=False,  # Không kích hoạt Quality Gate trong v1.0
        score_enabled=False,
        conflict_group=None,
        is_primary_scoring_rule=False,
        contribution_weight=0.0,  # Trọng số 0 để loại khỏi công thức tính DQ Score
        computed_score=None,  # Không gán điểm số định lượng cho Outlier v1.0
    )
```

### 5.4. Mẫu Xác định Trạng thái Công bố (Publication Status Determination)

```python
class PublicationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    WITHHELD = "WITHHELD"


class PublicationCheckInput(BaseModel):
    """Gói tham số đầu vào cho hàm xác định trạng thái công bố (tuân thủ quy tắc <= 2 params)."""

    run_status: str
    gate_status: QualityGateStatus
    dq_score: Optional[float]
    coverage_ratio: Optional[float] = None
    policy: ScoringPolicy  # Đồng bộ trực tiếp publication_threshold từ policy, loại bỏ default tách rời
    all_required_dimensions_measured: bool = True
    has_failed_required_rules: bool = (
        False  # Bất kỳ quy tắc bắt buộc nào bị FAILED_TO_MEASURE
    )
    has_unmeasured_required_rules: bool = False  # Bất kỳ quy tắc bắt buộc nào bị NOT_MEASURABLE / INSUFFICIENT_DATA / SKIPPED_BY_BUDGET


def determine_publication_status(
    inp: PublicationCheckInput,
) -> tuple[PublicationStatus, Optional[float]]:
    """
    Xác định PublicationStatus (PUBLISHED vs WITHHELD) theo FR-SCORE-006 & BR-009:
    - Điều kiện PUBLISHED:
      1. Lượt chạy thành công kỹ thuật: run_status == 'SUCCEEDED'
      2. Quality Gate không bị lỗi kỹ thuật hoặc thiếu chứng cứ:
         gate_status not in (QualityGateStatus.ERROR, QualityGateStatus.INSUFFICIENT_EVIDENCE)
      3. Độ phủ đạt ngưỡng tối thiểu theo policy: coverage_ratio >= policy.publication_threshold
      4. Tất cả các chiều chất lượng bắt buộc đều có ít nhất 1 quy tắc đủ điều kiện tính điểm (thuộc R_d^m)
      5. Không có phép đo bắt buộc nào bị lỗi kỹ thuật (FAILED_TO_MEASURE) hoặc không đo được
      6. Điểm tổng hợp dq_score đã được tính toán hợp lệ (không None)
    - Nếu vi phạm bất kỳ điều kiện nào:
      Trả về (PublicationStatus.WITHHELD, None) — dq_score bị gán None để ngăn ngừa ngộ nhận dữ liệu.
    """
    has_sufficient_coverage = (
        inp.coverage_ratio is not None
        and inp.coverage_ratio >= inp.policy.publication_threshold
    )
    is_eligible = (
        inp.run_status == "SUCCEEDED"
        and inp.gate_status
        not in (QualityGateStatus.ERROR, QualityGateStatus.INSUFFICIENT_EVIDENCE)
        and has_sufficient_coverage
        and inp.all_required_dimensions_measured
        and not inp.has_failed_required_rules
        and not inp.has_unmeasured_required_rules
        and inp.dq_score is not None
    )

    if is_eligible:
        return PublicationStatus.PUBLISHED, inp.dq_score

    return PublicationStatus.WITHHELD, None
```

### 5.5. Ma trận Bảng điểm Vàng (Golden Matrix for Gate & Publication Verification)

| STT | Kịch bản Kiểm thử | Trạng thái Phép đo & Vi phạm | Coverage | Tính toán DQ Score | QualityGateStatus | PublicationStatus | Điểm công bố (`dq_score`) |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **G1** | Quy tắc bắt buộc lỗi kỹ thuật | Có 1 required rule `FAILED_TO_MEASURE` | $90\%$ | $85.0$ | **`ERROR`** | **`WITHHELD`** | `null` |
| **G2** | Critical vi phạm + Đủ chứng cứ | Vi phạm critical rule (Zero-Tolerance) | $90\%$ | $85.0$ | **`FAIL`** | **`PUBLISHED`** | $85.0$ |
| **G3** | Critical vi phạm + Thiếu chứng cứ | Vi phạm critical rule (Zero-Tolerance) | $60\%$ | $85.0$ | **`FAIL`** | **`WITHHELD`** | `null` |
| **G4** | Thiếu độ phủ (Coverage thấp) | Không lỗi, không critical vi phạm | $75\%$ | $85.0$ | **`INSUFFICIENT_EVIDENCE`** | **`WITHHELD`** | `null` |
| **G5** | Thiếu phép đo bắt buộc | 1 required rule `NOT_MEASURABLE` | $85\%$ | $85.0$ | **`INSUFFICIENT_EVIDENCE`** | **`WITHHELD`** | `null` |
| **G6** | Điểm kém (Score < 60) | Không lỗi, không critical, đủ chứng cứ | $90\%$ | $55.0$ | **`FAIL`** | **`PUBLISHED`** | $55.0$ |
| **G7** | Điểm cảnh báo ($60 \le \text{Score} < 80$) | Không lỗi, không critical, đủ chứng cứ | $90\%$ | $72.0$ | **`WARN`** | **`PUBLISHED`** | $72.0$ |
| **G8** | Đạt chất lượng ($\text{Score} \ge 80$) | Không lỗi, không critical, đủ chứng cứ | $90\%$ | $92.5$ | **`PASS`** | **`PUBLISHED`** | $92.5$ |
| **G9** | Outlier phát hiện dị biệt | IQR Outlier advisory (`weight = 0.0`) | $90\%$ | $92.5$ | **`PASS`** | **`PUBLISHED`** | $92.5$ |
| **G10**| Mẫu số 0 ngoài scope predicate | Predicate loại toàn bộ dòng | N/A | `None` (`NOT_APPLICABLE`) | N/A (Rule level) | Loại khỏi mẫu số Coverage | N/A |
| **G11**| Mẫu số 0 do bảng trống / thiếu meta | Không có dòng quan sát / thiếu ref | N/A | `None` (`NOT_MEASURABLE`) | N/A (Rule level) | Tính vào Coverage (giảm Coverage) | N/A |
| **G12**| Gate-only bắt buộc không đo được | 1 required gate-only rule `NOT_MEASURABLE` | $90\%$ | $85.0$ | **`INSUFFICIENT_EVIDENCE`** | **`WITHHELD`** | `null` |
| **G13**| Critical rule không đo được | 1 optional critical rule `NOT_MEASURABLE` | $82\%$ | $85.0$ | **`PASS`** | **`PUBLISHED`** | $85.0$ |
| **G14**| Toàn bộ chiều ngoài scope ($D^e = \varnothing$) | Toàn bộ rule `NOT_APPLICABLE` | `null` | `null` | **`INSUFFICIENT_EVIDENCE`** | **`WITHHELD`** | `null` |
| **G15**| Quy tắc tùy chọn lỗi kỹ thuật | 1 optional rule `FAILED_TO_MEASURE` | $82\%$ | $85.0$ | **`PASS`** | **`PUBLISHED`** | $85.0$ |
| **G16**| Ngưỡng Coverage tùy biến theo Policy | Policy `publication_threshold = 0.85`, Coverage $= 82\%$ ($> 0.80$ mặc định nhưng $< 0.85$ cấu hình) | $82\%$ | $85.0$ | **`INSUFFICIENT_EVIDENCE`** | **`WITHHELD`** | `null` |
| **G17**| Chiều bắt buộc chỉ có quy tắc phụ | Chiều bắt buộc $d \in D_{req}$ chỉ có rule phụ `is_primary_scoring_rule = False` đo thành công ($R_d^m = \varnothing$) | $85\%$ | $85.0$ | **`INSUFFICIENT_EVIDENCE`** | **`WITHHELD`** | `null` |
| **G18**| Gate-only bắt buộc lỗi kỹ thuật | 1 quy tắc bắt buộc gate-only (`is_required = True`, `score_enabled = False`) bị `FAILED_TO_MEASURE` | $90\%$ | $85.0$ | **`ERROR`** | **`WITHHELD`** | `null` |
| **G19**| Critical vi phạm đồng thời thiếu độ phủ | Vi phạm critical rule (Zero-Tolerance) trong khi Coverage $= 65\% < \text{policy.threshold}$ | $65\%$ | $85.0$ | **`FAIL`** | **`WITHHELD`** | `null` |

> **Ghi chú kiến trúc:** Ma trận Golden Matrix (G1–G19) là hợp đồng đặc tả định chuẩn (Specification Contract) ràng buộc logic giữa Quality Gate Precedence 6 bậc và Publication Engine. Toàn bộ 19 kịch bản chuẩn này đã được hiện thực hóa và kiểm chứng tự động trong bộ test suite (`tests/unit/core/test_golden_matrix_g1_g9.py` và `test_golden_matrix_g10_g19.py`), đóng vai trò bài kiểm thử hồi quy đối chuẩn (Regression Benchmarking Contract) bảo đảm an toàn cho các giai đoạn mở rộng tiếp theo.

---

## 6. QUY TRÌNH DI TRÚ, TÍCH HỢP VÀ KIỂM CHỨNG TỰ ĐỘNG (MIGRATION & VERIFICATION PIPELINE)

```text
[Prototype / Candidate Code]
        │
        ▼ (Bước 1: Sàng lọc Logic Thuần túy - Clean Code & SLAP)
[Pure Function Extraction] ──► Tách logic nghiệp vụ khỏi Spark/SQL/Web/DB frameworks
        │
        ▼ (Bước 2: Viết Golden Unit Tests - First Invariant Validation)
[Golden Test Validation]   ──► Khớp 100% kết quả lý thuyết trên Golden Dataset (DQ_SCORING_THEORY)
        │
        ▼ (Bước 3: Đóng gói vào Clean Package - Ports & Adapters)
[Target Clean Package]     ──► Đặt vào đúng tầng: core/, ports/, services/, adapters/, presentation/
        │
        ▼ (Bước 4: Kiểm soát Chất lượng & Bảo mật - Static Gates)
[Static & Security Gate]   ──► ruff check, pytest, không hardcode, không lọt secret/.env, SRP <= 400 dòng
        │
        ▼ (Bước 5: Thử nghiệm Hiệu năng & Tài nguyên - Benchmark Exit Gate)
[Benchmark Exit Gate]      ──► TARGET_BENCHMARK mục tiêu thiết kế: End-to-End SLA <= 120s, RAM Spark <= 4.0GB trên k3s đơn nút 8 GB RAM (NFR-PERF-001/002)
```

### Các bước Kiểm thử Tự động Bắt buộc trong Pipeline
1. **Unit Testing:** Kiểm tra tính đơn định của các hàm tính toán điểm, null policy, và quality gate với 100% test coverage trên các hàm thuần túy.
2. **Replay Reproducibility Test:** Chạy 2 lần liên tiếp trên cùng snapshot dữ liệu; kiểm tra mã băm SHA-256 của `assessment_hash` phải trùng khớp tuyệt đối ($N=2$, diff băm $= 0$).
3. **Fault Containment Test:** Giả lập 1 quy tắc bị lỗi cú pháp regex hoặc ép kiểu sai; đảm bảo lượt chạy không bị sập và ghi nhận trạng thái `FAILED_TO_MEASURE` độc lập cho quy tắc đó.
4. **Secret Leak Detection:** Kiểm tra tĩnh không có chuỗi kết nối chứa mật khẩu, token thật hay tệp `.env` nào lọt vào git index.

---

## 7. BỘ TIÊU CHÍ KIỂM DUYỆT NGHIỆM THU TỔNG THỂ (COMPREHENSIVE ACCEPTANCE CHECKLIST)

> **Phạm vi Áp dụng Tiêu chí Nghiệm thu (Scope-Aware Checklist):** Bộ tiêu chí dưới đây áp dụng tương ứng theo phạm vi thay đổi (Change Scope). Các thay đổi đối với Domain Core thuần túy trong Phase 1 phải thỏa mãn 100% các tiêu chí về Kiến trúc thuần túy, Anti-Patching, Bất biến toán học và Golden Matrix Tests. Các tiêu chí về Spark Pushdown Single-Pass SQL, PostgreSQL RLS hay RFC 9457 API áp dụng khi hiện thực hóa các adapters và presentation layers tương ứng trong Phase 2.

Mọi thay đổi mã nguồn trước khi được merge vào nhánh chính hoặc bàn giao hoàn tất phải vượt qua 100% các tiêu chí dưới đây theo đúng phạm vi module:

### 7.1. Kiến trúc & Cấu trúc Tệp (Architecture & Modularity Gate)
- [ ] Tách bạch tuyệt đối các tầng Clean Architecture: Domain (`core`), Ports (`ports`), Services (`services`), Adapters (`adapters`), Delivery (`presentation`).
- [ ] Tầng `core/` không phụ thuộc vào bất kỳ I/O framework nào (không import Spark, SQLAlchemy, FastAPI, Requests).
- [ ] Kích thước mọi hàm tuân thủ $\le 30$ dòng; kích thước mọi tệp tin tuân thủ $\le 400$ dòng.
- [ ] Không xuất hiện các file rác tổng hợp (`utils.py`, `helpers.py`, `misc.py`).

### 7.2. Chuẩn mực Mã nguồn & Chống Patching (Clean Code & Anti-Patching Gate)
- [ ] Tuân thủ nguyên tắc YAGNI: Không sinh abstraction thừa, không tạo generic factory chưa cần dùng.
- [ ] Không có các câu lệnh `if` rẽ nhánh chắp vá để đối phó một test case cụ thể; lỗi được sửa tận gốc ở upstream.
- [ ] Không có bare except hoặc `try: ... except Exception: pass` nuốt lỗi.
- [ ] Mọi con số nghiệp vụ và ngưỡng chất lượng được nhận từ `ScoringPolicy` / `RunSpec`; không hardcode magic numbers.

### 7.3. Bảo mật & Vệ sinh Biến Môi trường (Security & Secret Hygiene Gate)
- [ ] Tệp `.env` không nằm trong Git tracking (`git check-ignore -v .env` trả về đúng rule).
- [ ] Tệp `.env.example` được cập nhật đầy đủ biến mẫu với giá trị giả định an toàn.
- [ ] Cấu hình được tải qua `Pydantic Settings` và thực hiện Fail-Fast nếu thiếu credential bắt buộc.
- [ ] Phản hồi lỗi API tuân thủ RFC 9457: Không lộ chuỗi kết nối CSDL, tên bảng hay stack trace.
- [ ] Dòng mẫu vi phạm chất lượng dữ liệu được giới hạn từ 10 đến tối đa 50 dòng (`LIMIT 50`) kèm che mờ PII 2 tầng.

### 7.4. Hiệu năng & Bất biến Toán học (Compute & Mathematical Invariants Gate)
- [ ] Profiling và Validation được đẩy xuống Apache Spark thông qua cơ chế Pushdown Single-Pass SQL; không nạp toàn phần bảng vào heap Python.
- [ ] Bảo toàn bất biến phân vùng: $\text{passed} + \text{failed} + \text{missing} + \text{miscast} + \text{not\_applicable} = \text{total\_observed}$.
- [ ] Mẫu số bằng 0 hoặc không đủ dữ liệu đo lường trả về `NOT_APPLICABLE` / `NOT_MEASURABLE`, không bao giờ ép về 0 hoặc 100.
- [ ] Tín hiệu ngoại lệ thống kê IQR được cô lập ở chế độ `ADVISORY` với trọng số bằng 0, không phạt điểm DQ Score.
- [ ] Thứ tự ưu tiên Cổng Chất lượng tuân thủ nghiêm ngặt 6 cấp bậc: `ERROR` $\succ$ Critical `FAIL` $\succ$ `INSUFFICIENT_EVIDENCE` $\succ$ `FAIL` $\succ$ `WARN` $\succ$ `PASS`.
- [ ] Đạt chuẩn Benchmark trên môi trường k3s nút đơn 8 GB RAM (TARGET_BENCHMARK mục tiêu thiết kế End-to-End SLA $\le 120$s cho 100.000 dòng dữ liệu theo NFR-PERF-001, ghi nhận kết quả đo kiểm thực nghiệm).

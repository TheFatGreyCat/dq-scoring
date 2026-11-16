# Lý thuyết bài toán và mô hình DQ Scoring

**Trạng thái:** nguồn chuẩn cho scoring semantics  
**Mục tiêu:** định nghĩa bài toán, công thức, giả định, đầu ra và giới hạn diễn giải  
**Nguyên tắc:** deterministic, explainable, evidence-aware

Tài liệu liên quan: [Chương 4: Kiến trúc hệ thống và thiết kế phần mềm](../Chapter_4.md), [Chương 5: Thiết kế dữ liệu và mô hình lớp chi tiết](../Chapter_5.md).

## 1. Bài toán

Với một snapshot dữ liệu cụ thể, hệ thống cần ước lượng mức độ dữ liệu tuân thủ các kỳ vọng chất lượng đã được phê duyệt.

Input:

```text
X  = Asset Version / source snapshot
R  = Immutable Rule Set Revision
P  = Immutable Scoring Policy Revision
B  = Optional Baseline Revision
L  = Resource and evidence limits
```

Output:

```text
Rule Results
Dimension Results
DQ Score
Quality Gate
Coverage
Confidence
Quality Signals
Bounded Evidence
```

Mô hình cần trả lời ba câu hỏi riêng biệt:

1. Dữ liệu quan sát được tốt đến đâu theo policy? — `DQ Score`.
2. Bao nhiêu phần kỳ vọng đã thực sự được đo? — `Coverage`.
3. Evidence đáng tin đến mức nào? — `Confidence`.

Không gộp ba câu hỏi thành một con số duy nhất.

## 2. DQ Score đo gì và không đo gì

DQ Score đo mức độ phù hợp với rules/policy trên snapshot được đánh giá.

DQ Score không tự chứng minh:

- Dataset có giá trị thương mại cao.
- Dữ liệu phản ánh đúng thực tế nếu không có reference data.
- Dataset phù hợp với mọi use case.
- Không có bias hoặc vấn đề đạo đức.
- Không tồn tại lỗi ngoài phạm vi rules đã chạy.
- Quan hệ nhân quả giữa lỗi và kết quả kinh doanh.

Trust/reputation, usage, transaction và user feedback phải là profile riêng; không được âm thầm trộn vào DQ Score kỹ thuật.

## 3. Sáu dimensions

| Dimension | Câu hỏi đo lường | Evidence điển hình | Điều không chứng minh |
| --- | --- | --- | --- |
| Completeness | Giá trị bắt buộc có hiện diện không? | Null, blank, conditional presence | Giá trị có đúng không |
| Accuracy | Giá trị có khớp reference/ground truth không? | Reference match, reconciliation | Không đo được nếu thiếu reference |
| Consistency | Các giá trị/ràng buộc có mâu thuẫn không? | Cross-field, referential, business invariant | Không đảm bảo đúng thực tế |
| Timeliness | Dữ liệu có đủ mới và đúng SLA không? | Freshness lag, update compliance | Không nói nội dung có đúng không |
| Uniqueness | Key/bản ghi có bị trùng không? | Key uniqueness, duplicate rate | Không đảm bảo entity resolution hoàn chỉnh |
| Validity | Giá trị có đúng kiểu, format, domain và range không? | Type, regex, domain, range | Giá trị hợp lệ vẫn có thể không chính xác |

Plausibility/range checks không được đặt tên là Accuracy. Chúng được công bố là `Accuracy Proxy` hoặc `Plausibility`.

## 4. Đơn vị đánh giá và phạm vi

Mỗi rule khai báo `evaluation_unit`:

```text
record
key
column
dataset
update_event
```

Với rule $r$, gọi:

- $U_r$: tập đơn vị có thể quan sát.
- $A_r \subseteq U_r$: tập thỏa điều kiện áp dụng rule trước khi xử lý null policy.
- $N_r = U_r \setminus A_r$: tập không áp dụng theo predicate.

Trên toàn bộ $U_r$, mỗi đơn vị phải thuộc đúng một trạng thái. Đơn vị ngoài predicate hoặc bị null policy loại khỏi denominator được ghi `NOT_APPLICABLE`; các đơn vị còn lại được phân loại thành passed, failed, missing hoặc miscast:

```text
PASSED
FAILED
MISSING
MISCAST
NOT_APPLICABLE
```

Tính loại trừ lẫn nhau là invariant:

$$
|U_r| = P_r + F_r + E_r + M_r + N_r
$$

Trong đó:

- $P_r$: passed count.
- $F_r$: failed count.
- $E_r$: missing/empty count.
- $M_r$: miscast count.
- $N_r$: not-applicable count.

## 5. Measurement status

Kết quả rule có một status độc lập với pass/fail:

```text
MEASURED
NOT_APPLICABLE
NOT_MEASURABLE
INSUFFICIENT_DATA
SKIPPED_BY_BUDGET
FAILED_TO_MEASURE
```

Ý nghĩa:

| Status | Có score? | Ảnh hưởng coverage |
| --- | --- | --- |
| `MEASURED` | Có, nếu denominator > 0 | Được tính đã đo |
| `NOT_APPLICABLE` | Không | Không làm giảm coverage nếu policy xác nhận không áp dụng |
| `NOT_MEASURABLE` | Không | Làm giảm coverage |
| `INSUFFICIENT_DATA` | Không | Làm giảm coverage |
| `SKIPPED_BY_BUDGET` | Không | Làm giảm coverage |
| `FAILED_TO_MEASURE` | Không | Làm giảm coverage và tạo operational signal |

Không dùng `0` thay cho trạng thái không đo được.

## 6. Null policy và denominator

### 6.1 `fail`

Missing là lỗi:

$$
n_r = P_r + F_r + M_r + E_r
$$

### 6.2 `ignore`

Missing bị loại khỏi scope và được báo cáo như not applicable:

$$
n_r = P_r + F_r + M_r
$$

### 6.3 `separate`

Missing được báo cáo riêng nhưng không đóng góp denominator:

$$
n_r = P_r + F_r + M_r
$$

### 6.4 `not_applicable`

Missing hoặc record ngoài predicate không đóng góp denominator:

$$
n_r = P_r + F_r + M_r
$$

Rule compiler phải phân loại `scope -> missing -> miscast -> failed -> passed` theo thứ tự cố định để tránh một record bị đếm nhiều trạng thái.

## 7. Rule Score

### 7.1 Pass-ratio rule

Nếu `measurement_status = MEASURED` và (n_r > 0):

$$
S_r = 100 \times \frac{P_r}{n_r}
$$

Trong đó $0 \le S_r \le 100$.

Nếu $n_r = 0$, không trả 100 và không được ép về điểm 0; $S_r = \text{null}$. Kết quả đo lường phải là `NOT_APPLICABLE` (nếu quy tắc không áp dụng cho tập dữ liệu, loại khỏi mẫu số Coverage) hoặc `NOT_MEASURABLE` (nếu thiếu dữ liệu/metadata tham chiếu, tính vào mẫu số Coverage làm giảm Coverage) tùy thuộc nguyên nhân nghiệp vụ.

### 7.2 Failure-ratio rule

Nếu engine trả số failure $V_r$:

$$
S_r = 100 \times \left(1 - \frac{V_r}{n_r}\right)
$$

Chỉ dùng khi mỗi evaluation unit được đếm tối đa một lần. Join làm nhân dòng phải dùng distinct evaluation key.

### 7.3 Freshness decay

Gọi $l$ là freshness lag và $s > 0$ là SLA:

$$
S_{fresh}(l,s) =
\begin{cases}
100, & l \le s \\
100\left(2 - \frac{l}{s}\right), & s < l \le 2s \\
0, & l > 2s
\end{cases}
$$

Hàm này liên tục, đơn điệu giảm và dễ giải thích. Một policy khác phải có formula revision riêng.

### 7.4 Dataset-level binary rule

Với rule có đúng một evaluation unit:

```text
pass -> 100
fail -> 0
not measured -> no score
```

Không ép mọi metric liên tục thành binary rule nếu chưa có threshold nghiệp vụ.

## 8. Rule quality status và gate

Với acceptance threshold $t_r$:

```text
S_r >= t_r -> PASS
S_r <  t_r -> FAIL
no score     -> measurement status tương ứng
```

`gate_enabled` khác `score_enabled`:

- Score-enabled rule đóng góp điểm.
- Gate-enabled rule có thể quyết định Quality Gate.
- Gate-only rule không cần đóng góp weighted score.

Một critical rule chỉ hard-fail khi measurement confidence đạt mức tối thiểu trong policy.

## 9. Trọng số rule

Trọng số hiệu dụng:

$$
w_r = w_r^{base} \times w_r^{severity} \times w_r^{criticality}
$$

Không nhân coverage hoặc confidence vào Rule Score. Làm vậy sẽ trộn chất lượng với độ đầy đủ evidence.

Quy tắc:

- Mọi factor phải dương.
- Factors được snapshot trong Scoring Policy Revision.
- Thay weight tạo policy revision mới.
- Không tự học weight trong critical path.

## 10. Conflict và double-counting

Hai rules cùng đo một hiện tượng trên cùng target có thể làm dataset bị trừ điểm hai lần.

Rules được nhóm bằng:

```text
dimension + target fields + conflict_group
```

Trong mỗi group:

- Một rule được cấu hình `primary_scoring_rule = true`.
- Rules còn lại vẫn tạo evidence nhưng không đóng góp score.
- Nếu có nhiều primary hoặc không xác định được primary, policy không hợp lệ.

Không chọn primary dựa trên rule có điểm cao/thấp hơn trong runtime; lựa chọn phải được phê duyệt trước run.

## 11. Dimension Score

Với dimension $d$, gọi $R_d^m$ là tập rules:

- `MEASURED`.
- score-enabled.
- primary trong conflict group.
- có score hợp lệ.

Dimension Score:

$$
D_d = \frac{\sum_{r \in R_d^m} w_r S_r}{\sum_{r \in R_d^m} w_r}
$$

Nếu $R_d^m = \varnothing$, $D_d$ không tồn tại và dimension không được gán 0.

### 11.1 Dimension coverage

Gọi $R_d^e$ là tập rules policy kỳ vọng đo, loại rules thực sự `NOT_APPLICABLE`:

$$
C_d = \frac{\sum_{r \in R_d^m} w_r}{\sum_{r \in R_d^e} w_r}
$$

$0 \le C_d \le 1$.

Coverage dùng configured importance, không dùng số lượng rules đơn thuần.

### 11.2 Vì sao không weight theo số records

Evaluation-weighted average:

$$
\frac{\sum P_r}{\sum n_r}
$$

có thể làm rule trên bảng lớn áp đảo rule nghiệp vụ quan trọng và đếm cùng record nhiều lần. Foundation dùng policy weights; số records chỉ là evidence metadata.

## 12. Dataset DQ Score

Gọi $\alpha_d$ là configured weight của dimension $d$, và $D^m$ là tập dimensions có score:

$$
S_{DQ} = \frac{\sum_{d \in D^m} \alpha_d D_d}{\sum_{d \in D^m} \alpha_d}
$$

Score được tái chuẩn hóa trên dimensions đã đo, nhưng coverage phải được công bố riêng để tránh tạo cảm giác chắc chắn sai.

### 12.1 Dataset coverage

Với $D^e$ là tất cả dimensions policy kỳ vọng:

$$
C_{DQ} = \frac{\sum_{d \in D^e} \alpha_d C_d}{\sum_{d \in D^e} \alpha_d}
$$

Không loại Accuracy khỏi coverage chỉ vì thiếu reference data nếu policy yêu cầu Accuracy. Khi đó Accuracy là `NOT_MEASURABLE` và coverage phản ánh khoảng trống evidence.

## 13. Confidence

Confidence không phải sample fraction.

Rule confidence $k_r$ được xác định theo measurement method:

| Measurement | Confidence |
| --- | --- |
| Deterministic full scan | 1.0 nếu source snapshot hợp lệ |
| Deterministic sample | Từ sampling design và uncertainty bound |
| Approximate aggregate | Từ error bound/sketch metadata |
| Statistical detector | Từ sample size, stability và detector assumptions |
| Không có uncertainty model | Không công bố confidence số; signal không hard-fail |

Weighted measurement confidence:

$$
K_m = \frac{\sum_{r \in R^m} w_r k_r}{\sum_{r \in R^m} w_r}
$$

Assessment confidence dùng nguyên tắc bảo thủ:

$$
K_{DQ} = \min(C_{DQ}, K_m, K_{source})
$$

Trong đó $K_{source}$ phản ánh khả năng xác nhận snapshot, schema và thời điểm đọc nguồn.

### 13.1 Quy chuẩn Confidence trong phiên bản v1.0

Trong phiên bản v1.0 chỉ thực hiện deterministic full scan trên immutable snapshot (không sampling, không suy diễn thống kê), trạng thái Confidence của Assessment luôn ghi nhận giá trị chuẩn `NOT_APPLICABLE` theo `FR-SCORE-009` và `BR-011` để bảo đảm tính trung thực kỹ thuật, không sinh số giả lập. Bất kỳ quy tắc critical nào trong v1.0 được đánh giá trực tiếp dựa trên kết quả đo lường (Zero-Tolerance hoặc Ngưỡng chấp nhận riêng) mà không bị cản trở bởi ngưỡng confidence giả định.

## 14. Quality Gate và Ma trận Trạng thái Công bố

Thứ tự quyết định tuân thủ nghiêm ngặt mô hình ưu tiên 6 cấp bậc (Quality Gate Precedence):

$$
\text{ERROR} \;\succ\; \text{Critical FAIL} \;\succ\; \text{INSUFFICIENT\_EVIDENCE} \;\succ\; \text{FAIL} \;\succ\; \text{WARN} \;\succ\; \text{PASS}
$$

### 14.1 Chi tiết 6 cấp bậc ưu tiên

1. **`ERROR`:** Có bất kỳ quy tắc bắt buộc nào (`is_required = true`, cả score-enabled lẫn gate-only) bị lỗi thực thi kỹ thuật (`measurement_status == 'FAILED_TO_MEASURE'`). Trạng thái công bố bắt buộc là `WITHHELD` (`dq_score = null`). Lưu ý: Quy tắc bắt buộc tuyệt đối không được mang tính tư vấn (`is_advisory = false`, tuân thủ bất biến loại trừ lẫn nhau `BR-025`).
2. **`Critical FAIL`:** Có ít nhất một quy tắc sống còn (`is_critical = true`, `gate_enabled = true`, không phải advisory) bị vi phạm trên tập bản ghi đo lường thành công (`MeasurementStatus.MEASURED`):
   - *Nhánh Zero-Tolerance (mặc định):* `failed > 0` hoặc `miscast > 0` hoặc penalized `missing > 0` (hoặc `violations > 0`).
   - *Nhánh Ngưỡng chấp nhận riêng:* $S_r < t_r$ (khi có cấu hình ngưỡng $t_r$).
   - *Trạng thái công bố:* `PUBLISHED` (kèm điểm số thực tế) nếu đủ chứng cứ ($C_{DQ} \ge \text{threshold}$ và không thiếu phép đo bắt buộc); `WITHHELD` (`dq_score = null`) nếu thiếu chứng cứ ($C_{DQ} < \text{threshold}$ hoặc có phép đo bắt buộc không đo được).
   - *Lưu ý:* Nếu quy tắc critical không thể đo lường được (`NOT_MEASURABLE`), nó không kích hoạt vi phạm critical Bậc 2 mà kích hoạt Bậc 3 `INSUFFICIENT_EVIDENCE` (nếu là quy tắc bắt buộc) hoặc làm giảm độ bao phủ $C_{DQ}$.
3. **`INSUFFICIENT_EVIDENCE`:** Không vi phạm critical, nhưng thiếu chứng cứ đo lường:
   - Tỷ lệ bao phủ $C_{DQ} < \text{coverage\_threshold}$ (tức $\text{publication\_threshold}$, mặc định $0.80$), HOẶC
   - Có bất kỳ quy tắc bắt buộc nào (cả score-enabled lẫn gate-only) không đo được (`NOT_MEASURABLE`, `INSUFFICIENT_DATA`, `SKIPPED_BY_BUDGET`), HOẶC
   - Thiếu toàn bộ phép đo của một chiều chất lượng bắt buộc ($R_d^m = \varnothing$), HOẶC
   - Không có chiều chất lượng nào kỳ vọng đo lường ($D^e = \varnothing$, khi đó $C_{DQ}$ không xác định / null) hoặc $S_{DQ} = \text{null}$.
   - *Trạng thái công bố:* `WITHHELD` (`dq_score = null`).
4. **`FAIL` (Score-based):** Đủ chứng cứ đo lường, không vi phạm critical, nhưng điểm chất lượng $S_{DQ} < \text{gate\_fail\_threshold}$ (tương đương $\text{warn\_min}$, mặc định $60.0$). Trạng thái công bố: `PUBLISHED`.
5. **`WARN`:** Đủ chứng cứ, không vi phạm critical, $\text{gate\_fail\_threshold} \le S_{DQ} < \text{gate\_warn\_threshold}$ (tương đương $\text{warn\_min} \le S_{DQ} < \text{pass\_min}$, mặc định $60.0 \le S_{DQ} < 80.0$). Trạng thái công bố: `PUBLISHED`.
6. **`PASS`:** Đủ chứng cứ, không vi phạm critical, $S_{DQ} \ge \text{gate\_warn\_threshold}$ (tương đương $\text{pass\_min}$, mặc định $\ge 80.0$). Trạng thái công bố: `PUBLISHED`.

### 14.2 Ma trận Quyết định Cổng Chất lượng và Trạng thái Công bố

| Cấp bậc Gate | Trạng thái Cổng | Điều kiện Phép đo / Vi phạm | $C_{DQ} \ge \tau_{pub}$ & Đủ phép đo bắt buộc | Trạng thái Công bố | Điểm lưu trữ (`dq_score`) |
| :---: | :--- | :--- | :---: | :---: | :---: |
| **1** | **`ERROR`** | Quy tắc bắt buộc lỗi kỹ thuật (`FAILED_TO_MEASURE`) | Bất kỳ | `WITHHELD` | `null` |
| **2** | **`FAIL`** | Vi phạm quy tắc Critical (Zero-Tolerance hoặc $S_r < t_r$) | Thỏa mãn (Đủ) | `PUBLISHED` | Điểm tính toán thực tế |
| **2** | **`FAIL`** | Vi phạm quy tắc Critical (Zero-Tolerance hoặc $S_r < t_r$) | Vi phạm (Thiếu) | `WITHHELD` | `null` |
| **3** | **`INSUFFICIENT_EVIDENCE`** | Không lỗi, không vi phạm critical, nhưng thiếu chứng cứ | Vi phạm (Thiếu) | `WITHHELD` | `null` |
| **4** | **`FAIL`** | Không vi phạm critical, $S_{DQ} < 60.0$ | Thỏa mãn (Đủ) | `PUBLISHED` | $S_{DQ} < 60.0$ |
| **5** | **`WARN`** | Không vi phạm critical, $60.0 \le S_{DQ} < 80.0$ | Thỏa mãn (Đủ) | `PUBLISHED` | $60.0 \le S_{DQ} < 80.0$ |
| **6** | **`PASS`** | Không vi phạm critical, $S_{DQ} \ge 80.0$ | Thỏa mãn (Đủ) | `PUBLISHED` | $S_{DQ} \ge 80.0$ |

*(Trong đó $\tau_{pub} = \text{policy.publication\_threshold}$, mặc định $0.80$)*

Nguyên tắc bất biến:
- Run thất bại do lỗi kỹ thuật toàn cục (`FAILED`) hoặc bị hủy (`CANCELLED`) không tạo Assessment hay Quality Gate.
- Outlier IQR trong v1.0 là `ADVISORY` (`is_advisory = true`, `weight = 0`), hoàn toàn không làm thay đổi DQ Score và không kích hoạt Quality Gate (không gây FAIL hay WARN). Muốn ảnh hưởng gate phải có policy revision, calibration evidence và human approval trong các pha tiếp theo.

## 15. Ví dụ đầy đủ

Policy dimension weights:

| Dimension | Weight |
| --- | ---: |
| Completeness | 0.30 |
| Validity | 0.30 |
| Uniqueness | 0.20 |
| Timeliness | 0.10 |
| Accuracy | 0.10 |

Dimension results:

| Dimension | Score | Coverage |
| --- | ---: | ---: |
| Completeness | 95.33 | 1.00 |
| Validity | 92.00 | 0.60 |
| Uniqueness | 99.50 | 1.00 |
| Timeliness | 80.00 | 1.00 |
| Accuracy | Không đo được | 0.00 |

DQ Score trên dimensions đã đo:

$$
S_{DQ} =
\frac{0.30(95.33)+0.30(92)+0.20(99.5)+0.10(80)}{0.90}
= 93.44
$$

Dataset coverage:

$$
C_{DQ} = 0.30(1)+0.30(0.6)+0.20(1)+0.10(1)+0.10(0)=0.78
$$

Nếu minimum coverage là 0.80:

```text
DQ Score: 93.44
Coverage: 0.78
Quality Gate: INSUFFICIENT_EVIDENCE
```

Ví dụ này cho thấy score cao không đồng nghĩa evidence đầy đủ.

## 16. Outlier và drift

### 16.1 Outlier

Foundation ưu tiên:

- Median/MAD.
- IQR.
- Rare-category rate.
- Cardinality change.

Outlier signal phải ghi target, sample size, threshold, detector revision, affected ratio và confidence.

### 16.2 Drift

| Data | Detector |
| --- | --- |
| Numeric distribution | PSI, KS hoặc Wasserstein |
| Categorical distribution | Jensen-Shannon hoặc Chi-square |
| Metric time series | EWMA hoặc CUSUM |

Drift đo sự thay đổi, không tự kết luận dữ liệu xấu. Baseline phải được phê duyệt và không tự cập nhật từ run có incident hoặc coverage thấp.

## 17. Rounding và numerical policy

- Tính nội bộ với precision đầy đủ.
- Chỉ round khi persist/publish theo policy.
- Công thức, rounding mode và precision có revision.
- Không so threshold trên giá trị đã format cho UI.
- Mọi output score được clamp vào `[0, 100]` sau kiểm tra numerical error.

## 18. Calibration

Thresholds và weights không phải hằng số phổ quát.

Quy trình calibration:

1. Chọn golden datasets có trạng thái được chuyên gia xác nhận.
2. Chạy candidate policy trên lịch sử.
3. Đo false pass, false fail và gate stability.
4. Phân tích sensitivity khi thay weight/threshold.
5. Review theo dataset type và business criticality.
6. Publish policy revision được phê duyệt.

Không dùng feedback chưa kiểm chứng để tự động thay scoring policy.

## 19. Invariants bắt buộc

1. Score luôn trong `[0, 100]` hoặc không tồn tại.
2. `NOT_MEASURED` không bao giờ bằng 0.
3. Denominator bằng 0 không trả 100.
4. Tăng passed count trong khi giữ denominator không làm score giảm.
5. Tăng failed/miscast/missing-as-fail không làm score tăng.
6. Một conflict group chỉ có một primary contributor.
7. Cùng snapshot, rule set, policy, baseline và formula tạo cùng result.
8. Coverage không tăng khi measurement chuyển từ measured sang failed/skipped.
9. Confidence không vượt coverage hoặc source confidence.
10. Hard gate không được kích hoạt bởi advisory AI.

## 20. Golden tests tối thiểu

- Null policy cho `fail`, `ignore`, `separate`, `not_applicable`.
- Empty, miscast và conditional scope loại trừ lẫn nhau.
- Zero denominator.
- Rule pass-ratio và freshness boundaries.
- Conflict group không double-count.
- Dimension weight normalization.
- Dataset score với missing dimensions.
- Weighted coverage.
- Confidence cap.
- Critical gate precedence.
- Outlier/drift không hard-fail mặc định.
- Determinism theo immutable input hashes.

## 21. Giới hạn và cách diễn giải

- Score phụ thuộc coverage của rules và chất lượng policy.
- Rule có thể đúng về kỹ thuật nhưng không phản ánh use case.
- Reference data sai làm Accuracy sai.
- Sample bias làm confidence bị đánh giá quá cao nếu sampling model không phù hợp.
- Drift có thể do thay đổi nghiệp vụ hợp lệ.
- So sánh score giữa hai dataset chỉ hợp lý khi policy và coverage tương đương.
- Trend qua thời gian chỉ hợp lý khi formula/policy revision được giữ hoặc được bridge có kiểm soát.

Dashboard/API luôn hiển thị cùng nhau:

```text
DQ Score
Quality Gate
Coverage
Confidence
Policy/Formula Revision
Top Gate Failures
Evidence Summary
```

# Bao cao hien trang du an DQ Scoring

**Du an:** DQ Scoring  
**Pham vi bao cao:** Trang thai thiet ke va trien khai Phase 1 Profiling Pipeline trong repository hien tai  
**Thoi diem cap nhat:** 26/06/2026, theo moi truong lam viec Asia/Saigon  
**Lan xac minh thuc thi:** 26/06/2026 01:05 UTC  
**Nguon doi chieu:** `README.md`, `docs/`, `profiling/`, `tests/`, `data/configs/`, `data/samples/`, artifact JSON/SQLite sinh tu pipeline

## 1. Tom tat dieu hanh

Du an hien dang o trang thai **MVP Phase 1 cho Profiling Pipeline da co the chay end-to-end tren dataset mau**. Pipeline doc config, nap du lieu CSV, thuc hien full scan hoac random sampling, profile schema/dataset/column, sinh candidate rule, phat hien anomaly co ban va luu ket qua vao SQLite store.

Ket qua xac minh moi nhat:

| Hang muc | Trang thai |
|---|---|
| Unit test | 5/5 passed |
| Pipeline `customer_master` | Chay thanh cong |
| Pipeline `amazon_products` | Chay thanh cong |
| Output store | Da ghi du 5 bang Phase 1 |
| Scoring chinh thuc | Chua trien khai, dung theo pham vi Phase 1 |
| Rules Engine | Chua trien khai |
| Dashboard/API | Chua trien khai |

Diem quan trong: repository hien tai **chua tinh `RuleScore`, `DimensionScore`, `DQ_Core` hay `FinalScore`**. Day la quyet dinh dung voi thiet ke: Profiling Pipeline chi tao profile result, candidate rule va anomaly flag; Rules Engine/Scoring Engine se xu ly scoring o cac buoc downstream.

## 2. Tai lieu hien co

Thu muc `docs` hien co ba tai lieu nen:

| Tai lieu | Vai tro |
|---|---|
| `DQ_Framework.md` | Dinh nghia 6 tru cot chat luong du lieu: Accuracy, Completeness, Consistency, Timeliness, Uniqueness, Validity |
| `DQ_Scoring_Model.md` | Dinh nghia cong thuc Rule Score, Dimension Score, DQ Core, Trust Score, Final Score va score history |
| `Profiling_Pipeline_Design.md` | Thiet ke chi tiet Pipeline Profiling, output schema, tich hop downstream va ke hoach Phase 1 |

Ba tai lieu nay thong nhat ve ranh gioi trach nhiem:

- Profiling Pipeline: tao thong ke, candidate rule, anomaly flag.
- Rules Engine: chay rule chinh thuc va tao Rule Evaluation Result.
- Scoring Engine: tinh diem chinh thuc.
- Dashboard/Data Catalog/API: hien thi ket qua, trend, issue breakdown.

## 3. Cau truc trien khai hien tai

### 3.1 Thanh phan source code

| File/module | Vai tro hien tai |
|---|---|
| `profiling/config.py` | Load va validate config YAML/JSON, co fallback parser YAML don gian neu thieu PyYAML |
| `profiling/loading.py` | Nap dataset; MVP ho tro CSV va Parquet |
| `profiling/sampling.py` | Ho tro `full_scan` va `random`; `stratified` moi khai bao trong config validator nhung chua implement |
| `profiling/schema_profile.py` | So sanh declared schema voi schema thuc te, bat missing/extra/type mismatch/nullable mismatch |
| `profiling/column_profile.py` | Tinh metric cap cot: null, blank, distinct, uniqueness, inferred type, numeric stats, top values, pattern, length, miscast |
| `profiling/dataset_profile.py` | Tinh metric cap dataset: row/column count, duplicate rows, freshness, expected row count, volume deviation, duration |
| `profiling/candidate_rules.py` | Sinh rule goi y cho completeness, uniqueness, regex/pattern, range, domain, freshness |
| `profiling/anomaly_detection.py` | Phat hien anomaly co ban: volume anomaly, null spike, pattern shift, type anomaly, numeric outlier |
| `profiling/store.py` | Tao va ghi SQLite store voi 5 bang output Phase 1 |
| `profiling/run.py` | CLI orchestration end-to-end va export JSON artifact |
| `profiling/models.py` | Dataclass schema noi bo cho config, profile result, candidate rule, anomaly flag |

### 3.2 Output schema da trien khai

SQLite store hien tao dung 5 bang Phase 1:

| Bang | Trang thai |
|---|---|
| `profiling_run` | Da co |
| `dataset_profile` | Da co, kem `schema_profile` encode JSON |
| `column_profile` | Da co |
| `candidate_rule` | Da co |
| `anomaly_flag` | Da co |

## 4. Config va dataset mau

Repository hien co hai config/dataset mau:

| Dataset | Config | Sample file | Muc dich |
|---|---|---|---|
| `customer_master` | `data/configs/customer_master.yaml` | `data/samples/customer_master.csv` | Dataset master data nho de test luong co ban |
| `amazon_products` | `data/configs/amazon.yaml` | `data/samples/amazon.csv` | Dataset catalog san pham lon hon de test profiling thuc te hon |

Ca hai config deu su dung:

- `execution_mode: gx_pandas`
- `sampling_method: full_scan`
- `enable_pattern_detection: true`
- `enable_candidate_rule_generation: true`
- `enable_basic_anomaly_detection: true`

Luu y: ten `gx_pandas` hien la execution mode tren config/design. Code MVP hien dung Pandas truc tiep, chua goi Great Expectations runtime.

## 5. Ket qua xac minh tu dong

Lenh da chay:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Ket qua:

| Test | Ket qua |
|---|---|
| `test_config_parser_requires_core_fields` | Passed |
| `test_loading_sampling_and_profiles` | Passed |
| `test_random_sampling_is_reproducible` | Passed |
| `test_candidate_rules_are_pending_review` | Passed |
| `test_end_to_end_writes_five_tables_and_no_scores` | Passed |

Tong ket: **5 tests passed, 0 failed**.

## 6. Ket qua chay pipeline mau

### 6.1 Dataset `customer_master`

Lenh da chay:

```powershell
.\.venv\Scripts\python.exe -m profiling.run --config data/configs/customer_master.yaml --store data/profile_store/report_customer_master.db --export-json data/profile_store/report_customer_master_profile.json
```

Ket qua summary:

| Metric | Gia tri |
|---|---:|
| `run_id` | `RUN-20260626010510-9dcabdc0` |
| `status` | `success` |
| `row_count` | 10 |
| `column_count` | 7 |
| `candidate_rule_count` | 23 |
| `anomaly_flag_count` | 1 |
| `duplicate_row_count` | 0 |
| `freshness_lag` | 40.336147 gio |
| `profile_duration_seconds` | 0.05959 |

Schema findings:

| Nhom | Chi tiet |
|---|---|
| Missing columns | Khong co |
| Extra columns | Khong co |
| Type mismatches | `age`: declared `integer`, actual Pandas `string`; `updated_at`: declared `datetime`, actual Pandas `string` |
| Nullable mismatches | `phone_number` co blank trong khi declared/mandatory khong cho phep null/blank |

Candidate rules theo dimension:

| Dimension | So luong |
|---|---:|
| Completeness | 7 |
| Uniqueness | 6 |
| Validity | 7 |
| Accuracy Proxy | 2 |
| Timeliness | 1 |

Candidate rules theo rule type:

| Rule type | So luong |
|---|---:|
| `not_null` | 7 |
| `uniqueness` | 6 |
| `regex` | 6 |
| `range` | 2 |
| `domain` | 1 |
| `freshness` | 1 |

Anomaly phat hien:

| Truong | Gia tri |
|---|---|
| `column_name` | `age` |
| `anomaly_type` | `type_anomaly` |
| `severity` | `high` |
| `current_value` | `0.1` |
| `baseline_value` | `0.01` |
| Dien giai | Ty le miscast cua `age` vuot nguong cau hinh |

### 6.2 Dataset `amazon_products`

Lenh da chay:

```powershell
.\.venv\Scripts\python.exe -m profiling.run --config data/configs/amazon.yaml --store data/profile_store/report_amazon.db --export-json data/profile_store/report_amazon_profile.json
```

Ket qua summary:

| Metric | Gia tri |
|---|---:|
| `run_id` | `RUN-20260626010510-77523f31` |
| `status` | `success` |
| `row_count` | 1,465 |
| `column_count` | 16 |
| `candidate_rule_count` | 22 |
| `anomaly_flag_count` | 1 |
| `duplicate_row_count` | 0 |
| `freshness_lag` | Khong co timestamp column |
| `profile_duration_seconds` | 3.206202 |

Schema findings:

| Nhom | Chi tiet |
|---|---|
| Missing columns | Khong co |
| Extra columns | Khong co |
| Type mismatches | `rating`: declared `numeric`, actual Pandas `string` |
| Nullable mismatches | Khong co |

Candidate rules theo dimension:

| Dimension | So luong |
|---|---:|
| Completeness | 16 |
| Validity | 3 |
| Accuracy Proxy | 1 |
| Uniqueness | 2 |

Candidate rules theo rule type:

| Rule type | So luong |
|---|---:|
| `not_null` | 16 |
| `regex` | 2 |
| `range` | 1 |
| `domain` | 1 |
| `uniqueness` | 2 |

Anomaly phat hien:

| Truong | Gia tri |
|---|---|
| `column_name` | `rating` |
| `anomaly_type` | `numeric_outlier` |
| `severity` | `medium` |
| `current_value` | `2.0..5.0` |
| `baseline_value` | `3.55..4.75` |
| Dien giai | Min/max cua `rating` nam ngoai khoang IQR expected range |

## 7. Muc do bam sat thiet ke Phase 1

| Yeu cau trong thiet ke | Trang thai hien tai | Ghi chu |
|---|---|---|
| Doc dataset tu file | Da co mot phan | Ho tro CSV/Parquet; Excel/JSON/database/datalake chua implement |
| Full scan | Da co | Dang dung cho ca hai dataset mau |
| Random sampling | Da co | Co test reproducible bang seed |
| Stratified sampling | Chua co | Validator chap nhan `stratified` nhung implementation raise `NotImplementedError` |
| Schema profiling | Da co | Missing/extra/type/nullable |
| Column profiling | Da co | Null, blank, distinct, uniqueness, stats, pattern, length, miscast |
| Dataset profiling | Da co | Row count, duplicate, freshness, volume deviation |
| Candidate rule generation | Da co | Rule o trang thai `pending_review` |
| Basic anomaly detection | Da co | Type, outlier, null spike/pattern shift neu co baseline, volume anomaly neu co expected row count |
| Profile store | Da co | SQLite MVP |
| Export JSON artifact | Da co | CLI ho tro `--export-json` |
| Official scoring | Chua co | Dung theo ranh gioi Phase 1 |
| Dashboard/API | Chua co | Chua nam trong source hien tai |

## 8. Khoang trong va han che hien tai

1. **Great Expectations chua duoc tich hop thuc thi**  
   `requirements.txt` co `great_expectations`, config co `execution_mode: gx_pandas`, nhung code profiling hien dung Pandas truc tiep. Neu muc tieu demo can GX Data Docs/Expectation Suite, can them integration layer.

2. **Loader moi o muc MVP**  
   Ho tro CSV/Parquet. Cac source type da validate nhu `excel`, `json`, `database`, `datalake` chua co adapter.

3. **Kieu du lieu CSV bi doc thanh string**  
   Vi `pd.read_csv(..., keep_default_na=False)` giu blank string va khong parse datetime, schema profile co the bao type mismatch cho cot numeric/datetime du co the ep kieu duoc o column profiling. Day la han che can quyet dinh: parse theo schema khi load, hay chap nhan mismatch nhu signal profiling.

4. **Candidate rule chua co workflow phe duyet**  
   Tat ca candidate rule dung `pending_review`. Chua co bang/config chuyen candidate thanh official rule.

5. **Baseline/anomaly con don gian**  
   Baseline lay tu lan profiling gan nhat trong SQLite. Chua co baseline window thuc su theo `baseline_window`, chua co drift detection nang cao.

6. **Scoring Engine chua co**  
   Chua co model/DB schema cho `score_run`, `rule_score_history`, `dimension_score_history`, `dataset_score_history`.

7. **Dashboard/API chua co**  
   Chua co UI hoac endpoint de xem profile, candidate rule, anomaly flag, score history.

8. **Test coverage moi tap trung happy path va mot so invariant quan trong**  
   Chua co test cho loader Parquet, unsupported source, stratified fallback, baseline anomaly qua nhieu run, SQLite schema migration, va cac edge case dataset rong.

## 9. Rui ro ky thuat

| Rui ro | Muc do | Anh huong | Huong xu ly de xuat |
|---|---|---|---|
| Khac biet giua declared schema va Pandas inferred type | Trung binh | Co the tao mismatch gay nhieu false positive | Them typed loading/casting theo declared schema hoac tach `raw_type` va `coerced_type` |
| Candidate rule qua nhieu voi dataset rong hoac cot high-cardinality | Trung binh | Data Steward kho review | Them ranking, confidence threshold, rule grouping |
| Output SQLite chua co migration/versioning | Trung binh | Kho nang cap schema sau nay | Them schema version va migration strategy |
| Chua co Rules Engine | Cao neu can scoring | Khong tinh duoc DQ score chinh thuc | Uu tien thiet ke official rule config va evaluation result |
| Chua co dashboard/API | Trung binh | Kho demo voi nguoi dung nghiep vu | Them API/Streamlit dashboard doc profile store |

## 10. De xuat uu tien tiep theo

### Uu tien ngan han

1. Chot ranh gioi loader: co nen cast du lieu theo `declared_schema` trong `load_dataset` hay giu raw string va chi profile coercion.
2. Bo sung test cho `amazon_products` de tranh regression tren dataset lon hon `customer_master`.
3. Implement hoac chan som `stratified` trong config neu chua lam, de validator khong chap nhan mode chua ho tro.
4. Them summary command/doc cho viec doc SQLite store va JSON artifact.
5. Them CI command chay `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` hoac command portable tu README.

### Uu tien trung han

1. Xay Rules Engine MVP: official rule config, null policy, scope, evaluation status.
2. Xay Scoring Engine MVP theo `DQ_Scoring_Model.md`: RuleScore, DimensionScore, DQ Core, TrustScore Phase 1, FinalScore.
3. Them score history tables va lien ket `profiling_run_id`.
4. Them dashboard/API doc profile, candidate rule, anomaly va score breakdown.
5. Neu van giu chien luoc GX-first, them Great Expectations adapter de sinh expectation/validation result chuan hoa.

## 11. Ket luan

Tinh den thoi diem bao cao, du an da co nen tang Phase 1 kha gon va dung huong: pipeline profiling da chay duoc end-to-end, output duoc chuan hoa, co test bao ve ranh gioi quan trong la **khong tinh diem chinh thuc trong profiling**.

De tien toi demo DQ Scoring hoan chinh, cong viec quan trong nhat tiep theo la bo sung Rules Engine va Scoring Engine. Khi hai phan nay co mat, cac output hien tai cua Profiling Pipeline se tro thanh dau vao truc tiep cho Rule Evaluation Result, score history va dashboard.

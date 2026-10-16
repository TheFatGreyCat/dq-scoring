"""Apache Spark compute engine adapter for single-pass vectorized pushdown."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from dq_scoring.adapters.compute.spark_settings import SparkSettings
from dq_scoring.adapters.compute.sql_rule_compiler import (
    CompiledRule,
    compile_rule,
    quoted_col,
)
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import S3Settings, get_s3_settings
from dq_scoring.adapters.storage.snapshot_objects import (
    SnapshotObjectError,
    pinned_ref,
    verify_object,
)
from dq_scoring.common.protected_transport import is_protected_processing_enabled
from dq_scoring.core.entities import (
    CanonicalMetric,
    DatasetSnapshot,
    OutlierExecutionOutput,
    QualityRule,
    RuleExecutionOutput,
)
from dq_scoring.core.exceptions import RunAbortedError
from dq_scoring.core.models import MeasurementStatus, RuleCounts
from dq_scoring.ports.compute_engine import IComputeEnginePort
from dq_scoring.ports.object_store import IObjectStorePort, ObjectRef

MIN_OUTLIER_SAMPLE = 4
"""Minimum parseable values needed for meaningful IQR quartiles."""


def _ensure_jdk_configured() -> None:
    """Auto-configure JAVA_HOME for local Spark execution if vendored JDK exists."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    local_jdk = project_root / ".tools" / "jdk-21"
    if (local_jdk / "bin" / ("java.exe" if os.name == "nt" else "java")).is_file() and "JAVA_HOME" not in os.environ:
        os.environ["JAVA_HOME"] = str(local_jdk)
        path_env = os.environ.get("PATH", "")
        bin_dir = str(local_jdk / "bin")
        if bin_dir not in path_env:
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{path_env}"


class PySparkComputeAdapter(IComputeEnginePort):
    """Production PySpark compute adapter executing single-pass SQL aggregations."""

    def __init__(
        self,
        spark: SparkSession | None = None,
        s3_settings: S3Settings | None = None,
        store: IObjectStorePort | None = None,
    ) -> None:
        _ensure_jdk_configured()
        self._s3_settings = s3_settings or get_s3_settings()
        self._store = store or S3ObjectStoreAdapter(settings=self._s3_settings)
        self._verified_snapshots: dict[UUID, tuple[ObjectRef, ObjectRef]] = {}

        if spark is not None:
            self._spark = spark
        else:
            settings = SparkSettings()
            self.settings = settings
            builder = SparkSession.builder.appName("dq-scoring-runner").master(settings.master)
            for key, value in settings.to_spark_conf().items():
                builder = builder.config(key, value)

            connector_baked = (Path(os.environ.get("SPARK_HOME", "/opt/spark")) / "jars" / "hadoop-aws-3.5.0.jar").is_file()
            if is_protected_processing_enabled():
                if not connector_baked:
                    raise ValueError(
                        "PROTECTED_COMPUTE_CONFIGURATION_REQUIRED: hadoop-aws connector must be baked into image; runtime package download is forbidden"
                    )
                packages_conf = ""
            else:
                packages_conf = "" if connector_baked else "org.apache.hadoop:hadoop-aws:3.5.0"
            if self._s3_settings.ca_bundle:
                os.environ["AWS_CA_BUNDLE"] = self._s3_settings.ca_bundle
            builder = (
                builder.config("spark.jars.packages", packages_conf)
                .config("spark.hadoop.fs.s3a.endpoint", self._s3_settings.endpoint_url)
                .config("spark.hadoop.fs.s3a.endpoint.region", self._s3_settings.region)
                .config("spark.hadoop.fs.s3a.path.style.access", "true")
                .config(
                    "spark.hadoop.fs.s3a.connection.ssl.enabled",
                    "true" if self._s3_settings.use_ssl or self._s3_settings.endpoint_url.startswith("https") else "false",
                )
                .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
                .config(
                    "spark.hadoop.fs.s3a.aws.credentials.provider",
                    "software.amazon.awssdk.auth.credentials.EnvironmentVariableCredentialsProvider",
                )
                .config("spark.hadoop.fs.s3a.change.detection.source", "versionid")
                .config("spark.hadoop.fs.s3a.change.detection.mode", "server")
                .config("spark.hadoop.fs.s3a.change.detection.version.required", "true")
                .config("spark.redaction.regex", "(?i)secret|password|token|access[._]?key|authorization")
            )

            os.environ["AWS_ACCESS_KEY_ID"] = self._s3_settings.access_key_id.get_secret_value()
            os.environ["AWS_SECRET_ACCESS_KEY"] = self._s3_settings.secret_access_key.get_secret_value()

            self._spark = builder.getOrCreate()

    @property
    def spark(self) -> SparkSession:
        """Return underlying SparkSession."""
        return self._spark

    def _object_ref(self, snapshot: DatasetSnapshot, descriptor: dict[str, Any]) -> ObjectRef:
        try:
            return pinned_ref(snapshot.tenant_id, descriptor, self._s3_settings.bucket_snapshots)
        except SnapshotObjectError as exc:
            raise RunAbortedError(str(exc)) from exc

    def _verify_object(self, ref: ObjectRef, descriptor: dict[str, Any], full: bool) -> None:
        try:
            verify_object(self._store, ref, descriptor, full)
        except SnapshotObjectError as exc:
            raise RunAbortedError(str(exc)) from exc

    def verify_snapshot(self, snapshot: DatasetSnapshot) -> None:
        if snapshot.source_kind != "OBJECT_FILE":
            raise RunAbortedError("LEGACY_SOURCE_UNSUPPORTED: Import this snapshot into object storage.")
        raw = snapshot.source_descriptor
        canonical = raw.get("canonical")
        if not isinstance(canonical, dict) or canonical.get("format") != "PARQUET":
            raise RunAbortedError("MALFORMED_IMPORT: Canonical Parquet descriptor is missing.")
        refs = (self._object_ref(snapshot, raw), self._object_ref(snapshot, canonical))
        full = self._verified_snapshots.get(snapshot.snapshot_id) != refs
        self._verify_object(refs[0], raw, full)
        self._verify_object(refs[1], canonical, full)
        self._verified_snapshots[snapshot.snapshot_id] = refs

    def release_snapshot(self, snapshot: DatasetSnapshot) -> None:
        self._verified_snapshots.pop(snapshot.snapshot_id, None)

    def _load_df(self, snapshot: DatasetSnapshot) -> DataFrame:
        self.verify_snapshot(snapshot)
        canonical = snapshot.source_descriptor["canonical"]
        uri = f"s3a://{canonical['bucket']}/{quote(canonical['key'], safe='/')}"
        return self._spark.read.parquet(uri)

    def profile_snapshot(
        self, snapshot: DatasetSnapshot, columns: list[str]
    ) -> list[CanonicalMetric]:
        """Compute single-pass canonical profiling metrics for columns."""
        if snapshot.total_rows == 0:
            return [
                CanonicalMetric(metric_name="row_count", column_name=c, metric_value=0)
                for c in columns
            ]
        df = self._load_df(snapshot)
        metrics: list[CanonicalMetric] = []
        for col in columns:
            if col not in df.columns:
                continue
            agg_row = df.select(
                F.count(F.lit(1)).alias("row_count"),
                F.count(F.when(F.col(col).isNull() | (F.trim(F.col(col)) == ""), 1)).alias("null_count"),
                F.approx_count_distinct(F.col(col)).alias("distinct_count"),
            ).collect()[0]
            metrics.extend([
                CanonicalMetric(metric_name="row_count", column_name=col, metric_value=agg_row["row_count"]),
                CanonicalMetric(metric_name="null_count", column_name=col, metric_value=agg_row["null_count"]),
                CanonicalMetric(metric_name="distinct_count", column_name=col, metric_value=agg_row["distinct_count"]),
            ])
        return metrics


    def execute_rules(
        self,
        snapshot: DatasetSnapshot,
        rules: list[QualityRule],
        sample_limit: int = 50,
    ) -> list[RuleExecutionOutput]:
        """Execute quality rules in a vectorized single-pass pushdown."""
        if snapshot.total_rows == 0:
            return [
                RuleExecutionOutput(
                    rule_id=r.rule_id,
                    counts=RuleCounts(),
                    status=MeasurementStatus.NOT_MEASURABLE,
                )
                for r in rules
            ]

        # Load DataFrame from dataset snapshot (infrastructure errors propagate to fail run)
        df = self._load_df(snapshot)
        available_cols = set(df.columns)
        structured_columns = {column["name"] for column in snapshot.schema_definition.get("columns", []) if isinstance(column, dict) and column.get("structural_encoding") == "JSON"}

        compiled_map: dict[UUID, CompiledRule] = {}
        failed_outputs: dict[UUID, RuleExecutionOutput] = {}
        for r in rules:
            try:
                compiled = compile_rule(r)
            except Exception as exc:  # noqa: BLE001 - rule fault containment
                failed_outputs[r.rule_id] = self._failed_output(r.rule_id, str(exc))
                continue
            missing_cols = [c for c in compiled.referenced_columns if c not in available_cols]
            if missing_cols:
                failed_outputs[r.rule_id] = self._failed_output(
                    r.rule_id, f"Target column '{missing_cols[0]}' not found in dataset"
                )
                continue
            kind = r.rule_type.upper()
            if (kind in ("JSON_FIELD", "JSON_ARRAY") and compiled.target_column not in structured_columns) or (
                kind in ("TYPE_PARSE", "DOMAIN_RANGE", "CROSS_FIELD", "TEXT_QUALITY", "SPELLING") and any(column in structured_columns for column in compiled.referenced_columns)
            ):
                failed_outputs[r.rule_id] = self._failed_output(r.rule_id, "STRUCTURED_COLUMN_REQUIRES_JSON_RULE")
                continue
            if kind == "JSON_FIELD" and r.parameters.get("check") == "REGEX":
                try:
                    df.sparkSession.range(1).select(F.lit("synthetic").rlike(r.parameters["pattern"])).collect()
                except Exception:  # noqa: BLE001 - rule-local Java regex syntax containment
                    failed_outputs[r.rule_id] = self._failed_output(r.rule_id, "REGEX_INVALID")
                    continue
            compiled_map[r.rule_id] = compiled

        if not compiled_map:
            return [
                failed_outputs.get(
                    r.rule_id,
                    RuleExecutionOutput(
                        rule_id=r.rule_id,
                        counts=RuleCounts(),
                        status=MeasurementStatus.FAILED_TO_MEASURE,
                    ),
                )
                for r in rules
            ]

        eval_df = df
        for cr in compiled_map.values():
            if cr.is_uniqueness and cr.uniqueness_column:
                w = Window.partitionBy(quoted_col(cr.uniqueness_column)).orderBy(F.lit(1))
                col_name = f"_rn_{cr.rule_id.hex}"
                eval_df = eval_df.withColumn(col_name, F.row_number().over(w))

        agg_exprs: list[Any] = []
        for cr in compiled_map.values():
            pfx = f"r_{cr.rule_id.hex}"
            is_missing = cr.missing_expr
            is_miscast = cr.miscast_expr
            if cr.is_uniqueness:
                rn_col = f"_rn_{cr.rule_id.hex}"
                is_failed = (~is_missing) & (F.col(rn_col) > 1)
            else:
                is_failed = cr.failed_expr

            is_na = cr.scope_expr if cr.scope_expr is not None else F.lit(False)
            is_passed = (~is_na) & (~is_missing) & (~is_miscast) & (~is_failed)

            agg_exprs.extend([
                F.sum(F.when(is_na, 1).otherwise(0)).alias(f"{pfx}_na"),
                F.sum(F.when((~is_na) & is_missing, 1).otherwise(0)).alias(f"{pfx}_missing"),
                F.sum(F.when((~is_na) & (~is_missing) & is_miscast, 1).otherwise(0)).alias(f"{pfx}_miscast"),
                F.sum(F.when((~is_na) & (~is_missing) & (~is_miscast) & is_failed, 1).otherwise(0)).alias(f"{pfx}_failed"),
                F.sum(F.when(is_passed, 1).otherwise(0)).alias(f"{pfx}_passed"),
            ])

        # Pushdown multi-rule aggregation query in single pass
        agg_row = eval_df.select(*agg_exprs).collect()[0]

        results: list[RuleExecutionOutput] = []
        for r in rules:
            if r.rule_id in failed_outputs:
                results.append(failed_outputs[r.rule_id])
                continue

            cr = compiled_map[r.rule_id]
            pfx = f"r_{cr.rule_id.hex}"
            na_cnt = int(agg_row[f"{pfx}_na"] or 0)
            missing_cnt = int(agg_row[f"{pfx}_missing"] or 0)
            miscast_cnt = int(agg_row[f"{pfx}_miscast"] or 0)
            failed_cnt = int(agg_row[f"{pfx}_failed"] or 0)
            passed_cnt = int(agg_row[f"{pfx}_passed"] or 0)
            total_obs = passed_cnt + failed_cnt + missing_cnt + miscast_cnt + na_cnt

            counts = RuleCounts(
                passed=passed_cnt,
                failed=failed_cnt,
                missing=missing_cnt,
                miscast=miscast_cnt,
                not_applicable=na_cnt,
                total_observed=total_obs,
            )

            status = MeasurementStatus.MEASURED
            if total_obs == 0:
                status = (
                    MeasurementStatus.NOT_MEASURABLE
                    if snapshot.total_rows == 0
                    else MeasurementStatus.NOT_APPLICABLE
                )

            evidence_samples: list[dict[str, Any]] = []
            if (failed_cnt > 0 or miscast_cnt > 0) and sample_limit > 0:
                try:
                    if cr.is_uniqueness:
                        rn_col = f"_rn_{cr.rule_id.hex}"
                        cond = (~cr.missing_expr) & (F.col(rn_col) > 1)
                    else:
                        cond = cr.miscast_expr | cr.failed_expr
                    # Data minimisation: evidence carries only the columns this rule reads.
                    masked_exprs = [
                        F.when(quoted_col(c).isNull(), F.lit(None))
                        .when(F.trim(quoted_col(c).cast("string")) == "", F.lit(""))
                        .otherwise(F.lit("[REDACTED]"))
                        .alias(c)
                        for c in cr.referenced_columns
                    ]
                    raw_samples = (
                        eval_df.filter(cond)
                        .select(*masked_exprs)
                        .limit(sample_limit)
                        .collect()
                    )
                    evidence_samples = [row.asDict() for row in raw_samples]
                except Exception:  # noqa: BLE001
                    evidence_samples = []

            results.append(
                RuleExecutionOutput(
                    rule_id=r.rule_id,
                    counts=counts,
                    status=status,
                    evidence_samples=evidence_samples,
                )
            )

        return results

    @staticmethod
    def _failed_output(rule_id: UUID, message: str) -> RuleExecutionOutput:
        return RuleExecutionOutput(
            rule_id=rule_id,
            counts=RuleCounts(),
            status=MeasurementStatus.FAILED_TO_MEASURE,
            error_message=message,
        )

    def detect_outliers(
        self,
        snapshot: DatasetSnapshot,
        column: str,
        k: float = 1.5,
        sample_limit: int = 50,
    ) -> OutlierExecutionOutput:
        """Detect numeric outliers using single-pass IQR calculation."""
        if snapshot.total_rows == 0:
            return OutlierExecutionOutput(
                column_name=column, total_evaluated=0, iqr=0.0, outlier_count=0
            )

        df = self._load_df(snapshot)
        if column not in df.columns:
            return OutlierExecutionOutput(
                column_name=column, total_evaluated=0, iqr=0.0, outlier_count=0
            )

        num_col = quoted_col(column).try_cast("double")
        valid_df = df.filter(num_col.isNotNull())
        valid_count = valid_df.count()

        if valid_count < MIN_OUTLIER_SAMPLE:
            return OutlierExecutionOutput(
                column_name=column,
                total_evaluated=valid_count,
                iqr=0.0,
                outlier_count=0,
            )

        q_row = valid_df.select(
            F.percentile_approx(num_col, [0.25, 0.75]).alias("q")
        ).collect()[0]
        q1, q3 = float(q_row["q"][0]), float(q_row["q"][1])
        iqr = q3 - q1
        lower_bound = q1 - k * iqr
        upper_bound = q3 + k * iqr

        outlier_cond = (num_col < lower_bound) | (num_col > upper_bound)
        outlier_count = valid_df.filter(outlier_cond).count()

        samples: list[dict[str, Any]] = []
        if outlier_count > 0 and sample_limit > 0:
            masked_col = (
                F.when(quoted_col(column).isNull(), F.lit(None))
                .when(F.trim(quoted_col(column).cast("string")) == "", F.lit(""))
                .otherwise(F.lit("[REDACTED]"))
                .alias(column)
            )
            raw_samples = valid_df.filter(outlier_cond).select(masked_col).limit(sample_limit).collect()
            samples = [row.asDict() for row in raw_samples]

        return OutlierExecutionOutput(
            column_name=column,
            total_evaluated=valid_count,
            iqr=float(iqr),
            outlier_count=outlier_count,
            outlier_samples=samples,
        )


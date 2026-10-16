"""Tabular dataset import adapter for CSV, Parquet, and JSONL inspection and canonical normalization."""

from __future__ import annotations

import csv
import decimal
import hashlib
import io
import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from dq_scoring.common.privacy import (
    PrivacyScanLimitExceededException,
    PrivacyScanner,
)
from dq_scoring.common.privacy_rules import PrivacyDetectorRule
from dq_scoring.common.redaction_utils import redact_sample_row
from dq_scoring.common.structured_values import (
    StructuredParsingError,
    canonical_compact_json,
    classify_value_kind,
    parse_structured_json,
)
from dq_scoring.ports.object_store import IObjectStorePort, ObjectRef

BINARY_MAGICS = (
    (b"%PDF", "PDF files are not supported"),
    (b"PK\x03\x04", "ZIP archives are not supported"),
    (b"\x89PNG", "PNG images are not supported"),
    (b"\xff\xd8\xff", "JPEG images are not supported"),
    (b"GIF8", "GIF images are not supported"),
)

IDENTIFIER_TOKENS = frozenset({"id", "account", "iban", "routing", "code", "ssn", "card", "pan"})
FINANCIAL_TOKENS = frozenset({"account", "iban", "routing", "ssn", "card", "pan", "bank", "credit"})
INTEGER_REGEX = re.compile(r"^(0|-?[1-9]\d*)$")
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_FORMAT_MAPPINGS = (
    ("%Y/%m/%d %H:%M", "yyyy/MM/dd HH:mm"),
    ("%Y-%m-%d %H:%M:%S", "yyyy-MM-dd HH:mm:ss"),
    ("%Y-%m-%dT%H:%M:%S", "yyyy-MM-dd'T'HH:mm:ss"),
    ("%Y-%m-%dT%H:%M:%SZ", "yyyy-MM-dd'T'HH:mm:ss'Z'"),
    ("%Y-%m-%dT%H:%M:%S.%fZ", "yyyy-MM-dd'T'HH:mm:ss.SSSSSS'Z'"),
)

class ImportInspectionException(Exception):
    """Raised when an uploaded dataset fails validation or structural invariants."""

    def __init__(
        self,
        error_code: str,
        detail: str,
        invalid_params: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.invalid_params = invalid_params


@dataclass(frozen=True)
class ImportInspection:
    """Outcome of dataset inspection and canonical Parquet normalization."""

    raw_ref: ObjectRef
    canonical_ref: ObjectRef
    raw_sha256: str
    canonical_sha256: str
    raw_size_bytes: int
    canonical_size_bytes: int
    exact_row_count: int
    columns: list[dict[str, Any]]
    preview_rows: list[dict[str, Any]]
    profile: dict[str, Any]
    warnings: list[str]
    normalization_version: int = 1
    sensitive_scan: dict[str, Any] = field(default_factory=lambda: {"status": "UNAVAILABLE"})

class TabularImportAdapter:
    """Inspects raw uploads, enforces format bounds, generates redacted preview/profile, and builds canonical Parquet."""

    def __init__(self, store: IObjectStorePort, temp_root: Path | str = ".tmp/imports") -> None:
        self._store = store
        self._temp_root = Path(temp_root)

    def inspect_and_normalize(
        self,
        *,
        source: ObjectRef,
        destination_bucket: str,
        destination_prefix: str,
        file_format: str,
        column_names_mapping: list[str] | None = None,
        delimiter: str = ",",
        privacy_columns: tuple[str, ...] = (),
        privacy_rules: Sequence[PrivacyDetectorRule] | None = None,
    ) -> ImportInspection:
        job_dir = self._temp_root / f"job-{uuid4()}"
        job_dir.mkdir(parents=True, exist_ok=True)
        raw_spool_path = job_dir / "raw_spool"
        canonical_spool_path = job_dir / "canonical.parquet"

        try:
            # 1. Preflight check: head source and check size
            source_meta_before = self._store.head(source)
            if source_meta_before.size_bytes == 0:
                raise ImportInspectionException("EMPTY_DATASET", "Uploaded file is 0 bytes.")

            # 2. Check scratch storage free space >= 2 * size + 256 MiB
            free_bytes = shutil.disk_usage(self._temp_root).free
            if free_bytes < (2 * source_meta_before.size_bytes + 256 * 1024 * 1024):
                raise ImportInspectionException("IMPORT_STORAGE_FULL", "Insufficient scratch space for dataset ingestion")

            # 3. Freeze source to destination attempt prefix
            ext = file_format.lower()
            raw_key = f"{destination_prefix.rstrip('/')}/source.{ext}"
            raw_meta = self._store.copy_object(
                source=source,
                bucket=destination_bucket,
                key=raw_key,
                source_etag=source_meta_before.etag,
            )
            frozen_raw_ref = ObjectRef(
                bucket=destination_bucket,
                key=raw_key,
                version_id=raw_meta.version_id,
            )

            # 4. Spool raw bytes to scratch file and compute raw SHA-256
            raw_sha256, raw_size = self._spool_and_hash(frozen_raw_ref, raw_spool_path)

            # 5. Compare source metadata before / after
            source_meta_after = self._store.head(source)
            if (
                source_meta_after.etag != source_meta_before.etag
                or source_meta_after.size_bytes != source_meta_before.size_bytes
                or (source_meta_before.version_id and source_meta_after.version_id != source_meta_before.version_id)
            ):
                raise ImportInspectionException("OBJECT_CHANGED", "Source storage object was modified concurrently during ingestion")

            # 6. Check binary magic
            self._check_binary_magic(raw_spool_path, file_format)

            fmt = file_format.upper()
            if fmt == "CSV":
                inspection = self._process_csv(
                    raw_spool_path,
                    canonical_spool_path,
                    delimiter=delimiter,
                    column_names_mapping=column_names_mapping,
                    privacy_columns=privacy_columns,
                    privacy_rules=privacy_rules,
                )
            elif fmt == "JSONL":
                inspection = self._process_jsonl(
                    raw_spool_path,
                    canonical_spool_path,
                    column_names_mapping=column_names_mapping,
                    privacy_columns=privacy_columns,
                    privacy_rules=privacy_rules,
                )
            elif fmt == "PARQUET":
                inspection = self._process_parquet(
                    raw_spool_path,
                    canonical_spool_path,
                    column_names_mapping=column_names_mapping,
                    privacy_columns=privacy_columns,
                    privacy_rules=privacy_rules,
                )
            else:
                raise ImportInspectionException("UNSUPPORTED_FORMAT", f"Unsupported format: {file_format}")
            # 3. Hash canonical Parquet and upload to destination prefix
            canonical_sha256, canonical_size = self._hash_file(canonical_spool_path)
            canonical_key = f"{destination_prefix.rstrip('/')}/canonical.parquet"
            with canonical_spool_path.open("rb") as f:
                mp_id = self._store.create_multipart(destination_bucket, canonical_key)
                part_size = 16 * 1024 * 1024
                part_num = 1
                parts = []
                while True:
                    chunk = f.read(part_size)
                    if not chunk:
                        break
                    stream = io.BytesIO(chunk)
                    etag = self._store.upload_part(
                        destination_bucket, canonical_key, mp_id, part_num, stream, len(chunk)
                    )
                    from dq_scoring.ports.object_store import UploadedPart
                    parts.append(UploadedPart(part_number=part_num, etag=etag, size_bytes=len(chunk)))
                    part_num += 1

                canonical_meta = self._store.complete_multipart(destination_bucket, canonical_key, mp_id, parts)

            canonical_ref = ObjectRef(
                bucket=destination_bucket,
                key=canonical_key,
                version_id=canonical_meta.version_id,
            )

            return ImportInspection(
                raw_ref=frozen_raw_ref,
                canonical_ref=canonical_ref,
                raw_sha256=raw_sha256,
                canonical_sha256=canonical_sha256,
                raw_size_bytes=raw_size,
                canonical_size_bytes=canonical_size,
                exact_row_count=inspection["exact_row_count"],
                columns=inspection["columns"],
                preview_rows=inspection["preview_rows"],
                profile=inspection["profile"],
                warnings=inspection["warnings"],
                normalization_version=inspection.get("normalization_version", 1),
                sensitive_scan=inspection.get("sensitive_scan", {"status": "UNAVAILABLE"}),
            )

        finally:
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)

    def _spool_and_hash(self, source: ObjectRef, dest_path: Path) -> tuple[str, int]:
        hasher = hashlib.sha256()
        total_bytes = 0
        stream = self._store.open_stream(source)
        try:
            with dest_path.open("wb") as out:
                while True:
                    chunk = stream.read(1024 * 1024)  # 1 MiB chunks
                    if not chunk:
                        break
                    if shutil.disk_usage(self._temp_root).free < 256 * 1024 * 1024:
                        raise ImportInspectionException("IMPORT_STORAGE_FULL", "Scratch storage reserve limit (256 MiB) reached")
                    hasher.update(chunk)
                    out.write(chunk)
                    total_bytes += len(chunk)
        finally:
            if hasattr(stream, "close"):
                stream.close()
        return hasher.hexdigest(), total_bytes

    def _check_binary_magic(self, path: Path, file_format: str) -> None:
        with path.open("rb") as f:
            header = f.read(16)
        for magic, reason in BINARY_MAGICS:
            if header.startswith(magic):
                raise ImportInspectionException("UNSUPPORTED_FORMAT", reason)
        if file_format.upper() in ("CSV", "JSONL") and header.startswith(b"PAR1"):
            raise ImportInspectionException("UNSUPPORTED_FORMAT", "Parquet binary magic detected in text upload")

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        hasher = hashlib.sha256()
        total_bytes = 0
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
                total_bytes += len(chunk)
        return hasher.hexdigest(), total_bytes

    # -----------------------------------------------------------------------
    # CSV Processing
    # -----------------------------------------------------------------------

    def _process_csv(
        self,
        raw_path: Path,
        canonical_path: Path,
        delimiter: str,
        column_names_mapping: list[str] | None,
        privacy_columns: tuple[str, ...] = (),
        privacy_rules: Sequence[PrivacyDetectorRule] | None = None,
    ) -> dict[str, Any]:
        # Set 8 MiB field size limit
        csv.field_size_limit(8 * 1024 * 1024)
        try:
            f = raw_path.open("r", encoding="utf-8-sig", newline="")
        except UnicodeDecodeError as exc:
            raise ImportInspectionException("MALFORMED_CSV", f"Invalid UTF-8 encoding: {exc}") from exc

        with f:
            reader = csv.reader(f, delimiter=delimiter, strict=True)
            try:
                header = next(reader, None)
            except (csv.Error, UnicodeDecodeError) as exc:
                raise ImportInspectionException("MALFORMED_CSV", f"CSV parsing error: {exc}") from exc

            if not header or all(not h.strip() for h in header):
                raise ImportInspectionException("EMPTY_DATASET", "CSV has no valid header row")

            raw_col_names = [h.strip() for h in header]
            if len(raw_col_names) > 1000:
                raise ImportInspectionException("TOO_MANY_COLUMNS", f"CSV contains {len(raw_col_names)} columns; max 1000 allowed")

            # Validate duplicate and empty column headers
            empty_positions = [i for i, col in enumerate(raw_col_names) if not col]
            if empty_positions and not column_names_mapping:
                raise ImportInspectionException(
                    "EMPTY_COLUMN_NAME",
                    f"Empty column names detected at index(es): {empty_positions}",
                    invalid_params=[{"name": f"col_{p}", "code": "EMPTY_COLUMN_NAME", "index": p} for p in empty_positions],
                )

            duplicates = {}
            for i, col in enumerate(raw_col_names):
                duplicates.setdefault(col, []).append(i)
            dup_cols = {k: v for k, v in duplicates.items() if len(v) > 1}
            if dup_cols and not column_names_mapping:
                raise ImportInspectionException(
                    "DUPLICATE_COLUMN_NAME",
                    f"Duplicate column names detected: {list(dup_cols.keys())}",
                    invalid_params=[{"name": k, "code": "DUPLICATE_COLUMN_NAME", "indices": v} for k, v in dup_cols.items()],
                )

            final_names = column_names_mapping if column_names_mapping else raw_col_names
            if len(final_names) != len(raw_col_names):
                raise ImportInspectionException("INVALID_COLUMN_MAPPING", "Mapped column count does not match original schema")

            columns = [
                {
                    "index": i,
                    "original_name": raw_col_names[i],
                    "name": final_names[i],
                    "type": "STRING",
                    "nullable": True,
                }
                for i in range(len(final_names))
            ]

            warnings: list[str] = []
            if len(final_names) == 1:
                warnings.append("SINGLE_COLUMN_INPUT")

            if len(json.dumps(columns).encode("utf-8")) > 500 * 1024:
                raise ImportInspectionException("SCHEMA_TOO_LARGE", "Schema definition exceeds 500 KiB")

            # Setup canonical Parquet writer
            pa_schema = pa.schema(
                [pa.field(name, pa.string(), nullable=True) for name in final_names],
                metadata={"normalization_version": "1"},
            )
            writer = pq.ParquetWriter(canonical_path, pa_schema, compression="zstd")
            batch_rows: list[list[str | None]] = []
            raw_preview_rows: list[dict[str, Any]] = []
            profile_sample: list[list[str | None]] = []
            sample_bytes = 0
            row_count = 0
            scanner = PrivacyScanner(columns=columns, extra_columns=privacy_columns, rules=privacy_rules)

            try:
                batch_bytes = 0
                for line_idx, row in enumerate(reader, start=2):
                    if len(row) != len(raw_col_names):
                        raise ImportInspectionException(
                            "MALFORMED_CSV",
                            f"Row {line_idx} has {len(row)} columns; expected {len(raw_col_names)}",
                        )

                    rec_bytes = sum(len(c.encode("utf-8")) for c in row)
                    if rec_bytes > 8 * 1024 * 1024:
                        raise ImportInspectionException("RECORD_TOO_LARGE", f"CSV row {line_idx} exceeds 8 MiB record limit")

                    cleaned_row = [cell if cell != "" else None for cell in row]
                    batch_rows.append(cleaned_row)
                    batch_bytes += sum(len(c.encode("utf-8")) for c in cleaned_row if c is not None)
                    row_count += 1

                    row_dict = {final_names[i]: cleaned_row[i] for i in range(len(final_names))}
                    try:
                        scanner.feed_row(row_dict)
                    except PrivacyScanLimitExceededException as exc:
                        raise ImportInspectionException("PRIVACY_SCAN_LIMIT_EXCEEDED", str(exc)) from exc
                    except Exception as exc:
                        raise ImportInspectionException("PRIVACY_SCAN_FAILED", f"Privacy scan error: {exc}") from exc

                    if row_count <= 50:
                        raw_preview_rows.append(row_dict)
                    if row_count <= 1000 and sample_bytes + rec_bytes <= 16 * 1024 * 1024:
                        profile_sample.append(cleaned_row)
                        sample_bytes += rec_bytes
                    elif row_count <= 1000 and "PROFILE_SAMPLE_LIMIT" not in warnings:
                        warnings.append("PROFILE_SAMPLE_LIMIT")

                    if len(batch_rows) >= 8192 or batch_bytes >= 16 * 1024 * 1024:
                        self._write_parquet_batch(writer, final_names, batch_rows)
                        batch_rows.clear()
                        batch_bytes = 0
                if batch_rows:
                    self._write_parquet_batch(writer, final_names, batch_rows)
                    batch_rows.clear()

            except (csv.Error, UnicodeDecodeError) as exc:
                raise ImportInspectionException("MALFORMED_CSV", "CSV syntax or UTF-8 is invalid.") from exc
            finally:
                writer.close()

            if row_count == 0:
                raise ImportInspectionException("EMPTY_DATASET", "Dataset contains a header but 0 data rows")

            try:
                sensitive_scan = scanner.finish()
            except Exception as exc:
                raise ImportInspectionException("PRIVACY_SCAN_FAILED", f"Privacy scan error: {exc}") from exc
            flagged_sensitive = set(sensitive_scan["sensitive_columns"])
            redacted_preview = self._build_preview(raw_preview_rows, sensitive_columns=flagged_sensitive)
            profile = self._build_profile(final_names, profile_sample, row_count, sensitive_columns=flagged_sensitive)

            return {
                "exact_row_count": row_count,
                "columns": columns,
                "preview_rows": redacted_preview,
                "profile": profile,
                "warnings": warnings,
                "normalization_version": 1,
                "sensitive_scan": sensitive_scan,
            }

    # -----------------------------------------------------------------------
    # JSONL Processing
    # -----------------------------------------------------------------------

    def _process_jsonl(
        self,
        raw_path: Path,
        canonical_path: Path,
        column_names_mapping: list[str] | None,
        privacy_columns: tuple[str, ...] = (),
        privacy_rules: Sequence[PrivacyDetectorRule] | None = None,
    ) -> dict[str, Any]:
        keys_order: list[str] = []
        keys_set: set[str] = set()
        key_logical_types: dict[str, set[str]] = {}
        container_columns: set[str] = set()
        row_count = 0
        with raw_path.open("r", encoding="utf-8-sig") as f:
            line_no = 0
            while True:
                line = f.readline(8 * 1024 * 1024 + 2)
                if not line:
                    break
                if len(line.encode("utf-8")) > 8 * 1024 * 1024:
                    raise ImportInspectionException("RECORD_TOO_LARGE", f"JSONL line {line_no + 1} exceeds 8 MiB record limit")
                line_no += 1
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = parse_structured_json(stripped, max_depth=32)
                except StructuredParsingError as exc:
                    if exc.error_code == "NESTING_TOO_DEEP":
                        raise ImportInspectionException("NESTING_TOO_DEEP", f"Line {line_no} nesting depth exceeds limit: {exc.detail}") from exc
                    raise ImportInspectionException("MALFORMED_JSONL", f"Line {line_no} error: {exc.detail}") from exc
                except Exception as exc:
                    raise ImportInspectionException("MALFORMED_JSONL", f"Line {line_no} is not valid JSON: {exc}") from exc

                if not isinstance(obj, dict):
                    raise ImportInspectionException("NESTED_DATA_UNSUPPORTED", f"Line {line_no} root must be a JSON object")
                row_count += 1

                for k, v in obj.items():
                    if k not in keys_set:
                        keys_set.add(k)
                        keys_order.append(k)
                        key_logical_types[k] = set()
                        if len(keys_order) > 1000:
                            raise ImportInspectionException("TOO_MANY_COLUMNS", "JSONL key union exceeds 1000 columns")
                    kind = classify_value_kind(v)
                    key_logical_types[k].add(kind)
                    if kind in ("OBJECT", "ARRAY"):
                        container_columns.add(k)

        if row_count == 0 or not keys_order:
            raise ImportInspectionException("EMPTY_DATASET", "JSONL file contains 0 valid data rows")

        final_names = column_names_mapping if column_names_mapping else keys_order
        if len(final_names) != len(keys_order) or len(set(final_names)) != len(final_names) or any(not name for name in final_names):
            raise ImportInspectionException("INVALID_COLUMN_MAPPING", "Mapped columns must be nonempty and one-to-one")
        has_containers = len(container_columns) > 0
        norm_version = 2 if has_containers else 1

        columns = []
        for i in range(len(final_names)):
            orig_k = keys_order[i]
            col_info: dict[str, Any] = {
                "index": i,
                "original_name": orig_k,
                "name": final_names[i],
                "type": "STRING",
                "nullable": True,
            }
            if orig_k in container_columns:
                col_info["structural_encoding"] = "JSON"
                col_info["logical_types"] = sorted(key_logical_types[orig_k])
            columns.append(col_info)

        warnings: list[str] = []
        if len(final_names) == 1:
            warnings.append("SINGLE_COLUMN_INPUT")
        if any(len(types) > 1 for types in key_logical_types.values()):
            warnings.append("MIXED_SCALAR_TYPES")

        if len(json.dumps(columns).encode("utf-8")) > 500 * 1024:
            raise ImportInspectionException("SCHEMA_TOO_LARGE", "Schema definition exceeds 500 KiB")

        # Pass 2: Write canonical Parquet
        pa_schema = pa.schema(
            [pa.field(name, pa.string(), nullable=True) for name in final_names],
            metadata={"normalization_version": str(norm_version)},
        )
        writer = pq.ParquetWriter(canonical_path, pa_schema, compression="zstd")
        scanner = PrivacyScanner(columns=columns, extra_columns=privacy_columns, rules=privacy_rules)
        batch_rows: list[list[str | None]] = []
        raw_preview_rows: list[dict[str, Any]] = []
        profile_sample: list[list[str | None]] = []
        current_idx = 0
        batch_bytes = 0
        sample_bytes = 0

        try:
            with raw_path.open("r", encoding="utf-8-sig") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    obj = parse_structured_json(stripped, max_depth=32)
                    try:
                        scanner.feed_row({final_names[i]: obj.get(k) for i, k in enumerate(keys_order)})
                    except PrivacyScanLimitExceededException as exc:
                        raise ImportInspectionException("PRIVACY_SCAN_LIMIT_EXCEEDED", str(exc)) from exc
                    except Exception as exc:
                        raise ImportInspectionException("PRIVACY_SCAN_FAILED", f"Privacy scan error: {exc}") from exc
                    row_vals: list[str | None] = []
                    for k in keys_order:
                        val = obj.get(k)
                        if val is None:
                            row_vals.append(None)
                        elif k in container_columns:
                            row_vals.append(canonical_compact_json(val))
                        elif isinstance(val, bool):
                            row_vals.append("true" if val else "false")
                        elif isinstance(val, (int, float, decimal.Decimal)):
                            row_vals.append(str(val))
                        else:
                            row_vals.append(str(val))

                    rec_bytes = sum(len(v.encode("utf-8")) for v in row_vals if v is not None)
                    if rec_bytes > 8 * 1024 * 1024:
                        raise ImportInspectionException("RECORD_TOO_LARGE", "JSONL record exceeds the byte limit.")
                    batch_rows.append(row_vals)
                    batch_bytes += rec_bytes
                    current_idx += 1

                    if current_idx <= 50:
                        raw_preview_rows.append({final_names[i]: row_vals[i] for i in range(len(final_names))})
                    if current_idx <= 1000 and sample_bytes + rec_bytes <= 16 * 1024 * 1024:
                        profile_sample.append(row_vals)
                        sample_bytes += rec_bytes
                    elif current_idx <= 1000 and "PROFILE_SAMPLE_LIMIT" not in warnings:
                        warnings.append("PROFILE_SAMPLE_LIMIT")

                    if len(batch_rows) >= 8192 or batch_bytes >= 16 * 1024 * 1024:
                        self._write_parquet_batch(writer, final_names, batch_rows)
                        batch_rows.clear()
                        batch_bytes = 0

            if batch_rows:
                self._write_parquet_batch(writer, final_names, batch_rows)
                batch_rows.clear()
        finally:
            writer.close()

        try:
            sensitive_scan = scanner.finish()
        except Exception as exc:
            raise ImportInspectionException("PRIVACY_SCAN_FAILED", f"Privacy scan error: {exc}") from exc
        flagged_sensitive = set(sensitive_scan["sensitive_columns"])
        redacted_preview = self._build_preview(raw_preview_rows, sensitive_columns=flagged_sensitive)
        container_cols = {final_names[i] for i, k in enumerate(keys_order) if k in container_columns}
        profile = self._build_profile(final_names, profile_sample, row_count, container_columns=container_cols, sensitive_columns=flagged_sensitive)

        return {
            "exact_row_count": row_count,
            "columns": columns,
            "preview_rows": redacted_preview,
            "profile": profile,
            "warnings": warnings,
            "normalization_version": norm_version,
            "sensitive_scan": sensitive_scan,
        }

    # -----------------------------------------------------------------------
    # Parquet Processing
    # -----------------------------------------------------------------------

    @staticmethod
    def _arrow_json_value(value: Any, arrow_type: pa.DataType, depth: int = 1) -> Any:
        if depth > 32:
            raise ImportInspectionException("NESTING_TOO_DEEP", "Parquet nesting exceeds 32 levels")
        if value is None:
            return None
        if pa.types.is_map(arrow_type):
            result = {}
            for key, item in value:
                if not isinstance(key, str):
                    raise ImportInspectionException("UNSUPPORTED_FORMAT", "Map keys must be strings")
                if key in result:
                    raise ImportInspectionException("DUPLICATE_KEY", "Duplicate map key")
                result[key] = TabularImportAdapter._arrow_json_value(item, arrow_type.item_type, depth + 1)
            return result
        if pa.types.is_struct(arrow_type):
            return {field.name: TabularImportAdapter._arrow_json_value(value.get(field.name), field.type, depth + 1) for field in arrow_type}
        if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type) or pa.types.is_fixed_size_list(arrow_type):
            return [TabularImportAdapter._arrow_json_value(item, arrow_type.value_type, depth + 1) for item in value]
        if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type) or pa.types.is_union(arrow_type):
            raise ImportInspectionException("UNSUPPORTED_FORMAT", "Binary or union nested value unsupported")
        return value

    def _process_parquet(
        self,
        raw_path: Path,
        canonical_path: Path,
        column_names_mapping: list[str] | None,
        privacy_columns: tuple[str, ...] = (),
        privacy_rules: Sequence[PrivacyDetectorRule] | None = None,
    ) -> dict[str, Any]:
        try:
            pq_file = pq.ParquetFile(raw_path, memory_map=True)
        except Exception as exc:
            raise ImportInspectionException("MALFORMED_PARQUET", f"Invalid Parquet file: {exc}") from exc

        # Validate row group byte size
        for rg_idx in range(pq_file.num_row_groups):
            rg_meta = pq_file.metadata.row_group(rg_idx)
            if rg_meta.total_byte_size > 256 * 1024 * 1024:
                raise ImportInspectionException(
                    "PARQUET_ROW_GROUP_TOO_LARGE",
                    f"Parquet row group {rg_idx} uncompressed size exceeds 256 MiB limit",
                )
        schema = pq_file.schema_arrow
        if len(schema.names) == 0:
            raise ImportInspectionException("EMPTY_DATASET", "Parquet file contains 0 columns")
        if len(schema.names) > 1000:
            raise ImportInspectionException("TOO_MANY_COLUMNS", "Parquet schema exceeds 1000 columns")

        container_col_indices: set[int] = set()
        container_col_types: dict[int, list[str]] = {}
        for idx, col_field in enumerate(schema):
            t = col_field.type
            if pa.types.is_binary(t) or pa.types.is_large_binary(t) or pa.types.is_union(t):
                raise ImportInspectionException("UNSUPPORTED_FORMAT", f"Column '{col_field.name}' type {t} is unsupported.")
            if pa.types.is_nested(t) or pa.types.is_struct(t) or pa.types.is_list(t) or pa.types.is_map(t):
                container_col_indices.add(idx)
                if pa.types.is_list(t) or pa.types.is_large_list(t) or pa.types.is_fixed_size_list(t):
                    container_col_types[idx] = ["ARRAY"]
                else:
                    container_col_types[idx] = ["OBJECT"]

        raw_col_names = schema.names
        final_names = column_names_mapping if column_names_mapping else raw_col_names
        if len(final_names) != len(raw_col_names) or len(set(final_names)) != len(final_names) or any(not name for name in final_names):
            raise ImportInspectionException("INVALID_COLUMN_MAPPING", "Mapped columns must be nonempty and one-to-one")
        has_containers = len(container_col_indices) > 0
        norm_version = 2 if has_containers else 1

        columns = []
        for i in range(len(final_names)):
            col_info = {
                "index": i,
                "original_name": raw_col_names[i],
                "name": final_names[i],
                "type": str(schema.field(i).type),
                "nullable": True,
            }
            if i in container_col_indices:
                col_info["structural_encoding"] = "JSON"
                col_info["logical_types"] = container_col_types[i]
            columns.append(col_info)

        if len(json.dumps(columns).encode("utf-8")) > 500 * 1024:
            raise ImportInspectionException("SCHEMA_TOO_LARGE", "Schema definition exceeds 500 KiB")

        pa_schema = pa.schema(
            [pa.field(name, pa.string(), nullable=True) for name in final_names],
            metadata={"normalization_version": str(norm_version)},
        )
        writer = pq.ParquetWriter(canonical_path, pa_schema, compression="zstd")
        row_count = 0
        raw_preview_rows: list[dict[str, Any]] = []
        profile_sample: list[list[str | None]] = []
        scanner = PrivacyScanner(columns=columns, extra_columns=privacy_columns, rules=privacy_rules)
        container_cols = {final_names[i] for i in container_col_indices}
        try:
            sample_bytes = 0
            for batch in pq_file.iter_batches(batch_size=8192):
                num_rows = batch.num_rows
                if num_rows == 0:
                    continue

                # Convert each column to string array
                str_cols = []
                for col_idx in range(len(final_names)):
                    col = batch.column(col_idx)
                    if col_idx in container_col_indices:
                        py_vals = col.to_pylist()
                        converted_vals = []
                        for pv in py_vals:
                            if pv is None:
                                converted_vals.append(None)
                            else:
                                converted = self._arrow_json_value(pv, schema.field(col_idx).type)
                                encoded = canonical_compact_json(converted)
                                try:
                                    parse_structured_json(encoded)
                                except StructuredParsingError as exc:
                                    raise ImportInspectionException(exc.error_code, "Invalid nested Parquet value") from exc
                                converted_vals.append(encoded)
                        str_col = pa.array(converted_vals, type=pa.string())
                    else:
                        str_col = col.cast(pa.string())
                    str_cols.append(str_col)

                str_batch = pa.RecordBatch.from_arrays(str_cols, names=final_names)
                writer.write_batch(str_batch)

                # Collect preview and profile samples
                for r in range(num_rows):
                    row_count += 1
                    row_vals = [str_cols[c][r].as_py() for c in range(len(final_names))]

                    rec_bytes = sum(len(v.encode("utf-8")) for v in row_vals if v is not None)
                    if rec_bytes > 8 * 1024 * 1024:
                        raise ImportInspectionException("RECORD_TOO_LARGE", "Parquet record exceeds the byte limit.")
                    row_dict = {final_names[c]: row_vals[c] for c in range(len(final_names))}
                    scan_dict = {}
                    for c_name, val_str in row_dict.items():
                        if val_str and c_name in container_cols:
                            try:
                                scan_dict[c_name] = parse_structured_json(val_str)
                            except (StructuredParsingError, ValueError, TypeError):
                                scan_dict[c_name] = val_str
                        else:
                            scan_dict[c_name] = val_str
                    try:
                        scanner.feed_row(scan_dict)
                    except PrivacyScanLimitExceededException as exc:
                        raise ImportInspectionException("PRIVACY_SCAN_LIMIT_EXCEEDED", str(exc)) from exc
                    except Exception as exc:
                        raise ImportInspectionException("PRIVACY_SCAN_FAILED", f"Privacy scan error: {exc}") from exc

                    if row_count <= 50:
                        raw_preview_rows.append(row_dict)
                    if row_count <= 1000 and sample_bytes + rec_bytes <= 16 * 1024 * 1024:
                        profile_sample.append(row_vals)
                        sample_bytes += rec_bytes

        finally:
            writer.close()

        if row_count == 0:
            raise ImportInspectionException("EMPTY_DATASET", "Parquet file contains 0 rows")

        warnings: list[str] = []
        if len(final_names) == 1:
            warnings.append("SINGLE_COLUMN_INPUT")
        if len(profile_sample) < min(row_count, 1000):
            warnings.append("PROFILE_SAMPLE_LIMIT")

        try:
            sensitive_scan = scanner.finish()
        except Exception as exc:
            raise ImportInspectionException("PRIVACY_SCAN_FAILED", f"Privacy scan error: {exc}") from exc
        flagged_sensitive = set(sensitive_scan["sensitive_columns"])
        redacted_preview = self._build_preview(raw_preview_rows, sensitive_columns=flagged_sensitive)
        profile = self._build_profile(final_names, profile_sample, row_count, container_columns=container_cols, sensitive_columns=flagged_sensitive)

        return {
            "exact_row_count": row_count,
            "columns": columns,
            "preview_rows": redacted_preview,
            "profile": profile,
            "warnings": warnings,
            "normalization_version": norm_version,
            "sensitive_scan": sensitive_scan,
        }
    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _write_parquet_batch(
        self,
        writer: pq.ParquetWriter,
        col_names: list[str],
        rows: list[list[str | None]],
    ) -> None:
        if shutil.disk_usage(self._temp_root).free < 256 * 1024 * 1024:
            raise ImportInspectionException("IMPORT_STORAGE_FULL", "Scratch storage reserve reached.")
        arrays = []
        for col_idx in range(len(col_names)):
            col_vals = [r[col_idx] for r in rows]
            arrays.append(pa.array(col_vals, type=pa.string()))
        batch = pa.RecordBatch.from_arrays(arrays, names=col_names)
        writer.write_batch(batch)

    @staticmethod
    def _redact_structured_value(value: Any) -> Any:
        if isinstance(value, dict):
            masked = redact_sample_row(value)
            return {key: TabularImportAdapter._redact_structured_value(item) for key, item in masked.items()}
        if isinstance(value, list):
            return [TabularImportAdapter._redact_structured_value(item) for item in value]
        return value

    @staticmethod
    def _build_preview(rows: list[dict[str, Any]], sensitive_columns: set[str] | None = None) -> list[dict[str, Any]]:
        redacted = []
        sens_cols = sensitive_columns or set()
        for r in rows[:50]:
            # Sensitive column full mask
            masked_r = {}
            for k, v in r.items():
                if k in sens_cols:
                    if v is None:
                        masked_r[k] = None
                    elif v == "":
                        masked_r[k] = ""
                    else:
                        masked_r[k] = "[REDACTED]"
                else:
                    k_lower = k.lower().replace("-", "_")
                    tokens = set(k_lower.split("_"))
                    if tokens & FINANCIAL_TOKENS:
                        masked_r[k] = "[REDACTED]"
                    else:
                        masked_r[k] = v
            masked = redact_sample_row(masked_r)
            cell_capped = {}
            for k, v in masked.items():
                if v is None:
                    cell_capped[k] = None
                elif isinstance(v, str):
                    stripped_v = v.strip()
                    if (stripped_v.startswith("{") and stripped_v.endswith("}")) or (stripped_v.startswith("[") and stripped_v.endswith("]")):
                        try:
                            parsed_json = parse_structured_json(stripped_v)
                            v_clean = canonical_compact_json(TabularImportAdapter._redact_structured_value(parsed_json))
                        except StructuredParsingError:
                            v_clean = v
                    else:
                        v_clean = v
                    if len(v_clean) > 256:
                        cell_capped[k] = v_clean[:253] + "..."
                    else:
                        cell_capped[k] = v_clean
                else:
                    s_val = str(v)
                    cell_capped[k] = s_val[:253] + "..." if len(s_val) > 256 else s_val
            redacted.append(cell_capped)

        # Bound encoded JSON to 500 KiB
        while redacted and len(json.dumps(redacted).encode("utf-8")) > 500 * 1024:
            redacted.pop()
        return redacted

    @classmethod
    def _build_profile(
        cls,
        col_names: list[str],
        sample_rows: list[list[str | None]],
        total_rows: int,
        container_columns: set[str] | None = None,
        sensitive_columns: set[str] | None = None,
    ) -> dict[str, Any]:
        sample_size = len(sample_rows)
        col_profiles = []
        containers = container_columns or set()

        for col_idx, col_name in enumerate(col_names):
            vals = [r[col_idx] for r in sample_rows]
            null_count = sum(1 for v in vals if v is None)
            non_null_count = sample_size - null_count
            non_null_vals = [v for v in vals if v is not None]

            distinct_set = set(non_null_vals[:1000])
            distinct_count = len(distinct_set)

            if col_name in containers:
                type_hint = "JSON"
                success_count = non_null_count
                ts_fmt = None
                min_val = None
                max_val = None
            else:
                type_hint, success_count, ts_fmt, min_val, max_val = cls._infer_profile_stats(col_name, non_null_vals)

            if sensitive_columns and col_name in sensitive_columns:
                min_val = None
                max_val = None
            col_stat: dict[str, Any] = {
                "name": col_name,
                "type_hint": type_hint,
                "null_count": null_count,
                "non_null_count": non_null_count,
                "distinct_count": distinct_count,
                "parse_success_count": success_count,
                "sample_rows": sample_size,
            }
            if ts_fmt:
                col_stat["timestamp_format"] = ts_fmt
            if min_val is not None:
                col_stat["min"] = min_val
            if max_val is not None:
                col_stat["max"] = max_val
            col_profiles.append(col_stat)

        return {
            "sample_rows": sample_size,
            "is_sample": True,
            "total_rows": total_rows,
            "columns": col_profiles,
        }

    @staticmethod
    def _infer_profile_stats(
        col_name: str, values: list[str]
    ) -> tuple[str, int, str | None, Any | None, Any | None]:
        if not values:
            return "STRING", 0, None, None, None

        lower_name = col_name.lower().replace("-", "_")
        tokens = set(lower_name.split("_"))
        is_identifier = bool(tokens & IDENTIFIER_TOKENS or lower_name.endswith("id"))
        total = len(values)
        threshold = 0.95

        # 1. Integer check (no leading-zero identifiers)
        if not is_identifier:
            int_vals = []
            for v in values:
                if INTEGER_REGEX.match(v):
                    try:
                        int_vals.append(int(v))
                    except ValueError:
                        pass
            if (len(int_vals) / total) >= threshold:
                return "INTEGER", len(int_vals), None, min(int_vals), max(int_vals)

        # 2. Double check
        if not is_identifier:
            dbl_vals = []
            for v in values:
                try:
                    d = decimal.Decimal(v)
                    if d.is_finite():
                        dbl_vals.append(d)
                except decimal.DecimalException:
                    pass
            if (len(dbl_vals) / total) >= threshold:
                return "DOUBLE", len(dbl_vals), None, str(min(dbl_vals)), str(max(dbl_vals))

        # 3. Timestamp check
        best_ts_fmt: str | None = None
        best_ts_matches: list[datetime] = []
        for py_fmt, canon_fmt in TIMESTAMP_FORMAT_MAPPINGS:
            matches = []
            for v in values:
                try:
                    dt = datetime.strptime(v, py_fmt).replace(tzinfo=UTC)
                    matches.append(dt)
                except ValueError:
                    pass
            if len(matches) > len(best_ts_matches):
                best_ts_matches = matches
                best_ts_fmt = canon_fmt

        if best_ts_fmt and (len(best_ts_matches) / total) >= threshold:
            min_ts = min(best_ts_matches).isoformat()
            max_ts = max(best_ts_matches).isoformat()
            return "TIMESTAMP", len(best_ts_matches), best_ts_fmt, min_ts, max_ts

        # 4. Date check
        date_matches: list[str] = []
        for v in values:
            if DATE_REGEX.match(v):
                try:
                    datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=UTC)
                    date_matches.append(v)
                except ValueError:
                    pass
        if (len(date_matches) / total) >= threshold:
            return "DATE", len(date_matches), None, min(date_matches), max(date_matches)

        # 5. Boolean check
        bool_matches = sum(1 for v in values if v.lower() in ("true", "false"))
        if (bool_matches / total) >= threshold:
            return "BOOLEAN", bool_matches, None, None, None

        return "STRING", total, None, None, None

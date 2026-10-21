"""Tabular dataset import adapter: raw-only freezing, bounded inspection, preview and profile."""

from __future__ import annotations

import decimal
import hashlib
import io
import json
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, BinaryIO, Literal

from dq_scoring.adapters.source.tabular_normalization import (
    ImportInspectionException,
    NormalizationSpec,
    inspect_schema,
    iter_normalized_batches,
)
from dq_scoring.adapters.storage.normalized_snapshot import PinnedObjectReader
from dq_scoring.common.privacy import (
    PrivacyScanLimitExceededException,
    PrivacyScanner,
)
from dq_scoring.common.privacy_rules import PrivacyDetectorRule
from dq_scoring.common.redaction_utils import redact_sample_row
from dq_scoring.common.structured_values import (
    StructuredParsingError,
    canonical_compact_json,
    parse_structured_json,
)
from dq_scoring.ports.object_store import (
    IObjectStorePort,
    ObjectChangedError,
    ObjectMetadata,
    ObjectRef,
    UploadedPart,
)

BINARY_MAGICS = (
    (b"%PDF", "PDF files are not supported"),
    (b"PK\x03\x04", "ZIP archives are not supported"),
    (b"\x89PNG", "PNG images are not supported"),
    (b"\xff\xd8\xff", "JPEG images are not supported"),
    (b"GIF8", "GIF images are not supported"),
)

HASH_CHUNK_BYTES = 1024 * 1024
PART_BYTES = 16 * 1024 * 1024
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


@dataclass(frozen=True)
class ImportInspection:
    """Outcome of raw snapshot inspection; normalization is replayed at read time from `normalization`."""

    raw_ref: ObjectRef
    raw_sha256: str
    raw_size_bytes: int
    exact_row_count: int
    columns: list[dict[str, Any]]
    preview_rows: list[dict[str, Any]]
    profile: dict[str, Any]
    warnings: list[str]
    normalization: NormalizationSpec
    storage_mode: Literal["OWNED_RAW", "EXTERNAL_VERSION"]
    sensitive_scan: dict[str, Any] = field(default_factory=lambda: {"status": "UNAVAILABLE"})

    @property
    def normalization_version(self) -> int:
        return self.normalization.version


class TabularImportAdapter:
    """Freezes (at most) one raw object, then inspects it with bounded memory and no scratch files."""

    def __init__(self, store: IObjectStorePort) -> None:
        self._store = store

    def inspect_snapshot(
        self,
        *,
        source: ObjectRef,
        source_store: IObjectStorePort,
        storage_mode: str,
        destination_bucket: str,
        destination_prefix: str,
        file_format: str,
        column_names_mapping: list[str] | None = None,
        delimiter: str = ",",
        source_id: str | None = None,
        reuse_owned: bool = False,
        privacy_columns: tuple[str, ...] = (),
        privacy_rules: Sequence[PrivacyDetectorRule] | None = None,
    ) -> ImportInspection:
        fmt = file_format.upper()
        external = storage_mode == "EXTERNAL_VERSION"
        if storage_mode not in ("OWNED_RAW", "EXTERNAL_VERSION"):
            raise ImportInspectionException("STORAGE_VIOLATION", "Unsupported snapshot storage mode.")
        if source_id == "shared" and source_store is self._store:
            raise ImportInspectionException("STORAGE_VIOLATION", "Shared sources require the read-only source client.")
        if external and (source_id != "shared" or reuse_owned or not source.version_id or source.version_id == "null"):
            raise ImportInspectionException("STORAGE_VIOLATION", "External snapshots require a shared source and pinned version.")
        if reuse_owned and (not source.version_id or source.version_id == "null"):
            raise ImportInspectionException("STORAGE_VIOLATION", "Retained raw object requires a pinned version.")

        if not external and not self._store.is_versioning_enabled(destination_bucket):
            raise ImportInspectionException("SNAPSHOT_VERSIONING_REQUIRED", "Snapshot bucket versioning is required.")
        reader_store = source_store if external else self._store
        raw_ref: ObjectRef | None = None
        try:
            before = self._head_source(source_store, source)
            if before.size_bytes == 0:
                raise ImportInspectionException("EMPTY_DATASET", "Uploaded file is 0 bytes.")
            if external or reuse_owned:
                raw_ref = ObjectRef(source.bucket, source.key, source.version_id)
            else:
                raw_ref = self._freeze_owned(
                    source, source_store, before, destination_bucket,
                    f"{destination_prefix.rstrip('/')}/source.{fmt.lower()}", source_id,
                )
            raw_sha256, raw_size = self._hash_and_check(reader_store, raw_ref, fmt)
            if raw_size != before.size_bytes:
                raise ImportInspectionException("OBJECT_CHANGED", "Raw object size differs from source metadata.")
            warnings: list[str] = []
            with self._open_raw(reader_store, raw_ref, fmt, raw_size) as raw:
                spec = inspect_schema(raw, file_format=fmt, column_names_mapping=column_names_mapping,
                                      delimiter=delimiter, warnings=warnings)
            result = self._scan(reader_store, raw_ref, raw_size, spec, warnings, privacy_columns, privacy_rules)
            after = self._head_source(source_store, source)
            if (
                after.etag != before.etag
                or after.size_bytes != before.size_bytes
                or (before.version_id and after.version_id != before.version_id)
            ):
                raise ImportInspectionException("OBJECT_CHANGED", "Source storage object was modified concurrently during ingestion")
            return ImportInspection(
                raw_ref=raw_ref,
                raw_sha256=raw_sha256,
                raw_size_bytes=raw_size,
                normalization=spec,
                storage_mode=storage_mode,  # type: ignore[arg-type]
                **result,
            )
        except ObjectChangedError as exc:
            error = ImportInspectionException("OBJECT_CHANGED", "Source storage object was modified concurrently during ingestion")
            self._retain(error, raw_ref, external)
            raise error from exc
        except ImportInspectionException as exc:
            self._retain(exc, raw_ref, external)
            raise

    @staticmethod
    def _retain(exc: ImportInspectionException, raw_ref: ObjectRef | None, external: bool) -> None:
        """Expose an already frozen owned raw so the caller can reuse it on retry."""
        if raw_ref is not None and not external:
            exc.raw_ref = raw_ref  # type: ignore[attr-defined]

    @staticmethod
    def _head_source(store: IObjectStorePort, source: ObjectRef) -> ObjectMetadata:
        meta = store.head(source)
        if source.version_id and meta.version_id and meta.version_id != source.version_id:
            raise ImportInspectionException("OBJECT_CHANGED", "Source version differs from the selected version.")
        return meta

    def _freeze_owned(
        self,
        source: ObjectRef,
        source_store: IObjectStorePort,
        before: ObjectMetadata,
        bucket: str,
        key: str,
        source_id: str | None,
    ) -> ObjectRef:
        if source_store is self._store and source_id is None:
            meta = self._store.copy_object(source=source, bucket=bucket, key=key, source_etag=before.etag)
        else:
            meta = self._stream_to_owned(source, source_store, before, bucket, key)
        if not meta.version_id or meta.version_id == "null":
            raise ImportInspectionException("SNAPSHOT_VERSIONING_REQUIRED", "Snapshot bucket did not return an object version.")
        return ObjectRef(bucket, key, meta.version_id)

    def _stream_to_owned(
        self, source: ObjectRef, source_store: IObjectStorePort, before: ObjectMetadata, bucket: str, key: str
    ) -> ObjectMetadata:
        """Multipart-copy a foreign object through memory (one part at a time) into the owned bucket."""
        stream = source_store.open_stream(source, if_match_etag=None if source.version_id else before.etag)
        upload_id: str | None = None
        try:
            upload_id = self._store.create_multipart(bucket, key)
            parts: list[UploadedPart] = []
            while chunk := self._read_part(stream):
                number = len(parts) + 1
                etag = self._store.upload_part(bucket, key, upload_id, number, io.BytesIO(chunk), len(chunk))
                parts.append(UploadedPart(part_number=number, etag=etag, size_bytes=len(chunk)))
            if not parts:
                raise ImportInspectionException("EMPTY_DATASET", "Uploaded file is 0 bytes.")
            after = self._head_source(source_store, source)
            if (
                after.etag != before.etag
                or after.size_bytes != before.size_bytes
                or (before.version_id and after.version_id != before.version_id)
            ):
                raise ImportInspectionException("OBJECT_CHANGED", "Source storage object was modified concurrently during ingestion")
            return self._store.complete_multipart(bucket, key, upload_id, parts)
        except BaseException:
            if upload_id is not None:
                # An abort failure must not mask the original error; orphan parts are lifecycle-cleaned.
                with suppress(Exception):
                    self._store.abort_multipart(bucket, key, upload_id)
            raise
        finally:
            stream.close()

    @staticmethod
    def _read_part(stream: BinaryIO) -> bytes:
        buf = bytearray()
        while len(buf) < PART_BYTES:
            chunk = stream.read(min(HASH_CHUNK_BYTES, PART_BYTES - len(buf)))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    @staticmethod
    @contextmanager
    def _open_raw(store: IObjectStorePort, ref: ObjectRef, fmt: str, size: int) -> Iterator[BinaryIO]:
        raw = PinnedObjectReader(store, ref, size) if fmt == "PARQUET" else store.open_stream(ref)
        try:
            yield raw  # type: ignore[misc]
        finally:
            raw.close()

    @staticmethod
    def _hash_and_check(store: IObjectStorePort, ref: ObjectRef, fmt: str) -> tuple[str, int]:
        hasher = hashlib.sha256()
        total = 0
        stream = store.open_stream(ref)
        try:
            while chunk := stream.read(HASH_CHUNK_BYTES):
                if total == 0:
                    TabularImportAdapter._check_binary_magic(chunk[:16], fmt)
                hasher.update(chunk)
                total += len(chunk)
        finally:
            stream.close()
        return hasher.hexdigest(), total

    @staticmethod
    def _check_binary_magic(header: bytes, file_format: str) -> None:
        for magic, reason in BINARY_MAGICS:
            if header.startswith(magic):
                raise ImportInspectionException("UNSUPPORTED_FORMAT", reason)
        if file_format.upper() in ("CSV", "JSONL") and header.startswith(b"PAR1"):
            raise ImportInspectionException("UNSUPPORTED_FORMAT", "Parquet binary magic detected in text upload")

    def _scan(
        self,
        store: IObjectStorePort,
        ref: ObjectRef,
        size: int,
        spec: NormalizationSpec,
        warnings: list[str],
        privacy_columns: tuple[str, ...],
        privacy_rules: Sequence[PrivacyDetectorRule] | None,
    ) -> dict[str, Any]:
        columns = list(spec.columns)
        names = [col["name"] for col in columns]
        containers = {col["name"] for col in columns if col.get("structural_encoding") == "JSON"}
        if len(names) == 1:
            warnings.insert(0, "SINGLE_COLUMN_INPUT")
        scanner = PrivacyScanner(columns=columns, extra_columns=privacy_columns, rules=privacy_rules)

        def scan(row: dict[str, Any]) -> None:
            try:
                scanner.feed_row(row)
            except PrivacyScanLimitExceededException as exc:
                raise ImportInspectionException("PRIVACY_SCAN_LIMIT_EXCEEDED", str(exc)) from exc
            except Exception as exc:
                raise ImportInspectionException("PRIVACY_SCAN_FAILED", "Privacy scan failed") from exc

        preview: list[dict[str, Any]] = []
        sample: list[list[str | None]] = []
        sample_bytes = 0
        count = 0
        with self._open_raw(store, ref, spec.format, size) as raw:
            for batch in iter_normalized_batches(raw, spec, scan_row=scan):
                for row in batch.to_pylist():
                    count += 1
                    vals = [row[n] for n in names]
                    rec_bytes = sum(len(v.encode("utf-8")) for v in vals if v is not None)
                    if count <= 50:
                        preview.append(row)
                    if count <= 1000 and sample_bytes + rec_bytes <= 16 * 1024 * 1024:
                        sample.append(vals)
                        sample_bytes += rec_bytes
                    elif count <= 1000 and "PROFILE_SAMPLE_LIMIT" not in warnings:
                        warnings.append("PROFILE_SAMPLE_LIMIT")
        try:
            sensitive_scan = scanner.finish()
        except Exception as exc:
            raise ImportInspectionException("PRIVACY_SCAN_FAILED", "Privacy scan failed") from exc
        sensitive = set(sensitive_scan["sensitive_columns"])
        return {
            "exact_row_count": count,
            "columns": columns,
            "preview_rows": self._build_preview(preview, sensitive_columns=sensitive),
            "profile": self._build_profile(names, sample, count, container_columns=containers,
                                           sensitive_columns=sensitive),
            "warnings": warnings,
            "sensitive_scan": sensitive_scan,
        }

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------


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
